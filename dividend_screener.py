#!/usr/bin/env python3
"""
Dividend Screener — Monthly Intelligence Report
Module A: Israeli market (TA-125), select 2 stocks
Module B: US Dividend Aristocrats, select 3 stocks
Gemini deep-analysis for each, HTML email + CSV export.
Runs on the 1st of every month at 08:30.
"""

import os
import sys
import csv
import time
import logging
import smtplib
import warnings
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import yfinance as yf
import pandas as pd
from google import genai
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Logging ────────────────────────────────────────────────────────────────────
_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dividend_screener.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.FileHandler(_log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Israeli TA-125 universe ────────────────────────────────────────────────────
TA125_TICKERS = [
    # Banks
    "LUMI.TA", "POLI.TA", "MZTF.TA", "DSCT.TA", "FTAL.TA",
    # Insurance & Finance
    "MIGDL.TA", "PHOE.TA", "CLAL.TA", "HPRT.TA", "IDFN.TA",
    # Real Estate
    "AZRG.TA", "AMOT.TA", "GZT.TA", "ROTS.TA", "MLSR.TA",
    "BIGA.TA", "AFPR.TA", "CPTP.TA", "GNRS.TA",
    # Energy & Utilities
    "ORL.TA", "ENLT.TA", "SPGE.TA", "NFTA.TA", "DLEKG.TA",
    # Telecom
    "BEZQ.TA", "PARTN.TA", "CELM.TA",
    # Pharma & Healthcare
    "TEVA.TA", "CRNT.TA", "MEDI.TA",
    # Technology
    "NICE.TA", "ESLT.TA", "RBLI.TA", "ORPN.TA", "SITI.TA",
    "NNDM.TA", "NVPT.TA",
    # Food & Consumer
    "SANO.TA", "AREN.TA", "WLFD.TA", "STRS.TA", "SHUFD.TA",
    "RAMI.TA",
    # Industrials & Materials
    "ICL.TA", "KRUR.TA", "KARE.TA", "MZTF.TA", "ILCO.TA",
    "LDCL.TA", "MNRT.TA",
    # Holding / Diversified
    "HARL.TA", "ALHE.TA", "ISCN.TA", "ISCD.TA",
]
TA125_TICKERS = list(dict.fromkeys(TA125_TICKERS))  # deduplicate

# ── US Dividend Aristocrats & Champions universe ───────────────────────────────
US_UNIVERSE = [
    # Consumer Staples
    "KO", "PG", "PEP", "CL", "KMB", "CLX", "GIS", "MKC", "HRL", "SJM",
    # Healthcare
    "JNJ", "ABT", "BDX", "MDT", "ABBV",
    # Industrials
    "EMR", "ITW", "DOV", "GPC", "CTAS", "EXPD", "NDSN", "PNR", "LECO",
    # Financials
    "AFL", "CB", "AMP", "SPGI", "FDS",
    # Technology
    "ADP", "MSFT", "AAPL", "TXN", "PAYX",
    # Energy
    "CVX", "XOM", "OXY",
    # Utilities
    "ED", "ES", "ATO", "WEC",
    # Real Estate (REITs)
    "O", "FRT", "ESS",
    # Materials
    "ALB", "LIN", "PPG", "RPM", "NUE",
    # Consumer Discretionary
    "LOW", "SHW", "GWW", "CINF", "TGT", "WMT",
]
US_UNIVERSE = list(dict.fromkeys(US_UNIVERSE))

# Test subsets
TEST_IL_TICKERS = ["LUMI.TA", "BEZQ.TA", "ICL.TA", "SANO.TA", "AZRG.TA",
                   "ORL.TA", "MZTF.TA", "PARTN.TA", "MIGDL.TA", "DSCT.TA"]
TEST_US_TICKERS = ["KO", "PG", "JNJ", "EMR", "AFL", "ADP", "CVX", "O",
                   "LIN", "TXN", "LOW", "CTAS", "MDT", "ABBV", "SPGI"]

GEMINI_CANDIDATES = [
    "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro",
    "gemini-2.0-flash-lite", "gemini-2.0-flash",
    "gemini-1.5-flash", "gemini-1.5-flash-latest",
]

ILS_MARKET_CAP_MIN = 500_000_000   # 500M ILS


# ── Utilities ──────────────────────────────────────────────────────────────────
def pick_gemini_model(api_key: str) -> str:
    client = genai.Client(api_key=api_key)
    try:
        available = {
            m.name.replace("models/", "")
            for m in client.models.list()
            if "generateContent" in getattr(m, "supported_generation_methods", [])
        }
        for c in GEMINI_CANDIDATES:
            if c in available:
                log.info("Gemini model: %s", c)
                return c
        if available:
            return next(iter(available))
    except Exception as exc:
        log.warning("Model list failed: %s", exc)
    return "gemini-2.0-flash"


def safe_float(val, default=None) -> Optional[float]:
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except Exception:
        return default


def normalize_yield(raw) -> Optional[float]:
    """Normalize yfinance dividendYield to a decimal ratio (0.05 = 5%).
    yfinance may return: decimal (0.045), percent (4.5), or percent*100 (450.0)."""
    v = safe_float(raw)
    if v is None:
        return None
    if v > 1.0:
        v = v / 100   # percent → decimal
    if v > 0.5:
        v = v / 100   # percent*100 leaked through first division
    return v


def fmt_pct(v, default="N/A") -> str:
    if v is None:
        return default
    return f"{v*100:.1f}%"


def fmt_num(v, default="N/A") -> str:
    if v is None:
        return default
    try:
        v = float(v)
        if abs(v) >= 1e12: return f"{v/1e12:.2f}T"
        if abs(v) >= 1e9:  return f"{v/1e9:.2f}B"
        if abs(v) >= 1e6:  return f"{v/1e6:.2f}M"
        return f"{v:,.0f}"
    except Exception:
        return str(v)


def calc_cagr(series: pd.Series, years: int) -> Optional[float]:
    """CAGR of last `years` complete annual periods."""
    if len(series) < 2:
        return None
    try:
        end_val   = float(series.iloc[-1])
        start_val = float(series.iloc[max(0, len(series) - years - 1)])
        if start_val <= 0 or end_val <= 0:
            return None
        n = min(years, len(series) - 1)
        return (end_val / start_val) ** (1 / n) - 1
    except Exception:
        return None


def consecutive_growth_years(annual_divs: pd.Series) -> int:
    """Count consecutive years of dividend growth from most recent complete year."""
    # Drop current (partial) year
    now = datetime.now().year
    annual = annual_divs[annual_divs.index.year < now]
    annual = annual[annual > 0]
    if len(annual) < 2:
        return 0
    vals = annual.values
    count = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] > vals[i - 1]:
            count += 1
        else:
            break
    return count


