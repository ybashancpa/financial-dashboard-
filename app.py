import os
import json
import math
import re
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, render_template
from dotenv import load_dotenv
import yfinance as yf
from google import genai

load_dotenv()

app = Flask(__name__)
DATA_DIR = Path(__file__).parent / "data"

IS_RENDER = bool(os.getenv('RENDER'))
if IS_RENDER:
    from gdrive_sync import download_json as _gdrive_dl
    DATA_DIR.mkdir(exist_ok=True)
    for _fname in ('globes_latest.json', 'international_latest.json',
                   'stock_spotlight_latest.json', 'dividend_latest.json'):
        try:
            _d = _gdrive_dl(_fname)
            if _d:
                (DATA_DIR / _fname).write_text(
                    json.dumps(_d, ensure_ascii=False, indent=2), encoding='utf-8'
                )
        except Exception as _e:
            print(f"[startup] {_fname}: {_e}")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

MACRO_SPECS = [
    {"label": "דולר/שקל", "ticker": "ILS=X",    "unit": "₪", "dec": 3},
    {"label": "S&P 500",  "ticker": "^GSPC",    "unit": "",  "dec": 0},
    {"label": 'ת"א 125', "ticker": "^TA125.TA", "unit": "",  "dec": 0},
    {"label": "US 10Y",   "ticker": "^TNX",     "unit": "%", "dec": 2},
    {"label": "נפט ברנט", "ticker": "BZ=F",     "unit": "$", "dec": 2},
    {"label": "זהב",      "ticker": "GC=F",     "unit": "$", "dec": 0},
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_price(val, unit, dec):
    if unit == "₪":
        return f"{val:.{dec}f}₪"
    if unit == "%":
        return f"{val:.{dec}f}%"
    if unit == "$":
        return f"${val:,.{dec}f}" if dec else f"${val:,.0f}"
    return f"{val:,.{dec}f}" if dec else f"{val:,.0f}"


def fmt_big(n):
    if n is None or (isinstance(n, float) and math.isnan(n)):
        return "N/A"
    n = float(n)
    if abs(n) >= 1e12:
        return f"${n/1e12:.2f}T"
    if abs(n) >= 1e9:
        return f"${n/1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"${n/1e6:.2f}M"
    return f"${n:,.0f}"


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 1)


