"""
tax_briefing.py – Daily tax digest from kolmas.net
Runs daily at 19:00, scrapes today's articles from 3 categories,
summarizes with Gemini, and sends a formatted Hebrew email.
"""

import os
import json
import logging
import smtplib
import re
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import google.generativeai as genai

# ── Setup ────────────────────────────────────────────────────────────────────

load_dotenv()

BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
LOG_DIR    = BASE_DIR / "logs"
SENT_FILE  = DATA_DIR / "kolmas_sent.json"
LOG_FILE   = LOG_DIR  / "kolmas.log"

DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

KOLMAS_URL      = "https://www.kolmas.net"
KOLMAS_EMAIL    = os.getenv("KOLMAS_EMAIL", "")
KOLMAS_PASSWORD = os.getenv("KOLMAS_PASSWORD", "")
GMAIL_USER      = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASS  = os.getenv("GMAIL_APP_PASSWORD", "")
RECIPIENT       = os.getenv("RECIPIENT_EMAIL") or GMAIL_USER
GEMINI_KEY      = os.getenv("GEMINI_API_KEY", "")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Categories configuration ─────────────────────────────────────────────────
CATEGORIES = [
    {
        "id":    "experts",
        "label": "👨‍💼 פינת המומחים",
        "emoji": "👨‍💼",
        "paths": [
            "/Column", "/Columns", "/column", "/columns",
            "/Article", "/Articles", "/article", "/articles",
            "/Expert", "/Experts", "/expert", "/experts",
            "/Opinion", "/Opinions", "/מומחים", "/פינת-המומחים",
            "/News/Columns", "/News/Articles",
        ],
    },
    {
        "id":    "decisions",
        "label": "⚖️ החלטות מיסוי חדשות",
        "emoji": "⚖️",
        "paths": [
            "/TaxRuling", "/TaxRulings", "/Ruling", "/Rulings",
            "/Decision", "/Decisions", "/decision", "/decisions",
            "/Ruling/Index", "/TaxDecision", "/TaxDecisions",
            "/החלטות-מיסוי", "/פסיקות", "/rulings", "/tax-rulings",
            "/News/Rulings", "/News/Decisions",
        ],
    },
]

# URL fragments that indicate legislation/law texts — skip these articles
LEGISLATION_SKIP = [
    "/Document/Index/1443",   # פקודות ותקנות ראשיות
    "/Document/Index/2523",
    "/Document/Index/1581",
    "/Document/Index/1329",
    "/Document/Index/1687",
    "/Document/Index/1860",
    "/Document/Index/1120",
    "/Encyclopedia/",          # אנציקלופדיה
    "pageid=About",
    "pageid=Contact",
]


# ── Persistence helpers ───────────────────────────────────────────────────────

def load_sent() -> set:
    try:
        if SENT_FILE.exists():
            data = json.loads(SENT_FILE.read_text(encoding="utf-8"))
            return set(data.get("sent_urls", []))
    except Exception:
        pass
    return set()