def get_fcf_series(ticker_obj: yf.Ticker, years: int = 3) -> list[Optional[float]]:
    """Return list of FCF for last `years` annual periods."""
    try:
        cf = ticker_obj.cash_flow
        if cf is None or cf.empty:
            return []
        for row in ["Free Cash Flow", "Operating Cash Flow"]:
            if row in cf.index:
                vals = cf.loc[row].tolist()[:years]
                return [safe_float(v) for v in vals]
    except Exception:
        pass
    return []


def get_eps_series(ticker_obj: yf.Ticker, years: int = 3) -> list[Optional[float]]:
    try:
        inc = ticker_obj.income_stmt
        if inc is None or inc.empty:
            return []
        for row in ["Diluted EPS", "Basic EPS"]:
            if row in inc.index:
                vals = inc.loc[row].tolist()[:years]
                return [safe_float(v) for v in vals]
    except Exception:
        pass
    return []


def get_annual_dividends(ticker_obj: yf.Ticker) -> pd.Series:
    try:
        divs = ticker_obj.dividends
        if len(divs) == 0:
            return pd.Series(dtype=float)
        annual = divs.resample("YE").sum()
        return annual[annual > 0]
    except Exception:
        return pd.Series(dtype=float)


# ── Raw Data Collector ─────────────────────────────────────────────────────────
class StockDataCollector:
    def collect(self, symbol: str) -> Optional[dict]:
        try:
            t    = yf.Ticker(symbol)
            info = t.info
            if not info or "longName" not in info:
                return None

            annual_divs  = get_annual_dividends(t)
            div_years    = sorted({y for y in annual_divs.index.year})
            last5_years  = set(range(datetime.now().year - 5, datetime.now().year))
            divs_in_5y   = len(last5_years & set(div_years))

            fcf_list  = get_fcf_series(t, years=5)
            eps_list  = get_eps_series(t, years=4)

            gross_yield = normalize_yield(info.get("dividendYield") or info.get("trailingAnnualDividendYield"))
            payout      = safe_float(info.get("payoutRatio"))
            roe         = safe_float(info.get("returnOnEquity"))
            de          = safe_float(info.get("debtToEquity"))
            mcap        = safe_float(info.get("marketCap"))
            beta        = safe_float(info.get("beta"))
            eps_ttm     = safe_float(info.get("trailingEps"))
            pe          = safe_float(info.get("trailingPE"))
            fpe         = safe_float(info.get("forwardPE"))
            sector      = info.get("sector") or info.get("sectorDisp") or "Unknown"

            consec_yrs  = consecutive_growth_years(annual_divs)
            # 5Y dividend CAGR (use last 6 complete annual values)
            div5_cagr = calc_cagr(annual_divs[annual_divs.index.year < datetime.now().year].tail(6), 5)
            # EPS growth (3Y)
            eps_growth = None
            if len(eps_list) >= 2:
                valid_eps = [e for e in eps_list[:3] if e is not None and e != 0]
                if len(valid_eps) >= 2:
                    eps_growth = (valid_eps[0] - valid_eps[-1]) / abs(valid_eps[-1]) / max(len(valid_eps) - 1, 1)

            # Holders & recent price
            holders = []
            try:
                ih = t.institutional_holders
                if ih is not None and not ih.empty:
                    for _, row in ih.head(3).iterrows():
                        holders.append(f"{row.get('Holder','?')[:30]} {float(row.get('pctHeld',0))*100:.1f}%")
            except Exception:
                pass

            desc = (info.get("longBusinessSummary") or "")[:500]

            return {
                "symbol":       symbol,
                "name":         info.get("longName", symbol),
                "sector":       sector,
                "description":  desc,
                "employees":    info.get("fullTimeEmployees"),
                "gross_yield":  gross_yield,
                "net_yield_il": (gross_yield * 0.75) if gross_yield else None,
                "payout":       payout,
                "roe":          roe,
                "de":           de,
                "mcap":         mcap,
                "beta":         beta,
                "eps_ttm":      eps_ttm,
                "pe":           pe,
                "forward_pe":   fpe,
                "divs_in_5y":   divs_in_5y,
                "consec_growth_years": consec_yrs,
                "div5_cagr":    div5_cagr,
                "eps_growth_avg": eps_growth,
                "fcf_list":     fcf_list,
                "eps_list":     eps_list,
                "fcf_positive_count": sum(1 for f in fcf_list if f and f > 0),
                "annual_divs":  annual_divs,
                "div_years":    div_years,
                "top_holders":  holders,
                "country":      info.get("country", ""),
                "currency":     info.get("currency", ""),
            }
        except Exception as exc:
            log.debug("Data error %s: %s", symbol, exc)
            return None


