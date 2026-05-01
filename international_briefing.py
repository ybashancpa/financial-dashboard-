#!/usr/bin/env python3
"""
International Briefing
Fetches RSS from Bloomberg, FT, The Economist, MIT Tech Review, HBR.
Filters relevant articles, summarizes with Gemini, sends via Gmail.
Schedule: Bloomberg/FT/MIT daily 07:15 | HBR/Economist Sundays only.
"""

import os
import sys
import time
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import feedparser
import google.generativeai as genai
from dotenv import load_dotenv

# Load .env from same directory as this script
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Logging ────────────────────────────────────────────────────────────────────
_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "international_briefing.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.FileHandler(_log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Sources ────────────────────────────────────────────────────────────────────
SOURCES_DAILY = [
    {"name": "Bloomberg",       "url": "https://feeds.bloomberg.com/markets/news.rss",             "base_cat": "macro"},
    {"name": "Financial Times", "url": "https://www.ft.com/rss/home",                              "base_cat": "macro"},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/",                   "base_cat": "fintech"},
]

SOURCES_SUNDAY = [
    {"name": "The Economist",   "url": "https://www.economist.com/finance-and-economics/rss.xml",  "base_cat": "strategic"},
    {"name": "HBR",             "url": "https://hbr.org/stories.rss",                             "base_cat": "strategic"},
]

# ── Filters ────────────────────────────────────────────────────────────────────
RELEVANT_KEYWORDS = {
    "financial regulation", "capital markets", "accounting", "fintech",
    "macroeconomics", "monetary policy", "tax policy", "corporate finance",
    "interest rate", "inflation", "central bank", "federal reserve",
    "ifrs", "gaap", "derivatives", "ipo", "merger", "acquisition",
    "hedge fund", "private equity", "venture capital", "cryptocurrency",
    "blockchain", "digital assets", "regulatory", "compliance",
    "fiscal policy", "treasury", "bond", "yield", "debt",
    "banking", "asset management", "esg", "audit", " tax", "tariff",
    "gdp", "recession", "economic growth", "stock market", "equity market",
    "earnings", "sec ", "financial crime", "aml",
}

REGULATION_KEYWORDS = {
    "regulation", "regulatory", "compliance", "sec ", "ifrs", "gaap",
    "audit", "tax policy", "tax reform", "accounting standard",
    "financial crime", "aml", "kyc", "enforcement", "legislation",
    "directive", "ruling", "sanction", "fine", "penalty",
}

MAX_ARTICLES_PER_SOURCE = 5
MAX_ARTICLE_CHARS = 3000
REQUEST_DELAY = 1.0

CATEGORIES = {
    "macro":      "🌍 מאקרו גלובלי",
    "regulation": "⚖️ רגולציה וציות",
    "fintech":    "💡 פינטק וטכנולוגיה",
    "strategic":  "🧠 חשיבה אסטרטגית",
}
CATEGORY_ORDER = ["macro", "regulation", "fintech", "strategic"]

GEMINI_CANDIDATES = [
    "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro",
    "gemini-2.0-flash-lite", "gemini-2.0-flash",
    "gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-1.5-pro",
]

SYSTEM_PROMPT = (
    "אתה יועץ פיננסי ומומחה לרגולציה פיננסית המסייע לרואי חשבון ישראלים. "
    "תפקידך: לתרגם ולסכם כתבות בינלאומיות ב-3-4 משפטים בעברית מקצועית וברורה. "
    "בסוף כל סיכום, הוסף שורה נפרדת: "
    "'📌 נקודה לתשומת לב לרו\"ח ישראלי:' ואחריה משפט אחד עם ההשלכה המעשית הקונקרטית."
)


# ── Helpers ────────────────────────────────────────────────────────────────────
def is_relevant(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in RELEVANT_KEYWORDS)


def detect_category(base_cat: str, text: str) -> str:
    if base_cat == "strategic":
        return "strategic"
    if base_cat == "fintech":
        return "fintech"
    t = text.lower()
    if any(kw in t for kw in REGULATION_KEYWORDS):
        return "regulation"
    return base_cat


def is_sunday() -> bool:
    return datetime.now().weekday() == 6


def pick_gemini_model(api_key: str) -> str:
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
        if available:
            chosen = next(iter(available))
            log.warning("Fallback model: %s", chosen)
            return chosen
    except Exception as exc:
        log.warning("Could not list models: %s – defaulting to gemini-2.0-flash", exc)
    return "gemini-2.0-flash"


