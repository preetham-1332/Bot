"""
P7 — Geopolitical fresh-shock detector.

No news feed required.  The detector uses price action alone:
  1. A "shock bar" is any D1 bar where |XAU log-return| > SHOCK_ATR_MULT * ATR_ratio.
  2. A shock persists for SHOCK_FRESH_DAYS trading days ("fresh shock").
  3. After that window the event is considered "priced in".

Interpretation
--------------
  shock_fresh  = +1 / -1  for bullish / bearish fresh shock (within SHOCK_FRESH_DAYS)
  shock_priced = +1 / -1  for priced-in shock (decayed direction)

  In the daily scoring model:
    fresh shock (same direction as trade) = additional +1 bonus
    priced-in shock (opposite direction)  = caution; may represent exhaustion

Manual override
---------------
For genuine geopolitical events, the user can set a flag in the panel by
adding a column "geo_override" (-1, 0, +1) to daily_panel.csv.
The combine_shock() function merges automatic + manual signals.

Parameters (Pine-aligned, calibrated on gold volatility)
----------------------------------------------------------
  SHOCK_ATR_MULT    = 2.5  -> flag D1 returns > 2.5x the ATR ratio
  ATR_FAST          = 14   -> ATR period (matches Pine atrLen=14, on D1)
  SHOCK_FRESH_DAYS  = 10   -> shock decays to "priced-in" after 10 trading days
  SHOCK_PRICED_DAYS = 25   -> shock fully forgotten after 25 trading days
"""

from __future__ import annotations
import numpy as np
import pandas as pd

SHOCK_ATR_MULT   = 2.5
ATR_FAST         = 14
SHOCK_FRESH_DAYS = 10
SHOCK_PRICED_DAYS = 25


# ── ATR on D1 ─────────────────────────────────────────────────────────────────

def _d1_atr(panel: pd.DataFrame, n: int = ATR_FAST) -> pd.Series:
    prev = panel["xau_close"].shift(1)
    tr   = pd.concat([
        panel["xau_high"] - panel["xau_low"],
        (panel["xau_high"] - prev).abs(),
        (panel["xau_low"]  - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean().rename("d1_atr")


# ── Shock detection ───────────────────────────────────────────────────────────

def compute_shock(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Detect fresh-shock and priced-in shock flags on D1 data.

    Returns a DataFrame (aligned to panel.index) with:
      d1_ret       : XAU daily log return
      d1_atr       : 14-period ATR
      shock_bar    : +1 (bullish spike), -1 (bearish spike), 0 (normal)
      shock_fresh  : +1/-1  while within SHOCK_FRESH_DAYS of the last shock
      shock_priced : +1/-1  while between FRESH and PRICED windows
      shock_gone   : bool, all shock windows have decayed
    """
    d1_ret = np.log(panel["xau_close"] / panel["xau_close"].shift(1))
    atr    = _d1_atr(panel)
    atr_pct = atr / panel["xau_close"]   # normalise ATR to % so it's scale-free

    # A shock bar: |ret| > SHOCK_ATR_MULT * atr_pct
    threshold = SHOCK_ATR_MULT * atr_pct
    shock_bar = pd.Series(0, index=panel.index)
    shock_bar.loc[d1_ret >  threshold] =  1
    shock_bar.loc[d1_ret < -threshold] = -1

    # Forward-propagate shock direction for SHOCK_FRESH_DAYS then PRICED_DAYS
    shock_fresh  = pd.Series(0, index=panel.index)
    shock_priced = pd.Series(0, index=panel.index)

    shock_idx    = shock_bar[shock_bar != 0].index
    arr          = panel.index

    for shock_dt in shock_idx:
        loc   = arr.get_loc(shock_dt)
        dirn  = shock_bar.loc[shock_dt]
        # Fresh window
        fresh_end  = min(loc + SHOCK_FRESH_DAYS  + 1, len(arr))
        priced_end = min(loc + SHOCK_PRICED_DAYS + 1, len(arr))
        for i in range(loc + 1, fresh_end):
            shock_fresh.iloc[i]  = dirn
        for i in range(fresh_end, priced_end):
            shock_priced.iloc[i] = dirn

    shock_gone = (shock_fresh == 0) & (shock_priced == 0)

    return pd.DataFrame({
        "d1_ret":       d1_ret.round(5),
        "d1_atr":       atr.round(3),
        "shock_bar":    shock_bar,
        "shock_fresh":  shock_fresh,
        "shock_priced": shock_priced,
        "shock_gone":   shock_gone,
    }, index=panel.index)


def combine_shock(shock_df: pd.DataFrame,
                  panel: pd.DataFrame) -> pd.Series:
    """
    Combine the automatic shock signal with a manual geo_override column
    (if present in panel).

    Returns a single signed series: shock_signal (+1 / 0 / -1).
    Manual override takes precedence when non-zero.
    """
    auto = shock_df["shock_fresh"].copy()
    if "geo_override" in panel.columns:
        override = panel["geo_override"].fillna(0).astype(int)
        # Manual override replaces auto when non-zero
        combined = auto.where(override == 0, override)
    else:
        combined = auto
    return combined.rename("shock_signal")


def shock_summary(shock_df: pd.DataFrame, panel: pd.DataFrame) -> str:
    """Human-readable summary."""
    n_shock = (shock_df["shock_bar"] != 0).sum()
    n_bull  = (shock_df["shock_bar"] ==  1).sum()
    n_bear  = (shock_df["shock_bar"] == -1).sum()
    latest  = shock_df[["shock_fresh", "shock_priced"]].iloc[-1]
    fresh   = int(latest["shock_fresh"])
    priced  = int(latest["shock_priced"])

    if fresh != 0:
        state = f"FRESH SHOCK ({'+' if fresh > 0 else ''}{fresh})"
    elif priced != 0:
        state = f"PRICED IN ({'+' if priced > 0 else ''}{priced})"
    else:
        state = "NO ACTIVE SHOCK"

    lines = [
        f"Shock detector ({len(shock_df)} D1 bars):",
        f"  Total shock bars : {n_shock}  "
        f"(bull={n_bull}, bear={n_bear}, threshold={SHOCK_ATR_MULT}x ATR)",
        f"  Current state    : {state}",
    ]

    # Last 5 shock events
    shocks = shock_df[shock_df["shock_bar"] != 0].tail(5)
    if not shocks.empty:
        lines.append("  Last 5 shock bars:")
        for dt, row in shocks.iterrows():
            dirn = "BULL" if row["shock_bar"] > 0 else "BEAR"
            lines.append(f"    {dt.date()}  {dirn:5s}  "
                         f"ret={row['d1_ret']:+.4f}  "
                         f"threshold={SHOCK_ATR_MULT*row['d1_atr']/panel.loc[dt,'xau_close']:+.4f}")
    return "\n".join(lines)