# ── Israeli Screener ───────────────────────────────────────────────────────────
class IsraeliScreener:
    FILTERS = {
        "net_yield":    ("net_yield_il",   ">",  0.03),
        "divs_3_of_5":  ("divs_in_5y",    ">=",  3),
        "payout":       ("payout",         "<",  0.65),
        "mcap":         ("mcap",           ">",  ILS_MARKET_CAP_MIN),
        "roe":          ("roe",            ">",  0.12),
        "fcf_pos_3y":   ("fcf_positive_count", ">=", 3),
    }

    def passes(self, d: dict) -> bool:
        checks = [
            d.get("net_yield_il")         and d["net_yield_il"]          > 0.03,
            d.get("divs_in_5y",0)                                        >= 3,
            d.get("payout")               and d["payout"]                < 0.65,
            d.get("mcap")                 and d["mcap"]                  > ILS_MARKET_CAP_MIN,
            d.get("roe")                  and d["roe"]                   > 0.12,
            d.get("fcf_positive_count",0)                                >= 3,
        ]
        # D/E filter: skip for financial sector (banks have high D/E by nature)
        if d.get("sector") not in ("Financial Services",):
            de = d.get("de")
            checks.append(de is not None and de < 0.7)
        # EPS growth
        if d.get("eps_growth_avg") is not None:
            checks.append(d["eps_growth_avg"] > 0)
        return all(checks)

    def score(self, d: dict) -> int:
        pts = 0
        # 30 pts: dividend consistency
        dy = d.get("divs_in_5y", 0)
        pts += 30 if dy >= 5 else (20 if dy == 4 else (10 if dy == 3 else 0))
        # 20 pts: net yield
        ny = d.get("net_yield_il") or 0
        pts += 20 if ny >= 0.05 else (15 if ny >= 0.04 else (10 if ny >= 0.03 else 0))
        # 20 pts: ROE
        roe = d.get("roe") or 0
        pts += 20 if roe > 0.20 else (15 if roe > 0.15 else (10 if roe > 0.12 else 0))
        # 15 pts: payout ratio
        po = d.get("payout") or 1
        pts += 15 if po < 0.40 else (10 if po < 0.55 else (5 if po < 0.65 else 0))
        # 15 pts: 3Y dividend CAGR
        dgr = d.get("div5_cagr") or 0
        pts += 15 if dgr > 0.08 else (10 if dgr > 0.04 else (5 if dgr > 0 else 0))
        return pts

    def select(self, candidates: list[dict], n: int = 2) -> list[dict]:
        passed   = [d for d in candidates if self.passes(d)]
        scored   = sorted(passed, key=lambda d: d.get("score", 0), reverse=True)
        selected, seen_sectors = [], set()
        for d in scored:
            if len(selected) >= n:
                break
            sec = d.get("sector", "Unknown")
            if sec not in seen_sectors:
                selected.append(d)
                seen_sectors.add(sec)
        # Fallback: relax D/E for financials if < n found
        if len(selected) < n:
            for d in scored:
                if len(selected) >= n:
                    break
                if d not in selected:
                    selected.append(d)
        return selected


