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
ROOT      = Path(__file__).parent
D1_DIR    = ROOT / "historical data" / "D1"
FRED_DIR  = ROOT / "historical data" / "fred"   # manual FRED CSV fallback
OUT_PATH  = ROOT / "daily_panel.csv"

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


def _parse_fred_csv(text_or_path) -> pd.Series:
    """Read a FRED CSV (DATE col + value col, '.' = NaN) from text or file path."""
    if isinstance(text_or_path, (str, io.StringIO)):
        src = text_or_path if isinstance(text_or_path, io.StringIO) else io.StringIO(text_or_path)
    else:
        src = text_or_path   # Path object
    df = pd.read_csv(src, index_col=0, parse_dates=True, na_values=".")
    s = df.iloc[:, 0]
    s.index.name = "date"
    return s


def fetch_fred(series_id: str) -> pd.Series:
    """
    Load a FRED series.  Priority:
      1. Local file  historical data/fred/<series_id>.csv  (manual download)
      2. FRED graph endpoint  (3 retries: 15 / 30 / 60 s)

    To use local files: paste this URL in your browser and Save As to the
    historical data/fred/ folder (create the folder first if it doesn't exist):
      https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10
      https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10
      https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS
    """
    local = FRED_DIR / f"{series_id}.csv"
    if local.exists():
        s = _parse_fred_csv(local)
        print(f"local file ({len(s):,} rows)", end="")
        return s

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    last_exc: Exception | None = None
    for attempt, timeout in enumerate([15, 30, 60], 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            s = _parse_fred_csv(io.StringIO(resp.text))
            # Cache locally so next run is instant
            FRED_DIR.mkdir(parents=True, exist_ok=True)
            local.write_text(resp.text, encoding="utf-8")
            print(f"downloaded + cached to {local.name}", end="")
            return s
        except Exception as exc:
            last_exc = exc
            if attempt < 3:
                print(f"attempt {attempt} failed ({type(exc).__name__}), retrying ...",
                      end=" ", flush=True)
    raise last_exc  # type: ignore[misc]


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
    # Load old panel now (before overwriting) so we can preserve stale FRED values
    # if the fetch fails. ffill(limit=5) covers a long weekend.
    old_panel: pd.DataFrame | None = None
    if OUT_PATH.exists():
        try:
            old_panel = pd.read_csv(OUT_PATH, index_col=0, parse_dates=True)
        except Exception:
            pass

    print("Fetching FRED series …")
    for series_id, col_name in _FRED.items():
        print(f"  {series_id} -> {col_name} ... ", end="", flush=True)
        try:
            raw = fetch_fred(series_id).rename(col_name)
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
            print(f"FAILED -- {exc}")
            # Fall back to previous panel values if available
            if old_panel is not None and col_name in old_panel.columns:
                cached = old_panel[col_name].reindex(xau_idx).ffill(limit=5)
                n_cached = cached.notna().sum()
                if n_cached > 0:
                    panel[col_name] = cached
                    print(f"  Using cached values from previous panel "
                          f"({n_cached:,} non-NaN, ffill+5d).")
                    continue
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
