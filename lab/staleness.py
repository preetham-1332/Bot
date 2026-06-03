"""
P10 -- Timestamp + staleness flag on every input.

Every data column feeding the system gets a freshness check:
  - File modification time  (has the panel been updated today?)
  - Last valid row date     (is the last observation current?)
  - Expected update lag     (FRED has 1-day lag; broker CSVs have 0-day lag)

A source is STALE when its last valid row is older than:
  lag_days + GRACE_DAYS  (grace covers weekends / public holidays)
"""

from __future__ import annotations
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT       = Path(__file__).parent.parent
GRACE_DAYS = 2   # weekend buffer before flagging stale


# column -> (expected_lag_days, human description)
SOURCES: dict[str, tuple[int, str]] = {
    "xau_close":      (1, "XAU/USD price (D1)"),
    "xag_close":      (1, "XAG/USD price (D1)"),
    "eur_close":      (1, "EUR/USD price (D1)"),
    "jpy_close":      (1, "USD/JPY price (D1)"),
    "usd_broad":      (3, "FRED DTWEXBGS (USD broad index)"),
    "us10y_nominal":  (1, "FRED DGS10 (10Y nominal yield)"),
    "us10y_real":     (1, "FRED DFII10 (10Y real yield)"),
    "macro_composite":(1, "Macro PCA composite (P1)"),
    "regime":         (1, "HMM regime (P0)"),
}


def check_panel_sources(panel: pd.DataFrame,
                         as_of: date | None = None) -> list[dict]:
    """
    Check each SOURCES column for freshness.
    Returns a list of dicts: {col, description, last_date, days_stale, is_stale, note}.
    """
    today = pd.Timestamp(as_of or date.today())
    rows  = []
    for col, (lag, desc) in SOURCES.items():
        if col not in panel.columns:
            rows.append({"col": col, "description": desc,
                         "last_date": None, "days_stale": None,
                         "is_stale": True, "note": "MISSING"})
            continue
        last = panel[col].last_valid_index()
        if last is None:
            rows.append({"col": col, "description": desc,
                         "last_date": None, "days_stale": None,
                         "is_stale": True, "note": "ALL NaN"})
            continue
        days  = int((today - last).days)
        stale = days > lag + GRACE_DAYS
        rows.append({
            "col":         col,
            "description": desc,
            "last_date":   last.date(),
            "days_stale":  days,
            "is_stale":    stale,
            "note":        f"STALE ({days}d)" if stale else "OK",
        })
    return rows


def panel_file_age(panel_path: Path | None = None) -> dict:
    """Return modification age of the panel CSV."""
    path = panel_path or ROOT / "daily_panel.csv"
    if not path.exists():
        return {"exists": False, "age_hours": None, "note": "FILE MISSING"}
    mtime   = datetime.fromtimestamp(path.stat().st_mtime)
    age_h   = (datetime.now() - mtime).total_seconds() / 3600
    is_old  = age_h > 26   # more than ~1 trading day
    return {
        "exists":    True,
        "modified":  mtime.strftime("%Y-%m-%d %H:%M"),
        "age_hours": round(age_h, 1),
        "is_stale":  is_old,
        "note":      f"STALE ({age_h:.0f}h old)" if is_old else "OK",
    }


def staleness_report(panel: pd.DataFrame,
                     panel_path: Path | None = None) -> str:
    """Formatted freshness report for daily_brief.py."""
    fi    = panel_file_age(panel_path)
    lines = ["Data freshness (P10):"]

    if fi["exists"]:
        lines.append(f"  Panel file   : last modified {fi['modified']}  "
                     f"({fi['age_hours']}h ago)  -- {fi['note']}")
    else:
        lines.append("  Panel file   : FILE MISSING -- run build_panel.py")

    rows = check_panel_sources(panel)
    lines.append(f"  {'Column':<18} {'Last date':<12} {'Days':>5}  Status")
    lines.append(f"  {'-'*18} {'-'*12} {'-'*5}  {'-'*12}")
    for r in rows:
        last = str(r["last_date"]) if r["last_date"] else "missing"
        days = str(r["days_stale"]) if r["days_stale"] is not None else "?"
        lines.append(f"  {r['col']:<18} {last:<12} {days:>5}  {r['note']}")

    any_stale = any(r["is_stale"] for r in rows)
    if any_stale:
        lines.append("")
        lines.append("  [!] One or more sources stale -- re-run build_panel.py")

    return "\n".join(lines)