# ── US Screener ────────────────────────────────────────────────────────────────
class USScreener:
    def passes(self, d: dict) -> bool:
        return all([
            d.get("gross_yield")         and d["gross_yield"]           > 0.020,
            d.get("consec_growth_years", 0)                             >= 5,
            d.get("payout")              and d["payout"]                < 0.70,
            d.get("roe")                 and d["roe"]                   > 0.15,
            d.get("beta")                is not None and d["beta"]      < 1.0,
            d.get("fcf_positive_count", 0)                              >= 3,
        ])

    def score(self, d: dict) -> int:
        pts = 0
        # 25 pts: Chowder Number (yield + 5Y div CAGR)
        chowder = (d.get("gross_yield") or 0) + (d.get("div5_cagr") or 0)
        d["chowder"] = round(chowder * 100, 1)
        pts += 25 if chowder > 0.15 else (20 if chowder > 0.13 else (15 if chowder > 0.11 else (10 if chowder > 0.08 else 0)))
        # 20 pts: consecutive dividend growth years
        cgy = d.get("consec_growth_years", 0)
        pts += 20 if cgy >= 50 else (15 if cgy >= 25 else (10 if cgy >= 10 else (5 if cgy >= 5 else 0)))
        # 20 pts: ROE
        roe = d.get("roe") or 0
        pts += 20 if roe > 0.25 else (15 if roe > 0.20 else (10 if roe > 0.15 else 0))
        # 20 pts: Beta
        beta = d.get("beta") or 1.0
        pts += 20 if beta < 0.5 else (15 if beta < 0.7 else (10 if beta < 1.0 else 0))
        # 15 pts: Payout ratio
        po = d.get("payout") or 1
        pts += 15 if po < 0.35 else (10 if po < 0.50 else (5 if po < 0.60 else 0))
        return pts

    def select(self, candidates: list[dict], n: int = 3) -> list[dict]:
        passed   = [d for d in candidates if self.passes(d)]
        scored   = sorted(passed, key=lambda d: d.get("score", 0), reverse=True)
        selected, seen_sectors = [], set()
        for d in scored:
            if len(selected) >= n:
                break
            sec = d.get("sector", "Unknown")
            if sec not in seen_sectors:
                selected.append(d)
                seen_sectors.add(sec)
        if len(selected) < n:
            for d in scored:
                if len(selected) >= n:
                    break
                if d not in selected:
                    selected.append(d)
        return selected


# ── Gemini Analyzer ────────────────────────────────────────────────────────────
class GeminiAnalyzer:
    def __init__(self, client, model_name: str) -> None:
        self.model = client
        self.model_name = model_name

    def analyze(self, d: dict, market: str) -> tuple[str, int]:
        currency = "₪" if market == "IL" else "$"
        mcap_fmt = fmt_num(d.get("mcap"))
        if market == "IL" and d.get("mcap"):
            mcap_fmt += " ₪"

        annual_div_str = ""
        try:
            ad = d.get("annual_divs", pd.Series())
            last5 = ad[ad.index.year >= datetime.now().year - 5]
            annual_div_str = " | ".join(
                f"{y}: {currency}{v:.2f}" for y, v in zip(last5.index.year, last5.values)
            )
        except Exception:
            pass

        prompt = f"""אתה אנליסט דיבידנד בכיר המתמחה בהשקעות ארוכות טווח עבור לקוחות ישראלים.

להלן נתונים כמותיים מלאים של החברה:

━━ פרטי החברה ━━
טיקר: {d['symbol']} | שם: {d['name']}
סקטור: {d['sector']} | מדינה: {d.get('country','?')}
שווי שוק: {mcap_fmt} | עובדים: {fmt_num(d.get('employees'))}
תיאור: {d.get('description','')}

━━ נתוני דיבידנד ━━
תשואה ברוטו: {fmt_pct(d.get('gross_yield'))} | תשואה נטו (25% מס): {fmt_pct(d.get('net_yield_il') or d.get('gross_yield'))}
יחס חלוקה: {fmt_pct(d.get('payout'))}
חלוקות ב-5 שנים אחרונות: {d.get('divs_in_5y',0)}/5
שנות גידול עקבי: {d.get('consec_growth_years',0)} שנה
CAGR דיבידנד 5Y: {fmt_pct(d.get('div5_cagr'))}
דיבידנד שנתי (5Y): {annual_div_str}
{"Chowder Number: " + str(d.get('chowder','N/A')) if market == 'US' else ''}

━━ נתונים פיננסיים ━━
ROE: {fmt_pct(d.get('roe'))} | D/E: {round(d.get('de') or 0, 2)}
EPS TTM: {d.get('eps_ttm','N/A')} | P/E: {round(d.get('pe') or 0,1)} | Forward P/E: {round(d.get('forward_pe') or 0,1)}
FCF (3Y): {' | '.join(fmt_num(f) for f in (d.get('fcf_list') or [])[:3])}
EPS (3Y): {' | '.join(str(round(e,2)) if e else 'N/A' for e in (d.get('eps_list') or [])[:3])}
Beta: {round(d.get('beta') or 1, 3)}

━━ גדולי המחזיקים ━━
{chr(10).join(d.get('top_holders') or ['אין נתונים'])}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
כתוב ניתוח עומק מקצועי בעברית בפורמט הבא בדיוק (כולל הספרות):

1. תיאור עסקי:
[3 שורות: מה החברה עושה ואיך מרוויחה]

2. החפיר התחרותי:
[מה מגן על הרווחים לטווח ארוך]

3. ניתוח דיבידנד:
[האם הדיבידנד בטוח? מה צפוי בעוד 5 שנים?]

4. ניתוח פיננסי:
[חוזקות וחולשות מהנתונים]

5. סיכונים עיקריים:
[3 סיכונים קונקרטיים]

6. סביבה מאקרו:
[איך ריבית/אינפלציה/רגולציה משפיעים]

7. תמחור:
[האם המניה זולה/הוגנת/יקרה כעת]

8. מסקנה לרו"ח ישראלי:
[האם מתאים לתיק דיבידנד ארוך טווח?]

9. ציון כולל: X/10
[הסבר קצר לציון]"""

        for attempt in range(3):
            try:
                resp = self.model.models.generate_content(model=self.model_name, contents=prompt)
                text = resp.text.strip()
                if text:
                    score = self._extract_score(text)
                    return text, score
            except Exception as exc:
                wait = 25 * (attempt + 1)
                log.warning("Analysis attempt %d failed (%s): %s – waiting %ds", attempt + 1, d["symbol"], exc, wait)
                time.sleep(wait)
        return "לא ניתן היה לייצר ניתוח.", 0

    @staticmethod
    def _extract_score(text: str) -> int:
        import re
        # Search whole text for section 9 score patterns
        for pattern in [
            r"9\.\s*ציון כולל[:\s*\*]*(\d+)\s*/\s*10",
            r"ציון כולל[:\s*\*]+(\d+)\s*/\s*10",
            r"ציון[:\s]+(\d+)\s*/\s*10",
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return int(m.group(1))
        # Fallback: find last X/10 pattern in text
        matches = re.findall(r"(\d+)\s*/\s*10", text)
        if matches:
            return int(matches[-1])
        return 0


# ── CSV Exporter ───────────────────────────────────────────────────────────────
class CSVExporter:
    def export(self, il_stocks: list[dict], us_stocks: list[dict]) -> str:
        month_str = datetime.now().strftime("%Y-%m")
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"dividend_report_{month_str}.csv"
        )
        fieldnames = [
            "market", "symbol", "name", "sector", "score",
            "gross_yield", "net_yield", "payout", "roe", "de",
            "mcap", "beta", "eps_ttm", "divs_in_5y", "consec_growth_years",
            "div5_cagr", "chowder", "gemini_score",
        ]
        rows = []
        for d in il_stocks:
            rows.append({
                "market": "IL", "symbol": d["symbol"], "name": d["name"],
                "sector": d["sector"], "score": d.get("score", 0),
                "gross_yield": fmt_pct(d.get("gross_yield")),
                "net_yield": fmt_pct(d.get("net_yield_il")),
                "payout": fmt_pct(d.get("payout")),
                "roe": fmt_pct(d.get("roe")),
                "de": d.get("de"), "mcap": fmt_num(d.get("mcap")),
                "beta": d.get("beta"), "eps_ttm": d.get("eps_ttm"),
                "divs_in_5y": d.get("divs_in_5y"), "consec_growth_years": d.get("consec_growth_years"),
                "div5_cagr": fmt_pct(d.get("div5_cagr")), "chowder": d.get("chowder", ""),
                "gemini_score": d.get("gemini_score", 0),
            })
        for d in us_stocks:
            rows.append({
                "market": "US", "symbol": d["symbol"], "name": d["name"],
                "sector": d["sector"], "score": d.get("score", 0),
                "gross_yield": fmt_pct(d.get("gross_yield")),
                "net_yield": fmt_pct(d.get("gross_yield")),
                "payout": fmt_pct(d.get("payout")),
                "roe": fmt_pct(d.get("roe")),
                "de": d.get("de"), "mcap": fmt_num(d.get("mcap")),
                "beta": d.get("beta"), "eps_ttm": d.get("eps_ttm"),
                "divs_in_5y": d.get("divs_in_5y"), "consec_growth_years": d.get("consec_growth_years"),
                "div5_cagr": fmt_pct(d.get("div5_cagr")), "chowder": d.get("chowder", ""),
                "gemini_score": d.get("gemini_score", 0),
            })
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        log.info("CSV saved: %s", path)
        return path