# ── RSS Fetcher ────────────────────────────────────────────────────────────────
class RSSFetcher:
    def fetch(self, source: dict) -> list[dict]:
        name = source["name"]
        url = source["url"]
        base_cat = source["base_cat"]
        log.info("Fetching %s -> %s", name, url)
        articles = []
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )})
            entries = feed.entries
            log.info("  %d total entries from %s", len(entries), name)
            count = 0
            for entry in entries:
                if count >= MAX_ARTICLES_PER_SOURCE:
                    break
                title = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                link = entry.get("link", "")
                if not title or not link:
                    continue
                combined = f"{title} {summary}"
                if not is_relevant(combined):
                    continue
                category = detect_category(base_cat, combined)
                content = f"{title}\n\n{summary}"[:MAX_ARTICLE_CHARS]
                articles.append({
                    "source": name,
                    "title": title,
                    "url": link,
                    "content": content,
                    "category": category,
                })
                count += 1
            log.info("  %d relevant articles from %s", len(articles), name)
        except Exception as exc:
            log.error("Error fetching %s: %s", name, exc)
        return articles


# ── Gemini Summarizer ──────────────────────────────────────────────────────────
class GeminiSummarizer:
    def __init__(self, api_key: str) -> None:
        model_name = pick_gemini_model(api_key)
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_PROMPT,
        )

    def summarize(self, article: dict) -> Optional[str]:
        prompt = (
            f"מקור: {article['source']}\n"
            f"כותרת: {article['title']}\n\n"
            f"תוכן:\n{article['content']}\n\n"
            "תרגם וסכם ב-3-4 משפטים בעברית. "
            "בסוף הוסף: '📌 נקודה לתשומת לב לרו\"ח ישראלי:' עם השלכה מעשית קונקרטית."
        )
        for attempt in range(3):
            try:
                resp = self.model.generate_content(prompt)
                text = self._extract_text(resp)
                if text:
                    return text
                log.warning("Gemini attempt %d: empty response", attempt + 1)
            except Exception as exc:
                wait = 20 * (attempt + 1)
                log.warning("Gemini attempt %d failed: %s – waiting %ds", attempt + 1, exc, wait)
                time.sleep(wait)
        log.error("Failed to summarize: %s", article.get("title", "?"))
        return None

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


# ── Email Sender ───────────────────────────────────────────────────────────────
class EmailSender:
    def __init__(self, user: str, app_password: str) -> None:
        self.user = user
        self.app_password = app_password

    def send(self, recipient: str, categorized: dict, date_str: str) -> bool:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🌍 International Briefing - {date_str}"
        msg["From"] = self.user
        msg["To"] = recipient
        msg.attach(MIMEText(self._plain(categorized, date_str), "plain", "utf-8"))
        msg.attach(MIMEText(self._html(categorized, date_str), "html", "utf-8"))
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as srv:
                srv.ehlo()
                srv.starttls()
                srv.login(self.user, self.app_password)
                srv.sendmail(self.user, recipient, msg.as_string())
            log.info("Email sent to %s", recipient)
            return True
        except smtplib.SMTPAuthenticationError:
            log.error("Gmail auth failed – verify GMAIL_APP_PASSWORD in .env")
        except Exception as exc:
            log.error("Email error: %s", exc)
        return False

    def _plain(self, categorized: dict, date_str: str) -> str:
        lines = [f"International Briefing - {date_str}", "=" * 55]
        for cat_key in CATEGORY_ORDER:
            arts = categorized.get(cat_key, [])
            if not arts:
                continue
            lines += ["", CATEGORIES[cat_key], "-" * 40]
            for a in arts:
                lines += [
                    f"\n[{a['source']}] {a['title']}",
                    a.get("summary", ""),
                    f"  {a['url']}",
                ]
        lines.append("\n\n* נוצר אוטומטית – International Briefing + Gemini AI *")
        return "\n".join(lines)

    def _html(self, categorized: dict, date_str: str) -> str:
        def esc(s: str) -> str:
            return (s.replace("&", "&amp;").replace("<", "&lt;")
                      .replace(">", "&gt;").replace('"', "&quot;"))

        body = ""
        for cat_key in CATEGORY_ORDER:
            arts = categorized.get(cat_key, [])
            if not arts:
                continue
            cat_label = CATEGORIES[cat_key]
            body += f'<div class="section"><div class="sec-title">{esc(cat_label)}</div>'
            for a in arts:
                raw_sum = a.get("summary", "")
                # Highlight the CPA note line
                import re
                highlighted = re.sub(
                    r"(📌\s*נקודה לתשומת לב לרו[\"״]ח ישראלי:)",
                    r'<span class="cpa-note">\1</span>',
                    esc(raw_sum)
                )
                body += (
                    f'<div class="card">'
                    f'<span class="src-badge">{esc(a["source"])}</span>'
                    f'<div class="art-title"><a href="{esc(a["url"])}">{esc(a["title"])}</a></div>'
                    f'<div class="art-sum">{highlighted}</div>'
                    f"</div>"
                )
            body += "</div>"

        return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="UTF-8">
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;margin:0;padding:16px;direction:rtl}}
.wrap{{max-width:700px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;
       box-shadow:0 3px 18px rgba(0,0,0,.14)}}