def save_sent(sent: set):
    SENT_FILE.write_text(
        json.dumps({"sent_urls": sorted(sent)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── HTTP session & login ──────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def login(session: requests.Session) -> bool:
    if not KOLMAS_EMAIL or not KOLMAS_PASSWORD:
        log.warning("KOLMAS credentials not set – proceeding without login (public content only)")
        return False

    try:
        # Step 1: GET the login page to capture CSRF token / cookies
        login_url_candidates = [
            f"{KOLMAS_URL}/login",
            f"{KOLMAS_URL}/user/login",
            f"{KOLMAS_URL}/signin",
            f"{KOLMAS_URL}/account/login",
        ]
        login_page = None
        login_url  = None
        for url in login_url_candidates:
            try:
                r = session.get(url, timeout=15)
                if r.status_code == 200 and (
                    "login" in r.url.lower() or "email" in r.text.lower()
                ):
                    login_page = r
                    login_url  = url
                    break
            except Exception:
                continue

        if not login_page:
            log.warning("Could not find login page – trying direct POST")
            login_url = f"{KOLMAS_URL}/login"

        # Parse CSRF token if present
        csrf = ""
        if login_page:
            soup = BeautifulSoup(login_page.text, "lxml")
            for name in ["_token", "csrf_token", "authenticity_token", "__RequestVerificationToken"]:
                tag = soup.find("input", {"name": name})
                if tag:
                    csrf = tag.get("value", "")
                    break

        payload = {
            "email":    KOLMAS_EMAIL,
            "password": KOLMAS_PASSWORD,
            "username": KOLMAS_EMAIL,   # some sites use "username"
        }
        if csrf:
            payload["_token"] = csrf

        r = session.post(login_url, data=payload, timeout=15, allow_redirects=True)

        if r.status_code in (200, 302) and (
            "logout" in r.text.lower()
            or "התנתק" in r.text
            or "שלום" in r.text
            or KOLMAS_EMAIL.split("@")[0].lower() in r.text.lower()
        ):
            log.info("Login successful")
            return True

        log.warning("Login may have failed (status=%s) – continuing anyway", r.status_code)
        return False

    except Exception as exc:
        log.error("Login error: %s", exc)
        return False


# ── Scraping ──────────────────────────────────────────────────────────────────

TODAY = date.today()
HEBREW_MONTHS = {
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "אפריל": 4,
    "מאי": 5, "יוני": 6, "יולי": 7, "אוגוסט": 8,
    "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
}


def parse_date_text(text: str) -> date | None:
    text = text.strip()
    # ISO format: 2026-05-01
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # DD/MM/YYYY
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    # DD בחודש YYYY (Hebrew)
    for heb, num in HEBREW_MONTHS.items():
        m = re.search(rf"(\d{{1,2}})\s+ב?{heb}\s+(\d{{4}})", text)
        if m:
            try:
                return date(int(m.group(2)), num, int(m.group(1)))
            except ValueError:
                pass
    return None


def is_today(text: str) -> bool:
    d = parse_date_text(text)
    if d:
        return d == TODAY
    # Relative keywords
    rel = text.strip().lower()
    return rel in ("היום", "לפני שעה", "לפני שעתיים", "עכשיו", "today", "just now")


def extract_article_text(session: requests.Session, url: str) -> str:
    try:
        r = session.get(url, timeout=20)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "lxml")
        # Remove nav/header/footer/ads
        for tag in soup.find_all(["nav", "header", "footer", "script", "style", "aside", "form"]):
            tag.decompose()
        # Try article body candidates
        for selector in [
            "article", ".article-content", ".post-content", ".entry-content",
            ".article-body", "#article-body", ".content-area", "main",
        ]:
            el = soup.select_one(selector)
            if el and len(el.get_text(strip=True)) > 100:
                return el.get_text(separator="\n", strip=True)[:4000]
        return soup.get_text(separator="\n", strip=True)[:4000]
    except Exception as exc:
        log.warning("Could not fetch article %s: %s", url, exc)
        return ""


def scrape_category(session: requests.Session, cat: dict) -> list[dict]:
    articles = []
    found_path = None

    for path in cat["paths"]:
        url = KOLMAS_URL + path
        try:
            r = session.get(url, timeout=20)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "lxml")

            # Find article/item containers
            items = (
                soup.find_all("article")
                or soup.select(".post, .article, .item, .news-item, .entry, .card, li.post")
            )

            if not items:
                # Fallback: scan all <a> tags with meaningful text
                items = [
                    a.parent for a in soup.find_all("a", href=True)
                    if len(a.get_text(strip=True)) > 20
                ]

            for item in items[:30]:
                # Title
                title_el = (
                    item.find(["h1", "h2", "h3", "h4"])
                    or item.find("a")
                )
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if len(title) < 10:
                    continue

                # URL
                link_el = item.find("a", href=True) or (title_el if title_el.name == "a" else None)
                href = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href and not href.startswith("http"):
                        href = KOLMAS_URL.rstrip("/") + "/" + href.lstrip("/")

                if not href:
                    continue

                # Skip legislation/encyclopedia texts
                if any(skip in href for skip in LEGISLATION_SKIP):
                    continue

                # Date
                date_text = ""
                for time_el in item.find_all(["time", "span", "div", "p"]):
                    t = time_el.get("datetime", "") or time_el.get_text(strip=True)
                    if parse_date_text(t) or is_today(t):
                        date_text = t
                        break

                if date_text and not is_today(date_text):
                    continue
                if not date_text:
                    date_text = TODAY.strftime("%d/%m/%Y")

                articles.append({
                    "title":     title,
                    "url":       href,
                    "date":      date_text,
                    "category":  cat["id"],
                    "cat_label": cat["label"],
                    "content":   "",
                })

            if articles:
                found_path = path
                log.info("Category '%s': found %d items from %s", cat["id"], len(articles), path)
                break

        except Exception as exc:
            log.warning("Error scraping %s%s: %s", KOLMAS_URL, path, exc)
            continue

    if not articles:
        log.warning("Category '%s': no articles found", cat["id"])

    return articles


# ── Gemini summarization ──────────────────────────────────────────────────────

def summarize(title: str, content: str) -> str:
    if not GEMINI_KEY:
        return f"• {title}\n• סיכום לא זמין (GEMINI_API_KEY חסר)\n• —"

    prompt = f"""סכם את הנושא הבא ב-3 שורות בדיוק בעברית תמציתית.
שורה 1: מה הנושא / ההחלטה / הפסיקה
שורה 2: מה המשמעות המעשית לרו"ח
שורה 3: מה צריך לשים לב אליו / פעולה נדרשת

כותרת: {title}

תוכן:
{content[:2000] if content else "(תוכן לא זמין – בסס על הכותרת בלבד)"}"""

    for model_name in ["gemini-2.5-flash", "gemini-2.0-flash-lite", "gemini-2.0-flash-001"]:
        try:
            model  = genai.GenerativeModel(model_name)
            result = model.generate_content(prompt)
            lines  = [l.strip() for l in result.text.strip().splitlines() if l.strip()]
            lines  = lines[:3]
            while len(lines) < 3:
                lines.append("—")
            return "\n".join(lines)
        except Exception as exc:
            log.warning("Gemini %s failed: %s", model_name, exc)

    return f"• {title[:80]}\n• שגיאה בסיכום\n• —"


def daily_insight(all_articles: list[dict]) -> str:
    if not GEMINI_KEY or not all_articles:
        return ""
    titles = "\n".join(f"- {a['title']}" for a in all_articles[:10])
    prompt = f"""בהתבסס על עדכוני המס הבאים של היום, כתוב משפט אחד בעברית שמחבר בין הנושאים לתמונה הגדולה:
{titles}"""
    try:
        model  = genai.GenerativeModel("gemini-2.5-flash")
        result = model.generate_content(prompt)
        return result.text.strip().splitlines()[0].strip()
    except Exception:
        return ""


# ── Email builder ─────────────────────────────────────────────────────────────

def build_email_html(articles: list[dict], insight: str) -> str:
    today_heb = TODAY.strftime("%d/%m/%Y")
    day_names  = {0:"ראשון",1:"שני",2:"שלישי",3:"רביעי",4:"חמישי",5:"שישי",6:"שבת"}
    day_name   = day_names.get(TODAY.weekday(), "")
    count      = len(articles)

    # Group by category
    by_cat: dict[str, list[dict]] = {}
    for a in articles:
        by_cat.setdefault(a["category"], []).append(a)

    cats_html = ""
    for cat in CATEGORIES:
        items = by_cat.get(cat["id"], [])
        if not items:
            continue

        items_html = ""
        for a in items:
            lines = a.get("summary", "").splitlines()
            l1 = lines[0] if len(lines) > 0 else "—"
            l2 = lines[1] if len(lines) > 1 else "—"
            l3 = lines[2] if len(lines) > 2 else "—"
            # strip leading bullet/dash markers
            l1 = re.sub(r"^[•\-\*\d\.\)]\s*", "", l1)
            l2 = re.sub(r"^[•\-\*\d\.\)]\s*", "", l2)
            l3 = re.sub(r"^[•\-\*\d\.\)]\s*", "", l3)
            items_html += f"""
            <div style="margin-bottom:20px;padding:14px 16px;background:#f9f9f9;border-right:4px solid #1a56db;border-radius:4px">
              <div style="font-weight:700;font-size:15px;color:#111;margin-bottom:8px">📌 {a['title']}</div>
              <div style="font-size:13px;color:#333;line-height:1.7">
                <div>🔹 {l1}</div>
                <div>💼 {l2}</div>
                <div>⚡ {l3}</div>
              </div>
              <div style="margin-top:10px">
                <a href="{a['url']}" style="color:#1a56db;font-size:12px;font-weight:600">🔗 לקריאה מלאה ←</a>
              </div>
            </div>"""

        cats_html += f"""
        <div style="margin-bottom:28px">
          <div style="font-size:17px;font-weight:700;color:#1a56db;border-bottom:2px solid #1a56db;padding-bottom:6px;margin-bottom:14px">{cat['label']}</div>
          <div style="background:#e8f0fe;padding:6px 12px;border-radius:4px;margin-bottom:12px;font-size:11px;color:#555">{'═'*44}</div>
          {items_html}
        </div>"""

    insight_block = ""
    if insight:
        insight_block = f"""
        <div style="margin-top:24px;padding:14px 18px;background:#fff8e1;border:1px solid #ffc107;border-radius:6px">
          <span style="font-weight:700;color:#e65100">💡 תובנת היום (Gemini):</span>
          <div style="margin-top:6px;font-size:13px;color:#333;line-height:1.6">{insight}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:20px;direction:rtl">
<div style="max-width:680px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.12)">
  <div style="background:linear-gradient(135deg,#1a237e,#1565c0);padding:22px 28px">
    <div style="font-size:22px;font-weight:800;color:#fff">⚖️ עדכון מס יומי | קולמס</div>
    <div style="font-size:13px;color:#90caf9;margin-top:4px">יום {day_name} {today_heb} · {count} עדכונים חדשים היום</div>
  </div>
  <div style="padding:24px 28px">
    {'<div style="color:#777;text-align:center;padding:30px;font-size:14px">אין עדכונים חדשים היום בקולמס.</div>' if not articles else cats_html}
    {insight_block}
    <div style="margin-top:30px;padding-top:16px;border-top:1px solid #eee;font-size:11px;color:#aaa;text-align:center">
      נשלח אוטומטית מ-Financial Intelligence Dashboard · {today_heb}
    </div>
  </div>
</div>
</body></html>"""


def build_email_plain(articles: list[dict], insight: str) -> str:
    today_str = TODAY.strftime("%d/%m/%Y")
    lines = [f"עדכון מס יומי – קולמס | {today_str}", "=" * 50, ""]

    by_cat: dict[str, list[dict]] = {}
    for a in articles:
        by_cat.setdefault(a["category"], []).append(a)

    for cat in CATEGORIES:
        items = by_cat.get(cat["id"], [])
        if not items:
            continue
        lines += [cat["label"], "=" * 40, ""]
        for a in items:
            lines.append(f"📌 {a['title']}")
            for l in (a.get("summary", "").splitlines() or ["—"])[:3]:
                lines.append(f"   {l}")
            lines.append(f"   🔗 {a['url']}")
            lines.append("")

    if insight:
        lines += ["", f"💡 תובנת היום: {insight}"]

    return "\n".join(lines)


# ── Send email ────────────────────────────────────────────────────────────────

def send_email(articles: list[dict], insight: str):
    if not GMAIL_USER or not GMAIL_APP_PASS:
        log.error("Gmail credentials not configured – cannot send email")
        return

    today_str = TODAY.strftime("%d/%m/%Y")
    subject   = f"⚖️ עדכון מס יומי - קולמס | {today_str}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT

    msg.attach(MIMEText(build_email_plain(articles, insight), "plain", "utf-8"))
    msg.attach(MIMEText(build_email_html(articles, insight),  "html",  "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASS)
            s.sendmail(GMAIL_USER, RECIPIENT, msg.as_bytes())
        log.info("Email sent to %s (%d articles)", RECIPIENT, len(articles))
    except Exception as exc:
        log.error("Failed to send email: %s", exc)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("── Tax Briefing started (%s) ──", TODAY.strftime("%d/%m/%Y"))

    session = make_session()
    login(session)

    sent = load_sent()
    all_articles: list[dict] = []

    for cat in CATEGORIES:
        raw = scrape_category(session, cat)
        for a in raw:
            if a["url"] in sent:
                log.info("Skip (already sent): %s", a["url"])
                continue
            log.info("Fetching article: %s", a["url"])
            a["content"] = extract_article_text(session, a["url"])
            log.info("Summarizing: %s", a["title"][:60])
            a["summary"] = summarize(a["title"], a["content"])
            all_articles.append(a)

    if not all_articles:
        log.info("No new articles today – sending empty notice")

    insight = daily_insight(all_articles)

    send_email(all_articles, insight)

    # Persist sent URLs
    new_sent = sent | {a["url"] for a in all_articles}
    save_sent(new_sent)

    log.info("── Tax Briefing done. %d articles processed ──", len(all_articles))


if __name__ == "__main__":
    main()
