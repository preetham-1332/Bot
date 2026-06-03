"""
P1 — Orthogonalized macro and session composites.

Macro composite
---------------
PC1 of a 5-factor dollar/rates matrix computed from daily_panel.csv:
  usd_broad change  (negated: dollar up = gold bearish)
  us10y_real change (negated: real yields up = gold bearish)
  us10y_nom  change (negated: nominal yields up = gold bearish)
  eur change        (kept:    EUR/USD up = dollar down = gold bullish)
  jpy change        (negated: USD/JPY up = dollar up = gold bearish)

All features are 20-day log/level changes, standardised to zero mean / unit
variance before PCA.  PC1 is sign-flipped if needed so that +ve = macro
tailwind for gold.

Session composite
-----------------
Normalised sum of 4 HUD-derived price-structure signals at the M5 level:
  htf_bias_s    : +1 bull / -1 bear  (1H close vs 1H VWAP)
  vwap_dist_n   : (close - vwap) / m5_atr  (clipped +-3)
  poc_vwap_n    : (pseudo_poc - vwap) / m5_atr  (clipped +-3)
  ib_state_s    : +1 above active IB high / -1 below active IB low / 0 inside

PCA on binary/semi-binary features provides limited compression; a simple
unit-weighted sum is used, then mapped to -2..+2 via rolling percentile.
The PC-loading approach is retained for the output report.

Lookahead note
--------------
Macro PCA is fitted on the full history (oracle view) — same trade-off as
the HMM regime classifier.  Rolling/causal refitting is Phase 2 hardening.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

# ── constants ─────────────────────────────────────────────────────────────────

CHANGE_DAYS      = 20     # horizon for macro feature changes (~1 month)
SCORE_LOOKBACK   = 252    # rolling window for quintile scoring (1 year)

_QUINT_EDGES = [0.20, 0.40, 0.60, 0.80]   # quintile breakpoints -> -2,-1,0,+1,+2


# ── helpers ───────────────────────────────────────────────────────────────────

def _quintile_score(s: pd.Series, lookback: int = SCORE_LOOKBACK) -> pd.Series:
    """
    Map a continuous series to -2..+2 via rolling quintile rank.
    The current bar is ranked against the previous `lookback` bars.
    """
    def _rank(x: np.ndarray) -> float:
        r = float((x[:-1] < x[-1]).sum()) / max(len(x) - 1, 1)
        if   r <= 0.20: return -2.0
        elif r <= 0.40: return -1.0
        elif r <= 0.60: return  0.0
        elif r <= 0.80: return  1.0
        else:           return  2.0

    return (s.rolling(lookback, min_periods=lookback // 2)
             .apply(_rank, raw=True)
             .rename(s.name + "_score"))


# ── macro composite ───────────────────────────────────────────────────────────

def _macro_feature_matrix(panel: pd.DataFrame,
                           n: int = CHANGE_DAYS) -> pd.DataFrame:
    """
    5-column signed-change matrix for the dollar/rates PCA.
    Positive values = macro tailwind for gold.
    """
    df = pd.DataFrame(index=panel.index)
    df["usd"]    = -np.log(panel["usd_broad"]     / panel["usd_broad"].shift(n))
    df["real10y"]= -(panel["us10y_real"]            .diff(n))
    df["nom10y"] = -(panel["us10y_nominal"]         .diff(n))
    df["eur"]    =  np.log(panel["eur_close"]      / panel["eur_close"].shift(n))
    df["jpy"]    = -np.log(panel["jpy_close"]      / panel["jpy_close"].shift(n))
    return df.dropna()


def fit_macro_pca(panel: pd.DataFrame
                  ) -> tuple[PCA, StandardScaler, pd.DataFrame]:
    """
    Fit a 5-component PCA on the full macro feature history.
    Returns (fitted PCA, fitted scaler, feature DataFrame).

    PC1 is sign-flipped so that +ve correlates with gold 20-day returns.
    """
    feats  = _macro_feature_matrix(panel)
    if feats.empty:
        raise ValueError(
            "Macro feature matrix is empty -- FRED columns (us10y_nominal, "
            "us10y_real, usd_broad) are all NaN.  Run build_panel.py first; "
            "if FRED is unreachable the cached values will be used automatically."
        )
    scaler = StandardScaler()
    X      = scaler.fit_transform(feats.values)

    pca = PCA(n_components=5)
    pca.fit(X)

    # Sign convention: PC1 positive = macro bullish for gold
    gold_ret = np.log(panel["xau_close"] / panel["xau_close"].shift(CHANGE_DAYS))
    shared   = feats.index.intersection(gold_ret.dropna().index)
    scores   = pca.transform(scaler.transform(_macro_feature_matrix(panel)
                              .reindex(shared).values))[:, 0]
    if np.corrcoef(scores, gold_ret.reindex(shared).values)[0, 1] < 0:
        pca.components_[0] *= -1

    return pca, scaler, feats


def compute_macro_composite(panel: pd.DataFrame,
                             pca: PCA | None = None,
                             scaler: StandardScaler | None = None,
                             ) -> pd.Series:
    """
    Project panel onto PC1 of the macro feature space.
    Returns a Series aligned to panel.index (NaN during warmup).
    """
    if pca is None or scaler is None:
        pca, scaler, _ = fit_macro_pca(panel)
    feats = _macro_feature_matrix(panel)
    X     = scaler.transform(feats.values)
    pc1   = pca.transform(X)[:, 0]
    return (pd.Series(pc1, index=feats.index, name="macro_composite")
              .reindex(panel.index))


def macro_loadings_report(pca: PCA, explained: np.ndarray) -> str:
    """Human-readable PC1 loadings summary."""
    names   = ["usd", "real10y", "nom10y", "eur", "jpy"]
    lines   = ["PC    Var%   usd    real10y  nom10y   eur    jpy"]
    lines  += ["-" * 55]
    for i in range(min(3, pca.n_components)):
        load = pca.components_[i]
        pct  = explained[i] * 100
        row  = f"PC{i+1}  {pct:5.1f}%  " + "  ".join(f"{v:+.3f}" for v in load)
        lines.append(row)
    return "\n".join(lines)


# ── session composite ─────────────────────────────────────────────────────────

def _ib_state(ctx: pd.DataFrame) -> pd.Series:
    """
    +1 if close is above the active IB high,
    -1 if close is below the active IB low,
     0 otherwise or unknown.
    Active IB = Asia IB during Tokyo; London IB during London; NY IB during NY.
    """
    h = ctx.index.hour
    out = pd.Series(0.0, index=ctx.index)

    # Tokyo: use asia IB
    tok = (h >= 1) & (h < 9)
    out.loc[tok & ctx["asia_ib_high"].notna()
            & (ctx["close"] > ctx["asia_ib_high"])]  =  1.0
    out.loc[tok & ctx["asia_ib_low"].notna()
            & (ctx["close"] < ctx["asia_ib_low"])]   = -1.0

    # London: use london IB
    lon = (h >= 8) & (h < 13)
    out.loc[lon & ctx["london_ib_high"].notna()
            & (ctx["close"] > ctx["london_ib_high"])] =  1.0
    out.loc[lon & ctx["london_ib_low"].notna()
            & (ctx["close"] < ctx["london_ib_low"])]  = -1.0

    # NY: use ny IB
    ny = (h >= 14) & (h < 22)
    out.loc[ny & ctx["ny_ib_high"].notna()
            & (ctx["close"] > ctx["ny_ib_high"])]     =  1.0
    out.loc[ny & ctx["ny_ib_low"].notna()
            & (ctx["close"] < ctx["ny_ib_low"])]      = -1.0

    return out


def compute_session_composite(ctx: pd.DataFrame) -> pd.Series:
    """
    Four price-structure signals normalised and summed -> session composite.

      htf_bias_s   : +1 bull / -1 bear
      vwap_dist_n  : (close - vwap) / atr, clipped to [-3, 3]
      poc_vwap_n   : (poc - vwap)   / atr, clipped to [-3, 3]
      ib_state_s   : +1 / 0 / -1

    The raw sum ranges -6..+6; it is returned unscaled so the caller can
    apply _quintile_score or inspect the components directly.
    """
    atr  = ctx["m5_atr"].replace(0, np.nan)

    htf_s  = ctx["htf_bull_bias"].fillna(False).astype(float) * 2 - 1  # +1/-1

    vwap_d = ((ctx["close"] - ctx["vwap"]) / atr).clip(-3, 3).fillna(0)

    poc_d  = ((ctx["pseudo_poc"] - ctx["vwap"]) / atr).clip(-3, 3).fillna(0)

    ib_s   = _ib_state(ctx)

    raw    = htf_s + vwap_d + poc_d + ib_s
    return raw.rename("session_composite")


def session_score_at_london_open(m5_ctx: pd.DataFrame) -> pd.Series:
    """
    For each calendar day, extract the session composite value at the bar
    immediately BEFORE London open (hour 6, last Tokyo bar) — the snapshot
    the trader sees when sizing up the London session.

    Returns a date-indexed Series of session composite scores.
    """
    comp = compute_session_composite(m5_ctx)
    # Last bar of hour 6 each day (just before London)
    pre_london = m5_ctx[m5_ctx.index.hour == 6].copy()
    pre_london["_d"] = pre_london.index.normalize()
    daily = comp.reindex(pre_london.index).groupby(pre_london["_d"]).last()
    daily.index.name = "date"
    return daily.rename("session_composite_eod_tokyo")
