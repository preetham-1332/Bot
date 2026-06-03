"""
ny_brief.py -- Pre-NY open check.  Run at 12:55 UTC.

Answers one question: should I be watching for a NY_SWEEP entry at 13:00?

Usage:
    python ny_brief.py
    python ny_brief.py --pnl -50 --balance 9525
"""

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from lab.regime import NAMES as REGIME_NAMES
from lab.events import EVENTS, is_blackout, _window
from lab.risk   import DEFAULT, daily_loss_status, total_dd_status

SEP  = "-" * 60
SEP2 = "=" * 60

# NY_SWEEP backtest stats (p0_run.py, reclaim+costs, 2R target)
_NY_STATS = {
    "TREND": dict(n=24, hit=41.7, avg_R=+0.517, pf=2.26),
    "RANGE": dict(n=16, hit=18.8, avg_R=-0.464, pf=0.44),
}

M5_PATH = ROOT / "historical data" / "M5" / "XAUUSD_M5.csv"


# ── loaders ──────────────────────────────────────────────────────────────────

def load_regime() -> tuple[str, int | None, float | None]:
    panel_path = ROOT / "daily_panel.csv"
    if not panel_path.exists():
        return "unknown", None, None
    panel = pd.read_csv(panel_path, index_col=0, parse_dates=True)
    if "regime" not in panel.columns:
        return "unknown", None, None
    last = panel.dropna(subset=["regime"]).iloc[-1]
    regime = REGIME_NAMES.get(int(last["regime"]), "unknown")
    macro_score = (int(last["macro_score"])
                   if "macro_score" in last.index and not np.isnan(last["macro_score"])
                   else None)
    xau_close = round(float(last["xau_close"]), 2) if "xau_close" in last.index else None
    return regime, macro_score, xau_close


def load_london_range(today: date) -> dict:
    """Return today's London Range locked values (07:00–12:59 UTC bars)."""
    if not M5_PATH.exists():
        return {}
    m5 = pd.read_csv(
        M5_PATH,
        sep="\t", thousands=" ",
        names=["date", "open", "high", "low", "close", "vol_tick", "volume"],
        header=0, index_col=0, parse_dates=True,
    )
    m5.index.name = "date"
    london = m5[
        (m5.index.date == today) &
        (m5.index.hour >= 7) &
        (m5.index.hour < 13)
    ]
    if london.empty:
        return {}
    return {
        "high":  round(london["high"].max(), 3),
        "low":   round(london["low"].min(), 3),
        "width": round(london["high"].max() - london["low"].min(), 3),
        "bars":  len(london),
        "first": london.index[0].strftime("%H:%M"),
        "last":  london.index[-1].strftime("%H:%M"),
    }


