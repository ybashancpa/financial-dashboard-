#!/usr/bin/env python3
"""
Dashboard Builder
Fetches macro data, reads all script JSON outputs,
generates a self-contained dashboard.html.
"""

import os
import sys
import json
import logging
import warnings
from datetime import datetime
import yfinance as yf

warnings.filterwarnings("ignore")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")
HTML_OUT  = os.path.join(BASE_DIR, "dashboard.html")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────
def load_json(fname: str, default=None):
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning("JSON load error %s: %s", fname, e)
        return default


def save_json(fname: str, data) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, fname), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def esc(s: str) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")


# ── Macro Fetcher ──────────────────────────────────────────────────────────────
MACRO_CFG = [
    ("USD/ILS",    "ILS=X",     "₪",  3,  "דולר/שקל"),
    ("S&P 500",    "^GSPC",     "",   0,  "S&P 500"),
    ("ת\"א 125",  "^TA125.TA", "",   0,  "ת\"א 125"),
    ("אג\"ח 10Y", "^TNX",      "%",  2,  "US 10Y"),
    ("נפט ברנט",   "BZ=F",      "$",  1,  "נפט ברנט"),
    ("זהב",        "GC=F",      "$",  0,  "זהב"),
]

def fetch_macro() -> list[dict]:
    results = []
    for label, ticker, unit, decimals, display in MACRO_CFG:
        try:
            hist = yf.Ticker(ticker).history(period="5d").dropna(subset=["Close"])
            if hist.empty:
                raise ValueError("empty")
            cur  = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else cur
            chg  = (cur - prev) / prev * 100 if prev else 0.0
            results.append({
                "label":   display,
                "price":   round(cur, decimals),
                "change":  round(chg, 2),
                "unit":    unit,
                "ticker":  ticker,
            })
        except Exception as exc:
            log.warning("Macro %s: %s", label, exc)
            results.append({"label": display, "price": None, "change": 0.0, "unit": unit, "ticker": ticker})
    return results


