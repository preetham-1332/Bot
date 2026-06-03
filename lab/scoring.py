"""
P3 — Symmetric signal scoring thresholds.

Replaces the old 14-factor additive model with a two-composite system
that scores drivers, not symptoms.

New model inputs
----------------
  macro_score    : -2..+2  (PC1 of dollar/rates cluster, quintile-ranked)
  session_score  : -2..+2  (price-structure composite: HTF+VWAP+POC+IB)
  regime         : TREND(1) or RANGE(0)  (D1 HMM)

Combined score   : macro_score + session_score  -> -4..+4

Thresholds (symmetric)
----------------------
  combined >= +3              STRONG_LONG
  combined in [+1, +2]        MILD_LONG
  combined == 0               NEUTRAL
  combined in [-2, -1]        MILD_SHORT
  combined <= -3              STRONG_SHORT

Regime modifier
---------------
  TREND + combined >= +2  =>  upgrade MILD_LONG  -> STRONG_LONG
  TREND + combined <= -2  =>  upgrade MILD_SHORT -> STRONG_SHORT
  RANGE                   =>  no modification (or use as confirmation to hold)

Old system asymmetry that this fixes
-------------------------------------
  Old STRONG LONG  required +8 / +14 = 57% of max.
  Old STRONG SHORT required  -5 / -14 = 36% of max.
  => implicit long bias in the original thresholds.
  New thresholds are +-3 out of +-4 (75%) for STRONG on both sides.
"""

from __future__ import annotations
from dataclasses import dataclass

# ── Signal labels ─────────────────────────────────────────────────────────────

STRONG_LONG  = "STRONG_LONG"
MILD_LONG    = "MILD_LONG"
NEUTRAL      = "NEUTRAL"
MILD_SHORT   = "MILD_SHORT"
STRONG_SHORT = "STRONG_SHORT"

SIGNAL_LABELS = [STRONG_SHORT, MILD_SHORT, NEUTRAL, MILD_LONG, STRONG_LONG]

# Minimum combined score required for any directional trade
MIN_LONG_SCORE  =  1   # combined must be >= +1 to consider a long
MIN_SHORT_SCORE = -1   # combined must be <= -1 to consider a short

# Minimum score for full size; below this use half size
FULL_SIZE_LONG  =  2
FULL_SIZE_SHORT = -2


# ── Scoring function ──────────────────────────────────────────────────────────

@dataclass
class SignalLabel:
    label:        str
    combined:     int
    macro_score:  int
    session_score: int
    regime:       str
    regime_boost: bool   # True if TREND upgraded the label
    tradeable:    bool   # combined meets MIN threshold
    full_size:    bool   # combined meets FULL_SIZE threshold


def classify(macro_score: int,
             session_score: int,
             regime: int | str) -> SignalLabel:
    """
    Produce a SignalLabel from the three model inputs.

    macro_score   : int in [-2, +2]
    session_score : int in [-2, +2]
    regime        : 0 (RANGE) or 1 (TREND), or the string "RANGE"/"TREND"
    """
    if isinstance(regime, str):
        regime_int = 1 if regime.upper() == "TREND" else 0
    else:
        regime_int = int(regime)
    regime_str = "TREND" if regime_int == 1 else "RANGE"

    combined = int(macro_score) + int(session_score)

    # Base label from thresholds
    if combined >= 3:
        label = STRONG_LONG
    elif combined >= 1:
        label = MILD_LONG
    elif combined == 0:
        label = NEUTRAL
    elif combined >= -2:
        label = MILD_SHORT
    else:
        label = STRONG_SHORT

    # Regime modifier: TREND upgrades MILD -> STRONG
    regime_boost = False
    if regime_int == 1:
        if label == MILD_LONG:
            label = STRONG_LONG
            regime_boost = True
        elif label == MILD_SHORT:
            label = STRONG_SHORT
            regime_boost = True

    tradeable = (label in (MILD_LONG, STRONG_LONG) or
                 label in (MILD_SHORT, STRONG_SHORT))

    full_size = (combined >= FULL_SIZE_LONG or combined <= FULL_SIZE_SHORT or
                 (regime_boost and tradeable))

    return SignalLabel(
        label=label,
        combined=combined,
        macro_score=int(macro_score),
        session_score=int(session_score),
        regime=regime_str,
        regime_boost=regime_boost,
        tradeable=tradeable,
        full_size=full_size,
    )


def label_to_size_pct(sig: SignalLabel, base_pct: float = 0.5) -> float:
    """
    Map signal label to a risk % per trade.
    Half-size for MILD without regime boost; full-size for STRONG or regime-boosted.
    """
    if not sig.tradeable:
        return 0.0
    if sig.full_size:
        return base_pct
    return base_pct * 0.5


def format_label(sig: SignalLabel) -> str:
    """One-line summary of the signal label."""
    boost = " [TREND boost]" if sig.regime_boost else ""
    size  = "full size" if sig.full_size else "half size"
    if not sig.tradeable:
        size = "NO TRADE"
    return (f"{sig.label}{boost}  "
            f"(combined {sig.combined:+d} = macro {sig.macro_score:+d} "
            f"+ session {sig.session_score:+d}, regime={sig.regime})  "
            f"-> {size}")


# ── Historical threshold analysis helper ─────────────────────────────────────

def score_history(panel, session_daily) -> "pd.DataFrame":
    """
    Apply classify() to the full panel history.
    Returns a date-indexed DataFrame with signal labels for every day.
    """
    import pandas as pd
    import numpy as np
    from lab.regime import NAMES as RN

    sess = session_daily["session_score"].dropna()
    sess.index = sess.index.normalize()

    rows = []
    merged = (panel[["macro_score", "regime"]]
              .dropna(subset=["macro_score"])
              .join(sess.rename("session_score"), how="inner")
              .dropna())

    for dt, row in merged.iterrows():
        if np.isnan(row["session_score"]):
            continue
        sig = classify(
            int(row["macro_score"]),
            int(row["session_score"]),
            int(row["regime"]),
        )
        rows.append({
            "date":          dt,
            "macro_score":   sig.macro_score,
            "session_score": sig.session_score,
            "regime":        sig.regime,
            "combined":      sig.combined,
            "label":         sig.label,
            "regime_boost":  sig.regime_boost,
            "tradeable":     sig.tradeable,
            "full_size":     sig.full_size,
        })
    return pd.DataFrame(rows).set_index("date")
