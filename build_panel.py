"""
build_panel.py — ingest broker D1 CSVs + FRED → daily_panel.csv

Run from the project root:
    python build_panel.py

Outputs:
    daily_panel.csv  (date-indexed, one row per XAU trading day)

Columns
-------
xau_{open,high,low,close,vol_tick,volume}
xag_{open,high,low,close,vol_tick,volume}
eur_{open,high,low,close,vol_tick,volume}   # EUR/USD
jpy_{open,high,low,close,vol_tick,volume}   # USD/JPY
us10y_nominal   ← FRED DGS10
us10y_real      ← FRED DFII10
usd_broad       ← FRED DTWEXBGS  (weekly series, forward-filled to trading days)
"""

import io
import sys
from pathlib import Path

import pandas as pd
import requests

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent
D1_DIR   = ROOT / "historical data" / "D1"
OUT_PATH = ROOT / "daily_panel.csv"

# broker CSVs: tab-sep, 7 data cols, 6-name header (MT4 export)
# pandas auto-promotes col-0 (datetime) to index when header count < data count
_BROKER_COLS = ["date", "open", "high", "low", "close", "vol_tick", "volume"]

# FRED series → output column name
_FRED = {
    "DGS10":    "us10y_nominal",   # 10-year Treasury nominal yield (daily)
    "DFII10":   "us10y_real",      # 10-year TIPS real yield (daily)
    "DTWEXBGS": "usd_broad",       # Nominal Broad USD Index (weekly Mon → ffill)
}


# ── loaders ───────────────────────────────────────────────────────────────────

def load_broker_d1(path: Path) -> pd.DataFrame:
    """Read one MT4-style D1 CSV: tab-sep, space-thousands, 7 cols / 6 headers."""
    df = pd.read_csv(
        path,
        sep="\t",
        thousands=" ",
        names=_BROKER_COLS,
        header=0,        # discard the broker header row
        index_col=0,     # datetime → index
        parse_dates=True,
    )
    df.index.name = "date"
    # drop any duplicate dates (rare broker re-export artefact)
    df = df[~df.index.duplicated(keep="last")]
    return df.sort_index()


def fetch_fred(series_id: str) -> pd.Series:
    """
    Download a FRED series via the public graph-CSV endpoint (no API key).
    Returns a daily Series with NaN where FRED records a missing value (".").
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(
        io.StringIO(resp.text),
        index_col=0,
        parse_dates=True,
        na_values=".",
    )
    s = df.iloc[:, 0]
    s.index.name = "date"
    return s


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # 1. broker CSVs -----------------------------------------------------------
    print("Loading broker D1 CSVs …")
    symbols = [
        ("XAUUSD", "xau"),
        ("XAGUSD", "xag"),
        ("EURUSD", "eur"),
        ("USDJPY", "jpy"),
    ]

    frames: dict[str, pd.DataFrame] = {}
    for ticker, prefix in symbols:
        path = D1_DIR / f"{ticker}_D1.csv"
        if not path.exists():
            sys.exit(f"ERROR: missing file: {path}")
        df = load_broker_d1(path)
        frames[prefix] = df
        print(f"  {ticker}: {len(df):,} rows  "
              f"{df.index[0].date()} -> {df.index[-1].date()}")

    # 2. build panel on XAU trading-day index ----------------------------------
    xau_idx = frames["xau"].index

    panel = frames["xau"].rename(columns=lambda c: f"xau_{c}")
    for prefix, df in list(frames.items())[1:]:
        panel = panel.join(
            df.rename(columns=lambda c: f"{prefix}_{c}"),
            how="left",
        )

    # 3. FRED ------------------------------------------------------------------
    print("Fetching FRED series …")
    for series_id, col_name in _FRED.items():
        print(f"  {series_id} -> {col_name} ... ", end="", flush=True)
        try:
            raw = fetch_fred(series_id).rename(col_name)
            # align to trading days: union index → sort → ffill gaps (max 7 days)
            # → reindex back to XAU days only
            aligned = (
                raw
                .reindex(xau_idx.union(raw.index))
                .sort_index()
                .ffill(limit=7)
                .reindex(xau_idx)
            )
            panel[col_name] = aligned
            n_ok = aligned.notna().sum()
            print(f"{n_ok:,} non-NaN / {len(xau_idx):,} rows")
        except Exception as exc:
            print(f"FAILED — {exc}")
            print(f"  Warning: {col_name} will be all-NaN.", file=sys.stderr)
            panel[col_name] = float("nan")

    # 4. write -----------------------------------------------------------------
    panel.to_csv(OUT_PATH)
    print(f"\nWrote: {OUT_PATH}")

    # 5. diagnostics -----------------------------------------------------------
    print(f"\nShape     : {panel.shape[0]:,} rows × {panel.shape[1]} cols")
    print(f"Date span : {panel.index[0].date()} -> {panel.index[-1].date()}")
    print(f"\nColumns:")
    for col in panel.columns:
        print(f"  {col}")

    nan_counts = panel.isna().sum()
    nonempty = nan_counts[nan_counts > 0]
    print(f"\nNaN counts (columns with any missing):")
    if nonempty.empty:
        print("  none")
    else:
        print(nonempty.to_string())

    print(f"\nTail (last 3 rows):")
    print(panel.tail(3).to_string())


if __name__ == "__main__":
    main()