# ── Demo Data ──────────────────────────────────────────────────────────────────
def create_demo_data() -> None:
    """Write demo JSON files when real files are absent."""
    now_str = datetime.now().isoformat()

    if not os.path.exists(os.path.join(DATA_DIR, "globes_latest.json")):
        save_json("globes_latest.json", {
            "updated": now_str,
            "date": datetime.now().strftime("%d/%m/%Y"),
            "sections": {
                "ראשי": [
                    {"title": "בנק ישראל: ריבית נותרת על 4.5%", "url": "#", "summary": "הוועדה המוניטרית החליטה להותיר את הריבית ללא שינוי לאור הנתונים המאקרו-כלכליים האחרונים."},
                    {"title": "מדד המחירים לצרכן עלה ב-0.3%", "url": "#", "summary": "האינפלציה מתמתנת בהדרגה, אך נותרת מעל יעד הבנק המרכזי."},
                    {"title": "חברות ישראליות בהייטק מגייסות 1.2 מיליארד דולר", "url": "#", "summary": "גל גיוסים חדש בסטארטאפים ישראלים, בדגש על AI ו-Cybersecurity."},
                ],
                "כלכלה": [
                    {"title": "התוצר הגולמי צמח ב-2.1% ברבעון הראשון", "url": "#", "summary": "הצמיחה מעל הציפיות, מונעת על ידי יצוא שירותי טכנולוגיה."},
                    {"title": "יצוא ישראלי שובר שיאים", "url": "#", "summary": "נתוני סחר חוץ מצביעים על יצוא שיא בתעשיות הטכנולוגיה והפארמה."},
                ],
            }
        })

    if not os.path.exists(os.path.join(DATA_DIR, "international_latest.json")):
        save_json("international_latest.json", {
            "updated": now_str,
            "date": datetime.now().strftime("%d/%m/%Y"),
            "categories": {
                "macro": [
                    {"source": "Bloomberg", "title": "Fed Signals Pause in Rate Hikes", "url": "#", "summary": "הפד מסמן הפסקה במחזור העלאות הריבית לאור ירידת האינפלציה. נקודה לתשומת לב לרו\"ח ישראלי: עשוי להשפיע על שער הדולר/שקל ועל עלויות מימון חברות ישראליות."},
                    {"source": "Financial Times", "title": "European Growth Stalls in Q1", "url": "#", "summary": "הכלכלה האירופית מאטה, עם צמיחה אפסית ברבעון הראשון. נקודה לתשומת לב לרו\"ח ישראלי: חברות ישראליות עם חשיפה לאירופה עשויות להרגיש לחץ על ההכנסות."},
                ],
                "regulation": [
                    {"source": "Bloomberg", "title": "SEC Tightens Crypto Reporting Rules", "url": "#", "summary": "רשות ניירות הערך האמריקאית מחמירה דרישות דיווח לנכסי קריפטו. נקודה לתשומת לב לרו\"ח ישראלי: חברות ישראליות עם פעילות קריפטו יצטרכו לעמוד בתקנות החדשות."},
                ],
                "fintech": [
                    {"source": "MIT Tech Review", "title": "AI Models Revolutionize Financial Forecasting", "url": "#", "summary": "מודלי AI משנים את עולם החיזוי הפיננסי עם דיוק חסר תקדים. נקודה לתשומת לב לרו\"ח ישראלי: כלים חדשים לניתוח פיננסי עשויים לשפר ביקורת ובדיקת נאותות."},
                ],
                "strategic": [],
            }
        })

    if not os.path.exists(os.path.join(DATA_DIR, "stock_spotlight_latest.json")):
        save_json("stock_spotlight_latest.json", {
            "updated": now_str,
            "date": datetime.now().strftime("%d/%m/%Y"),
            "day_label": "יום שישי",
            "stocks": [
                {
                    "ticker": "MDB", "company_name": "MongoDB Inc.",
                    "trend": "האצת AI ופלטפורמות נתונים", "sector": "Technology",
                    "current_price": 245.0, "52w_high": 290.0, "52w_low": 185.0,
                    "ma50": 235.0, "ma200": 218.0, "rsi": 62.5,
                    "market_cap": 17500000000, "pe": 145.0,
                    "reason": "MongoDB נהנית מצמיחה גבוהה בשימוש במסדי נתוני וקטורים לאפליקציות AI.",
                    "analysis": "🎯 למה עכשיו:\nMongoDB ממוקמת היטב בגל ה-AI, עם Atlas Vector Search המאפשר אחסון ושאילתות על embeddings.\n\n🏆 יתרון תחרותי (Moat):\nמסד הנתונים NoSQL המוביל עם מעל 47,000 לקוחות ויכולות AI ייחודיות.\n\n💰 ניתוח כספי:\nצמיחת Revenue של 22% YoY, עם שיפור בשולי הרווח הגולמי.\n\n📈 ניתוח טכני:\nמניה מעל MA200 (תמיכה חזקה), RSI ב-62 - אזור בריא.\n\n⚠️ סיכונים עיקריים:\n1. תחרות מ-AWS/Google/Azure\n2. תמחור גבוה (P/E 145)\n3. חשיפה לקיצוץ בתקציבי IT\n\n✅ תמצית:\nמניה מעניינת לעקוב - כניסה בירידות.",
                    "gemini_score": 7,
                },
                {
                    "ticker": "OWL", "company_name": "Blue Owl Capital",
                    "trend": "צמיחת שוק ההון הפרטי", "sector": "Financial Services",
                    "current_price": 21.5, "52w_high": 26.0, "52w_low": 16.0,
                    "ma50": 20.8, "ma200": 19.5, "rsi": 55.0,
                    "market_cap": 19000000000, "pe": 38.0,
                    "reason": "Blue Owl מנהלת נכסים חלופיים עם חשיפה גבוהה ל-Private Credit הצומח.",
                    "analysis": "🎯 למה עכשיו:\nגידול בביקוש ל-Private Credit על רקע הגבלות בנקאיות מחמירות.\n\n🏆 יתרון תחרותי (Moat):\nמנהל נכסים מוביל ב-Direct Lending עם AUM של $174 מיליארד.\n\n💰 ניתוח כספי:\nFee-related earnings צומחים ב-30%+, עם הכנסות חוזרות יציבות.\n\n📈 ניתוח טכני:\nמגמת עלייה עקבית, מעל שתי הממוצעות. RSI מאוזן.\n\n⚠️ סיכונים עיקריים:\n1. סיכון אשראי בתיק ה-Private Credit\n2. הידוק רגולטורי\n3. האטה כלכלית עלולה לפגוע בביקוש\n\n✅ תמצית:\nמעניין לרו\"ח — חשיפה ייחודית לשוק הון פרטי.",
                    "gemini_score": 8,
                },
            ]
        })

    if not os.path.exists(os.path.join(DATA_DIR, "dividend_latest.json")):
        save_json("dividend_latest.json", {
            "updated": now_str,
            "month": datetime.now().strftime("%B %Y"),
            "il_stocks": [
                {"symbol": "LUMI.TA", "name": "Bank Leumi", "sector": "Financial Services",
                 "gross_yield": 0.0452, "net_yield_il": 0.0339, "payout": 0.383,
                 "roe": 0.158, "de": None, "mcap": 110000000000, "beta": 0.44,
                 "divs_in_5y": 5, "consec_growth_years": 4, "score": 75, "gemini_score": 7,
                 "analysis": "1. תיאור עסקי:\nבנק לאומי הוא אחד משני הבנקים הגדולים בישראל, עם נוכחות גלובלית.\n\n2. החפיר התחרותי:\nרשת סניפים ענפה, מיתוג חזק, ועלויות מעבר גבוהות ללקוחות.\n\n3. ניתוח דיבידנד:\nדיבידנד יציב עם מדיניות חלוקה של 40-50% מהרווח. בטוח לטווח בינוני.\n\n8. מסקנה לרו\"ח ישראלי:\nמתאים לתיק דיבידנד סולידי עם חשיפה לשוק הפיננסי הישראלי.\n\n9. ציון כולל: 7/10\nבנק יציב ומדיבידנד, אך עם מגבלות רגולטוריות."},
                {"symbol": "MZTF.TA", "name": "Mizrahi Tefahot Bank", "sector": "Financial Services",
                 "gross_yield": 0.038, "net_yield_il": 0.0285, "payout": 0.35,
                 "roe": 0.175, "de": None, "mcap": 45000000000, "beta": 0.52,
                 "divs_in_5y": 5, "consec_growth_years": 6, "score": 80, "gemini_score": 8,
                 "analysis": "1. תיאור עסקי:\nמזרחי טפחות, הבנק החמישי בגודלו בישראל, מתמחה במשכנתאות ובנקאות קמעונאית.\n\n3. ניתוח דיבידנד:\nגידול עקבי בדיבידנד עם Payout Ratio שמרני. סיכון נמוך.\n\n9. ציון כולל: 8/10\nROE גבוה וגידול עקבי בדיבידנד מהווים יתרון ברור."},
            ],
            "us_stocks": [
                {"symbol": "JNJ", "name": "Johnson & Johnson", "sector": "Healthcare",
                 "gross_yield": 0.034, "payout": 0.605, "roe": 0.26, "de": 0.5,
                 "mcap": 350000000000, "beta": 0.33, "consec_growth_years": 62,
                 "chowder": 12.5, "score": 85, "gemini_score": 9,
                 "analysis": "1. תיאור עסקי:\nJ&J היא קונגלומרט בריאות עולמי המורכב מתרופות, ציוד רפואי.\n\n2. החפיר התחרותי:\n62 שנות גידול דיבידנד רצוף - Dividend King. מוניטין בלתי ניתן לשכפול.\n\n9. ציון כולל: 9/10\nDividend King קלאסי - מתאים ביותר לתיק ארוך טווח."},
                {"symbol": "PG", "name": "Procter & Gamble", "sector": "Consumer Staples",
                 "gross_yield": 0.028, "payout": 0.62, "roe": 0.31, "de": 0.65,
                 "mcap": 360000000000, "beta": 0.40, "consec_growth_years": 68,
                 "chowder": 11.0, "score": 82, "gemini_score": 8,
                 "analysis": "1. תיאור עסקי:\nP&G מייצרת מוצרי צריכה בסיסיים המוכרים ב-180 מדינות.\n\n9. ציון כולל: 8/10\nDividend King יציב עם מוניטין עולמי."},
                {"symbol": "ADP", "name": "Automatic Data Processing", "sector": "Technology",
                 "gross_yield": 0.022, "payout": 0.60, "roe": 0.88, "de": 0.3,
                 "mcap": 105000000000, "beta": 0.88, "consec_growth_years": 50,
                 "chowder": 14.5, "score": 88, "gemini_score": 9,
                 "analysis": "1. תיאור עסקי:\nADP היא ספקית שירותי שכר, משאבי אנוש וניהול כוח אדם עולמית.\n\n9. ציון כולל: 9/10\nROE יוצא דופן (88%) עם 50 שנות גידול דיבידנד רצוף."},
            ]
        })

    if not os.path.exists(os.path.join(DATA_DIR, "watchlist.json")):
        save_json("watchlist.json", {"tickers": ["AAPL", "MSFT", "LUMI.TA"]})


