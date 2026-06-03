"""
Session feature engine — aligned to LSE v5 Pine defaults.

Session hours (UTC, matching HUD inputs):
  Tokyo      00:00 - 09:00   (tokyoOpen=0,   tokyoClose=9)
  London     07:00 - 16:00   (londonOpen=7,  londonClose=16)
  NY         13:00 - 22:00   (nyOpen=13,     nyClose=22)
  London/NY  13:00 - 16:00   (overlap)

IB formation = first 60 min of each session open:
  Asia IB    : hour == 0  (00:00-00:55 UTC), confirmed after 01:00
  London IB  : hour == 7  (07:00-07:55 UTC), confirmed after 08:00
  NY IB      : hour == 13 (13:00-13:55 UTC), confirmed after 14:00

Asian Range (for sweep) = full Tokyo range locked at London open:
  Built:  all bars with hour in [0..6] (00:00-06:55)
  Locked: available from hour 7 onwards (London open)

All values are lookahead-safe -- a bar at timestamp T only sees
information confirmed by completed bars before T.
"""
import numpy as np
import pandas as pd

# ── HUD session constants (match Pine input defaults) ─────────────────────────
TOKYO_START    = 0
TOKYO_END      = 9
LONDON_START   = 7
LONDON_END     = 16
NY_START       = 13
NY_END         = 22

ASIA_IB_HOUR    = 0    # IB builds hour 0, available from hour 1
LONDON_IB_HOUR  = 7    # IB builds hour 7, available from hour 8
NY_IB_HOUR      = 13   # IB builds hour 13, available from hour 14

LONDON_SWEEP_HOUR = 7  # bullSweepAsian / bearSweepAsian only fire this hour

# Pine input defaults
ATR_LEN        = 14
REGIME_THRESH  = 0.6   # regimeThresh
DRIFT_BODY_MIN = 0.4   # driftBodyMin
DRIFT_BARS     = 3     # driftBars
TOKYO_BODY_MIN = 0.3   # tokyoBreakBody
TOKYO_CONF     = 2     # tokyoConfBars
POC_LOOKBACK   = 60    # pocLookback
VOL_LOOKBACK   = 80    # volLookback
VOL_PERCENTILE = 75    # volPercentile


# ── helpers ───────────────────────────────────────────────────────────────────

def _true_range(m5: pd.DataFrame) -> pd.Series:
    prev = m5["close"].shift(1)
    return pd.concat([
        m5["high"] - m5["low"],
        (m5["high"] - prev).abs(),
        (m5["low"]  - prev).abs(),
    ], axis=1).max(axis=1)


def _atr(m5: pd.DataFrame, n: int = ATR_LEN) -> pd.Series:
    return _true_range(m5).rolling(n).mean().rename("m5_atr")


# ── session label ─────────────────────────────────────────────────────────────

def session_label(idx: pd.DatetimeIndex) -> pd.Series:
    h = idx.hour
    out = pd.Series("off", index=idx, dtype=object)
    out[(h >= TOKYO_START)  & (h < TOKYO_END)]  = "tokyo"
    out[(h >= LONDON_START) & (h < NY_START)]   = "london"
    out[(h >= NY_START)     & (h < LONDON_END)] = "london_ny"   # overlap
    out[(h >= LONDON_END)   & (h < NY_END)]     = "ny"
    return out


# ── Asian Range (full Tokyo session, locked at London open) ───────────────────

def compute_asian_range(m5: pd.DataFrame) -> pd.DataFrame:
    """
    Asian Range = max/min of all Tokyo bars with hour < LONDON_START (00:00-06:55).
    These are fully confirmed before London opens at 07:00.
    Returns a date-indexed DataFrame: asian_range_high, asian_range_low.
    """
    h    = m5.index.hour
    mask = (h >= TOKYO_START) & (h < LONDON_START)     # 00:00-06:55
    sub  = m5[mask].copy()
    sub["_date"] = sub.index.normalize()
    hi = sub.groupby("_date")["high"].max().rename("asian_range_high")
    lo = sub.groupby("_date")["low"].min().rename("asian_range_low")
    return pd.concat([hi, lo], axis=1)


# ── Session IBs ───────────────────────────────────────────────────────────────

def compute_ibs(m5: pd.DataFrame) -> pd.DataFrame:
    """
    First-hour IBs for each session.
    Returns date-indexed DataFrame: asia_ib_*, london_ib_*, ny_ib_*
    """
    h = m5.index.hour

    def _ib(mask, prefix):
        sub = m5[mask].copy()
        sub["_date"] = sub.index.normalize()
        hi = sub.groupby("_date")["high"].max().rename(f"{prefix}_ib_high")
        lo = sub.groupby("_date")["low"].min().rename(f"{prefix}_ib_low")
        return pd.concat([hi, lo], axis=1)

    asia   = _ib(h == ASIA_IB_HOUR,   "asia")
    london = _ib(h == LONDON_IB_HOUR, "london")
    ny     = _ib(h == NY_IB_HOUR,     "ny")
    return pd.concat([asia, london, ny], axis=1)


