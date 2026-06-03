"""Data loaders for broker CSVs and the daily panel."""
from pathlib import Path
import pandas as pd

ROOT   = Path(__file__).parent.parent
D1_DIR = ROOT / "historical data" / "D1"
M5_DIR = ROOT / "historical data" / "m5"
PANEL  = ROOT / "daily_panel.csv"

_COLS = ["date", "open", "high", "low", "close", "vol_tick", "volume"]


def _broker_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(
        path, sep="\t", thousands=" ",
        names=_COLS, header=0, index_col=0, parse_dates=True,
    )
    df.index.name = "date"
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_panel() -> pd.DataFrame:
    df = pd.read_csv(PANEL, index_col=0, parse_dates=True)
    df.index.name = "date"
    return df


def load_m5() -> pd.DataFrame:
    return _broker_csv(M5_DIR / "XAUUSD_M5.csv")