# ── HTML Generator ─────────────────────────────────────────────────────────────
class HTMLGenerator:

    def generate(self, macro: list, globes: dict, intl: dict,
                 spotlight: dict, dividend: dict) -> str:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
        watchlist = load_json("watchlist.json", {"tickers": []})
        wl_json   = json.dumps(watchlist.get("tickers", []), ensure_ascii=False)

        macro_strip  = self._macro_strip(macro)
        tab_news     = self._tab_news(globes, intl)
        tab_stocks   = self._tab_stocks(spotlight)
        tab_dividend = self._tab_dividend(dividend)
        tab_watchlist = self._tab_watchlist()

        return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>📊 Financial Intelligence Dashboard</title>
<style>{self._css()}</style>
</head>
<body>

<header class="hdr">
  <div class="hdr-brand">
    <span class="hdr-icon">📊</span>
    <span class="hdr-title">Financial Intelligence Dashboard</span>
  </div>
  <div class="hdr-meta">
    <span class="hdr-updated">⏱ עודכן: {esc(timestamp)}</span>
    <button class="btn-refresh" onclick="location.reload()">🔄 רענן</button>
  </div>
</header>

{macro_strip}

<div class="tab-bar">
  <button class="tab-btn active" data-tab="news"      onclick="switchTab(this,'news')">📰 חדשות היום</button>
  <button class="tab-btn"        data-tab="stocks"    onclick="switchTab(this,'stocks')">📈 מניות</button>
  <button class="tab-btn"        data-tab="dividend"  onclick="switchTab(this,'dividend')">💰 דיבידנד</button>
  <button class="tab-btn"        data-tab="watchlist" onclick="switchTab(this,'watchlist')">📋 מעקב</button>
</div>

<div class="tab-content active" id="tab-news">{tab_news}</div>
<div class="tab-content"        id="tab-stocks">{tab_stocks}</div>
<div class="tab-content"        id="tab-dividend">{tab_dividend}</div>
<div class="tab-content"        id="tab-watchlist">{tab_watchlist}</div>

