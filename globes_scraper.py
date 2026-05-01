#!/usr/bin/env python3
"""
Globes Daily News Summarizer
Scrapes globes.co.il, summarizes with Gemini API, sends via Gmail.
"""

import os
import re
import sys
import time
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Force UTF-8 on Windows console so Hebrew/special chars don't crash
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.FileHandler("globes_scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL = "https://www.globes.co.il"

# Sections: each is a (display-name, url) pair.
# The main page is always fetched; the others are attempted and skipped on 404.
SECTIONS: dict[str, str] = {
    "ראשי":        f"{BASE_URL}/news/",
    "כלכלה":       f"{BASE_URL}/news/home.aspx?fid=585",
    'נדל"ן':       f"{BASE_URL}/news/real-estate",
    "הייטק":       f"{BASE_URL}/news/home.aspx?fid=594",
}

# Article URL pattern for globes.co.il
ARTICLE_RE = re.compile(r"article\.aspx\?.*did=\d+", re.IGNORECASE)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

MAX_ARTICLES_PER_SECTION = 5
MAX_ARTICLE_CHARS        = 3500
REQUEST_DELAY            = 1.5   # seconds between HTTP requests

SYSTEM_PROMPT = (
    "אתה עורך חדשות פיננסי מנוסה בישראל. "
    "סכם כתבות מגלובס ב-3-4 משפטים בעברית מקצועית. "
    "הדגש עובדות, נתונים מספריים ומשמעות כלכלית-עסקית. "
    "היה תמציתי וממוקד."
)

# Preferred Gemini model names (tried in order until one works)
GEMINI_CANDIDATES = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro",
    "gemini-pro",
]


# ── Gemini model auto-detection ───────────────────────────────────────────────
def pick_gemini_model(api_key: str) -> str:
    """Return the first available model from GEMINI_CANDIDATES."""
    genai.configure(api_key=api_key)
    try:
        available = {
            m.name.replace("models/", "")
            for m in genai.list_models()
            if "generateContent" in getattr(m, "supported_generation_methods", [])
        }
        log.info("Available Gemini models: %s", available)
        for candidate in GEMINI_CANDIDATES:
            if candidate in available:
                log.info("Selected model: %s", candidate)
                return candidate
        # Fall back to first available
        if available:
            chosen = next(iter(available))
            log.warning("None of preferred models found; using: %s", chosen)
            return chosen
    except Exception as exc:
        log.warning("Could not list Gemini models (%s) – defaulting to gemini-2.0-flash.", exc)
    return "gemini-2.0-flash"


# ── Scraper ───────────────────────────────────────────────────────────────────
class GlobesScraper:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def login(self, email: str, password: str) -> bool:
        if not email or not password:
            log.info("No Globes credentials – scraping as guest.")
            return False
        try:
            login_url = f"{BASE_URL}/news/account/login.aspx"
            resp = self.session.get(login_url, timeout=30)
            soup = BeautifulSoup(resp.text, "lxml")
            form_data: dict[str, str] = {}
            form = soup.find("form")
            if form:
                for inp in form.find_all("input"):
                    name = inp.get("name", "")
                    if name:
                        form_data[name] = inp.get("value", "")
            form_data["email"]    = email
            form_data["password"] = password
            resp2 = self.session.post(login_url, data=form_data, timeout=30)
            if "logout" in resp2.text.lower() or email in resp2.text:
                log.info("Logged in to Globes.")
                return True
            log.warning("Globes login returned guest session – continuing as guest.")
        except Exception as exc:
            log.error("Login error: %s", exc)
        return False

    def get_section_articles(self, section: str, url: str) -> list[dict]:
        articles: list[dict] = []
        log.info("Fetching section '%s' -> %s", section, url)
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            links = self._extract_links(soup)
            log.info("  %d candidate links in '%s'.", len(links), section)
            for art_url, title in links[:MAX_ARTICLES_PER_SECTION]:
                content = self._fetch_article_text(art_url)
                if content:
                    articles.append(
                        {"section": section, "title": title,
                         "url": art_url, "content": content}
                    )
                time.sleep(REQUEST_DELAY)
        except requests.HTTPError as exc:
            log.warning("Section '%s' skipped: %s", section, exc)
        except Exception as exc:
            log.error("Error in section '%s': %s", section, exc)
        return articles

    def _extract_links(self, soup: BeautifulSoup) -> list[tuple[str, str]]:
        seen: set[str] = set()
        results: list[tuple[str, str]] = []
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if not ARTICLE_RE.search(href):
                continue
            full_url = self._abs(href)
            if full_url in seen:
                continue
            title = ""
            parent = a.parent
            if parent:
                h = parent.find(["h1", "h2", "h3", "h4"])
                if h:
                    title = h.get_text(strip=True)
            if not title:
                title = a.get_text(strip=True)
            if len(title) < 8:
                continue
            seen.add(full_url)
            results.append((full_url, title))
        return results

    def _fetch_article_text(self, url: str) -> Optional[str]:
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            for sel in [
                ".article-body", ".articleText", "[itemprop='articleBody']",
                ".article-content", "#article-content", ".story-body",
                ".news-content", "article", "main",
            ]:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text("\n", strip=True)
                    if len(text) > 150:
                        return re.sub(r"\n{3,}", "\n\n", text)[:MAX_ARTICLE_CHARS]
        except Exception as exc:
            log.error("Error fetching %s: %s", url, exc)
        return None

    @staticmethod
    def _abs(href: str) -> str:
        if href.startswith("http"):
            return href
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            return BASE_URL + href
        return BASE_URL + "/" + href


