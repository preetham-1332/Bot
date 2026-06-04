"""
P6 — COT reconciliation + FRED staleness check.

COT (Commitments of Traders)
-----------------------------
Source: CFTC Disaggregated Futures-Only report.
Gold contract: COMEX 100 Troy Oz, market code 088691.

Metric: net_spec_pct = (Money Manager Longs - Money Manager Shorts) / Open Interest
  Positive = specs net long gold (supportive, but crowded = reversal risk)
  Negative = specs net short gold (headwind, but crowded short = squeeze risk)

Crowding flags:
  > 90th percentile of trailing 3-year history  -> CROWDED_LONG  (fade risk)
  < 10th percentile                              -> CROWDED_SHORT (squeeze risk)
  Otherwise                                      -> NEUTRAL

FRED staleness check
--------------------
Flags any FRED series in daily_panel.csv that has not been updated
within the last 7 calendar days.  Stale data silently degrades the
macro composite.
"""

from __future__ import annotations
from pathlib import Path
import io
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

# ── constants ─────────────────────────────────────────────────────────────────

GOLD_MARKET_CODE = "088691"     # COMEX 100 Troy Oz

# CFTC disaggregated futures-only report URLs
_CFTC_CURRENT_URL  = "https://www.cftc.gov/dea/newcot/f_disagg.txt"
_CFTC_HISTORY_BASE = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"

CROWDED_LONG_PCT  = 90
CROWDED_SHORT_PCT = 10
COT_HISTORY_DAYS  = 3 * 252    # 3 years for percentile baseline
STALE_DAYS        = 7          # flag FRED series not updated within this many days

# Column names in CFTC disaggregated CSV
_COT_COLS = {
    "Market and Exchange Names":                  "market",
    "As of Date in Form YYYY-MM-DD":              "date",
    "Open Interest (All)":                        "oi",
    "M_Money_Positions_Long_All":                 "mm_long",
    "M_Money_Positions_Short_All":                "mm_short",
    "M_Money_Positions_Spread_All":               "mm_spread",
}


# ── COT download + parse ──────────────────────────────────────────────────────

def _fetch_cot_text(year: int | None = None,
                    timeout: int = 20) -> str | None:
    """Fetch raw CFTC text, return content string or None on failure."""
    if year is None:
        url = _CFTC_CURRENT_URL
    else:
        url = _CFTC_HISTORY_BASE.format(year=year)
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        if url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                names = z.namelist()
                target = next((n for n in names if n.endswith(".txt")), names[0])
                return z.read(target).decode("utf-8", errors="replace")
        return r.text
    except Exception as e:
        return None


def _parse_cot_text(text: str) -> pd.DataFrame:
    """Parse CFTC disaggregated CSV text into a DataFrame."""
    df = pd.read_csv(io.StringIO(text), low_memory=False)
    # Normalise column names (strip whitespace)
    df.columns = df.columns.str.strip()

    # Find required columns (names vary slightly by year)
    rename = {}
    for raw, nice in _COT_COLS.items():
        match = [c for c in df.columns if raw.lower() in c.lower()]
        if match:
            rename[match[0]] = nice

    df = df.rename(columns=rename)
    required = {"market", "date", "oi", "mm_long", "mm_short"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    gold = df[df["market"].str.contains(GOLD_MARKET_CODE, na=False)].copy()
    gold["date"]  = pd.to_datetime(gold["date"], errors="coerce")
    for col in ["oi", "mm_long", "mm_short"]:
        gold[col] = pd.to_numeric(gold[col], errors="coerce")
    return gold[["date", "oi", "mm_long", "mm_short"]].dropna().sort_values("date")


def download_cot(years: list[int] | None = None,
                 cache_path: Path | None = None) -> pd.DataFrame:
    """
    Download and cache COT data for the specified years + current report.
    Returns a DataFrame with columns: date, oi, mm_long, mm_short, net_spec_pct.

    If cache_path exists and is < 7 days old, returns cached version.
    If download fails, returns an empty DataFrame and prints a warning.
    """
    if cache_path and cache_path.exists():
        age = (date.today() - date.fromtimestamp(cache_path.stat().st_mtime)).days
        if age < STALE_DAYS:
            try:
                cached = pd.read_csv(cache_path, parse_dates=["date"])
                # Recompute metrics if cache was written without them
                if "net_spec_pct" not in cached.columns:
                    cached = _add_cot_metrics(cached)
                return cached
            except Exception:
                pass

    if years is None:
        current_year = date.today().year
        years = list(range(max(current_year - 3, 2018), current_year))

    pieces = []
    for yr in years:
        text = _fetch_cot_text(year=yr)
        if text:
            parsed = _parse_cot_text(text)
            if not parsed.empty:
                pieces.append(parsed)

    # Always try current report
    cur_text = _fetch_cot_text(year=None)
    if cur_text:
        parsed = _parse_cot_text(cur_text)
        if not parsed.empty:
            pieces.append(parsed)

    if not pieces:
        print("  [COT] WARNING: CFTC download failed. "
              "Manually download from:\n"
              "  https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm\n"
              "  (Disaggregated Futures-Only -> 'View History')\n"
              "  Save as outputs/cot_gold.csv with columns: date,oi,mm_long,mm_short")
        return pd.DataFrame(columns=["date", "oi", "mm_long", "mm_short",
                                     "net_spec_pct", "cot_score"])

    df = (pd.concat(pieces, ignore_index=True)
            .drop_duplicates(subset=["date"])
            .sort_values("date")
            .reset_index(drop=True))

    df = _add_cot_metrics(df)

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache_path, index=False)

    return df


