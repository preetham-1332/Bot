"""
Expectancy harness v2 — setups aligned to LSE v5 Pine.

Three setups, each matching the actual Pine entry conditions:

  LSE_SWEEP   — London open hour (hour==7) only.
                Bar sweeps the FULL Asian Range high/low and closes back inside.
                Wick must exceed sweepWickMin*0.7 ATR (= 0.49 ATR).
                Gate: (bull_flow OR absorption) AND NOT regime drift.

  TOKYO_BREAK — Within Tokyo session (hour in [1..8], tok_bar_num >= 9).
                Close > prev_tok_high (cumulative Tokyo max shifted by 1).
                Body > 0.3 ATR, bullish close, HTF bias aligned.
                Signal fires on the 2nd consecutive qualifying bar (tokyoConfBars=2).

  DRIFT       — Any session; all 7 Pine conditions simultaneously:
                  m5_drift + bullMomentum(3 consec) + bullMicroConfirmed(3 consec) +
                  pocLeftBehindBull + vwapRideBull(3 consec) + htfBullBias + vol_rank>=50

Trade mechanics
---------------
  entry      : open of the bar AFTER the signal bar (no lookahead)
  stop long  : LSE_SWEEP   -> signal bar low  - STOP_BUFFER
               TOKYO_BREAK -> prev_tok_high   - STOP_BUFFER
               DRIFT       -> signal bar low  - STOP_BUFFER
  stop short : LSE_SWEEP   -> signal bar high + STOP_BUFFER
               TOKYO_BREAK -> prev_tok_low    + STOP_BUFFER
               DRIFT       -> signal bar high + STOP_BUFFER
  target     : entry +/- TARGET_R * risk_pts
  cost       : COST_PTS deducted per trade (round-trip spread + slippage)
  min risk   : trades with risk_pts < MIN_RISK_PTS are skipped
  max hold   : MAX_HOLD_BARS M5 bars; timeout exit at last bar's close
"""
import numpy as np
import pandas as pd

from lab.features import (
    LONDON_SWEEP_HOUR, TOKYO_END,
    TOKYO_BODY_MIN, TOKYO_CONF,
    DRIFT_BODY_MIN, DRIFT_BARS,
)

# Trade constants
STOP_BUFFER   = 2.0
TARGET_R      = 2.0
COST_PTS      = 0.50
MIN_RISK_PTS  = 3.0
MAX_HOLD_BARS = 48

# Pine sweep constants
SWEEP_WICK_MIN    = 0.7   # sweepWickMin input default
SWEEP_WICK_FACTOR = 0.7   # Asian sweep uses sweepWickMin * 0.7

# Pine drift constants
POC_LEAVE_MIN = 0.5   # pocLeaveMin input default
DRIFT_VOL_MIN = 50    # driftVolMin input default


# ── helpers ───────────────────────────────────────────────────────────────────

def _streak(s: pd.Series) -> pd.Series:
    """Running count of consecutive True values; resets to 0 on False."""
    grp = (~s).cumsum()
    cnt = s.groupby(grp).cumsum()
    return cnt.where(s, 0).astype(int)


# ── signal detection ──────────────────────────────────────────────────────────

