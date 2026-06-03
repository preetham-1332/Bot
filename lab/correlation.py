"""
P5 — Rolling correlation monitor.

Computes 20-day and 60-day rolling correlations of XAU 1D log-returns
against each dollar/rates factor.  Decoupling is flagged when the
short-window correlation falls more than 1 std below its own 1-year
baseline — this is treated as a signal in its own right.

Decouple interpretation
-----------------------
  +1  (bull decouple)  XAU is RISING despite a negative macro composite
                        -> structural demand overriding macro headwinds
                        -> adds +1 to the combined signal score
  -1  (bear decouple)  XAU is FALLING despite a positive macro composite
                        -> structural selling overriding macro tailwinds
                        -> adds -1 to the combined signal score
   0  Normal tracking  correlation is within one std of baseline
"""

from __future__ import annotations
import numpy as np
import pandas as pd

WINDOWS    = (20, 60)          # rolling correlation windows (trading days)
BASELINE   = 252               # long-run baseline window for decouple detection
DECOUPLE_Z = -1.0              # z-score threshold: below this = decoupling


# ── feature returns ───────────────────────────────────────────────────────────

def _factor_returns(panel: pd.DataFrame) -> pd.DataFrame:
    """
    1D log-returns / changes for XAU and the 5 macro factors.
    Signed so that +ve = bullish for gold (mirrors lab/pca.py convention).
    """
    df = pd.DataFrame(index=panel.index)
    df["xau"]     =  np.log(panel["xau_close"]  / panel["xau_close"].shift(1))
    df["usd"]     = -np.log(panel["usd_broad"]   / panel["usd_broad"].shift(1))
    df["real10y"] = -(panel["us10y_real"]          .diff(1))
    df["nom10y"]  = -(panel["us10y_nominal"]       .diff(1))
    df["eur"]     =  np.log(panel["eur_close"]   / panel["eur_close"].shift(1))
    df["jpy"]     = -np.log(panel["jpy_close"]   / panel["jpy_close"].shift(1))
    df["xag"]     =  np.log(panel["xag_close"]   / panel["xag_close"].shift(1))
    return df


# ── rolling correlations ──────────────────────────────────────────────────────

def compute_rolling_corr(panel: pd.DataFrame) -> pd.DataFrame:
    """
    For each factor, compute rolling 20D and 60D correlations with XAU.
    Returns a DataFrame of correlation columns aligned to panel.index.
    """
    rets    = _factor_returns(panel)
    factors = ["usd", "real10y", "nom10y", "eur", "jpy", "xag"]
    cols    = {}

    for w in WINDOWS:
        for f in factors:
            key = f"corr_{w}d_{f}"
            pair = rets[["xau", f]].dropna()
            roll = pair["xau"].rolling(w).corr(pair[f])
            cols[key] = roll

    return pd.DataFrame(cols, index=panel.index)


def compute_macro_corr(panel: pd.DataFrame,
                       macro_composite_col: str = "macro_composite",
                       window: int = 20) -> pd.Series:
    """
    Rolling {window}-day correlation of XAU returns vs the macro composite.
    Requires that panel already has the macro_composite column (from P1).
    """
    xau_ret = np.log(panel["xau_close"] / panel["xau_close"].shift(1))
    macro   = panel[macro_composite_col]
    pair    = pd.concat([xau_ret.rename("xau"), macro], axis=1).dropna()
    return (pair["xau"].rolling(window)
                       .corr(pair[macro_composite_col])
                       .rename(f"corr_{window}d_macro")
                       .reindex(panel.index))


# ── decouple flag ─────────────────────────────────────────────────────────────

def compute_decouple_flag(panel: pd.DataFrame,
                          short_window: int = 20,
                          baseline: int = BASELINE,
                          z_threshold: float = DECOUPLE_Z) -> pd.DataFrame:
    """
    Decouple flag: +1 / 0 / -1 per day.

    Algorithm:
      1. Compute rolling {short_window}-day correlation of XAU vs macro_composite.
      2. Compute rolling {baseline}-day mean and std of that correlation.
      3. z = (short_corr - baseline_mean) / baseline_std
      4. Decoupling when z < z_threshold (correlation has collapsed).
      5. Direction (+1 or -1) from the sign of XAU's own short-window return
         vs the sign of macro_composite over the same window.

    Returns DataFrame: corr_20d_macro, corr_mean, corr_std, corr_z, decouple
    """
    if "macro_composite" not in panel.columns:
        raise ValueError("Run p1_run.py first to add macro_composite to panel.")

    short_corr = compute_macro_corr(panel, window=short_window)

    corr_mean = short_corr.rolling(baseline, min_periods=baseline // 2).mean()
    corr_std  = short_corr.rolling(baseline, min_periods=baseline // 2).std()
    corr_z    = (short_corr - corr_mean) / corr_std.replace(0, np.nan)

    # Direction of decouple
    xau_ret_w  = np.log(panel["xau_close"] / panel["xau_close"].shift(short_window))
    macro_w    = panel["macro_composite"].rolling(short_window).mean()

    is_decoupled = corr_z < z_threshold

    direction = pd.Series(0, index=panel.index)
    direction.loc[is_decoupled & (xau_ret_w > 0) & (macro_w < 0)] =  1  # bull decouple
    direction.loc[is_decoupled & (xau_ret_w < 0) & (macro_w > 0)] = -1  # bear decouple

    return pd.DataFrame({
        "corr_20d_macro": short_corr,
        "corr_mean":      corr_mean,
        "corr_std":       corr_std,
        "corr_z":         corr_z.round(3),
        "decouple":       direction,
    }, index=panel.index)


def decouple_summary(decouple_df: pd.DataFrame) -> str:
    """Human-readable summary of the decouple series."""
    n_bull = (decouple_df["decouple"] ==  1).sum()
    n_bear = (decouple_df["decouple"] == -1).sum()
    n_norm = (decouple_df["decouple"] ==  0).sum()
    total  = len(decouple_df.dropna(subset=["decouple"]))
    latest = decouple_df["decouple"].dropna().iloc[-1] if total > 0 else 0
    latest_z = decouple_df["corr_z"].dropna().iloc[-1] if total > 0 else float("nan")
    latest_corr = decouple_df["corr_20d_macro"].dropna().iloc[-1] if total > 0 else float("nan")
    label = {1: "BULL DECOUPLE", -1: "BEAR DECOUPLE", 0: "NORMAL TRACKING"}
    lines = [
        f"Decouple distribution ({total} days):",
        f"  Bull decouple (+1) : {n_bull:>5}  ({100*n_bull/max(total,1):.1f}%)",
        f"  Normal tracking (0): {n_norm:>5}  ({100*n_norm/max(total,1):.1f}%)",
        f"  Bear decouple (-1) : {n_bear:>5}  ({100*n_bear/max(total,1):.1f}%)",
        f"",
        f"Latest: corr_20d={latest_corr:+.3f}  z={latest_z:+.3f}  -> {label.get(int(latest), '?')}",
    ]
    return "\n".join(lines)