def _add_cot_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Add net_spec_pct and rolling-percentile cot_score."""
    df = df.copy()
    df["net_spec_pct"] = ((df["mm_long"] - df["mm_short"])
                          / df["oi"].replace(0, np.nan) * 100).round(2)

    # Rolling percentile rank (3-year trailing window, ~156 weekly observations)
    lookback = min(156, len(df) - 1)

    def _pct_rank(x: np.ndarray) -> float:
        return float((x[:-1] < x[-1]).sum()) / max(len(x) - 1, 1) * 100

    df["cot_pct_rank"] = (df["net_spec_pct"]
                          .rolling(lookback, min_periods=lookback // 2)
                          .apply(_pct_rank, raw=True)
                          .round(1))

    df["cot_score"] = 0
    df.loc[df["cot_pct_rank"] >= CROWDED_LONG_PCT,  "cot_score"] = -1  # crowded long = fade risk
    df.loc[df["cot_pct_rank"] <= CROWDED_SHORT_PCT, "cot_score"] =  1  # crowded short = squeeze

    return df


def align_cot_to_panel(cot: pd.DataFrame,
                       panel: pd.DataFrame) -> pd.DataFrame:
    """
    Forward-fill weekly COT values onto the daily panel index.
    Each COT release covers the previous Tuesday; it's published on Friday.
    We forward-fill from the release date (Friday) with a 7-day limit.
    """
    if cot.empty:
        return pd.DataFrame(index=panel.index,
                            columns=["net_spec_pct", "cot_pct_rank", "cot_score"])
    cot_idx = cot.set_index("date")[["net_spec_pct", "cot_pct_rank", "cot_score"]]
    aligned = cot_idx.reindex(panel.index.union(cot_idx.index)).sort_index()
    aligned = aligned.ffill(limit=7)
    return aligned.reindex(panel.index)


# ── FRED staleness check ──────────────────────────────────────────────────────

FRED_COLS = {
    "us10y_nominal": "DGS10",
    "us10y_real":    "DFII10",
    "usd_broad":     "DTWEXBGS",
}


def check_fred_staleness(panel: pd.DataFrame,
                         stale_days: int = STALE_DAYS) -> list[dict]:
    """
    Check how recently each FRED series was last updated in the panel.
    Returns a list of dicts: {series, last_date, days_stale, is_stale}.
    """
    today   = pd.Timestamp(date.today())
    results = []
    for col, series_id in FRED_COLS.items():
        if col not in panel.columns:
            results.append({"series": series_id, "col": col,
                            "last_date": None, "days_stale": None,
                            "is_stale": True, "note": "column missing"})
            continue
        last = panel[col].last_valid_index()
        if last is None:
            days = None
            stale = True
        else:
            days  = (today - last).days
            stale = days > stale_days
        results.append({
            "series":     series_id,
            "col":        col,
            "last_date":  last.date() if last else None,
            "days_stale": days,
            "is_stale":   stale,
            "note":       f"STALE ({days}d)" if stale else "OK",
        })
    return results


def fred_staleness_report(panel: pd.DataFrame) -> str:
    """Return a formatted staleness report string."""
    rows   = check_fred_staleness(panel)
    lines  = ["FRED data freshness:"]
    lines += [f"  {'Series':<12} {'Last date':<12} {'Days old':>9}  Status"]
    lines += [f"  {'-'*12} {'-'*12} {'-'*9}  {'-'*10}"]
    for r in rows:
        last  = str(r["last_date"]) if r["last_date"] else "missing"
        days  = str(r["days_stale"]) if r["days_stale"] is not None else "?"
        lines.append(f"  {r['series']:<12} {last:<12} {days:>9}  {r['note']}")
    return "\n".join(lines)