def detect_signals(m5_ctx: pd.DataFrame) -> pd.DataFrame:
    """
    Vectorised signal detection on the context-enriched M5 DataFrame.

    Returns one row per trade signal sorted by timestamp.
    Columns: setup, direction, <all m5_ctx columns>.

    Only the FIRST signal of each (setup, direction) per calendar day is kept.
    """
    h   = m5_ctx.index.hour
    day = m5_ctx.index.normalize()

    # ── LSE_SWEEP (Asian Range sweep at London open) ──────────────────────────
    at_london_open = h == LONDON_SWEEP_HOUR
    has_asian      = m5_ctx["asian_range_high"].notna() & m5_ctx["asian_range_low"].notna()
    not_drift      = ~m5_ctx["m5_drift"].fillna(False)
    atr            = m5_ctx["m5_atr"]
    wick_thresh    = atr * SWEEP_WICK_MIN * SWEEP_WICK_FACTOR   # 0.49 ATR

    lse_base = at_london_open & has_asian & not_drift

    lse_long = (
        lse_base
        & (m5_ctx["low"]  < m5_ctx["asian_range_low"])
        & (m5_ctx["close"] >= m5_ctx["asian_range_low"])
        & ((m5_ctx["asian_range_low"] - m5_ctx["low"]) > wick_thresh)
        & (m5_ctx["bull_flow"] | m5_ctx["absorption"])
    )

    lse_short = (
        lse_base
        & (m5_ctx["high"]  > m5_ctx["asian_range_high"])
        & (m5_ctx["close"] <= m5_ctx["asian_range_high"])
        & ((m5_ctx["high"] - m5_ctx["asian_range_high"]) > wick_thresh)
        & (m5_ctx["bear_flow"] | m5_ctx["absorption"])
    )

    # ── TOKYO_BREAK (consecutive Tokyo range expansion) ───────────────────────
    in_tokyo   = (h >= 1) & (h < TOKYO_END)   # hour 1..8; hour 0 = IB building
    tok_ready  = m5_ctx["tok_bar_num"].fillna(-1) >= 9   # >= 10 bars into Tokyo

    tok_bull_base = (
        in_tokyo & tok_ready
        & m5_ctx["prev_tok_high"].notna()
        & (m5_ctx["close"] > m5_ctx["prev_tok_high"])
        & (m5_ctx["body_pct"].fillna(0) > TOKYO_BODY_MIN)
        & (m5_ctx["close"] > m5_ctx["open"])
    )

    tok_bear_base = (
        in_tokyo & tok_ready
        & m5_ctx["prev_tok_low"].notna()
        & (m5_ctx["close"] < m5_ctx["prev_tok_low"])
        & (m5_ctx["body_pct"].fillna(0) > TOKYO_BODY_MIN)
        & (m5_ctx["close"] < m5_ctx["open"])
    )

    tok_bull_streak = _streak(tok_bull_base)
    tok_bear_streak = _streak(tok_bear_base)

    tokyo_long  = (tok_bull_streak == TOKYO_CONF) & m5_ctx["htf_bull_bias"].fillna(False)
    tokyo_short = (tok_bear_streak == TOKYO_CONF) & m5_ctx["htf_bear_bias"].fillna(False)

    # ── DRIFT (all 7 Pine conditions) ─────────────────────────────────────────
    bull_candle   = (m5_ctx["close"] > m5_ctx["open"]) & (m5_ctx["body_pct"].fillna(0) > DRIFT_BODY_MIN)
    bear_candle   = (m5_ctx["close"] < m5_ctx["open"]) & (m5_ctx["body_pct"].fillna(0) > DRIFT_BODY_MIN)

    bull_momentum = _streak(bull_candle) >= DRIFT_BARS
    bear_momentum = _streak(bear_candle) >= DRIFT_BARS

    hh_hl = (m5_ctx["high"] > m5_ctx["high"].shift(1)) & (m5_ctx["low"] > m5_ctx["low"].shift(1))
    ll_lh = (m5_ctx["high"] < m5_ctx["high"].shift(1)) & (m5_ctx["low"] < m5_ctx["low"].shift(1))

    bull_micro = _streak(hh_hl) >= DRIFT_BARS
    bear_micro = _streak(ll_lh) >= DRIFT_BARS

    poc_diff     = m5_ctx["close"] - m5_ctx["pseudo_poc"].fillna(np.nan)
    poc_left_bull = (poc_diff >  atr * POC_LEAVE_MIN)
    poc_left_bear = (poc_diff < -atr * POC_LEAVE_MIN)

    above_vwap    = m5_ctx["close"] > m5_ctx["vwap"]
    below_vwap    = m5_ctx["close"] < m5_ctx["vwap"]
    vwap_ride_bull = _streak(above_vwap) >= DRIFT_BARS
    vwap_ride_bear = _streak(below_vwap) >= DRIFT_BARS

    drift_vol_ok  = m5_ctx["vol_rank"].fillna(0) >= DRIFT_VOL_MIN
    is_drift      = m5_ctx["m5_drift"].fillna(False)

    drift_long = (
        is_drift & bull_momentum & bull_micro &
        poc_left_bull & vwap_ride_bull &
        m5_ctx["htf_bull_bias"].fillna(False) & drift_vol_ok
    )

    drift_short = (
        is_drift & bear_momentum & bear_micro &
        poc_left_bear & vwap_ride_bear &
        m5_ctx["htf_bear_bias"].fillna(False) & drift_vol_ok
    )

    # ── collect and deduplicate ───────────────────────────────────────────────
    masks = {
        ("LSE_SWEEP",   "long"):  lse_long,
        ("LSE_SWEEP",   "short"): lse_short,
        ("TOKYO_BREAK", "long"):  tokyo_long,
        ("TOKYO_BREAK", "short"): tokyo_short,
        ("DRIFT",       "long"):  drift_long,
        ("DRIFT",       "short"): drift_short,
    }

    pieces = []
    for (setup, direction), mask in masks.items():
        cands = m5_ctx[mask].copy()
        if cands.empty:
            continue
        # Keep only the first signal per calendar day
        first = cands[
            ~pd.Series(day[mask], index=cands.index).duplicated(keep="first")
        ]
        first = first.assign(setup=setup, direction=direction)
        pieces.append(first)

    if not pieces:
        return pd.DataFrame()

    return pd.concat(pieces).sort_index()