<script>
const INITIAL_WATCHLIST = {wl_json};

/* ── Tab switching ── */
function switchTab(btn, id) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + id).classList.add('active');
  localStorage.setItem('activeTab', id);
  if (id === 'watchlist') renderWatchlist();
}}

/* Restore last tab */
(function() {{
  const last = localStorage.getItem('activeTab') || 'news';
  const btn = document.querySelector('[data-tab="' + last + '"]');
  if (btn) switchTab(btn, last);
}})();

/* ── Watchlist ── */
let watchlist = JSON.parse(localStorage.getItem('watchlistTickers') || 'null');
if (!watchlist) {{
  watchlist = INITIAL_WATCHLIST;
  localStorage.setItem('watchlistTickers', JSON.stringify(watchlist));
}}

function addTicker() {{
  const inp = document.getElementById('wl-input');
  const t   = inp.value.trim().toUpperCase();
  if (!t || watchlist.includes(t)) {{ inp.value=''; return; }}
  watchlist.push(t);
  localStorage.setItem('watchlistTickers', JSON.stringify(watchlist));
  inp.value = '';
  renderWatchlist();
  fetchPrices([t]);
}}

function removeTicker(t) {{
  watchlist = watchlist.filter(x => x !== t);
  localStorage.setItem('watchlistTickers', JSON.stringify(watchlist));
  document.getElementById('wl-row-' + t.replace('.','_'))?.remove();
}}

function renderWatchlist() {{
  const tbody = document.getElementById('wl-tbody');
  tbody.innerHTML = watchlist.map(t => `
    <tr id="wl-row-${{t.replace('.','_')}}">
      <td class="wl-ticker">${{t}}</td>
      <td class="wl-price" id="wl-p-${{t.replace('.','_')}}">⏳</td>
      <td class="wl-chg"   id="wl-c-${{t.replace('.','_')}}">–</td>
      <td class="wl-yield" id="wl-y-${{t.replace('.','_')}}">–</td>
      <td><button class="btn-remove" onclick="removeTicker('${{t}}')">✕</button></td>
    </tr>`).join('');
  fetchPrices(watchlist);
}}

async function fetchPrices(tickers) {{
  for (const t of tickers) {{
    try {{
      const url = `https://query1.finance.yahoo.com/v8/finance/chart/${{t}}?interval=1d&range=5d&includePrePost=false`;
      const r   = await fetch(url, {{headers:{{'User-Agent':'Mozilla/5.0'}}}});
      const d   = await r.json();
      const res = d.chart?.result?.[0];
      if (!res) continue;
      const closes = (res.indicators.quote[0].close || []).filter(v => v != null);
      const cur  = closes.at(-1);
      const prev = closes.at(-2) ?? cur;
      const chg  = prev ? (cur - prev) / prev * 100 : 0;
      const cur$ = res.meta.currency === 'ILS' ? cur.toFixed(2) + '₪' : '$' + cur.toFixed(2);
      const safe = t.replace('.','_');
      const pEl = document.getElementById('wl-p-' + safe);
      const cEl = document.getElementById('wl-c-' + safe);
      if (pEl) pEl.textContent = cur$;
      if (cEl) {{
        cEl.textContent = (chg >= 0 ? '▲ +' : '▼ ') + chg.toFixed(2) + '%';
        cEl.className   = 'wl-chg ' + (chg >= 0 ? 'up' : 'down');
      }}
    }} catch(e) {{
      const safe = t.replace('.','_');
      const p = document.getElementById('wl-p-' + safe);
      if (p) p.textContent = 'N/A';
    }}
  }}
}}

document.getElementById('wl-input')?.addEventListener('keydown', e => {{
  if (e.key === 'Enter') addTicker();
}});

/* Auto-refresh watchlist prices every 5 min */
setInterval(() => fetchPrices(watchlist), 5 * 60 * 1000);
</script>
</body>
</html>"""

    # ── CSS ────────────────────────────────────────────────────────────────────
    def _css(self) -> str:
        return """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#0d1117;color:#e6edf3;direction:rtl;
     min-height:100vh;font-size:14px}
