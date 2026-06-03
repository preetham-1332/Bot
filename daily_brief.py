"""
daily_brief.py -- Morning risk envelope and session context.

Run each day before the session opens:
    python daily_brief.py
    python daily_brief.py --pnl -120.50        # with today's running P&L
    python daily_brief.py --pnl -120.50 --balance 9900  # custom balance (after prior losses)

Outputs
-------
  0. Event blackout banner (P11) -- shown prominently if a release is near
  1. Current regime (D1 HMM) + ATR ratio
  2. Macro composite score (PC1 of dollar/rates cluster)
  3. Session composite score (price-structure signals pre-London)
  4. Combined signal: macro + session + regime interpretation
  5. Contextual filters: decouple flag, COT crowding, shock state
  6. Risk envelope: lot sizes at common stop distances (broker IV, not GVZ)
  7. Circuit breaker status (daily + total DD)
  8. Kelly sizer status (informational)
  9. Session notes: which setups have edge in current regime
 10. Data freshness check (P10) -- staleness flags for all inputs
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from lab.risk import (
    DEFAULT, RiskConfig, position_size, lot_table,
    daily_loss_status, total_dd_status, exposure_check,
    kelly_size_info,
)
from lab.regime    import NAMES as REGIME_NAMES
from lab.scoring   import classify, format_label, label_to_size_pct
from lab.events    import event_calendar_report, is_blackout
from lab.staleness import staleness_report

SEP  = "-" * 60
SEP2 = "=" * 60


def print_event_banner() -> None:
    """P11 -- Prominent blackout banner shown before all other output."""
    from datetime import timezone as tz
    blacked, active = is_blackout()
    if blacked:
        print("!" * 60)
        print("  EVENT BLACKOUT ACTIVE -- DO NOT OPEN NEW POSITIONS")
        for ev in active:
            print(f"  {ev.name}  [{ev.category}]")
            if ev.note:
                print(f"  {ev.note}")
        print("!" * 60)
        print()


def load_latest_regime() -> dict:
    """Read the last row of daily_panel.csv for current regime + macro composite."""
    panel_path = ROOT / "daily_panel.csv"
    if not panel_path.exists():
        return {}
    panel = pd.read_csv(panel_path, index_col=0, parse_dates=True)
    if "regime" not in panel.columns:
        return {}
    last = panel.dropna(subset=["regime"]).iloc[-1]
    ctx = {
        "date":       last.name.date(),
        "regime":     REGIME_NAMES.get(int(last["regime"]), "unknown"),
        "atr_ratio":  round(last["atr_ratio"], 4) if "atr_ratio" in last.index else None,
        "xau_close":  round(last["xau_close"], 2) if "xau_close" in last.index else None,
    }
    if "macro_composite" in last.index:
        ctx["macro_composite"] = round(float(last["macro_composite"]), 4)
    if "macro_score" in last.index and not np.isnan(last["macro_score"]):
        ctx["macro_score"] = int(last["macro_score"])
    return ctx


def load_contextual_signals() -> dict:
    """Read P5/P6/P7 columns from daily_panel.csv."""
    panel_path = ROOT / "daily_panel.csv"
    if not panel_path.exists():
        return {}
    panel = pd.read_csv(panel_path, index_col=0, parse_dates=True)
    last = panel.iloc[-1]
    result = {}
    for col in ["corr_20d_macro", "decouple", "shock_fresh", "shock_priced",
                "cot_score", "cot_pct_rank"]:
        if col in last.index and not pd.isna(last[col]):
            result[col] = last[col]
    return result


def load_session_composite() -> dict:
    """Read the most recent pre-London session composite from outputs/session_daily.csv."""
    path = ROOT / "outputs" / "session_daily.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df = df.dropna(subset=["session_composite"])
    if df.empty:
        return {}
    last = df.iloc[-1]
    return {
        "date":       last.name.date() if hasattr(last.name, "date") else str(last.name)[:10],
        "sess_raw":   round(float(last["session_composite"]), 3),
        "sess_score": int(last["session_score"]) if not np.isnan(last["session_score"]) else None,
    }


def load_expectancy_summary() -> dict:
    """Load key cells from the regime-sliced expectancy table."""
    path = ROOT / "outputs" / "expectancy_regime.csv"
    if not path.exists():
        return {}
    tbl = pd.read_csv(path)
    summary = {}
    for _, row in tbl.iterrows():
        key = (row["setup"], row["direction"], row["regime_lbl"])
        summary[key] = {
            "n":     int(row["n"]),
            "hit%":  float(row["hit_%"]),
            "avg_R": float(row["avg_R"]),
            "pf":    float(row["profit_factor"]) if not pd.isna(row["profit_factor"]) else float("nan"),
        }
    return summary


_SCORE_LABEL = {-2: "STRONG BEAR", -1: "MILD BEAR", 0: "NEUTRAL",
                 1: "MILD BULL",   2: "STRONG BULL"}


def print_composite_block(ctx: dict, sess: dict) -> None:
    """Macro composite + session composite + combined interpretation."""
    print()
    print("[ 2 ] COMPOSITE SIGNALS  (P1 -- orthogonalised)")
    print(SEP)

    macro_score = ctx.get("macro_score")
    macro_raw   = ctx.get("macro_composite")
    sess_score  = sess.get("sess_score")
    sess_raw    = sess.get("sess_raw")

    # Macro
    if macro_score is not None:
        label = _SCORE_LABEL.get(macro_score, "?")
        print(f"  Macro composite : {macro_raw:+.4f}  ->  score {macro_score:+d}  ({label})")
        print(f"  Components      : PC1 of usd_broad + us10y_real + us10y_nom + EUR + JPY")
        print(f"  Interpretation  : +ve = dollar/rates tailwind for gold; -ve = headwind")
    else:
        print("  Macro composite : run p1_run.py first")

    print()

    # Session
    if sess_score is not None:
        label = _SCORE_LABEL.get(sess_score, "?")
        print(f"  Session composite: {sess_raw:+.3f}  ->  score {sess_score:+d}  ({label})")
        print(f"  Components       : HTF bias + VWAP dist + POC/VWAP + IB state  (pre-London)")
        sess_date = sess.get("date", "?")
        print(f"  Snapshot date    : {sess_date}")
    else:
        print("  Session composite: run p1_run.py first")

    # Combined (P3 symmetric thresholds)
    if macro_score is not None and sess_score is not None:
        regime = ctx.get("regime", "unknown")
        sig    = classify(macro_score, sess_score, regime)
        size_pct = label_to_size_pct(sig, base_pct=0.5)
        print()
        print(f"  Combined score   : {sig.combined:+d}  "
              f"(macro {macro_score:+d} + session {sess_score:+d})")
        boost_tag = "  [TREND boost]" if sig.regime_boost else ""
        print(f"  Signal label     : {sig.label}{boost_tag}")
        if sig.tradeable:
            print(f"  Size guidance    : {size_pct:.2f}% risk/trade  "
                  f"(${DEFAULT.account_balance * size_pct / 100:.0f})")
        else:
            print(f"  Size guidance    : NO TRADE  (combined {sig.combined:+d} = neutral)")

        # Flag divergence
        if macro_score * sess_score < 0:
            print(f"  [!] DIVERGENCE -- macro ({macro_score:+d}) vs session ({sess_score:+d})."
                  f" Discretionary override required.")


def print_regime_block(ctx: dict, exp: dict) -> None:
    print(SEP2)
    print("  DAILY BRIEF -- Project X XAU/USD")
    now_utc = datetime.now(timezone.utc)
    print(f"  Generated: {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print(SEP2)
    print()
    print("[ 1 ] MARKET REGIME")
    print(SEP)
    if not ctx:
        print("  daily_panel.csv not found -- run p0_run.py first")
        return
    print(f"  Last D1 close : {ctx.get('date')}")
    regime = ctx.get("regime", "unknown")
    atr_r  = ctx.get("atr_ratio")
    if atr_r is not None:
        vol_label = ("VOLATILE" if atr_r > 1.6
                     else "DRIFT" if atr_r < 0.7
                     else "NEUTRAL")
        print(f"  HMM Regime    : {regime}")
        print(f"  ATR ratio     : {atr_r:.4f}  ({vol_label})")
    if ctx.get("xau_close"):
        print(f"  XAU/USD close : {ctx['xau_close']}")

    print()
    print("  Setup edge in current regime:")
    for setup in ("TOKYO_BREAK", "LSE_SWEEP", "DRIFT"):
        for direction in ("long", "short"):
            cell = exp.get((setup, direction, regime))
            if cell and cell["n"] >= 20:
                flag = "*" if cell["avg_R"] > 0 else " "
                print(f"  {flag} {setup:<14} {direction:<6}  "
                      f"n={cell['n']:>3}  hit={cell['hit%']:.0f}%  avg_R={cell['avg_R']:+.3f}")
            elif cell:
                print(f"    {setup:<14} {direction:<6}  "
                      f"n={cell['n']:>3}  (small sample)")
    if not exp:
        print("  Run p0_run.py to generate expectancy table.")


def print_contextual_block(signals: dict) -> None:
    print()
    print("[ 3 ] CONTEXTUAL FILTERS  (P5 decouple | P6 COT | P7 shock)")
    print(SEP)

    if not signals:
        print("  Run p5_p9_run.py to populate contextual filters.")
        return

    # P5 decouple
    decouple = signals.get("decouple")
    corr     = signals.get("corr_20d_macro")
    if decouple is not None:
        decouple = int(decouple)
        label = {1:  "BULL DECOUPLE (+1 bonus) -- XAU rising vs macro headwind",
                 -1: "BEAR DECOUPLE (-1 penalty) -- XAU falling vs macro tailwind",
                  0: "NORMAL TRACKING"}.get(decouple, "?")
        corr_str = f"  (corr_20d={corr:+.3f})" if corr is not None else ""
        print(f"  P5 Decouple  : {label}{corr_str}")
    else:
        print("  P5 Decouple  : n/a  (run p5_p9_run.py)")

    # P6 COT
    cot_score = signals.get("cot_score")
    cot_rank  = signals.get("cot_pct_rank")
    if cot_score is not None:
        cot_label = {
             1: "CROWDED SHORT -> squeeze risk (bullish bias)",
            -1: "CROWDED LONG  -> fade risk (bearish bias)",
             0: "NEUTRAL",
        }.get(int(cot_score), "?")
        rank_str = f"  ({cot_rank:.0f}th percentile)" if cot_rank is not None else ""
        print(f"  P6 COT score : {cot_label}{rank_str}")
    else:
        print("  P6 COT score : n/a  (download cot_gold.csv from CFTC manually)")

    # P7 shock
    fresh  = signals.get("shock_fresh")
    priced = signals.get("shock_priced")
    fresh_i  = int(fresh)  if fresh  is not None else 0
    priced_i = int(priced) if priced is not None else 0
    if fresh is not None:
        if fresh_i != 0:
            dirn = "BULLISH" if fresh_i > 0 else "BEARISH"
            print(f"  P7 Shock     : FRESH {dirn} SHOCK  (+1 bonus if same direction)")
        elif priced_i != 0:
            dirn = "bullish" if priced_i > 0 else "bearish"
            print(f"  P7 Shock     : PRICED IN ({dirn}) -- exhaustion caution")
        else:
            print("  P7 Shock     : NO ACTIVE SHOCK")
    else:
        print("  P7 Shock     : n/a  (run p5_p9_run.py)")

    # Net combined adjustment
    adj = int(decouple or 0) + fresh_i
    if adj != 0:
        print(f"  Net P5+P7    : {adj:+d} adjustment to combined score")


def print_risk_block(config: RiskConfig,
                     daily_pnl: float,
                     balance: float) -> None:
    print()
    print("[ 5 ] RISK ENVELOPE")
    print(SEP)
    print(f"  Account     : ${config.account_balance:,.0f}  (FundingPips challenge)")
    print(f"  Risk/trade  : {config.risk_pct}%  =  ${config.account_balance * config.risk_pct / 100:.0f}")
    print(f"  Daily limit : {config.daily_loss_limit_pct}% hard  /  "
          f"{config.daily_soft_stop_pct}% soft  "
          f"(${config.account_balance * config.daily_soft_stop_pct / 100:.0f} / "
          f"${config.account_balance * config.daily_loss_limit_pct / 100:.0f})")
    print(f"  Total DD    : {config.total_dd_limit_pct}% max  "
          f"(${config.account_balance * config.total_dd_limit_pct / 100:.0f})")
    print()

    print("  LOT SIZE TABLE  (1 lot = 100oz; $1 move = $100/lot)")
    print(f"  {'Stop pts':>8}  {'Lots':>6}  {'Lots(broker IV>30%)':>20}  {'$ risk':>7}")
    print(f"  {'-'*8}  {'-'*6}  {'-'*20}  {'-'*7}")
    for row in lot_table(config):
        print(f"  {row['stop_pts']:>8}  {row['lots']:>6.2f}  "
              f"{row['lots_iv']:>20.2f}  ${row['usd_risk']:>6.0f}")


def print_circuit_breaker(daily_pnl: float,
                          balance: float,
                          config: RiskConfig) -> None:
    print()
    print("[ 6 ] CIRCUIT BREAKER")
    print(SEP)
    ds = daily_loss_status(daily_pnl, config)
    print(f"  Today P&L     : ${daily_pnl:+.2f}")
    print(f"  Daily status  : {ds['status']}")
    print(f"  Used / limit  : ${abs(ds['daily_loss_usd']):.2f} / "
          f"${ds['soft_limit_usd']:.2f} soft  ({ds['pct_used']:.1f}% of hard limit)")
    print(f"  Remaining     : ${ds['remaining_usd']:.2f} before soft stop")

    # Total DD check
    peak    = config.account_balance
    td      = total_dd_status(peak, balance, config)
    print()
    print(f"  Account bal   : ${balance:,.2f}  (peak = ${peak:,.0f})")
    dd_status = "OK" if td["can_trade"] else "STOP TRADING"
    print(f"  Total DD      : {td['dd_pct']:.2f}%  (${abs(td['dd_usd']):.2f})  "
          f"-- {dd_status}")
    print(f"  DD remaining  : ${td['remaining_usd']:.2f} before hard limit")


def print_kelly_block(exp: dict, regime: str) -> None:
    print()
    print("[ 7 ] KELLY SIZER  (informational -- parked)")
    print(SEP)
    print("  Status: PARKED until n >= 100 per cell (current best: TOKYO_BREAK TREND ~70)")
    print()
    for setup, direction in [("TOKYO_BREAK", "long"), ("TOKYO_BREAK", "short")]:
        cell = exp.get((setup, direction, regime))
        if not cell:
            continue
        # Estimate avg_win_R and avg_loss_R from net_R distribution
        # At 2R target with binary win/loss: avg_win ~ 2R - cost, avg_loss ~ -1R - cost
        # Use the actual avg_R and hit% to back-calculate
        hit = cell["hit%"] / 100.0
        avg_r = cell["avg_R"]
        if hit > 0:
            avg_win_R  =  1.9   # approx: 2R target net of costs
            avg_loss_R = -1.13  # approx: -1R stop net of costs
            ki = kelly_size_info(hit, avg_win_R, avg_loss_R)
            print(f"  {setup} {direction} ({regime}): "
                  f"hit={cell['hit%']:.1f}%  avg_R={avg_r:+.3f}  "
                  f"-> {ki['status']}")


def print_session_notes(regime: str) -> None:
    print()
    print("[ 8 ] SESSION NOTES")
    print(SEP)
    now_utc = datetime.now(timezone.utc).hour
    sessions = [
        (0,  9,  "TOKYO     00:00-09:00"),
        (7,  16, "LONDON    07:00-16:00"),
        (13, 22, "NEW YORK  13:00-22:00"),
    ]
    for start, end, label in sessions:
        if start <= now_utc < end:
            tag = " <-- ACTIVE"
        elif now_utc < start:
            tag = f" (opens in {start - now_utc}h)"
        else:
            tag = " (closed)"
        print(f"  {label}{tag}")

    print()
    print("  Hard rules checklist:")
    print("  [ ] IB still building? -> NO ENTRY (wait for session IB to lock)")
    print("  [ ] Broker margin IV > 30%? -> USE half lots (IV column above; broker O/N IV, not CBOE GVZ)")
    print("  [ ] 3+ confluent sigs? -> Required before entry")
    print("  [ ] Correlated open?   -> XAU + XAG + SHORT_USD = one bet")
    if regime == "TREND":
        print()
        print("  REGIME = TREND -> TOKYO_BREAK has positive edge (+0.15R avg)")
        print("  Prioritise breakout continuation; avoid counter-trend fades")
    elif regime == "RANGE":
        print()
        print("  REGIME = RANGE -> TOKYO_BREAK near breakeven; LSE_SWEEP inconclusive")
        print("  Reduce size or wait for regime to shift")


def main():
    parser = argparse.ArgumentParser(
        description="Project X daily risk brief")
    parser.add_argument("--pnl",     type=float, default=0.0,
                        help="Today's running P&L in USD (negative = loss)")
    parser.add_argument("--balance", type=float, default=DEFAULT.account_balance,
                        help="Current account balance in USD")
    parser.add_argument("--iv",      type=float, default=0.0,
                        help="Broker overnight margin IV %% (NOT CBOE GVZ; triggers half-size if > 30)")
    args = parser.parse_args()

    config   = DEFAULT
    ctx      = load_latest_regime()
    sess     = load_session_composite()
    exp      = load_expectancy_summary()
    ctx_sigs = load_contextual_signals()
    regime   = ctx.get("regime", "unknown")

    # P11 -- event blackout banner (shown before everything else if active)
    print_event_banner()

    print_regime_block(ctx, exp)
    print_composite_block(ctx, sess)
    print_contextual_block(ctx_sigs)

    # P11 -- full event calendar block
    print()
    print("[ 4 ] EVENT CALENDAR  (P11 -- blackout windows)")
    print(SEP)
    print()
    print(event_calendar_report())

    # Renumber downstream blocks
    print_risk_block(config, args.pnl, args.balance)
    print_circuit_breaker(args.pnl, args.balance, config)
    print_kelly_block(exp, regime)
    print_session_notes(regime)

    # P10 -- data freshness (bottom of brief, informational)
    panel_path = ROOT / "daily_panel.csv"
    if panel_path.exists():
        panel = pd.read_csv(panel_path, index_col=0, parse_dates=True)
        print()
        print("[ 10 ] DATA FRESHNESS  (P10)")
        print(SEP)
        print()
        print(staleness_report(panel, panel_path))
    else:
        print()
        print("[ 10 ] DATA FRESHNESS  -- daily_panel.csv not found")

    print()
    print(SEP2)
    print("  END OF BRIEF")
    print(SEP2)


if __name__ == "__main__":
    main()