# P8 reclaim-filter constants
RECLAIM_BARS = 4      # bars after signal to watch for reclaim (4 x 5min = 20 min)
RECLAIM_PTS  = 3.0    # points back through the swept level = invalidated

# P9 VWAP-exit constants
VWAP_EXIT_ENABLED = False   # default off; p5_p9_run.py passes True for comparison


# ── trade simulation ───────────────────────────────────────────────────────────

def simulate(signals: pd.DataFrame,
             m5_ctx: pd.DataFrame,
             reclaim_filter: bool = False,
             vwap_exit: bool = False) -> pd.DataFrame:
    """
    Bar-by-bar trade simulation.

    reclaim_filter (P8): skip LSE_SWEEP entries where price re-closes
        through the swept Asian Range level within RECLAIM_BARS bars.
    vwap_exit (P9): add a third exit condition — when close crosses the
        daily VWAP AND the HTF bias has flipped (structural confirmation).
        This fires only if stop and target are not already hit first.
    """
    opens  = m5_ctx["open"].to_numpy()
    highs  = m5_ctx["high"].to_numpy()
    lows   = m5_ctx["low"].to_numpy()
    closes = m5_ctx["close"].to_numpy()
    n      = len(opens)

    # P8 arrays
    asian_hi = m5_ctx["asian_range_high"].to_numpy()
    asian_lo = m5_ctx["asian_range_low"].to_numpy()

    # P9 arrays
    vwaps     = m5_ctx["vwap"].to_numpy()          if vwap_exit else None
    htf_bulls = m5_ctx["htf_bull_bias"].to_numpy() if vwap_exit else None
    htf_bears = m5_ctx["htf_bear_bias"].to_numpy() if vwap_exit else None
    pocs      = m5_ctx["pseudo_poc"].to_numpy()    if vwap_exit else None

    pos_lookup = {ts: i for i, ts in enumerate(m5_ctx.index)}

    records = []
    for ts, row in signals.iterrows():
        sig_pos = pos_lookup.get(ts)
        if sig_pos is None or sig_pos + 1 >= n:
            continue
        entry_pos = sig_pos + 1
        entry     = opens[entry_pos]

        # ── stop placement ────────────────────────────────────────────────────
        if row["direction"] == "long":
            if row["setup"] == "TOKYO_BREAK":
                ref  = row.get("prev_tok_high", np.nan)
                stop = (ref - STOP_BUFFER) if not np.isnan(ref) else (row["low"] - STOP_BUFFER)
            else:
                stop = row["low"] - STOP_BUFFER
            risk_pts = entry - stop
        else:
            if row["setup"] == "TOKYO_BREAK":
                ref  = row.get("prev_tok_low", np.nan)
                stop = (ref + STOP_BUFFER) if not np.isnan(ref) else (row["high"] + STOP_BUFFER)
            else:
                stop = row["high"] + STOP_BUFFER
            risk_pts = stop - entry

        if risk_pts < MIN_RISK_PTS:
            continue

        # ── P8: reclaim filter (LSE_SWEEP only) ───────────────────────────────
        if reclaim_filter and row["setup"] == "LSE_SWEEP":
            ref_hi = asian_hi[sig_pos]
            ref_lo = asian_lo[sig_pos]
            check_end = min(entry_pos + RECLAIM_BARS, n)
            invalidated = False
            for rb in range(entry_pos, check_end):
                if row["direction"] == "long":
                    if (not np.isnan(ref_lo) and
                            closes[rb] < ref_lo - RECLAIM_PTS):
                        invalidated = True; break
                else:
                    if (not np.isnan(ref_hi) and
                            closes[rb] > ref_hi + RECLAIM_PTS):
                        invalidated = True; break
            if invalidated:
                continue

        target = (entry + TARGET_R * risk_pts if row["direction"] == "long"
                  else entry - TARGET_R * risk_pts)

        # ── scan forward bars ─────────────────────────────────────────────────
        outcome    = "timeout"
        exit_price = closes[min(entry_pos + MAX_HOLD_BARS - 1, n - 1)]

        # Record the HTF bias at entry for P9 comparison
        htf_bull_at_entry = bool(htf_bulls[entry_pos]) if vwap_exit else True
        htf_bear_at_entry = bool(htf_bears[entry_pos]) if vwap_exit else True

        end_pos = min(entry_pos + MAX_HOLD_BARS, n)
        for j in range(entry_pos, end_pos):
            if row["direction"] == "long":
                if lows[j]  <= stop:   exit_price = stop;   outcome = "loss"; break
                if highs[j] >= target: exit_price = target; outcome = "win";  break
                # P9: structural VWAP exit
                if vwap_exit:
                    v = vwaps[j]; p = pocs[j]
                    vwap_cross  = (not np.isnan(v)) and closes[j] < v
                    htf_flipped = htf_bull_at_entry and (not bool(htf_bulls[j]))
                    poc_crossed = (not np.isnan(p)) and (not np.isnan(v)) and p < v
                    if vwap_cross and (htf_flipped or poc_crossed):
                        exit_price = closes[j]; outcome = "vwap_exit"; break
            else:
                if highs[j] >= stop:   exit_price = stop;   outcome = "loss"; break
                if lows[j]  <= target: exit_price = target; outcome = "win";  break
                if vwap_exit:
                    v = vwaps[j]; p = pocs[j]
                    vwap_cross  = (not np.isnan(v)) and closes[j] > v
                    htf_flipped = htf_bear_at_entry and (not bool(htf_bears[j]))
                    poc_crossed = (not np.isnan(p)) and (not np.isnan(v)) and p > v
                    if vwap_cross and (htf_flipped or poc_crossed):
                        exit_price = closes[j]; outcome = "vwap_exit"; break

        # ── R-multiple (costs deducted) ───────────────────────────────────────
        gross_R = ((exit_price - entry) / risk_pts if row["direction"] == "long"
                   else (entry - exit_price) / risk_pts)
        net_R   = gross_R - COST_PTS / risk_pts

        records.append({
            "date":      ts.normalize(),
            "setup":     row["setup"],
            "direction": row["direction"],
            "session":   row["session"],
            "regime":    row.get("regime", np.nan),
            "entry":     round(entry, 3),
            "stop":      round(stop,  3),
            "target":    round(target, 3),
            "exit":      round(exit_price, 3),
            "risk_pts":  round(risk_pts, 3),
            "outcome":   outcome,
            "gross_R":   round(gross_R, 4),
            "net_R":     round(net_R, 4),
        })

    return pd.DataFrame(records)


