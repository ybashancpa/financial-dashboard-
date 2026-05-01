"""
send_demo_emails.py
Sends one demo email for each briefing type using existing JSON data.
Run: python send_demo_emails.py
"""

import sys
import os
import json
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# ── add project root to path so we can import from each script ───────────────
sys.path.insert(0, str(BASE_DIR))


def read_json(name: str) -> dict:
    p = DATA_DIR / name
    if not p.exists():
        log.warning("Missing: %s", p)
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Globes Scraper
# ─────────────────────────────────────────────────────────────────────────────
def send_globes_demo():
    log.info("── 1/5 Sending Globes demo ──")
    try:
        from globes_scraper import EmailSender
        data = read_json("globes_latest.json")
        if not data:
            log.warning("No globes_latest.json – skipping"); return

        summarized = {
            sec: [{"title": a["title"], "url": a["url"], "summary": a.get("summary","")}
                  for a in arts]
            for sec, arts in data.get("sections", {}).items()
        }
        date_str = data.get("date", datetime.now().strftime("%d/%m/%Y"))
        intro    = "עדכון גלובס יומי – דמו (נשלח ידנית)"

        sender = EmailSender(
            os.getenv("GMAIL_USER",""),
            os.getenv("GMAIL_APP_PASSWORD","")
        )
        ok = sender.send(os.getenv("RECIPIENT_EMAIL") or os.getenv("GMAIL_USER"), summarized, intro, date_str)
        log.info("Globes demo: %s", "✓ נשלח" if ok else "✗ נכשל")
    except Exception as e:
        log.error("Globes demo error: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# 2. International Briefing
# ─────────────────────────────────────────────────────────────────────────────
def send_international_demo():
    log.info("── 2/5 Sending International demo ──")
    try:
        from international_briefing import EmailSender
        data = read_json("international_latest.json")
        if not data:
            log.warning("No international_latest.json – skipping"); return

        categorized = {
            cat: [{"source": a.get("source",""), "title": a["title"],
                   "url": a["url"], "summary": a.get("summary","")}
                  for a in arts]
            for cat, arts in data.get("categories", {}).items()
        }
        date_str = data.get("date", datetime.now().strftime("%d/%m/%Y"))

        sender = EmailSender(
            os.getenv("GMAIL_USER",""),
            os.getenv("GMAIL_APP_PASSWORD","")
        )
        ok = sender.send(os.getenv("RECIPIENT_EMAIL") or os.getenv("GMAIL_USER"), categorized, date_str)
        log.info("International demo: %s", "✓ נשלח" if ok else "✗ נכשל")
    except Exception as e:
        log.error("International demo error: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Stock Spotlight
# ─────────────────────────────────────────────────────────────────────────────
def send_stocks_demo():
    log.info("── 3/5 Sending Stock Spotlight demo ──")
    try:
        from stock_spotlight import EmailSender
        data = read_json("stock_spotlight_latest.json")
        if not data:
            log.warning("No stock_spotlight_latest.json – skipping"); return

        # Reconstruct the format expected by EmailSender.send():
        # stocks = [{"trend": {...}, "stock_data": {"technical": {...}}, "analysis": "..."}]
        stocks = []
        for s in data.get("stocks", []):
            stocks.append({
                "trend": {
                    "ticker":       s.get("ticker", ""),
                    "company_name": s.get("company_name", ""),
                    "trend":        s.get("trend", ""),
                    "reason":       s.get("reason", ""),
                    "sector":       s.get("sector", ""),
                },
                "stock_data": {
                    "technical": {
                        "current_price": s.get("current_price"),
                        "52w_high":      s.get("52w_high"),
                        "52w_low":       s.get("52w_low"),
                        "ma50":          s.get("ma50"),
                        "ma200":         s.get("ma200"),
                        "rsi":           s.get("rsi"),
                        "market_cap":    s.get("market_cap"),
                        "pe":            s.get("pe"),
                    }
                },
                "analysis":     s.get("analysis", ""),
                "gemini_score": s.get("gemini_score", 0),
            })

        date_str = data.get("date", datetime.now().strftime("%d/%m/%Y"))
        day_lbl  = data.get("day_label", "")

        sender = EmailSender(
            os.getenv("GMAIL_USER",""),
            os.getenv("GMAIL_APP_PASSWORD","")
        )
        ok = sender.send(os.getenv("RECIPIENT_EMAIL") or os.getenv("GMAIL_USER"), stocks, date_str, day_lbl)
        log.info("Stock Spotlight demo: %s", "✓ נשלח" if ok else "✗ נכשל")
    except Exception as e:
        log.error("Stock Spotlight demo error: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Dividend Screener
# ─────────────────────────────────────────────────────────────────────────────
def send_dividend_demo():
    log.info("── 4/5 Sending Dividend Screener demo ──")
    try:
        from dividend_screener import EmailSender
        data = read_json("dividend_latest.json")
        if not data:
            log.warning("No dividend_latest.json – skipping"); return

        il_sel = data.get("il_stocks", [])
        us_sel = data.get("us_stocks", [])

        sender = EmailSender(
            os.getenv("GMAIL_USER",""),
            os.getenv("GMAIL_APP_PASSWORD","")
        )
        ok = sender.send(
            os.getenv("RECIPIENT_EMAIL") or os.getenv("GMAIL_USER"),
            il_sel, us_sel,
            il_total=len(il_sel) + 5,
            us_total=len(us_sel) + 20,
            il_passed=len(il_sel) + 2,
            us_passed=len(us_sel) + 8,
        )
        log.info("Dividend demo: %s", "✓ נשלח" if ok else "✗ נכשל")
    except Exception as e:
        log.error("Dividend demo error: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Tax Briefing (kolmas.net) – runs live with real login
# ─────────────────────────────────────────────────────────────────────────────
def send_tax_demo():
    log.info("── 5/5 Sending Tax Briefing (live run) ──")
    try:
        import tax_briefing
        tax_briefing.main()
    except Exception as e:
        log.error("Tax Briefing error: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("═══ שולח 5 אימיילי דמו ═══")
    send_globes_demo()
    send_international_demo()
    send_stocks_demo()
    send_dividend_demo()
    send_tax_demo()
    log.info("═══ סיום שליחת דמו ═══")