.hdr{{background:linear-gradient(135deg,#0d1b2a,#1b3a5c,#1e5799);color:#fff;
      padding:26px 30px;text-align:center}}
.hdr h1{{margin:0;font-size:23px;letter-spacing:.5px}}
.hdr .dt{{margin:5px 0 0;opacity:.82;font-size:13px}}
.section{{margin:0 20px 10px}}
.sec-title{{font-size:17px;font-weight:700;border-bottom:2px solid #1e5799;
            padding:16px 0 8px;color:#0d1b2a}}
.card{{background:#f5f8fc;border-radius:9px;padding:14px 16px;margin:9px 0;
       border-right:4px solid #1e5799}}
.src-badge{{display:inline-block;background:#1e5799;color:#fff;font-size:10px;
            padding:2px 9px;border-radius:10px;margin-bottom:7px;font-weight:600}}
.art-title{{font-size:14px;font-weight:700;margin-bottom:7px}}
.art-title a{{color:#0d1b2a;text-decoration:none}}
.art-title a:hover{{text-decoration:underline}}
.art-sum{{font-size:13px;color:#333;line-height:1.75;white-space:pre-line}}
.cpa-note{{color:#b5451b;font-weight:700}}
.ftr{{background:#eef1f5;padding:13px;text-align:center;font-size:11px;
      color:#888;border-top:1px solid #ddd}}
</style></head>
<body><div class="wrap">
<div class="hdr">
  <h1>🌍 International Briefing</h1>
  <p class="dt">{esc(date_str)}</p>
</div>
{body}
<div class="ftr">נוצר אוטומטית | International Briefing | Gemini AI</div>
</div></body></html>"""


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    now = datetime.now()
    log.info("International Briefing starting – %s", now.strftime("%d/%m/%Y %H:%M"))

    gmail_user   = os.getenv("GMAIL_USER", "")
    gmail_app_pw = os.getenv("GMAIL_APP_PASSWORD", "")
    gemini_key   = os.getenv("GEMINI_API_KEY", "")
    recipient    = os.getenv("RECIPIENT_EMAIL", gmail_user)

    missing = [k for k, v in {
        "GEMINI_API_KEY":     gemini_key,
        "GMAIL_USER":         gmail_user,
        "GMAIL_APP_PASSWORD": gmail_app_pw,
    }.items() if not v]
    if missing:
        log.error("Missing env vars: %s – check .env file.", ", ".join(missing))
        sys.exit(1)

    sunday = is_sunday()
    sources = SOURCES_DAILY + (SOURCES_SUNDAY if sunday else [])
    log.info(
        "Running as %s – %d sources active",
        "Sunday (+ HBR/Economist)" if sunday else "weekday",
        len(sources),
    )

    fetcher    = RSSFetcher()
    summarizer = GeminiSummarizer(api_key=gemini_key)
    sender     = EmailSender(user=gmail_user, app_password=gmail_app_pw)

    all_articles: list[dict] = []
    for source in sources:
        arts = fetcher.fetch(source)
        all_articles.extend(arts)
        time.sleep(REQUEST_DELAY)

    date_str = now.strftime("%d/%m/%Y")

    if not all_articles:
        log.warning("No relevant articles found – sending notification email.")
        sender.send(recipient, {}, date_str)
        return

    log.info("Total relevant: %d articles – summarizing with Gemini...", len(all_articles))

    categorized: dict[str, list[dict]] = {k: [] for k in CATEGORY_ORDER}
    for art in all_articles:
        summary = summarizer.summarize(art)
        if summary:
            art["summary"] = summary
            categorized[art["category"]].append(art)

    total = sum(len(v) for v in categorized.values())
    log.info(
        "Done: %d articles summarized | %s",
        total,
        " | ".join(f"{CATEGORIES[k]}: {len(categorized[k])}" for k in CATEGORY_ORDER if categorized[k]),
    )

    ok = sender.send(recipient, categorized, date_str)

    # Save JSON for dashboard
    try:
        import json as _json
        _data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(_data_dir, exist_ok=True)
        with open(os.path.join(_data_dir, "international_latest.json"), "w", encoding="utf-8") as _f:
            _json.dump({
                "updated": now.isoformat(),
                "date": date_str,
                "categories": {
                    cat: [{"source": a["source"], "title": a["title"],
                           "url": a["url"], "summary": a.get("summary", "")}
                          for a in arts]
                    for cat, arts in categorized.items()
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
