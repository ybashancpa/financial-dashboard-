#!/usr/bin/env python3
"""
Stock Spotlight
Runs Tue & Fri at 08:00.
Identifies 2 market trends from recent news, finds 1 stock per trend,
performs deep yfinance analysis, sends Hebrew analysis email.
"""

import os
import sys
import json
import re
import time
import logging
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import feedparser
import yfinance as yf
import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Logging ────────────────────────────────────────────────────────────────────
_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_spotlight.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.FileHandler(_log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── News sources ───────────────────────────────────────────────────────────────
NEWS_SOURCES = [
    {"name": "Bloomberg",       "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"name": "Financial Times", "url": "https://www.ft.com/rss/home"},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/"},
    {"name": "The Economist",   "url": "https://www.economist.com/finance-and-economics/rss.xml"},
    {"name": "HBR",             "url": "https://hbr.org/stories.rss"},
]

GEMINI_CANDIDATES = [
    "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro",
    "gemini-2.0-flash-lite", "gemini-2.0-flash",
    "gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-1.5-pro",
]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


# ── Helpers ────────────────────────────────────────────────────────────────────
def pick_gemini_model(api_key: str) -> str:
    genai.configure(api_key=api_key)
    try:
        available = {
            m.name.replace("models/", "")
            for m in genai.list_models()
            if "generateContent" in getattr(m, "supported_generation_methods", [])
        }
        for candidate in GEMINI_CANDIDATES:
            if candidate in available:
                log.info("Selected Gemini model: %s", candidate)
                return candidate
        if available:
            chosen = next(iter(available))
            log.warning("Fallback model: %s", chosen)
            return chosen
    except Exception as exc:
        log.warning("Could not list Gemini models: %s", exc)
    return "gemini-2.0-flash"


def calculate_rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_g = gain.rolling(window=period, min_periods=period).mean()
    avg_l = loss.rolling(window=period, min_periods=period).mean()
    rs    = avg_g / avg_l.replace(0, float("nan"))
    rsi   = 100 - (100 / (1 + rs))
    valid = rsi.dropna()
    return round(float(valid.iloc[-1]), 1) if not valid.empty else 0.0


def fmt_number(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A"
    try:
        v = float(val)
        if abs(v) >= 1e12:
            return f"${v/1e12:.2f}T"
        if abs(v) >= 1e9:
            return f"${v/1e9:.2f}B"
        if abs(v) >= 1e6:
            return f"${v/1e6:.2f}M"
        return f"${v:,.0f}"
    except Exception:
        return str(val)


def parse_json_from_gemini(text: str) -> list:
    text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    return json.loads(text)


def get_date_range() -> tuple[datetime, datetime]:
    """Return (start, end) for the relevant news window."""
    today   = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    weekday = datetime.now().weekday()  # 0=Mon 1=Tue … 4=Fri 6=Sun
    if weekday == 1:    # Tuesday → Sun–Tue
        start = today - timedelta(days=2)
    elif weekday == 4:  # Friday → Wed–Fri
        start = today - timedelta(days=2)
    else:               # testing / other days → last 4 days
        start = today - timedelta(days=4)
    return start.replace(hour=0, minute=0, second=0), today


def day_label() -> str:
    weekday = datetime.now().weekday()
    if weekday == 1:
        return "יום שלישי"
    if weekday == 4:
        return "יום שישי"
    return datetime.now().strftime("%A")


# ── News Fetcher ───────────────────────────────────────────────────────────────
class NewsFetcher:
    def fetch_headlines(self, start: datetime, end: datetime) -> list[str]:
        headlines = []
        for src in NEWS_SOURCES:
            try:
                feed    = feedparser.parse(src["url"], request_headers=REQUEST_HEADERS)
                fetched = 0
                for entry in feed.entries:
                    pub = entry.get("published_parsed") or entry.get("updated_parsed")
                    if pub:
                        pub_dt = datetime(*pub[:6])
                        if not (start <= pub_dt <= end):
                            continue
                    title   = entry.get("title", "").strip()
                    summary = entry.get("summary", "").strip()
                    if title:
                        headlines.append(f"[{src['name']}] {title}. {summary[:120]}")
                        fetched += 1
                log.info("%s: %d headlines in range", src["name"], fetched)
            except Exception as exc:
                log.error("Error fetching %s: %s", src["name"], exc)
        # Fallback: if date-filtered result is too thin, take latest 8 per source
        if len(headlines) < 6:
            log.warning("Few headlines in date range (%d) – using latest entries", len(headlines))
            headlines = []
            for src in NEWS_SOURCES:
                try:
                    feed = feedparser.parse(src["url"], request_headers=REQUEST_HEADERS)
                    for entry in feed.entries[:8]:
                        title = entry.get("title", "").strip()
                        summary = entry.get("summary", "").strip()
                        if title:
                            headlines.append(f"[{src['name']}] {title}. {summary[:120]}")
                except Exception:
                    pass
        log.info("Total headlines collected: %d", len(headlines))
        return headlines


# ── Trend Identifier ───────────────────────────────────────────────────────────
class TrendIdentifier:
    def __init__(self, model) -> None:
        self.model = model

    def identify(self, headlines: list[str]) -> list[dict]:
        bullets = "\n".join(f"• {h}" for h in headlines)
        prompt = (
            "להלן כותרות חדשות פיננסיות וטכנולוגיות מהימים האחרונים:\n\n"
            f"{bullets}\n\n"
            "זהה 2 טרנדים טכנולוגיים או פיננסיים חדשניים ומשמעותיים מהכתבות.\n"
            "לכל טרנד — הצע מניה אמריקאית ספציפית הנסחרת בבורסה האמריקאית (NYSE/NASDAQ) "
            "שיכולה להרוויח ממנו.\n"
            "בחר מניות עם פוטנציאל צמיחה ברור, לא מניות שנמצאות כבר בשיא.\n\n"
            "החזר אך ורק JSON תקני ללא מרקדאון, בפורמט:\n"
            '[{"trend": "...", "ticker": "SYMBOL", "company_name": "...", "reason": "..."},'
            ' {"trend": "...", "ticker": "SYMBOL", "company_name": "...", "reason": "..."}]'
        )
        for attempt in range(3):
            try:
                resp  = self.model.generate_content(prompt)
                text  = resp.text.strip()
                trends = parse_json_from_gemini(text)
                log.info("Identified trends: %s", [t.get("ticker") for t in trends])
                return trends[:2]
            except Exception as exc:
                wait = 20 * (attempt + 1)
                log.warning("Trend identification attempt %d failed: %s – waiting %ds", attempt + 1, exc, wait)
                time.sleep(wait)
        raise RuntimeError("Failed to identify trends after 3 attempts")


# ── Stock Data Collector ───────────────────────────────────────────────────────
class StockDataCollector:
    def collect(self, ticker_symbol: str) -> dict:
        log.info("Collecting yfinance data for %s", ticker_symbol)
        ticker = yf.Ticker(ticker_symbol)
        info   = ticker.info

        company = {
            "name":        info.get("longName", ticker_symbol),
            "sector":      info.get("sector", "N/A"),
            "industry":    info.get("industry", "N/A"),
            "employees":   f"{info.get('fullTimeEmployees', 'N/A'):,}" if isinstance(info.get("fullTimeEmployees"), int) else "N/A",
            "description": (info.get("longBusinessSummary") or "")[:600],
            "country":     info.get("country", "N/A"),
            "website":     info.get("website", ""),
        }

        # ── Technical indicators ──────────────────────────────────────────────
        try:
            hist  = ticker.history(period="2y")
            close = hist["Close"].dropna()
            vol   = hist["Volume"].dropna()

            technical = {
                "current_price": round(float(close.iloc[-1]), 2),
                "52w_high":      round(float(info.get("fiftyTwoWeekHigh",  close.rolling(252).max().iloc[-1])), 2),
                "52w_low":       round(float(info.get("fiftyTwoWeekLow",   close.rolling(252).min().iloc[-1])), 2),
                "ma50":          round(float(close.rolling(50).mean().iloc[-1]),  2) if len(close) >= 50  else None,
                "ma200":         round(float(close.rolling(200).mean().iloc[-1]), 2) if len(close) >= 200 else None,
                "rsi":           calculate_rsi(close),
                "avg_volume_30d": int(vol.rolling(30).mean().iloc[-1]) if len(vol) >= 30 else int(vol.mean()),
                "market_cap":    info.get("marketCap"),
                "pe_ratio":      info.get("trailingPE"),
                "forward_pe":    info.get("forwardPE"),
            }
        except Exception as exc:
            log.warning("Technical data error for %s: %s", ticker_symbol, exc)
            technical = {}

        # ── Financials (3 years annual) ───────────────────────────────────────
        financials = []
        try:
            inc = ticker.income_stmt
            for col in list(inc.columns)[:3]:
                year_label = col.strftime("%Y") if hasattr(col, "strftime") else str(col)[:4]
                revenue    = self._safe_row(inc, ["Total Revenue"], col)
                net_income = self._safe_row(inc, ["Net Income"], col)
                diluted_eps = self._safe_row(inc, ["Diluted EPS", "Basic EPS"], col)
                financials.append({
                    "year":        year_label,
                    "revenue":     revenue,
                    "net_income":  net_income,
                    "diluted_eps": diluted_eps,
                })
        except Exception as exc:
            log.warning("Financials error for %s: %s", ticker_symbol, exc)

        trailing_eps = info.get("trailingEps")
        forward_eps  = info.get("forwardEps")

        # ── Institutional holders ─────────────────────────────────────────────
        holders = []
        try:
            ih = ticker.institutional_holders
            if ih is not None and not ih.empty:
                for _, row in ih.head(5).iterrows():
                    holders.append({
                        "holder":     str(row.get("Holder", "")),
                        "pct_held":   f"{float(row.get('pctHeld', 0)) * 100:.2f}%",
                        "value":      fmt_number(row.get("Value")),
                        "pct_change": f"{float(row.get('pctChange', 0)) * 100:+.2f}%",
                    })
        except Exception as exc:
            log.warning("Institutional holders error for %s: %s", ticker_symbol, exc)

        # ── Insider transactions (last 3 months) ──────────────────────────────
        insiders = []
        try:
            it = ticker.insider_transactions
            if it is not None and not it.empty:
                cutoff = datetime.now() - timedelta(days=90)
                it_copy = it.copy()
                it_copy["_date"] = pd.to_datetime(it_copy.get("Start Date", it_copy.index), errors="coerce")
                recent = it_copy[it_copy["_date"] >= cutoff]
                for _, row in recent.head(8).iterrows():
                    insiders.append({
                        "date":        str(row.get("Start Date", ""))[:10],
                        "insider":     str(row.get("Insider", "")),
                        "position":    str(row.get("Position", "")),
                        "transaction": str(row.get("Transaction", "")),
                        "shares":      f"{int(row['Shares']):,}" if pd.notna(row.get("Shares")) else "N/A",
                        "value":       fmt_number(row.get("Value")),
                    })
        except Exception as exc:
            log.warning("Insider transactions error for %s: %s", ticker_symbol, exc)

        return {
            "ticker":        ticker_symbol,
            "company":       company,
            "technical":     technical,
            "financials":    financials,
            "trailing_eps":  trailing_eps,
            "forward_eps":   forward_eps,
            "holders":       holders,
            "insiders":      insiders,
        }

    @staticmethod
    def _safe_row(df: pd.DataFrame, row_names: list[str], col) -> Optional[float]:
        for name in row_names:
            try:
                if name in df.index:
                    val = df.loc[name, col]
                    if pd.notna(val):
                        return float(val)
            except Exception:
                pass
        return None


# ── Stock Analysis Generator ───────────────────────────────────────────────────
class StockAnalysisGenerator:
    def __init__(self, model) -> None:
        self.model = model

    def analyze(self, stock: dict, trend: dict) -> str:
        fin_text = self._fmt_financials(stock["financials"])
        tech     = stock["technical"]
        holders_text  = self._fmt_holders(stock["holders"])
        insiders_text = self._fmt_insiders(stock["insiders"])

        price = tech.get("current_price", "N/A")
        ma50  = tech.get("ma50",  "N/A")
        ma200 = tech.get("ma200", "N/A")
        rsi   = tech.get("rsi",   "N/A")
        high  = tech.get("52w_high", "N/A")
        low   = tech.get("52w_low",  "N/A")
        pe    = tech.get("pe_ratio",  "N/A")
        fpe   = tech.get("forward_pe","N/A")
        mcap  = fmt_number(tech.get("market_cap"))
        vol   = f"{tech.get('avg_volume_30d', 'N/A'):,}" if isinstance(tech.get("avg_volume_30d"), int) else "N/A"

        prompt = f"""אתה אנליסט פיננסי בכיר המייעץ לרואי חשבון ישראלים המחפשים השקעות ערך בשוק האמריקאי.

טרנד שזוהה: {trend.get("trend")}
מדוע המניה קשורה לטרנד: {trend.get("reason")}

━━ פרטי החברה ━━
מניה: {stock["ticker"]} | {stock["company"]["name"]}
סקטור: {stock["company"]["sector"]} | תעשייה: {stock["company"]["industry"]}
מדינה: {stock["company"]["country"]} | עובדים: {stock["company"]["employees"]}
שווי שוק: {mcap}
תיאור: {stock["company"]["description"]}

━━ נתונים כספיים שנתיים ━━
{fin_text}
EPS נגרר: {stock.get("trailing_eps", "N/A")} | EPS צפוי: {stock.get("forward_eps", "N/A")}

━━ ניתוח טכני ━━
מחיר נוכחי: ${price}
52W: שיא ${high} / שפל ${low}
MA50: ${ma50} | MA200: ${ma200}
RSI(14): {rsi} | P/E: {pe} | Forward P/E: {fpe}
נפח ממוצע 30 יום: {vol}

━━ 5 משקיעים מוסדיים גדולים ━━
{holders_text}

━━ עסקאות Insiders (3 חודשים אחרונים) ━━
{insiders_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
כתוב ניתוח מעמיק ומקצועי בעברית, בפורמט הבא בדיוק:

🎯 למה עכשיו:
[2-3 משפטים על הקשר לטרנד ולמה הזמן נכון]

🏆 יתרון תחרותי (Moat):
[מה מבדיל את החברה מהמתחרים, האם יש חומות ביצור]

👔 ניסיון ההנהלה:
[הערכה על ניסיון המנהלים הבכירים בתעשייה]

💰 ניתוח כספי:
[האם הצמיחה בריאה, מגמות ב-Revenue ו-Net Income, רמת הרווחיות]

📈 ניתוח טכני:
[מיקום ביחס ל-MA50/MA200, RSI, האם במגמת עלייה או ירידה]

👥 משקיעים מוסדיים:
[האם המוסדיים מגדילים / מקטינים פוזיציות]

🏦 פעילות Insiders:
[האם מנהלים קונים או מוכרים — מה זה מסמן]

⚠️ סיכונים עיקריים:
[3-4 סיכונים ספציפיים]

✅ תמצית:
[האם מעניין לעקוב, מה יהיה הטריגר לכניסה]"""

        for attempt in range(3):
            try:
                resp = self.model.generate_content(prompt)
                text = resp.text.strip()
                if text:
                    return text
            except Exception as exc:
                wait = 25 * (attempt + 1)
                log.warning("Analysis attempt %d failed: %s – waiting %ds", attempt + 1, exc, wait)
                time.sleep(wait)
        return "לא ניתן היה לייצר ניתוח."

    @staticmethod
    def _fmt_financials(financials: list[dict]) -> str:
        if not financials:
            return "N/A"
        rows = [f"{'שנה':<6} {'Revenue':<12} {'Net Income':<12} {'Diluted EPS':<10}"]
        rows.append("-" * 44)
        for f in financials:
            rows.append(
                f"{f['year']:<6} "
                f"{fmt_number(f['revenue']):<12} "
                f"{fmt_number(f['net_income']):<12} "
                f"{str(round(f['diluted_eps'], 2) if f['diluted_eps'] else 'N/A'):<10}"
            )
        return "\n".join(rows)

    @staticmethod
    def _fmt_holders(holders: list[dict]) -> str:
        if not holders:
            return "אין נתונים"
        return "\n".join(
            f"{h['holder'][:35]:<35} {h['pct_held']:>7}  ({h['pct_change']})  {h['value']}"
            for h in holders
        )

    @staticmethod
    def _fmt_insiders(insiders: list[dict]) -> str:
        if not insiders:
            return "אין עסקאות בחודשים האחרונים"
        return "\n".join(
            f"{i['date']}  {i['insider'][:25]:<25} {i['position'][:20]:<20} "
            f"{i['transaction']:<6} {i['shares']} מניות  {i['value']}"
            for i in insiders
        )


# ── Email Sender ───────────────────────────────────────────────────────────────
class EmailSender:
    def __init__(self, user: str, app_password: str) -> None:
        self.user = user
        self.app_password = app_password

    def send(self, recipient: str, stocks: list[dict], date_str: str, day_lbl: str) -> bool:
        subject = f"📈 Stock Spotlight - {day_lbl} {date_str}"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = self.user
        msg["To"]      = recipient
        msg.attach(MIMEText(self._plain(stocks, date_str, day_lbl), "plain", "utf-8"))
        msg.attach(MIMEText(self._html(stocks, date_str, day_lbl),  "html",  "utf-8"))
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as srv:
                srv.ehlo()
                srv.starttls()
                srv.login(self.user, self.app_password)
                srv.sendmail(self.user, recipient, msg.as_string())
            log.info("Email sent to %s", recipient)
            return True
        except smtplib.SMTPAuthenticationError:
            log.error("Gmail auth failed – check GMAIL_APP_PASSWORD in .env")
        except Exception as exc:
            log.error("Email error: %s", exc)
        return False

    def _plain(self, stocks: list[dict], date_str: str, day_lbl: str) -> str:
        lines = [f"📈 Stock Spotlight - {day_lbl} {date_str}", "=" * 55]
        for i, s in enumerate(stocks, 1):
            ticker = s["trend"].get("ticker", "?")
            name   = s["trend"].get("company_name", "")
            trend  = s["trend"].get("trend", "")
            lines += [
                "",
                f"🔍 טרנד {i}: {trend}",
                "━" * 45,
                f"מניה {i}: {ticker} — {name}",
                "━" * 45,
                s.get("analysis", ""),
                "",
            ]
        lines.append("\n⚠️ לידיעה בלבד — אינו מהווה המלצת השקעה")
        return "\n".join(lines)

    def _html(self, stocks: list[dict], date_str: str, day_lbl: str) -> str:
        def esc(s: str) -> str:
            return (s.replace("&", "&amp;").replace("<", "&lt;")
                      .replace(">", "&gt;").replace('"', "&quot;"))

        def fmt_analysis(text: str) -> str:
            text = esc(text)
            # Bold section headers
            text = re.sub(
                r"(🎯 למה עכשיו:|🏆 יתרון תחרותי.*?:|👔 ניסיון ההנהלה:|"
                r"💰 ניתוח כספי:|📈 ניתוח טכני:|👥 משקיעים מוסדיים:|"
                r"🏦 פעילות Insiders:|⚠️ סיכונים עיקריים:|✅ תמצית:)",
                r'<strong class="sec-lbl">\1</strong>',
                text
            )
            return text.replace("\n", "<br>")

        cards = ""
        for i, s in enumerate(stocks, 1):
            ticker  = esc(s["trend"].get("ticker", "?"))
            name    = esc(s["trend"].get("company_name", ""))
            trend   = esc(s["trend"].get("trend", ""))
            reason  = esc(s["trend"].get("reason", ""))
            tech    = s.get("stock_data", {}).get("technical", {})
            price   = tech.get("current_price", "N/A")
            rsi     = tech.get("rsi", "N/A")
            ma50    = tech.get("ma50", "N/A")
            ma200   = tech.get("ma200", "N/A")
            h52     = tech.get("52w_high", "N/A")
            l52     = tech.get("52w_low",  "N/A")
            mcap    = fmt_number(tech.get("market_cap"))
            analysis_html = fmt_analysis(s.get("analysis", ""))

            # RSI color
            rsi_class = "rsi-neutral"
            if isinstance(rsi, (int, float)):
                rsi_class = "rsi-over" if rsi > 70 else ("rsi-under" if rsi < 30 else "rsi-neutral")

            # MA trend
            trend_signal = ""
            if isinstance(price, (int, float)) and isinstance(ma200, (int, float)):
                if price > ma200:
                    trend_signal = '<span class="trend-up">▲ מעל MA200</span>'
                else:
                    trend_signal = '<span class="trend-down">▼ מתחת MA200</span>'

            cards += f"""
<div class="stock-card">
  <div class="trend-header">
    <span class="trend-num">טרנד {i}</span>
    <span class="trend-text">{trend}</span>
  </div>
  <div class="stock-header">
    <span class="ticker">{ticker}</span>
    <span class="company-name">{name}</span>
    <span class="price-badge">${price}</span>
    {trend_signal}
  </div>
  <div class="reason-box">💡 {reason}</div>

  <div class="metrics-row">
    <div class="metric"><div class="m-label">שווי שוק</div><div class="m-val">{mcap}</div></div>
    <div class="metric"><div class="m-label">52W גבוה</div><div class="m-val">${h52}</div></div>
    <div class="metric"><div class="m-label">52W נמוך</div><div class="m-val">${l52}</div></div>
    <div class="metric"><div class="m-label">MA50</div><div class="m-val">${ma50}</div></div>
    <div class="metric"><div class="m-label">MA200</div><div class="m-val">${ma200}</div></div>
    <div class="metric"><div class="m-label">RSI(14)</div>
      <div class="m-val {rsi_class}">{rsi}</div></div>
  </div>

  <div class="analysis-box">{analysis_html}</div>
</div>"""

        return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="UTF-8">
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#0d1117;margin:0;padding:16px;direction:rtl;color:#e6edf3}}
.wrap{{max-width:740px;margin:0 auto;background:#161b22;border-radius:14px;overflow:hidden;
       box-shadow:0 4px 24px rgba(0,0,0,.5)}}
.hdr{{background:linear-gradient(135deg,#1a1a2e,#0d2137,#0f3460);color:#fff;
      padding:28px 32px;text-align:center}}
.hdr h1{{margin:0;font-size:24px;letter-spacing:.5px}}
.hdr .dt{{margin:6px 0 0;opacity:.75;font-size:13px}}
.stock-card{{margin:16px;background:#1c2128;border-radius:12px;overflow:hidden;
             border:1px solid #30363d}}
.trend-header{{background:#21262d;padding:10px 16px;border-bottom:1px solid #30363d;
               display:flex;align-items:center;gap:10px}}
.trend-num{{background:#388bfd;color:#fff;font-size:11px;font-weight:700;
            padding:3px 10px;border-radius:12px}}
.trend-text{{font-size:13px;color:#8b949e;font-style:italic}}
.stock-header{{padding:14px 16px 6px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.ticker{{font-size:26px;font-weight:800;color:#58a6ff;font-family:monospace}}
.company-name{{font-size:15px;font-weight:600;color:#e6edf3;flex:1}}
.price-badge{{background:#238636;color:#fff;padding:4px 12px;border-radius:8px;
              font-size:14px;font-weight:700}}
.trend-up{{color:#3fb950;font-size:12px;font-weight:600}}
.trend-down{{color:#f85149;font-size:12px;font-weight:600}}
.reason-box{{margin:0 16px 12px;background:#0d1117;border-radius:8px;padding:10px 14px;
             font-size:13px;color:#a5d6ff;border-right:3px solid #388bfd}}
.metrics-row{{display:flex;flex-wrap:wrap;gap:8px;padding:0 16px 14px}}
.metric{{background:#21262d;border-radius:8px;padding:8px 12px;min-width:90px;text-align:center;
         border:1px solid #30363d}}
.m-label{{font-size:10px;color:#8b949e;margin-bottom:3px}}
.m-val{{font-size:14px;font-weight:700;color:#e6edf3}}
.rsi-over{{color:#f85149}}
.rsi-under{{color:#3fb950}}
.rsi-neutral{{color:#e6edf3}}
.analysis-box{{margin:0 16px 16px;background:#0d1117;border-radius:10px;padding:16px;
               font-size:13px;line-height:1.85;color:#c9d1d9;border:1px solid #21262d}}
.sec-lbl{{color:#58a6ff;font-weight:700;display:block;margin-top:10px}}
.disclaimer{{background:#21262d;padding:14px;text-align:center;font-size:11px;
             color:#6e7681;border-top:1px solid #30363d}}
</style></head>
<body><div class="wrap">
<div class="hdr">
  <h1>📈 Stock Spotlight</h1>
  <p class="dt">{esc(day_lbl)} | {esc(date_str)}</p>
</div>
{cards}
<div class="disclaimer">⚠️ לידיעה בלבד — אינו מהווה המלצת השקעה | נוצר אוטומטית | Gemini AI + yfinance</div>
</div></body></html>"""


# ── Task Scheduler Setup ───────────────────────────────────────────────────────
def setup_scheduled_tasks() -> None:
    import subprocess
    script = os.path.abspath(__file__)
    python = sys.executable

    tasks = [
        ("Stock Spotlight Tuesday", "TUE", "08:00"),
        ("Stock Spotlight Friday",  "FRI", "08:00"),
    ]
    for task_name, day, time_str in tasks:
        result = subprocess.run(
            ["schtasks", "/Create",
             "/TN", task_name,
             "/TR", f'"{python}" "{script}"',
             "/SC", "WEEKLY",
             "/D",  day,
             "/ST", time_str,
             "/RL", "HIGHEST",
             "/F"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            log.info("Scheduled task created: %s (%s %s)", task_name, day, time_str)
        else:
            log.warning("Task creation for '%s': %s", task_name, result.stderr.strip() or result.stdout.strip())


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    now = datetime.now()
    log.info("Stock Spotlight starting – %s", now.strftime("%d/%m/%Y %H:%M"))

    gmail_user   = os.getenv("GMAIL_USER", "")
    gmail_app_pw = os.getenv("GMAIL_APP_PASSWORD", "")
    gemini_key   = os.getenv("GEMINI_API_KEY", "")
    recipient    = os.getenv("RECIPIENT_EMAIL", gmail_user)

    missing = [k for k, v in {
        "GEMINI_API_KEY": gemini_key, "GMAIL_USER": gmail_user, "GMAIL_APP_PASSWORD": gmail_app_pw
    }.items() if not v]
    if missing:
        log.error("Missing env vars: %s – check .env", ", ".join(missing))
        sys.exit(1)

    # Build Gemini model
    model_name = pick_gemini_model(gemini_key)
    model      = genai.GenerativeModel(model_name=model_name)

    # Components
    fetcher    = NewsFetcher()
    identifier = TrendIdentifier(model)
    collector  = StockDataCollector()
    analyzer   = StockAnalysisGenerator(model)
    sender     = EmailSender(user=gmail_user, app_password=gmail_app_pw)

    # Date range
    start, end = get_date_range()
    log.info("News window: %s → %s", start.strftime("%d/%m/%Y"), end.strftime("%d/%m/%Y"))

    # Step 1 – fetch headlines
    headlines = fetcher.fetch_headlines(start, end)
    if not headlines:
        log.error("No headlines collected. Aborting.")
        sys.exit(1)

    # Step 2 – identify trends + tickers
    log.info("Identifying trends from %d headlines...", len(headlines))
    trends = identifier.identify(headlines)
    if not trends:
        log.error("No trends identified. Aborting.")
        sys.exit(1)

    # Step 3 & 4 – collect data + analyze each stock
    stocks_output = []
    for trend in trends:
        ticker_symbol = trend.get("ticker", "").upper().strip()
        log.info("Processing %s for trend: %s", ticker_symbol, trend.get("trend"))
        try:
            stock_data = collector.collect(ticker_symbol)
            analysis   = analyzer.analyze(stock_data, trend)
            stocks_output.append({
                "trend":      trend,
                "stock_data": stock_data,
                "analysis":   analysis,
            })
        except Exception as exc:
            log.error("Failed to process %s: %s", ticker_symbol, exc)

    if not stocks_output:
        log.error("No stocks processed successfully.")
        sys.exit(1)

    # Step 5 – send email
    date_str = now.strftime("%d/%m/%Y")
    day_lbl  = day_label()
    ok = sender.send(recipient, stocks_output, date_str, day_lbl)

    # Save JSON for dashboard
    try:
        import json as _json
        _data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(_data_dir, exist_ok=True)
        _payload = {"updated": now.isoformat(), "date": date_str, "day_label": day_lbl, "stocks": []}
        for s in stocks_output:
            tech = s.get("stock_data", {}).get("technical", {})
            _payload["stocks"].append({
                "ticker":       s["trend"].get("ticker", ""),
                "company_name": s["trend"].get("company_name", ""),
                "trend":        s["trend"].get("trend", ""),
                "reason":       s["trend"].get("reason", ""),
                "sector":       s.get("stock_data", {}).get("company", {}).get("sector", ""),
                "current_price": tech.get("current_price"),
                "52w_high":     tech.get("52w_high"),
                "52w_low":      tech.get("52w_low"),
                "ma50":         tech.get("ma50"),
                "ma200":        tech.get("ma200"),
                "rsi":          tech.get("rsi"),
                "market_cap":   tech.get("market_cap"),
                "pe":           tech.get("pe_ratio"),
                "analysis":     s.get("analysis", ""),
                "gemini_score": s.get("gemini_score", 0),
            })
        with open(os.path.join(_data_dir, "stock_spotlight_latest.json"), "w", encoding="utf-8") as _f:
            _json.dump(_payload, _f, ensure_ascii=False, indent=2)
        try:
            from gdrive_sync import upload_json as _gdrive_upload
            _gdrive_upload("stock_spotlight_latest.json", _payload)
        except Exception as _e2:
            log.warning("Drive upload failed: %s", _e2)
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
    # Register scheduled tasks on first run
    if "--setup-tasks" in sys.argv or True:  # always ensure tasks exist
        setup_scheduled_tasks()
    main()