# ── Gemini Summarizer ─────────────────────────────────────────────────────────
class GeminiSummarizer:
    def __init__(self, api_key: str) -> None:
        model_name = pick_gemini_model(api_key)
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_PROMPT,
        )

    def summarize_articles(self, articles: list[dict]) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for art in articles:
            sec = art["section"]
            result.setdefault(sec, [])
            summary = self._summarize_one(art)
            if summary:
                result[sec].append(
                    {"title": art["title"], "url": art["url"], "summary": summary}
                )
        return result

    @staticmethod
    def _extract_text(resp) -> str:
        try:
            return resp.text.strip()
        except Exception:
            pass
        try:
            return resp.candidates[0].content.parts[0].text.strip()
        except Exception:
            return ""

    def _summarize_one(self, art: dict) -> Optional[str]:
        prompt = (
            f"כותרת: {art['title']}\n\n"
            f"תוכן:\n{art['content']}\n\n"
            "סכם ב-3-4 משפטים."
        )
        for attempt in range(3):
            try:
                resp = self.model.generate_content(prompt)
                text = self._extract_text(resp)
                if text:
                    return text
                log.warning("Gemini attempt %d: empty response.", attempt + 1)
            except Exception as exc:
                wait = 20 * (attempt + 1)
                log.warning("Gemini attempt %d failed: %s – waiting %ds.", attempt + 1, exc, wait)
                time.sleep(wait)
        log.error("Failed to summarize: %s", art.get("title", "?"))
        return None

    def intro_paragraph(self, summarized: dict[str, list[dict]], date_str: str) -> str:
        titles = [
            f"[{sec}] {a['title']}"
            for sec, arts in summarized.items()
            for a in arts
        ]
        if not titles:
            return ""
        bullets = "\n".join(f"- {t}" for t in titles)
        prompt = (
            f"להלן כותרות מגלובס לתאריך {date_str}:\n{bullets}\n\n"
            "כתוב 2-3 משפטי מבוא המסכמים את הנושאים המרכזיים של היום."
        )
        try:
            resp = self.model.generate_content(prompt)
            return self._extract_text(resp)
        except Exception as exc:
            log.error("Intro paragraph error: %s", exc)
            return ""


# ── Email Sender ──────────────────────────────────────────────────────────────
class EmailSender:
    def __init__(self, user: str, app_password: str) -> None:
        self.user = user
        self.app_password = app_password

    def send(self, recipient: str, summarized: dict[str, list[dict]],
             intro: str, date_str: str) -> bool:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[גלובס] תקציר יומי - {date_str}"
        msg["From"]    = self.user
        msg["To"]      = recipient
        msg.attach(MIMEText(self._plain(summarized, intro, date_str), "plain", "utf-8"))
        msg.attach(MIMEText(self._html(summarized, intro, date_str),  "html",  "utf-8"))
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as srv:
                srv.ehlo()
                srv.starttls()
                srv.login(self.user, self.app_password)
                srv.sendmail(self.user, recipient, msg.as_string())
            log.info("Email sent to %s.", recipient)
            return True
        except smtplib.SMTPAuthenticationError:
            log.error("Gmail auth failed – verify GMAIL_APP_PASSWORD in .env.")
        except Exception as exc:
            log.error("Email error: %s", exc)
        return False

    def _plain(self, summarized: dict, intro: str, date_str: str) -> str:
        lines = [f"תקציר גלובס - {date_str}", "=" * 50]
        if intro:
            lines += ["", intro, "-" * 50]
        for sec, arts in summarized.items():
            lines += ["", f"[ {sec} ]", "-" * 30]
            for a in arts:
                lines += [f"\n* {a['title']}", a["summary"], f"  {a['url']}"]
        lines.append("\n\n* נוצר אוטומטית – Globes Summarizer + Gemini AI *")
        return "\n".join(lines)

    def _html(self, summarized: dict, intro: str, date_str: str) -> str:
        def esc(s: str) -> str:
            return (s.replace("&", "&amp;").replace("<", "&lt;")
                      .replace(">", "&gt;").replace('"', "&quot;"))

        body = ""
        for sec, arts in summarized.items():
            if not arts:
                continue
            body += f'<div class="section"><div class="sec-title">&#128205; {esc(sec)}</div>'
            for a in arts:
                body += (
                    f'<div class="card">'
                    f'<div class="art-title"><a href="{esc(a["url"])}">{esc(a["title"])}</a></div>'
                    f'<div class="art-sum">{esc(a["summary"])}</div>'
                    f"</div>"
                )
            body += "</div>"

        intro_html = (
            f'<div class="intro"><strong>&#128200; סיכום היום:</strong> {esc(intro)}</div>'
            if intro else ""
        )

        return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="UTF-8">
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f4f6f8;margin:0;padding:16px;direction:rtl}}
.wrap{{max-width:680px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;
       box-shadow:0 2px 12px rgba(0,0,0,.12)}}
