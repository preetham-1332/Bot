"""
2-state GaussianHMM regime classifier for D1 XAU/USD.

States : RANGE (0) -- choppy, mean-reverting
         TREND (1) -- directional, momentum

Features fed to the HMM:
  log_ret     -- daily log return (captures size and direction)
  eff_ratio   -- 14-bar Kaufman Efficiency Ratio (0=chop, 1=trend)

ATR ratio is computed separately and is NOT an HMM feature --
it is the independent volatility axis (per audit spec).

Lookahead note: fit_regime() trains on the full history and runs
full-sequence Viterbi.  Both steps use future data (oracle view).
This is acceptable for a first-pass backtest; a rolling/causal
implementation is Phase 2 hardening.
"""
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

RANGE = 0
TREND = 1
NAMES = {RANGE: "RANGE", TREND: "TREND"}


# ── features ──────────────────────────────────────────────────────────────────

def _efficiency_ratio(close: pd.Series, n: int = 14) -> pd.Series:
    """
    ER = |close[t] - close[t-n]| / sum(|close[i]-close[i-1]|, i=t-n+1..t)
    Clipped to [0, 1].  1 = pure trend, 0 = pure chop.
    """
    net   = (close - close.shift(n)).abs()
    path  = close.diff().abs().rolling(n).sum()
    return (net / path.replace(0, np.nan)).clip(0, 1).rename("eff_ratio")


def _atr_series(high, low, close, n):
    prev = close.shift(1)
    tr = pd.concat([high - low,
                    (high - prev).abs(),
                    (low  - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


# ── public API ─────────────────────────────────────────────────────────────────

def compute_atr_ratio(panel: pd.DataFrame,
                      fast: int = 14, slow: int = 60) -> pd.Series:
    """
    ATR(fast) / ATR(slow) -- the independent volatility axis.
    >1 = above-average volatility, <1 = compressed.
    """
    h, l, c = panel["xau_high"], panel["xau_low"], panel["xau_close"]
    return (_atr_series(h, l, c, fast) / _atr_series(h, l, c, slow)).rename("atr_ratio")


def fit_regime(panel: pd.DataFrame,
               n_iter: int = 400,
               n_seeds: int = 8) -> tuple[pd.Series, GaussianHMM]:
    """
    Fit a 2-state GaussianHMM and return (regime_series, fitted_model).

    regime_series is int-typed: RANGE=0, TREND=1, aligned to panel.index.
    NaN for the warmup rows where eff_ratio is not yet defined.

    Multiple random seeds are tried; the run with the highest log-likelihood
    is kept.
    """
    close = panel["xau_close"]
    log_ret   = np.log(close / close.shift(1))
    eff_ratio = _efficiency_ratio(close, 14)

    feats = pd.DataFrame({"log_ret": log_ret, "eff_ratio": eff_ratio}).dropna()
    X = feats.values

    best_model, best_ll = None, -np.inf
    for seed in range(n_seeds):
        m = GaussianHMM(
            n_components=2,
            covariance_type="full",
            n_iter=n_iter,
            random_state=seed,
        )
        m.fit(X)
        ll = m.score(X)
        if ll > best_ll:
            best_ll, best_model = ll, m

    raw = best_model.predict(X)

    # TREND = state with higher mean efficiency ratio (column index 1)
    trend_idx = int(np.argmax(best_model.means_[:, 1]))
    mapped = np.where(raw == trend_idx, TREND, RANGE).astype(float)

    regime = pd.Series(mapped, index=feats.index, name="regime")
    regime = regime.reindex(panel.index)   # NaN for warmup rows
    return regime, best_model


def describe_model(model: GaussianHMM, trend_idx: int) -> str:
    """Return a human-readable summary of the HMM parameters."""
    range_idx = 1 - trend_idx
    lines = []
    for i, label in [(range_idx, "RANGE"), (trend_idx, "TREND")]:
        mu  = model.means_[i]
        cov = model.covars_[i]
        lines.append(
            f"  State {label}: mean_log_ret={mu[0]:.5f}  "
            f"mean_eff_ratio={mu[1]:.4f}  "
            f"std_log_ret={cov[0,0]**0.5:.5f}"
        )
    tm = model.transmat_
    lines.append(
        f"  Transition: P(RANGE->TREND)={tm[range_idx, trend_idx]:.4f}  "
        f"P(TREND->RANGE)={tm[trend_idx, range_idx]:.4f}"
    )
    return "\n".join(lines)