# ── ATR-based M5 regime (matches Pine regimeLabel) ───────────────────────────

def compute_m5_regime(m5: pd.DataFrame) -> pd.DataFrame:
    """
    M5-bar ATR ratio and regime flags matching Pine Layer 8.
    atrRatio       = atr(14) / sma(atr(14), 20)
    regimeVolatile = atrRatio > 1 + REGIME_THRESH  (> 1.60)
    regimeDrift    = atrRatio < 1 - REGIME_THRESH*0.5 (< 0.70)
    regimeNeutral  = everything else
    """
    atr    = _atr(m5, ATR_LEN)
    atr_ma = atr.rolling(20).mean()
    ratio  = atr / atr_ma.replace(0, np.nan)
    volatile = ratio > (1.0 + REGIME_THRESH)
    drift    = ratio < (1.0 - REGIME_THRESH * 0.5)
    neutral  = ~volatile & ~drift
    return pd.DataFrame({
        "m5_atr":      atr,
        "m5_atr_ratio": ratio,
        "m5_volatile": volatile,
        "m5_drift":    drift,
        "m5_neutral":  neutral,
    })


# ── Volume metrics ────────────────────────────────────────────────────────────

def compute_vol_metrics(m5: pd.DataFrame, atr: pd.Series) -> pd.DataFrame:
    """
    Rolling volume percentile rank and derived flags (matches Pine Layer 6).
    vol_rank   = pct rank of current bar volume vs last VOL_LOOKBACK bars
    vol_surge  = vol_rank >= VOL_PERCENTILE
    bull_flow  = vol_surge AND close > open AND body_pct > 0.5
    bear_flow  = vol_surge AND close < open AND body_pct > 0.5
    absorption = vol_surge AND body_pct < 0.35
    """
    vol = m5["volume"]
    # Rolling percentile rank: fraction of last N bars with lower volume
    vol_rank = vol.rolling(VOL_LOOKBACK, min_periods=10).apply(
        lambda x: float((x[:-1] < x[-1]).sum()) / max(len(x) - 1, 1) * 100,
        raw=True
    )
    body  = (m5["close"] - m5["open"]).abs()
    b_pct = body / atr.replace(0, np.nan)
    surge = vol_rank >= VOL_PERCENTILE
    return pd.DataFrame({
        "vol_rank":   vol_rank,
        "vol_surge":  surge,
        "bull_flow":  surge & (m5["close"] > m5["open"]) & (b_pct > 0.5),
        "bear_flow":  surge & (m5["close"] < m5["open"]) & (b_pct > 0.5),
        "absorption": surge & (b_pct < 0.35),
        "body_size":  body,
        "body_pct":   b_pct,
    })


# ── Daily VWAP (session-anchored, resets at midnight UTC) ────────────────────

def compute_daily_vwap(m5: pd.DataFrame) -> pd.Series:
    """Cumulative VWAP from midnight UTC, matching Pine ta.vwap(hlc3)."""
    df        = m5.copy()
    df["_d"]  = df.index.normalize()
    df["hlc3"]= (df["high"] + df["low"] + df["close"]) / 3
    df["tpv"] = df["hlc3"] * df["volume"]
    c_tpv     = df.groupby("_d")["tpv"].cumsum()
    c_vol     = df.groupby("_d")["volume"].cumsum()
    return (c_tpv / c_vol.replace(0, np.nan)).rename("vwap")


# ── Pseudo-POC (Pine Layer 4) ─────────────────────────────────────────────────

def compute_pseudo_poc(m5: pd.DataFrame) -> pd.Series:
    """
    Close of the highest-volume bar in the last POC_LOOKBACK bars.
    Matches Pine:  for i = 0 to pocLookback-1: if vol[i] > maxVol: poc := close[i]
    """
    vol   = m5["volume"].to_numpy()
    close = m5["close"].to_numpy()
    poc   = np.full(len(m5), np.nan)
    for i in range(POC_LOOKBACK, len(m5)):
        w   = slice(i - POC_LOOKBACK, i + 1)
        poc[i] = close[i - POC_LOOKBACK + int(np.argmax(vol[w]))]
    return pd.Series(poc, index=m5.index, name="pseudo_poc")


# ── 1H HTF Bias (matches Pine request.security "60", lookahead_off) ──────────