.hdr{{background:linear-gradient(135deg,#003366,#0055aa);color:#fff;padding:24px 28px;text-align:center}}
.hdr h1{{margin:0;font-size:22px}}.hdr .dt{{margin:4px 0 0;opacity:.85;font-size:13px}}
.intro{{background:#eef3ff;border-right:4px solid #0055aa;margin:18px;padding:14px 18px;
        border-radius:6px;font-size:14px;line-height:1.7}}
.section{{margin:0 18px 10px}}
.sec-title{{color:#003366;font-size:17px;font-weight:700;border-bottom:2px solid #0055aa;
            padding-bottom:6px;margin:18px 0 12px}}
.card{{background:#f8f9fb;border-radius:8px;padding:14px 16px;margin-bottom:10px}}
.art-title{{font-size:14px;font-weight:700;margin-bottom:6px}}
.art-title a{{color:#003366;text-decoration:none}}.art-title a:hover{{text-decoration:underline}}
.art-sum{{font-size:13px;color:#333;line-height:1.65}}
.ftr{{background:#f0f0f0;padding:12px;text-align:center;font-size:11px;color:#888;
      border-top:1px solid #ddd}}
</style></head>
<body><div class="wrap">
<div class="hdr"><h1>&#128240; תקציר יומי גלובס</h1><p class="dt">{esc(date_str)}</p></div>
{intro_html}
{body}
<div class="ftr">נוצר אוטומטית | Globes Summarizer | Gemini AI</div>
</div></body></html>"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("Globes Summarizer starting – %s", datetime.now().strftime("%d/%m/%Y %H:%M"))

    globes_email    = os.getenv("GLOBES_EMAIL",      "")
    globes_password = os.getenv("GLOBES_PASSWORD",   "")
    gmail_user      = os.getenv("GMAIL_USER",        "")
    gmail_app_pw    = os.getenv("GMAIL_APP_PASSWORD","")
    gemini_key      = os.getenv("GEMINI_API_KEY",    "")
    recipient       = os.getenv("RECIPIENT_EMAIL",   gmail_user)

    missing = [k for k, v in {
        "GEMINI_API_KEY":     gemini_key,
        "GMAIL_USER":         gmail_user,
        "GMAIL_APP_PASSWORD": gmail_app_pw,
    }.items() if not v]
    if missing:
        log.error("Missing env vars: %s – check .env file.", ", ".join(missing))
        sys.exit(1)

    scraper    = GlobesScraper()
    summarizer = GeminiSummarizer(api_key=gemini_key)
    sender     = EmailSender(user=gmail_user, app_password=gmail_app_pw)

    scraper.login(globes_email, globes_password)

    all_articles: list[dict] = []
    for sec_name, sec_url in SECTIONS.items():
        arts = scraper.get_section_articles(sec_name, sec_url)
        log.info("'%s': %d articles collected.", sec_name, len(arts))
        all_articles.extend(arts)
        time.sleep(REQUEST_DELAY)

    date_str = datetime.now().strftime("%d/%m/%Y")

    if not all_articles:
        log.warning("No articles found – sending notification email.")
        sender.send(recipient, {}, "לא נמצאו כתבות להיום.", date_str)
        return

    log.info("Total: %d articles – summarizing with Gemini...", len(all_articles))
    summarized = summarizer.summarize_articles(all_articles)
    intro      = summarizer.intro_paragraph(summarized, date_str)

    ok = sender.send(recipient, summarized, intro, date_str)

    # Save JSON for dashboard
    try:
        import json as _json
        _data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(_data_dir, exist_ok=True)
        with open(os.path.join(_data_dir, "globes_latest.json"), "w", encoding="utf-8") as _f:
            _json.dump({
                "updated": datetime.now().isoformat(),
                "date": date_str,
                "sections": {
                    sec: [{"title": a["title"], "url": a["url"], "summary": a.get("summary", "")}
                          for a in arts]
                    for sec, arts in summarized.items()
                }
            }, _f, ensure_ascii=False, indent=2)
        import subprocess
        subprocess.Popen(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_builder.py")],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as _e:
        log.warning("Dashboard update failed: %s", _e)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