# ── Email Sender ───────────────────────────────────────────────────────────────
class EmailSender:
    def __init__(self, user: str, app_password: str) -> None:
        self.user = user
        self.app_password = app_password

    def send(self, recipient: str, il_sel: list[dict], us_sel: list[dict],
             il_total: int, us_total: int, il_passed: int, us_passed: int) -> bool:
        month_str = datetime.now().strftime("%B %Y")
        subject   = f"💰 Dividend Research - {month_str} | 5 מניות נבחרות"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = self.user
        msg["To"]      = recipient
        msg.attach(MIMEText(
            self._plain(il_sel, us_sel, il_total, us_total, il_passed, us_passed, month_str),
            "plain", "utf-8"
        ))
        msg.attach(MIMEText(
            self._html(il_sel, us_sel, il_total, us_total, il_passed, us_passed, month_str),
            "html", "utf-8"
        ))
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as srv:
                srv.ehlo(); srv.starttls()
                srv.login(self.user, self.app_password)
                srv.sendmail(self.user, recipient, msg.as_string())
            log.info("Email sent to %s", recipient)
            return True
        except smtplib.SMTPAuthenticationError:
            log.error("Gmail auth failed – check GMAIL_APP_PASSWORD")
        except Exception as exc:
            log.error("Email error: %s", exc)
        return False

    def _plain(self, il_sel, us_sel, il_total, us_total, il_passed, us_passed, month_str) -> str:
        lines = [f"DIVIDEND INTELLIGENCE REPORT — {month_str}",
                 f"נסרקו: {il_total+us_total} מניות | עברו סינון: {il_passed+us_passed}", "="*55]
        lines += ["", "🇮🇱 שוק ישראלי — 2 מניות נבחרות", "="*40]
        for i, d in enumerate(il_sel, 1):
            lines += [
                f"\nמניה {i}/{len(il_sel)}: {d['symbol']} | {d['name']} | {d['sector']}",
                f"ניקוד סינון: {d.get('score',0)}/100",
                f"תשואת דיבידנד נטו: {fmt_pct(d.get('net_yield_il'))}",
                f"חלוקה עקבית: {d.get('divs_in_5y',0)}/5 שנים | יחס חלוקה: {fmt_pct(d.get('payout'))}",
                f"ROE: {fmt_pct(d.get('roe'))} | D/E: {d.get('de','N/A')}",
                f"שווי שוק: {fmt_num(d.get('mcap'))} ₪",
                "", "--- ניתוח Gemini ---",
                d.get("analysis", ""),
                f"⭐ ציון: {d.get('gemini_score',0)}/10",
            ]
        lines += ["", "🇺🇸 שוק אמריקאי — 3 מניות נבחרות", "="*40]
        for i, d in enumerate(us_sel, 1):
            lines += [
                f"\nמניה {i}/{len(us_sel)}: {d['symbol']} | {d['name']} | {d['sector']}",
                f"ניקוד סינון: {d.get('score',0)}/100",
                f"תשואת דיבידנד: {fmt_pct(d.get('gross_yield'))}",
                f"שנות הגדלת דיבידנד: {d.get('consec_growth_years',0)} | Chowder: {d.get('chowder','N/A')}",
                f"יחס חלוקה: {fmt_pct(d.get('payout'))} | ROE: {fmt_pct(d.get('roe'))} | Beta: {d.get('beta','N/A')}",
                f"שווי שוק: ${fmt_num(d.get('mcap'))}",
                "", "--- ניתוח Gemini ---",
                d.get("analysis", ""),
                f"⭐ ציון: {d.get('gemini_score',0)}/10",
            ]
        lines.append("\n⚠️ לידיעה בלבד — אינו מהווה המלצת השקעה")
        return "\n".join(lines)

    def _html(self, il_sel, us_sel, il_total, us_total, il_passed, us_passed, month_str) -> str:
        def esc(s: str) -> str:
            return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

        def fmt_analysis(text: str) -> str:
            import re
            text = esc(text)
            text = re.sub(r"(\d+\.\s+(?:תיאור עסקי|החפיר התחרותי|ניתוח דיבידנד|ניתוח פיננסי|סיכונים עיקריים|סביבה מאקרו|תמחור|מסקנה לרו[\"״]ח ישראלי|ציון כולל)[:\s]?)",
                          r'<strong class="sec-h">\1</strong>', text)
            return text.replace("\n", "<br>")

        def stock_card(d: dict, idx: int, total: int, market: str) -> str:
            flag   = "🇮🇱" if market == "IL" else "🇺🇸"
            cy     = "₪" if market == "IL" else "$"
            yield_ = fmt_pct(d.get("net_yield_il") if market == "IL" else d.get("gross_yield"))
            extra  = (f'<div class="metric"><div class="m-lbl">Chowder</div>'
                      f'<div class="m-val">{d.get("chowder","N/A")}</div></div>') if market == "US" else ""
            growth_lbl = "תשואה נטו" if market == "IL" else "תשואה"
            consec = d.get("consec_growth_years", 0)
            return f"""
<div class="stock-card">
  <div class="card-header">
    <span class="idx-badge">{flag} מניה {idx}/{total}</span>
    <span class="sector-tag">{esc(d.get('sector',''))}</span>
    <span class="score-badge">ניקוד: {d.get('score',0)}/100</span>
  </div>
  <div class="ticker-row">
    <span class="ticker">{esc(d['symbol'])}</span>
    <span class="cname">{esc(d['name'])}</span>
  </div>
  <div class="metrics-row">
    <div class="metric"><div class="m-lbl">{growth_lbl}</div><div class="m-val hi">{yield_}</div></div>
    <div class="metric"><div class="m-lbl">Payout</div><div class="m-val">{fmt_pct(d.get('payout'))}</div></div>
    <div class="metric"><div class="m-lbl">ROE</div><div class="m-val">{fmt_pct(d.get('roe'))}</div></div>
    <div class="metric"><div class="m-lbl">שנות גידול</div><div class="m-val">{consec}y</div></div>
    <div class="metric"><div class="m-lbl">Beta</div><div class="m-val">{round(d.get('beta') or 0,2)}</div></div>
    <div class="metric"><div class="m-lbl">שווי שוק</div><div class="m-val">{cy}{fmt_num(d.get('mcap'))}</div></div>
    {extra}
  </div>
  <div class="analysis-box">{fmt_analysis(d.get('analysis',''))}</div>
  <div class="score-row">⭐ ציון Gemini: <strong>{d.get('gemini_score',0)}/10</strong></div>
</div>"""

        # Comparison table
        all_stocks = [(d, "IL") for d in il_sel] + [(d, "US") for d in us_sel]
        table_rows = ""
        for d, mkt in all_stocks:
            yld = fmt_pct(d.get("net_yield_il") if mkt == "IL" else d.get("gross_yield"))
            table_rows += (
                f"<tr><td>{'🇮🇱' if mkt=='IL' else '🇺🇸'} {esc(d['symbol'])}</td>"
                f"<td>{yld}</td><td>{fmt_pct(d.get('payout'))}</td>"
                f"<td>{fmt_pct(d.get('roe'))}</td><td>{d.get('gemini_score',0)}/10</td></tr>"
            )

        il_cards = "".join(stock_card(d, i+1, len(il_sel), "IL") for i, d in enumerate(il_sel))
        us_cards = "".join(stock_card(d, i+1, len(us_sel), "US") for i, d in enumerate(us_sel))

        return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="UTF-8">
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#0d1117;margin:0;padding:14px;
     direction:rtl;color:#e6edf3}}
