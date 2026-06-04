"""
convert_cot.py -- Convert raw CFTC files to cot_gold.csv

Reads any combination of:
  - CFTC disaggregated .txt files  (e.g. "2025 COT futures only.txt")
  - CFTC disaggregated .xls files  (e.g. "cot_gold.xls")

Filters for COMEX Gold (contract code 088691), extracts the four
columns the system needs, and writes outputs/cot_gold.csv.

Usage:
    python convert_cot.py                    # auto-detects files in project root
    python convert_cot.py file1.txt file2.xls  # explicit files
"""

import sys
from pathlib import Path

import pandas as pd

ROOT    = Path(__file__).parent
OUT_CSV = ROOT / "outputs" / "cot_gold.csv"

GOLD_CODE = "088691"   # COMEX 100 Troy Oz
GOLD_NAME = "GOLD - COMMODITY EXCHANGE INC."


def _read_file(path: Path) -> pd.DataFrame:
    """Read a raw CFTC file (txt or xls) and return all rows."""
    suffix = path.suffix.lower()
    if suffix in (".txt", ".csv"):
        df = pd.read_csv(path, low_memory=False)
    elif suffix in (".xls", ".xlsx"):
        df = pd.read_excel(path)
    else:
        print(f"  Skipping {path.name} -- unknown extension")
        return pd.DataFrame()
    df.columns = df.columns.str.strip()
    return df


def _extract_gold(df: pd.DataFrame) -> pd.DataFrame:
    """Filter for COMEX Gold and return date, oi, mm_long, mm_short."""
    if df.empty:
        return pd.DataFrame()

    # Find the market/name column
    name_col = next((c for c in df.columns
                     if "market" in c.lower() and "exchange" in c.lower()), None)
    code_col = next((c for c in df.columns
                     if "contract_market_code" in c.lower()), None)

    if name_col is None:
        print("  Could not find market name column -- skipping")
        return pd.DataFrame()

    # Filter: prefer code match, fall back to name match
    if code_col is not None:
        mask = df[code_col].astype(str).str.contains(GOLD_CODE, na=False)
    else:
        mask = df[name_col].str.contains("GOLD - COMMODITY EXCHANGE", na=False)

    gold = df[mask].copy()
    if gold.empty:
        return pd.DataFrame()

    # Find date column (prefer YYYY-MM-DD format)
    date_col = next((c for c in df.columns
                     if "report_date" in c.lower() and "yyyy" in c.lower()), None)
    if date_col is None:
        date_col = next((c for c in df.columns
                         if "report_date" in c.lower()), None)
    if date_col is None:
        print("  Could not find date column -- skipping")
        return pd.DataFrame()

    # Find OI and MM columns
    oi_col  = next((c for c in df.columns if c == "Open_Interest_All"), None)
    mml_col = next((c for c in df.columns
                    if "m_money_positions_long" in c.lower() and "all" in c.lower()), None)
    mms_col = next((c for c in df.columns
                    if "m_money_positions_short" in c.lower() and "all" in c.lower()
                    and "spread" not in c.lower()), None)

    missing = [n for n, c in [("oi", oi_col), ("mm_long", mml_col), ("mm_short", mms_col)]
               if c is None]
    if missing:
        print(f"  Missing columns {missing} -- skipping")
        return pd.DataFrame()

    out = pd.DataFrame({
        "date":     gold[date_col],
        "oi":       pd.to_numeric(gold[oi_col],  errors="coerce"),
        "mm_long":  pd.to_numeric(gold[mml_col], errors="coerce"),
        "mm_short": pd.to_numeric(gold[mms_col], errors="coerce"),
    })
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    return out.dropna()


def main():
    # Determine which files to process
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]
    else:
        # Auto-detect: files with "COT" or "cot" or "fut_disagg" in the name
        candidates = (list(ROOT.glob("*.txt")) + list(ROOT.glob("*.xls")) +
                      list(ROOT.glob("*.xlsx")) + [OUT_CSV.with_suffix(".xls"),
                                                    OUT_CSV.with_suffix(".xlsx")])
        paths = [p for p in candidates
                 if p.exists() and p != OUT_CSV
                 and any(k in p.name.lower() for k in ("cot", "fut_disagg", "disagg"))]

    if not paths:
        print("No COT files found. Pass file paths as arguments or place")
        print("CFTC txt/xls files in the project root.")
        sys.exit(1)

    pieces = []
    for path in paths:
        print(f"Reading {path.name} ...", end=" ")
        df_raw = _read_file(path)
        if df_raw.empty:
            print("empty")
            continue
        gold = _extract_gold(df_raw)
        if gold.empty:
            print("no gold rows found")
            continue
        print(f"{len(gold)} gold rows  "
              f"({gold['date'].min().date()} -> {gold['date'].max().date()})")
        pieces.append(gold)

    if not pieces:
        print("\nERROR: No gold data found in any file.")
        sys.exit(1)

    combined = (
        pd.concat(pieces, ignore_index=True)
        .drop_duplicates(subset=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )

    combined["date"] = combined["date"].dt.strftime("%Y-%m-%d")
    combined.to_csv(OUT_CSV, index=False)

    print(f"\nWrote: {OUT_CSV}")
    print(f"Rows  : {len(combined)}")
    print(f"Range : {combined['date'].iloc[0]} -> {combined['date'].iloc[-1]}")
    print(f"\nLatest 3 rows:")
    print(combined.tail(3).to_string(index=False))
    print()
    print("Now run:  python p5_p9_run.py")


if __name__ == "__main__":
    main()