def compute_htf_bias(m5: pd.DataFrame) -> pd.DataFrame:
    """
    For each M5 bar: was the last COMPLETED 1H bar bullish vs its daily VWAP?

    htf_bull_bias = prev_1H_close > prev_1H_daily_vwap
    htf_bear_bias = prev_1H_close < prev_1H_daily_vwap

    Matches Pine:
      htfClose = request.security(ticker, "60", close,        lookahead_off)
      htfVwap  = request.security(ticker, "60", ta.vwap(hlc3),lookahead_off)
      htfBullBias = htfClose > htfVwap
    """
    h1 = m5.resample("h").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["close"])

    h1["_d"]   = h1.index.normalize()
    h1["hlc3"] = (h1["high"] + h1["low"] + h1["close"]) / 3
    h1["tpv"]  = h1["hlc3"] * h1["volume"]
    c_tpv = h1.groupby("_d")["tpv"].cumsum()
    c_vol = h1.groupby("_d")["volume"].cumsum()
    h1["vwap"] = c_tpv / c_vol.replace(0, np.nan)

    # Shift 1: each M5 bar inside a 1H period sees the PREVIOUS 1H bar's values
    prev_close = h1["close"].shift(1)
    prev_vwap  = h1["vwap"].shift(1)
    bull = (prev_close > prev_vwap).rename("htf_bull_bias")
    bear = (prev_close < prev_vwap).rename("htf_bear_bias")

    bull_m5 = bull.reindex(m5.index, method="ffill")
    bear_m5 = bear.reindex(m5.index, method="ffill")
    return pd.concat([bull_m5, bear_m5], axis=1)


# ── Running Tokyo range (for TOKYO_BREAK within Tokyo) ───────────────────────

def compute_tokyo_running_range(m5: pd.DataFrame) -> pd.DataFrame:
    """
    For bars inside the Tokyo session, compute the cumulative max(high) and
    min(low) of ALL PREVIOUS Tokyo bars on the same day (not including current).

    Used by TOKYO_BREAK to detect close > prev Tokyo high without lookahead.
    """
    tok_mask = m5.index.hour < TOKYO_END
    sub      = m5[tok_mask].copy()
    sub["_d"] = sub.index.normalize()

    ph = sub.groupby("_d")["high"].transform(
        lambda s: s.expanding().max().shift(1)
    )
    pl = sub.groupby("_d")["low"].transform(
        lambda s: s.expanding().min().shift(1)
    )
    # Count bars into Tokyo session (for tokyoRangeReady = >= 10 bars)
    bar_num = sub.groupby("_d").cumcount()

    out = pd.DataFrame({
        "prev_tok_high": ph,
        "prev_tok_low":  pl,
        "tok_bar_num":   bar_num,
    }, index=sub.index)
    return out.reindex(m5.index)   # NaN for non-Tokyo bars


# ── Master context builder ────────────────────────────────────────────────────

def attach_context(m5: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich M5 bars with all derived features needed by the expectancy harness.
    Returns a copy of m5 with extra columns; all values are lookahead-safe.
    """
    out = m5.copy()
    out["session"] = session_label(m5.index)
    out["_date"]   = out.index.normalize()
    out["_h"]      = out.index.hour

    # ── Asian Range (available from hour 7 onwards) ───────────────────────────
    ar = compute_asian_range(m5)
    out = out.join(ar, on="_date")
    out.loc[out["_h"] < LONDON_START, ["asian_range_high", "asian_range_low"]] = np.nan

    # ── Session IBs (masked until confirmed) ─────────────────────────────────
    ibs = compute_ibs(m5)
    out = out.join(ibs, on="_date")
    out.loc[out["_h"] < (ASIA_IB_HOUR + 1),   ["asia_ib_high",   "asia_ib_low"]]   = np.nan
    out.loc[out["_h"] < (LONDON_IB_HOUR + 1), ["london_ib_high", "london_ib_low"]] = np.nan
    out.loc[out["_h"] < (NY_IB_HOUR + 1),     ["ny_ib_high",     "ny_ib_low"]]     = np.nan

    # ── ATR + M5 regime ───────────────────────────────────────────────────────
    reg = compute_m5_regime(m5)
    for col in reg.columns:
        out[col] = reg[col]

    # ── Volume metrics ────────────────────────────────────────────────────────
    vm = compute_vol_metrics(m5, reg["m5_atr"])
    for col in vm.columns:
        out[col] = vm[col]

    # ── Daily VWAP + pseudo-POC ───────────────────────────────────────────────
    out["vwap"]       = compute_daily_vwap(m5)
    out["pseudo_poc"] = compute_pseudo_poc(m5)

    # ── 1H HTF bias ───────────────────────────────────────────────────────────
    htf = compute_htf_bias(m5)
    out["htf_bull_bias"] = htf["htf_bull_bias"]
    out["htf_bear_bias"] = htf["htf_bear_bias"]

    # ── Running Tokyo range (for TOKYO_BREAK) ─────────────────────────────────
    tkr = compute_tokyo_running_range(m5)
    out["prev_tok_high"] = tkr["prev_tok_high"]
    out["prev_tok_low"]  = tkr["prev_tok_low"]
    out["tok_bar_num"]   = tkr["tok_bar_num"]

    return out.drop(columns=["_date", "_h"])