.wrap{{max-width:760px;margin:0 auto;background:#161b22;border-radius:14px;overflow:hidden;
       box-shadow:0 4px 28px rgba(0,0,0,.55)}}
.hdr{{background:linear-gradient(135deg,#1a1a2e,#16213e,#0f3460);color:#fff;
      padding:26px 30px;text-align:center}}
.hdr h1{{margin:0;font-size:23px}} .hdr .sub{{margin:6px 0 0;opacity:.75;font-size:13px}}
.section-hdr{{background:#21262d;padding:12px 20px;border-top:2px solid #388bfd;
              font-size:16px;font-weight:700;color:#58a6ff}}
.stock-card{{margin:14px 16px;background:#1c2128;border-radius:12px;
             overflow:hidden;border:1px solid #30363d}}
.card-header{{background:#21262d;padding:10px 16px;display:flex;align-items:center;gap:10px;
              flex-wrap:wrap;border-bottom:1px solid #30363d}}
.idx-badge{{background:#238636;color:#fff;font-size:11px;padding:3px 10px;border-radius:12px;font-weight:700}}
.sector-tag{{background:#0d2137;color:#79c0ff;font-size:11px;padding:3px 9px;border-radius:8px}}
.score-badge{{margin-right:auto;background:#6e40c9;color:#fff;font-size:11px;
              padding:3px 10px;border-radius:12px;font-weight:700}}
.ticker-row{{padding:12px 16px 4px;display:flex;align-items:baseline;gap:12px}}
.ticker{{font-size:24px;font-weight:800;color:#58a6ff;font-family:monospace}}
.cname{{font-size:14px;color:#8b949e}}
.metrics-row{{display:flex;flex-wrap:wrap;gap:8px;padding:8px 16px 14px}}
.metric{{background:#21262d;border-radius:8px;padding:7px 11px;min-width:85px;
         text-align:center;border:1px solid #30363d}}
.m-lbl{{font-size:10px;color:#8b949e;margin-bottom:3px}}
.m-val{{font-size:14px;font-weight:700;color:#e6edf3}}
.m-val.hi{{color:#3fb950;font-size:16px}}
.analysis-box{{margin:0 16px 10px;background:#0d1117;border-radius:10px;padding:14px;
               font-size:13px;line-height:1.8;color:#c9d1d9;border:1px solid #21262d}}
.sec-h{{color:#58a6ff;font-weight:700;display:block;margin-top:8px}}
.score-row{{padding:10px 16px 14px;font-size:13px;color:#8b949e;text-align:left}}
.score-row strong{{color:#f1c40f;font-size:16px}}
.table-wrap{{margin:14px 16px;border-radius:10px;overflow:hidden;border:1px solid #30363d}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#21262d;color:#8b949e;padding:9px 12px;text-align:center;font-weight:600}}
td{{padding:9px 12px;text-align:center;border-top:1px solid #21262d;color:#e6edf3}}
tr:hover td{{background:#1c2128}}
.disc{{background:#21262d;padding:13px;text-align:center;font-size:11px;
       color:#6e7681;border-top:1px solid #30363d}}
</style></head>
<body><div class="wrap">
<div class="hdr">
  <h1>💰 Dividend Intelligence Report</h1>
  <p class="sub">{esc(month_str)} | נסרקו: {il_total+us_total} מניות | עברו סינון: {il_passed+us_passed}</p>
</div>

<div class="section-hdr">🇮🇱 שוק ישראלי — 2 מניות נבחרות</div>
{il_cards}

<div class="section-hdr">🇺🇸 שוק אמריקאי — 3 מניות נבחרות</div>
{us_cards}

<div class="section-hdr">📋 טבלת השוואה מהירה</div>
<div class="table-wrap">
<table>
  <tr><th>מניה</th><th>תשואה</th><th>Payout</th><th>ROE</th><th>ציון</th></tr>
  {table_rows}
</table>
</div>

<div class="disc">⚠️ המידע לצרכי מחקר בלבד — אינו מהווה המלצת השקעה | Gemini AI + yfinance</div>
</div></body></html>"""


# ── Task Scheduler ─────────────────────────────────────────────────────────────
def setup_scheduled_task() -> None:
    import subprocess
    result = subprocess.run(
        ["schtasks", "/Create",
         "/TN", "Dividend Screener Monthly",
         "/TR", f'"{sys.executable}" "{os.path.abspath(__file__)}"',
         "/SC", "MONTHLY", "/D", "1", "/ST", "08:30",
         "/RL", "HIGHEST", "/F"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        log.info("Scheduled task created: Dividend Screener Monthly (1st of month 08:30)")
    else:
        log.warning("Task creation: %s", result.stderr.strip() or result.stdout.strip())


# ── Main ───────────────────────────────────────────────────────────────────────
def main(test_mode: bool = False) -> None:
    log.info("Dividend Screener starting – %s%s",
             datetime.now().strftime("%d/%m/%Y %H:%M"),
             " [TEST MODE]" if test_mode else "")

    gmail_user   = os.getenv("GMAIL_USER", "")
    gmail_app_pw = os.getenv("GMAIL_APP_PASSWORD", "")
    gemini_key   = os.getenv("GEMINI_API_KEY", "")
    recipient    = os.getenv("RECIPIENT_EMAIL", gmail_user)

    missing = [k for k, v in {
        "GEMINI_API_KEY": gemini_key, "GMAIL_USER": gmail_user, "GMAIL_APP_PASSWORD": gmail_app_pw
    }.items() if not v]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        sys.exit(1)

    model_name = pick_gemini_model(gemini_key)
    client     = genai.Client(api_key=gemini_key)

    collector     = StockDataCollector()
    il_screener   = IsraeliScreener()
    us_screener   = USScreener()
    analyzer      = GeminiAnalyzer(client, model_name)
    sender        = EmailSender(gmail_user, gmail_app_pw)
    exporter      = CSVExporter()

    il_tickers = TEST_IL_TICKERS if test_mode else TA125_TICKERS
    us_tickers = TEST_US_TICKERS if test_mode else US_UNIVERSE

    # ── Israeli data collection ──────────────────────────────────────────────
    log.info("Scanning %d Israeli tickers...", len(il_tickers))
    il_data = []
    for sym in il_tickers:
        d = collector.collect(sym)
        if d:
            d["score"] = il_screener.score(d)
            il_data.append(d)
        time.sleep(0.3)

    il_passed  = [d for d in il_data if il_screener.passes(d)]
    log.info("Israeli: %d scanned → %d passed filters", len(il_data), len(il_passed))
    il_selected = il_screener.select(il_passed, n=2)

    # ── US data collection ───────────────────────────────────────────────────
    log.info("Scanning %d US tickers...", len(us_tickers))
    us_data = []
    for sym in us_tickers:
        d = collector.collect(sym)
        if d:
            d["score"] = us_screener.score(d)
            us_data.append(d)
        time.sleep(0.3)

    us_passed  = [d for d in us_data if us_screener.passes(d)]
    log.info("US: %d scanned → %d passed filters", len(us_data), len(us_passed))
    us_selected = us_screener.select(us_passed, n=3)

    if not il_selected and not us_selected:
        log.error("No stocks selected in either market. Aborting.")
        sys.exit(1)

    # ── Gemini analysis ──────────────────────────────────────────────────────
    log.info("Running Gemini analysis for %d stocks...", len(il_selected) + len(us_selected))
    for d in il_selected:
        analysis, score = analyzer.analyze(d, "IL")
        d["analysis"]     = analysis
        d["gemini_score"] = score
        log.info("  %s → Gemini score: %d/10", d["symbol"], score)

    for d in us_selected:
        analysis, score = analyzer.analyze(d, "US")
        d["analysis"]     = analysis
        d["gemini_score"] = score
        log.info("  %s → Gemini score: %d/10", d["symbol"], score)

    # ── Export CSV ───────────────────────────────────────────────────────────
    csv_path = exporter.export(il_selected + il_passed[:5], us_selected + us_passed[:5])
    log.info("Report saved: %s", csv_path)

    # ── Send email ───────────────────────────────────────────────────────────
    ok = sender.send(
        recipient,
        il_selected, us_selected,
        il_total=len(il_data), us_total=len(us_data),
        il_passed=len(il_passed), us_passed=len(us_passed),
    )

    # Save JSON for dashboard
    try:
        import json as _json
        _data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(_data_dir, exist_ok=True)
        def _to_dict(d):
            return {k: v for k, v in d.items()
                    if not hasattr(v, 'empty') and k not in ('annual_divs', 'fcf_list', 'eps_list', 'top_holders')}
        with open(os.path.join(_data_dir, "dividend_latest.json"), "w", encoding="utf-8") as _f:
            _json.dump({
                "updated": datetime.now().isoformat(),
                "month": datetime.now().strftime("%B %Y"),
                "il_stocks": [_to_dict(d) for d in il_selected],
                "us_stocks": [_to_dict(d) for d in us_selected],
            }, _f, ensure_ascii=False, indent=2, default=str)
        try:
            from sync_to_render import sync_to_render as _sync
            with open(os.path.join(_data_dir, "dividend_latest.json"), encoding="utf-8") as _rf:
                _sync("dividend_latest.json", _json.load(_rf))
        except Exception as _e2:
            log.warning("Render sync failed: %s", _e2)
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
    setup_scheduled_task()
    test = "--test" in sys.argv
    main(test_mode=test)