# ── expectancy tables ─────────────────────────────────────────────────────────

def _metrics(g: pd.DataFrame) -> pd.Series:
    n        = len(g)
    wins     = g.loc[g["net_R"] > 0, "net_R"]
    losses   = g.loc[g["net_R"] <= 0, "net_R"]
    hit_rate = (g["outcome"] == "win").mean()
    avg_R    = g["net_R"].mean()
    pf       = (wins.sum() / abs(losses.sum())
                if len(losses) > 0 and abs(losses.sum()) > 1e-9 else np.nan)
    return pd.Series({
        "n":             n,
        "hit_%":         round(100 * hit_rate, 1),
        "avg_R":         round(avg_R, 3),
        "profit_factor": round(pf, 2) if not np.isnan(pf) else np.nan,
        "p95_R":         round(g["net_R"].quantile(0.95), 2),
        "p05_R":         round(g["net_R"].quantile(0.05), 2),
    })


def expectancy_table(trades: pd.DataFrame) -> pd.DataFrame:
    """Aggregate expectancy sliced by setup x direction x regime."""
    from lab.regime import NAMES as REGIME_NAMES

    if trades.empty:
        return pd.DataFrame()

    df = trades.copy()
    df["regime_lbl"] = df["regime"].map(
        lambda x: REGIME_NAMES.get(int(x), "unknown") if not np.isnan(x) else "unknown"
    )

    tbl = (
        df.groupby(["setup", "direction", "regime_lbl"], observed=True)
          .apply(_metrics, include_groups=False)
          .reset_index()
          .sort_values(["setup", "direction", "regime_lbl"])
          .reset_index(drop=True)
    )
    return tbl


def session_table(trades: pd.DataFrame) -> pd.DataFrame:
    """Secondary table: setup x direction x session (all regimes combined)."""
    if trades.empty:
        return pd.DataFrame()

    tbl = (
        trades.groupby(["setup", "direction", "session"], observed=True)
              .apply(_metrics, include_groups=False)
              .reset_index()
              .sort_values(["setup", "direction", "session"])
              .reset_index(drop=True)
    )
    return tbl