def check_ny_open_blackout(today: date) -> list:
    """Return any events whose blackout window covers 13:00 UTC today."""
    ny_open = datetime(today.year, today.month, today.day, 13, 0,
                       tzinfo=timezone.utc)
    blocked = []
    for ev in EVENTS:
        if ev.date_utc != today:
            continue
        if ev.time_utc == "ALL_DAY":
            blocked.append(ev)
            continue
        w = _window(ev)
        if w and w[0] <= ny_open <= w[1]:
            blocked.append(ev)
    return blocked


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pre-NY open brief (12:55 UTC)")
    parser.add_argument("--pnl",     type=float, default=0.0,
                        help="Today's running P&L in USD")
    parser.add_argument("--balance", type=float, default=DEFAULT.account_balance,
                        help="Current account balance in USD")
    args = parser.parse_args()

    now_utc = datetime.now(timezone.utc)
    today   = now_utc.date()

    # ── header ───────────────────────────────────────────────────────────────
    print(SEP2)
    print("  NY OPEN BRIEF -- Project X XAU/USD")
    print(f"  Generated : {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  NY opens  : {today} 13:00 UTC  "
          f"({max(0, (13 - now_utc.hour) * 60 - now_utc.minute)} min away)")
    print(SEP2)

    # ── active blackout banner ────────────────────────────────────────────────
    blacked, active = is_blackout()
    if blacked:
        print()
        print("!" * 60)
        print("  BLACKOUT ACTIVE NOW -- DO NOT OPEN NEW POSITIONS")
        for ev in active:
            print(f"  {ev.name}  [{ev.category}]")
        print("!" * 60)

    # ── [ 1 ] event check at NY open ─────────────────────────────────────────
    print()
    print("[ 1 ] EVENT CHECK -- 13:00 UTC blackout")
    print(SEP)
    ny_blocked = check_ny_open_blackout(today)
    if ny_blocked:
        print("  BLOCKED -- event blackout covers NY open:")
        for ev in ny_blocked:
            w = _window(ev)
            window_str = (f"  {w[0].strftime('%H:%M')}-{w[1].strftime('%H:%M')} UTC"
                          if w else "  ALL DAY")
            print(f"    {ev.name}  [{ev.category}]{window_str}")
        event_clear = False
    else:
        print("  CLEAR -- no event blackout at 13:00 UTC")
        event_clear = True

    # ── [ 2 ] regime ─────────────────────────────────────────────────────────
    print()
    print("[ 2 ] REGIME")
    print(SEP)
    regime, macro_score, xau_close = load_regime()
    stats = _NY_STATS.get(regime, {})

    print(f"  HMM regime  : {regime}")
    if xau_close:
        print(f"  XAU D1 close: {xau_close}")

    print()
    if regime == "TREND":
        print("  NY_SWEEP edge  : POSITIVE in TREND")
        print(f"    n={stats['n']}  hit={stats['hit']:.0f}%  "
              f"avg_R={stats['avg_R']:+.3f}  PF={stats['pf']:.2f}")
        regime_go = True
    elif regime == "RANGE":
        print("  NY_SWEEP edge  : NEGATIVE in RANGE -- skip unless strong confluence")
        print(f"    n={stats['n']}  hit={stats['hit']:.0f}%  "
              f"avg_R={stats['avg_R']:+.3f}  PF={stats['pf']:.2f}")
        regime_go = False
    else:
        print("  Regime unknown -- run p0_run.py")
        regime_go = False

    # ── [ 3 ] London Range ───────────────────────────────────────────────────
    print()
    print("[ 3 ] LONDON RANGE  (locked at 13:00 UTC)")
    print(SEP)
    lr = load_london_range(today)
    if lr:
        print(f"  High  : {lr['high']:.3f}")
        print(f"  Low   : {lr['low']:.3f}")
        print(f"  Width : {lr['width']:.1f} pts  "
              f"({lr['bars']} bars  {lr['first']}-{lr['last']} UTC)")
        if lr["width"] < 8:
            print("  [!] Tight range (<8pts) -- sweep less reliable; require stronger wick")
        elif lr["width"] > 40:
            print("  [!] Wide range (>40pts) -- larger stop needed; check lot size")
        london_range_ok = True

        print()
        print("  Sweep trigger (Pine confirms automatically):")
        print(f"    LONG  : bar low < {lr['low']:.3f}  AND  close >= {lr['low']:.3f}  "
              f"AND wick > threshold")
        print(f"    SHORT : no edge -- short side negative in both regimes")
    else:
        # Check if M5 file exists but just doesn't have today's data
        if M5_PATH.exists():
            import pandas as _pd
            _tail = _pd.read_csv(M5_PATH, sep="\t", thousands=" ",
                                 names=["date","open","high","low","close","v1","v2"],
                                 header=0, index_col=0, parse_dates=True).index[-1]
            print(f"  M5 file last bar : {_tail}  (file not updated today)")
            print(f"  Export today's M5 from MT4/TradingView and re-run.")
        else:
            print(f"  M5 file not found: {M5_PATH}")
        london_range_ok = False

    # ── [ 4 ] macro context ──────────────────────────────────────────────────
    print()
    print("[ 4 ] MACRO CONTEXT")
    print(SEP)
    _SCORE_LABEL = {-2: "STRONG BEAR (headwind for longs)",
                    -1: "MILD BEAR",
                     0: "NEUTRAL",
                     1: "MILD BULL",
                     2: "STRONG BULL (tailwind for longs)"}
    if macro_score is not None:
        label = _SCORE_LABEL.get(macro_score, "?")
        print(f"  Macro score : {macro_score:+d}  ({label})")
        if macro_score <= -1:
            print("  Note: macro headwind -- use as tie-breaker, not a blocker")
            print("        if Pine gives clean sweep + reclaim, take it")
    else:
        print("  Macro score : n/a -- run p1_run.py")

    # ── [ 5 ] circuit breaker ────────────────────────────────────────────────
    print()
    print("[ 5 ] CIRCUIT BREAKER")
    print(SEP)
    config  = DEFAULT
    ds      = daily_loss_status(args.pnl, config)
    td      = total_dd_status(config.account_balance, args.balance, config)
    print(f"  Today P&L  : ${args.pnl:+.2f}")
    print(f"  Daily      : {ds['status']}  "
          f"(${abs(ds['daily_loss_usd']):.0f} used of "
          f"${ds['soft_limit_usd']:.0f} soft limit)")
    dd_ok = "OK" if td["can_trade"] else "STOP TRADING"
    print(f"  Total DD   : {td['dd_pct']:.2f}%  -- {dd_ok}")
    cb_green = "GREEN" in ds["status"] and td["can_trade"]

    # ── [ 6 ] verdict ────────────────────────────────────────────────────────
    print()
    print("[ 6 ] NY_SWEEP VERDICT")
    print(SEP)

    checks = [
        ("Regime = TREND",          regime_go),
        ("No blackout at 13:00",    event_clear),
        ("Circuit breaker green",   cb_green),
        ("London Range loaded",     london_range_ok),
    ]
    all_pass = all(ok for _, ok in checks)

    for label, ok in checks:
        tick = "OK " if ok else "NO "
        print(f"  [{tick}] {label}")

    print()
    if all_pass:
        print("  >>> WATCH  -- conditions met, wait for Pine sweep signal <<<")
        print()
        print("  Entry rules (Pine confirms, you execute):")
        print("   1. Bar OPENS at 13:00 (NYS signal fires on that bar)")
        print("   2. Low swept below London Low AND closed back above it")
        print("   3. Wick > minimum threshold")
        print("   4. bull_flow OR absorption dot visible")
        print("   5. Enter on NEXT bar open (confirmed bar only)")
    elif not regime_go and event_clear and cb_green:
        print("  >>> SKIP  -- RANGE regime, no NY_SWEEP edge today <<<")
        print("  Watch for LSE_SWEEP or TOKYO_BREAK continuation instead.")
    elif not event_clear:
        print("  >>> BLOCKED  -- event blackout covers NY open <<<")
        print("  Do not open new positions during the blackout window.")
    elif not cb_green:
        print("  >>> BLOCKED  -- circuit breaker <<<")
        print("  Daily or total drawdown limit reached.")
    else:
        print("  >>> SKIP  -- not all conditions met <<<")

    # ── upcoming events reminder ──────────────────────────────────────────────
    from lab.events import next_events
    upcoming = next_events(now_utc, n=2)
    if upcoming:
        print()
        print(SEP)
        print("  Next events:")
        for ev, cd in upcoming:
            w = _window(ev)
            window_str = (f"  blackout {w[0].strftime('%H:%M')}-{w[1].strftime('%H:%M')} UTC"
                          if w else "  full day")
            print(f"    {ev.date_utc}  {ev.time_utc} UTC  ({cd})  "
                  f"{ev.name}  [{ev.category}]{window_str}")

    print()
    print(SEP2)
    print("  END OF NY BRIEF")
    print(SEP2)


if __name__ == "__main__":
    main()