a{color:#58a6ff;text-decoration:none} a:hover{text-decoration:underline}

/* Header */
.hdr{background:linear-gradient(135deg,#0d1117,#161b22,#1a2332);
     padding:14px 24px;display:flex;align-items:center;justify-content:space-between;
     border-bottom:1px solid #30363d;position:sticky;top:0;z-index:100}
.hdr-brand{display:flex;align-items:center;gap:10px}
.hdr-icon{font-size:22px}
.hdr-title{font-size:18px;font-weight:700;color:#58a6ff;letter-spacing:.3px}
.hdr-meta{display:flex;align-items:center;gap:12px}
.hdr-updated{font-size:12px;color:#8b949e}
.btn-refresh{background:#21262d;border:1px solid #30363d;color:#e6edf3;padding:5px 14px;
             border-radius:6px;cursor:pointer;font-size:12px;transition:.2s}
.btn-refresh:hover{background:#388bfd;border-color:#388bfd}

/* Macro strip */
.macro-strip{display:flex;gap:10px;padding:12px 24px;background:#161b22;
             border-bottom:1px solid #30363d;overflow-x:auto;flex-wrap:nowrap}
.macro-card{background:#1c2128;border:1px solid #30363d;border-radius:10px;
            padding:10px 16px;min-width:110px;text-align:center;flex-shrink:0;
            transition:.2s} .macro-card:hover{border-color:#58a6ff}
.m-label{font-size:10px;color:#8b949e;margin-bottom:4px}
.m-price{font-size:17px;font-weight:700;color:#e6edf3}
.m-chg{font-size:11px;margin-top:3px}
.up{color:#3fb950} .down{color:#f85149}

/* Tab bar */
.tab-bar{display:flex;gap:6px;padding:12px 24px;background:#161b22;
         border-bottom:1px solid #30363d;position:sticky;top:53px;z-index:99}
.tab-btn{background:#21262d;border:1px solid #30363d;color:#8b949e;padding:7px 18px;
         border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;transition:.2s}
.tab-btn.active{background:#388bfd;border-color:#388bfd;color:#fff}
.tab-btn:hover:not(.active){background:#30363d;color:#e6edf3}

/* Tab content */
.tab-content{display:none;padding:20px 24px}
.tab-content.active{display:block}

/* News grid */
.news-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.news-col-title{font-size:15px;font-weight:700;color:#58a6ff;padding-bottom:10px;
                border-bottom:2px solid #30363d;margin-bottom:12px}
.news-card{background:#1c2128;border:1px solid #30363d;border-radius:8px;
           padding:12px 14px;margin-bottom:10px;border-right:3px solid #388bfd;
           transition:.15s} .news-card:hover{background:#21262d}
.news-card.cat-macro{border-right-color:#388bfd}
.news-card.cat-regulation{border-right-color:#8957e5}
.news-card.cat-fintech{border-right-color:#3fb950}
.news-card.cat-strategic{border-right-color:#d29922}
.news-card.cat-news{border-right-color:#58a6ff}
.news-source{display:inline-block;background:#21262d;font-size:10px;color:#8b949e;
             padding:2px 7px;border-radius:8px;margin-bottom:5px}
.news-title{font-size:13px;font-weight:600;line-height:1.4;margin-bottom:5px}
.news-summary{font-size:12px;color:#8b949e;line-height:1.65}
.cpa-note{color:#d29922;font-weight:600}

/* Stock cards (spotlight) */
.stocks-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.stock-card{background:#1c2128;border:1px solid #30363d;border-radius:12px;overflow:hidden}
.sc-trend{background:#21262d;padding:9px 14px;font-size:11px;color:#8b949e;
          border-bottom:1px solid #30363d;display:flex;align-items:center;gap:8px}
.trend-pill{background:#388bfd22;border:1px solid #388bfd;color:#58a6ff;
            padding:2px 9px;border-radius:10px;font-size:11px}
.sc-header{padding:12px 16px 6px;display:flex;align-items:baseline;gap:10px}
.sc-ticker{font-size:26px;font-weight:800;color:#58a6ff;font-family:monospace}
.sc-name{font-size:13px;color:#8b949e}
.sc-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:8px 16px 12px}
.sm{background:#21262d;border-radius:7px;padding:7px 9px;text-align:center;border:1px solid #30363d}
.sm-l{font-size:10px;color:#8b949e;margin-bottom:2px}
.sm-v{font-size:13px;font-weight:700}
.sc-analysis{margin:0 16px 10px;background:#0d1117;border-radius:8px;padding:13px;
              font-size:12px;line-height:1.8;color:#c9d1d9;border:1px solid #21262d;
              max-height:250px;overflow-y:auto}
.sc-analysis strong,.an-h{color:#58a6ff;font-weight:700}
.sc-score{padding:10px 16px 14px;display:flex;align-items:center;gap:10px}
.score-bar-wrap{flex:1;background:#21262d;border-radius:6px;height:8px;overflow:hidden}
.score-bar-fill{height:100%;border-radius:6px;background:linear-gradient(90deg,#388bfd,#3fb950);transition:width .5s}
.score-label{font-size:13px;font-weight:700;color:#3fb950;min-width:45px;text-align:center}

/* Dividend cards */
.div-section-title{font-size:15px;font-weight:700;padding:0 0 10px;border-bottom:2px solid #30363d;margin-bottom:14px}
.div-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin-bottom:24px}
.div-card{background:#1c2128;border:1px solid #30363d;border-radius:12px;overflow:hidden}
.div-card.il{border-top:3px solid #1f6feb}
.div-card.us{border-top:3px solid #238636}
.dc-header{padding:12px 16px 6px;display:flex;align-items:baseline;gap:10px}
.dc-ticker{font-size:20px;font-weight:800;font-family:monospace}
.il .dc-ticker{color:#58a6ff} .us .dc-ticker{color:#3fb950}
.dc-name{font-size:12px;color:#8b949e}
.dc-sector{font-size:10px;background:#21262d;padding:2px 7px;border-radius:8px;color:#8b949e;margin-right:auto}
.dc-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding:6px 16px 10px}
.dm{background:#21262d;border-radius:6px;padding:6px 8px;text-align:center}
.dm-l{font-size:9px;color:#8b949e;margin-bottom:2px}
.dm-v{font-size:12px;font-weight:700}
.dm-v.hi{color:#3fb950;font-size:14px}
.dc-score{padding:8px 16px;display:flex;align-items:center;gap:8px;font-size:12px;color:#8b949e}
.dc-score strong{color:#f1c40f}

/* Watchlist */
.wl-header{display:flex;align-items:center;gap:12px;margin-bottom:18px;flex-wrap:wrap}
.wl-title{font-size:16px;font-weight:700;color:#58a6ff}
.wl-input-wrap{display:flex;gap:8px;margin-right:auto}
#wl-input{background:#21262d;border:1px solid #30363d;color:#e6edf3;padding:7px 14px;
           border-radius:8px;font-size:13px;width:180px;outline:none}
#wl-input:focus{border-color:#58a6ff}
.btn-add{background:#238636;border:none;color:#fff;padding:7px 18px;border-radius:8px;
         cursor:pointer;font-size:13px} .btn-add:hover{background:#2ea043}
.wl-table-wrap{background:#1c2128;border:1px solid #30363d;border-radius:10px;overflow:hidden}
table.wl-table{width:100%;border-collapse:collapse}
.wl-table th{background:#21262d;color:#8b949e;padding:10px 14px;text-align:center;
             font-size:12px;font-weight:600;border-bottom:1px solid #30363d}
.wl-table td{padding:10px 14px;text-align:center;border-top:1px solid #21262d;font-size:13px}
.wl-table tr:hover td{background:#21262d}
.wl-ticker{font-weight:700;font-family:monospace;color:#58a6ff;text-align:right!important}
.wl-price{font-weight:700}
.btn-remove{background:#da3633;border:none;color:#fff;padding:3px 9px;border-radius:6px;
            cursor:pointer;font-size:11px} .btn-remove:hover{background:#b91c1c}
.wl-hint{font-size:11px;color:#6e7681;margin-top:8px;text-align:center}

/* Score bar */
.score-bar-wrap{flex:1;background:#21262d;border-radius:6px;height:8px}
.score-bar-fill{height:100%;border-radius:6px}

@media(max-width:768px){
  .news-grid,.stocks-grid{grid-template-columns:1fr}
  .macro-strip{gap:7px;padding:10px 14px}
  .tab-bar{padding:10px 14px;gap:4px}
  .tab-btn{padding:6px 11px;font-size:12px}
  .tab-content{padding:14px}
}"""

    # ── Macro strip ────────────────────────────────────────────────────────────
    def _macro_strip(self, macro: list) -> str:
        cards = ""
        for m in macro:
            if m.get("price") is None:
                cards += f'<div class="macro-card"><div class="m-label">{esc(m["label"])}</div><div class="m-price" style="font-size:13px;color:#6e7681">N/A</div></div>'
                continue
            chg   = m["change"]
            unit  = m["unit"]
            price = m["price"]
            # Format price display
            if unit == "₪":
                price_str = f"{price}{unit}"
            elif unit == "%":
                price_str = f"{price}%"
            elif unit == "$":
                price_str = f"${price:,.0f}" if price > 100 else f"${price:.1f}"
            else:
                price_str = f"{price:,.0f}" if price > 100 else str(price)

            chg_class = "up" if chg >= 0 else "down"
            chg_icon  = "▲" if chg >= 0 else "▼"
            cards += f"""<div class="macro-card">
  <div class="m-label">{esc(m["label"])}</div>
  <div class="m-price">{esc(price_str)}</div>
  <div class="m-chg {chg_class}">{chg_icon} {abs(chg):.2f}%</div>
</div>"""
        return f'<div class="macro-strip">{cards}</div>'

    # ── News tab ───────────────────────────────────────────────────────────────
    def _tab_news(self, globes: dict, intl: dict) -> str:
        # Globes column
        globes_cards = ""
        sections = globes.get("sections", {})
        for sec, articles in sections.items():
            for a in articles:
                title   = esc(a.get("title", ""))
                url     = esc(a.get("url", "#"))
                summary = esc(a.get("summary", ""))
                globes_cards += f"""<div class="news-card cat-news">
  <div class="news-source">גלובס — {esc(sec)}</div>
  <div class="news-title"><a href="{url}" target="_blank">{title}</a></div>
  <div class="news-summary">{summary}</div>
</div>"""
        if not globes_cards:
            globes_cards = '<p style="color:#6e7681;font-size:12px">אין נתונים — הרץ globes_scraper.py</p>'

        # International column
        CAT_LABELS = {
            "macro":      ("cat-macro",      "🌍 מאקרו גלובלי"),
            "regulation": ("cat-regulation", "⚖️ רגולציה"),
            "fintech":    ("cat-fintech",    "💡 פינטק"),
            "strategic":  ("cat-strategic",  "🧠 אסטרטגיה"),
        }
        intl_cards = ""
        categories = intl.get("categories", {})
        for cat_key, (css_cls, cat_label) in CAT_LABELS.items():
            articles = categories.get(cat_key, [])
            for a in articles:
                title   = esc(a.get("title", ""))
                url     = esc(a.get("url", "#"))
                source  = esc(a.get("source", ""))
                summary = a.get("summary", "")
                # Highlight CPA note
                import re
                summary_esc = esc(summary)
                summary_esc = re.sub(
                    r"(📌\s*נקודה לתשומת לב לרו[\"״]ח ישראלי:)",
                    r'<span class="cpa-note">\1</span>', summary_esc
                )
                intl_cards += f"""<div class="news-card {css_cls}">
  <div class="news-source">{source} · {cat_label}</div>
  <div class="news-title"><a href="{url}" target="_blank">{title}</a></div>
  <div class="news-summary">{summary_esc}</div>
</div>"""
        if not intl_cards:
            intl_cards = '<p style="color:#6e7681;font-size:12px">אין נתונים — הרץ international_briefing.py</p>'

        updated_g = globes.get("date", "—")
        updated_i = intl.get("date", "—")
        return f"""<div class="news-grid">
  <div>
    <div class="news-col-title">🇮🇱 גלובס <small style="color:#6e7681;font-size:11px">{esc(updated_g)}</small></div>
    {globes_cards}
  </div>
  <div>
    <div class="news-col-title">🌍 בינלאומי <small style="color:#6e7681;font-size:11px">{esc(updated_i)}</small></div>
    {intl_cards}
  </div>
</div>"""

    # ── Stocks tab ─────────────────────────────────────────────────────────────
    def _tab_stocks(self, spotlight: dict) -> str:
        stocks = spotlight.get("stocks", [])
        if not stocks:
            return '<p style="color:#6e7681">אין נתונים — הרץ stock_spotlight.py</p>'

        cards = ""
        for s in stocks[:2]:
            ticker   = esc(s.get("ticker", "?"))
            name     = esc(s.get("company_name", ""))
            trend    = esc(s.get("trend", ""))
            sector   = esc(s.get("sector", ""))
            price    = s.get("current_price", "N/A")
            ma50     = s.get("ma50", "N/A")
            ma200    = s.get("ma200", "N/A")
            rsi      = s.get("rsi", "N/A")
            h52      = s.get("52w_high", "N/A")
            l52      = s.get("52w_low", "N/A")
            pe       = s.get("pe", "N/A")
            analysis = self._fmt_analysis(s.get("analysis", ""))
            score    = int(s.get("gemini_score", 0))
            score_w  = score * 10

            cards += f"""<div class="stock-card">
  <div class="sc-trend">
    <span style="color:#8b949e">טרנד:</span>
    <span class="trend-pill">{trend}</span>
    <span style="margin-right:auto;font-size:10px">{esc(sector)}</span>
  </div>
  <div class="sc-header">
    <span class="sc-ticker">{ticker}</span>
    <span class="sc-name">{name}</span>
  </div>
  <div class="sc-metrics">
    <div class="sm"><div class="sm-l">מחיר</div><div class="sm-v">${price}</div></div>
    <div class="sm"><div class="sm-l">52W גבוה</div><div class="sm-v">${h52}</div></div>
    <div class="sm"><div class="sm-l">52W נמוך</div><div class="sm-v">${l52}</div></div>
    <div class="sm"><div class="sm-l">MA50</div><div class="sm-v">${ma50}</div></div>
    <div class="sm"><div class="sm-l">MA200</div><div class="sm-v">${ma200}</div></div>
    <div class="sm"><div class="sm-l">RSI</div><div class="sm-v">{rsi}</div></div>
  </div>
  <div class="sc-analysis">{analysis}</div>
  <div class="sc-score">
    <span style="font-size:12px;color:#8b949e">ציון Gemini:</span>
    <div class="score-bar-wrap">
      <div class="score-bar-fill" style="width:{score_w}%;background:{'#3fb950' if score>=7 else '#d29922' if score>=5 else '#f85149'}"></div>
    </div>
    <span class="score-label" style="color:{'#3fb950' if score>=7 else '#d29922' if score>=5 else '#f85149'}">{score}/10</span>
  </div>
</div>"""

        updated = spotlight.get("date", "—")
        day_lbl  = spotlight.get("day_label", "")
        return f"""<div style="margin-bottom:14px">
  <span style="font-size:12px;color:#6e7681">דוח אחרון: {esc(day_lbl)} {esc(updated)}</span>
</div>
<div class="stocks-grid">{cards}</div>"""

    # ── Dividend tab ───────────────────────────────────────────────────────────
    def _tab_dividend(self, dividend: dict) -> str:
        if not dividend:
            return '<p style="color:#6e7681">אין נתונים — הרץ dividend_screener.py</p>'

        def stock_card(d: dict, market: str) -> str:
            sym     = esc(d.get("symbol", "?"))
            name    = esc(d.get("name", ""))
            sector  = esc(d.get("sector", ""))
            yld     = d.get("net_yield_il") if market == "IL" else d.get("gross_yield")
            yld_str = f"{yld*100:.1f}%" if yld else "N/A"
            payout  = d.get("payout")
            po_str  = f"{payout*100:.0f}%" if payout else "N/A"
            roe     = d.get("roe")
            roe_str = f"{roe*100:.0f}%" if roe else "N/A"
            consec  = d.get("consec_growth_years", 0)
            score   = int(d.get("gemini_score", 0))
            chowder = d.get("chowder", "")
            chowder_html = f'<div class="dm"><div class="dm-l">Chowder</div><div class="dm-v">{chowder}</div></div>' if chowder else ""
            return f"""<div class="div-card {market.lower()}">
  <div class="dc-header">
    <span class="dc-ticker">{sym}</span>
    <span class="dc-name">{name}</span>
    <span class="dc-sector">{sector}</span>
  </div>
  <div class="dc-metrics">
    <div class="dm"><div class="dm-l">{"תשואה נטו" if market=="IL" else "תשואה"}</div><div class="dm-v hi">{yld_str}</div></div>
    <div class="dm"><div class="dm-l">Payout</div><div class="dm-v">{po_str}</div></div>
    <div class="dm"><div class="dm-l">ROE</div><div class="dm-v">{roe_str}</div></div>
    <div class="dm"><div class="dm-l">שנות גידול</div><div class="dm-v">{consec}y</div></div>
    {chowder_html}
  </div>
  <div class="dc-score">
    ⭐ ציון Gemini: <strong style="color:{'#3fb950' if score>=7 else '#d29922'}">{score}/10</strong>
    <div class="score-bar-wrap" style="flex:1;margin-right:8px">
      <div class="score-bar-fill" style="width:{score*10}%;background:{'#3fb950' if score>=7 else '#d29922'}"></div>
    </div>
  </div>
</div>"""

        il_cards = "".join(stock_card(d, "IL") for d in dividend.get("il_stocks", []))
        us_cards = "".join(stock_card(d, "US") for d in dividend.get("us_stocks", []))
        month = dividend.get("month", "—")

        return f"""<div style="margin-bottom:14px">
  <span style="font-size:12px;color:#6e7681">דוח חודשי: {esc(month)}</span>
</div>
<div class="div-section-title">🇮🇱 שוק ישראלי</div>
<div class="div-grid">{il_cards or '<p style="color:#6e7681">אין נתונים</p>'}</div>
<div class="div-section-title">🇺🇸 שוק אמריקאי</div>
<div class="div-grid">{us_cards or '<p style="color:#6e7681">אין נתונים</p>'}</div>"""

    # ── Watchlist tab ──────────────────────────────────────────────────────────
    def _tab_watchlist(self) -> str:
        return """<div class="wl-header">
  <span class="wl-title">📋 רשימת מעקב אישית</span>
  <div class="wl-input-wrap">
    <input id="wl-input" type="text" placeholder="הקלד טיקר (AAPL, LUMI.TA...)">
    <button class="btn-add" onclick="addTicker()">+ הוסף</button>
  </div>
</div>
<div class="wl-table-wrap">
  <table class="wl-table">
    <thead><tr>
      <th style="text-align:right">טיקר</th>
      <th>מחיר</th>
      <th>שינוי יומי</th>
      <th>תשואת דיב'</th>
      <th>הסר</th>
    </tr></thead>
    <tbody id="wl-tbody"></tbody>
  </table>
</div>
<p class="wl-hint">⏱ המחירים מתרעננים כל 5 דקות אוטומטית | נשמר בדפדפן</p>"""

    # ── Analysis formatter ─────────────────────────────────────────────────────
    @staticmethod
    def _fmt_analysis(text: str) -> str:
        import re
        text = esc(text)
        text = re.sub(
            r"(🎯[^:]*:|🏆[^:]*:|👔[^:]*:|💰[^:]*:|📈[^:]*:|"
            r"👥[^:]*:|🏦[^:]*:|⚠️[^:]*:|✅[^:]*:|"
            r"\d+\.\s+(?:תיאור|החפיר|ניתוח|סיכון|מסקנה|ציון|סביבה|תמחור)[^:]*:)",
            r'<strong class="an-h">\1</strong>',
            text
        )
        return text.replace("\n", "<br>")


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("Dashboard Builder starting – %s", datetime.now().strftime("%d/%m/%Y %H:%M"))
    os.makedirs(DATA_DIR, exist_ok=True)

    # Generate demo data for missing files
    create_demo_data()

    # Fetch macro
    log.info("Fetching macro data...")
    macro = fetch_macro()
    save_json("macro_latest.json", {
        "updated": datetime.now().isoformat(),
        "data": macro,
    })

    # Load all JSON
    globes   = load_json("globes_latest.json",        {})
    intl     = load_json("international_latest.json",  {})
    spotlight = load_json("stock_spotlight_latest.json", {})
    dividend = load_json("dividend_latest.json",       {})

    # Generate HTML
    html = HTMLGenerator().generate(macro, globes, intl, spotlight, dividend)
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html)
    log.info("Dashboard written: %s", HTML_OUT)


if __name__ == "__main__":
    main()