def read_json(path: Path):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def write_json(path: Path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_ticker_live(ticker: str) -> dict:
    item = {"ticker": ticker, "price": "–", "change": 0, "up": True,
            "div_yield": "–", "market_cap": "–"}
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        if hist.empty:
            return item
        closes = hist["Close"].dropna().tolist()
        cur = closes[-1]
        prev = closes[-2] if len(closes) >= 2 else cur
        chg = (cur - prev) / prev * 100 if prev else 0
        info = t.info
        suffix = "₪" if info.get("currency") == "ILS" else "$"
        item["price"] = f"{suffix}{cur:.2f}"
        item["change"] = round(chg, 2)
        item["up"] = chg >= 0
        dy = info.get("dividendYield") or info.get("yield") or info.get("trailingAnnualDividendYield")
        item["div_yield"] = f"{dy*100:.2f}%" if dy else "–"
        fpe = info.get("forwardPE")
        item["forward_pe"] = round(fpe, 1) if fpe else None
        mc = info.get("marketCap") or info.get("totalAssets")
        item["market_cap"] = fmt_big(mc) if mc else "–"
    except Exception as e:
        item["error"] = str(e)
    return item


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/macro")
def api_macro():
    items = []
    for m in MACRO_SPECS:
        try:
            hist = yf.Ticker(m["ticker"]).history(period="5d")
            if hist.empty:
                raise ValueError("no data")
            closes = hist["Close"].dropna().tolist()
            cur = closes[-1]
            prev = closes[-2] if len(closes) >= 2 else cur
            chg = (cur - prev) / prev * 100 if prev else 0
            items.append({
                "label": m["label"],
                "price": fmt_price(cur, m["unit"], m["dec"]),
                "change": round(chg, 2),
                "up": chg >= 0,
            })
        except Exception:
            items.append({"label": m["label"], "price": "–", "change": 0, "up": True})
    return jsonify({"updated": datetime.now().strftime("%d/%m/%Y %H:%M"), "items": items})


@app.route("/api/news")
def api_news():
    return jsonify({
        "globes": read_json(DATA_DIR / "globes_latest.json"),
        "international": read_json(DATA_DIR / "international_latest.json"),
    })


@app.route("/api/stocks")
def api_stocks():
    return jsonify(read_json(DATA_DIR / "stock_spotlight_latest.json"))


@app.route("/api/dividends")
def api_dividends():
    data = read_json(DATA_DIR / "dividend_latest.json")
    for s in data.get("us_stocks", []):
        gy = s.get("gross_yield")
        if gy and gy > 0.5:  # stored 100x too large due to yfinance format change
            s["gross_yield"] = gy / 100
            s["net_yield_il"] = s["gross_yield"] * 0.75
            cagr = s.get("div5_cagr") or 0
            if s.get("chowder") is not None:
                s["chowder"] = round((s["gross_yield"] + cagr) * 100, 1)
    return jsonify(data)


@app.route("/api/watchlist", methods=["GET"])
def api_watchlist_get():
    tickers = read_json(DATA_DIR / "watchlist.json").get("tickers", [])
    return jsonify({"tickers": [fetch_ticker_live(t) for t in tickers]})


@app.route("/api/watchlist/add", methods=["POST"])
def api_watchlist_add():
    body = request.get_json(force=True) or {}
    ticker = body.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    wl = read_json(DATA_DIR / "watchlist.json")
    tickers = wl.get("tickers", [])
    if ticker not in tickers:
        tickers.append(ticker)
        write_json(DATA_DIR / "watchlist.json", {"tickers": tickers})
    return jsonify(fetch_ticker_live(ticker))


@app.route("/api/watchlist/remove", methods=["DELETE"])
def api_watchlist_remove():
    body = request.get_json(force=True) or {}
    ticker = body.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    wl = read_json(DATA_DIR / "watchlist.json")
    write_json(DATA_DIR / "watchlist.json",
               {"tickers": [x for x in wl.get("tickers", []) if x != ticker]})
    return jsonify({"ok": True})


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    body = request.get_json(force=True) or {}
    ticker = body.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    if not gemini_client:
        return jsonify({"error": "GEMINI_API_KEY לא מוגדר ב-.env"}), 500

    try:
        t = yf.Ticker(ticker)
        info = t.info
        hist_1y = t.history(period="1y")
        closes = hist_1y["Close"].dropna().tolist()

        cur = closes[-1] if closes else None
        ma50  = round(sum(closes[-50:])  / min(50,  len(closes)), 2) if closes else None
        ma200 = round(sum(closes[-200:]) / min(200, len(closes)), 2) if closes else None
        rsi   = calc_rsi(closes)
        hi52  = round(max(closes), 2) if closes else None
        lo52  = round(min(closes), 2) if closes else None

        company = info.get("longName", ticker)
        sector  = info.get("sector", "N/A")
        mcap    = fmt_big(info.get("marketCap"))
        pe      = info.get("trailingPE")
        fpe     = info.get("forwardPE")
        dy      = info.get("dividendYield") or info.get("yield") or info.get("trailingAnnualDividendYield")
        dy_pct  = round(dy * 100, 2) if dy else None
        payout  = info.get("payoutRatio")

        fin_lines = []
        try:
            fin = t.financials
            for col in list(fin.columns)[:3]:
                yr  = col.year if hasattr(col, "year") else str(col)
                rev = fin.loc["Total Revenue", col] if "Total Revenue" in fin.index else None
                net = fin.loc["Net Income",    col] if "Net Income"    in fin.index else None
                fin_lines.append(f"  {yr}: הכנסות {fmt_big(rev)}, רווח נקי {fmt_big(net)}")
        except Exception:
            pass

        inst_lines = []
        try:
            inst = t.institutional_holders
            if inst is not None and not inst.empty:
                for _, row in inst.head(5).iterrows():
                    pct = row.get("pctHeld", 0) or 0
                    inst_lines.append(f"  - {row.get('Holder','?')}: {pct*100:.2f}%")
        except Exception:
            pass

        ins_lines = []
        try:
            ins = t.insider_transactions
            if ins is not None and not ins.empty:
                for _, row in ins.head(5).iterrows():
                    ins_lines.append(
                        f"  - {row.get('Insider','?')} | {row.get('Transaction','?')} | {fmt_big(row.get('Value', 0))}"
                    )
        except Exception:
            pass

        prompt = f"""אתה אנליסט פיננסי בכיר. נתח את המניה {ticker} ({company}) עבור רו"ח ישראלי.

נתוני שוק:
- מחיר: ${f"{cur:.2f}" if cur else "N/A"} | שווי שוק: {mcap} | סקטור: {sector}
- P/E: {round(pe,2) if pe else "N/A"} | Forward P/E: {round(fpe,2) if fpe else "N/A"}
- 52W גבוה/נמוך: ${hi52} / ${lo52}
- MA50: ${ma50} | MA200: ${ma200} | RSI(14): {rsi}
- תשואת דיב': {f"{dy_pct:.2f}%" if dy_pct else "אין"} | Payout: {f"{payout*100:.1f}%" if payout else "N/A"}

נתונים כספיים (3 שנים):
{chr(10).join(fin_lines) if fin_lines else "  לא זמין"}

משקיעים מוסדיים:
{chr(10).join(inst_lines) if inst_lines else "  לא זמין"}

עסקאות Insiders:
{chr(10).join(ins_lines) if ins_lines else "  לא זמין"}

כתוב ניתוח מעמיק בעברית עם 7 סעיפים מודגשים:
**1. תיאור עסקי קצר**
**2. חוזקות וחולשות מהנתונים**
**3. ניתוח טכני – מגמה נוכחית**
**4. האם הדיבידנד בטוח?**
**5. סיכונים עיקריים**
**6. תמחור – זול/הוגן/יקר**
**7. ציון 1-10 עם המלצה** (פורמט: ציון: X/10)"""

        response = gemini_client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        analysis = response.text

        score = 5
        m = re.search(r"ציון[:\s]*(\d+)\s*/\s*10", analysis)
        if m:
            score = int(m.group(1))

        change = 0
        if len(closes) >= 2:
            change = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)

        return jsonify({
            "ticker":     ticker,
            "company":    company,
            "sector":     sector,
            "price":      f"${cur:.2f}" if cur else "N/A",
            "change":     change,
            "up":         change >= 0,
            "ma50":       ma50,
            "ma200":      ma200,
            "rsi":        rsi,
            "hi52":       hi52,
            "lo52":       lo52,
            "market_cap": mcap,
            "div_yield":  f"{dy_pct:.2f}%" if dy_pct else "–",
            "pe":         round(pe, 2) if pe else None,
            "forward_pe": round(fpe, 2) if fpe else None,
            "analysis":   analysis,
            "score":      score,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/ping')
def ping():
    return 'ok', 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
