"""
p0_run.py -- Phase 1 / P0 deliverable

Runs:
  1. Regime classifier on D1 -> adds regime + atr_ratio to daily_panel.csv
  2. Session feature engine on M5
  3. Expectancy harness on M5 signals sliced by regime
  4. Prints the regime-sliced expectancy table

Run from the project root:
    python p0_run.py

Outputs
-------
  daily_panel.csv          -- updated with regime + atr_ratio columns
  outputs/trade_log.csv    -- every simulated trade
  outputs/expectancy_regime.csv  -- main table (setup x direction x regime)
  outputs/expectancy_session.csv -- secondary table (setup x direction x session)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from lab.loaders    import load_panel, load_m5
from lab.regime     import fit_regime, compute_atr_ratio, describe_model, NAMES, TREND
from lab.features   import attach_context
from lab.expectancy import detect_signals, simulate, expectancy_table, session_table

OUT_DIR = ROOT / "outputs"
OUT_DIR.mkdir(exist_ok=True)

SEP = "-" * 70


def main():
    # ------------------------------------------------------------------
    # 1. Regime classifier on D1
    # ------------------------------------------------------------------
    print(SEP)
    print("STEP 1 -- Regime classifier (D1)")
    print(SEP)

    panel = load_panel()
    print(f"Panel loaded: {len(panel):,} rows  "
          f"{panel.index[0].date()} -> {panel.index[-1].date()}")

    regime, model = fit_regime(panel)

    # Identify which state index maps to TREND
    trend_idx = int(np.argmax(model.means_[:, 1]))

    print("\nHMM parameters:")
    print(describe_model(model, trend_idx))

    # Distribution
    valid = regime.dropna().astype(int)
    n_range = (valid == 0).sum()
    n_trend = (valid == 1).sum()
    pct_trend = 100 * n_trend / len(valid)
    print(f"\nRegime distribution ({len(valid):,} labelled bars):")
    print(f"  RANGE : {n_range:,}  ({100-pct_trend:.1f}%)")
    print(f"  TREND : {n_trend:,}  ({pct_trend:.1f}%)")

    # Last 10 regime labels
    recent = regime.dropna().tail(10).astype(int).map(NAMES)
    print("\nMost recent 10 regime labels:")
    for dt, lbl in recent.items():
        print(f"  {dt.date()}  {lbl}")

    # ATR ratio
    atr_ratio = compute_atr_ratio(panel)
    print(f"\nATR ratio (14/60) -- last bar: {atr_ratio.dropna().iloc[-1]:.4f}  "
          f"(>1 = elevated vol, <1 = compressed)")

    # Update daily_panel.csv
    panel["regime"]    = regime
    panel["atr_ratio"] = atr_ratio
    panel.to_csv(ROOT / "daily_panel.csv")
    print("\ndaily_panel.csv updated with regime + atr_ratio columns.")

    # ------------------------------------------------------------------
    # 2. M5 session features
    # ------------------------------------------------------------------
    print("\n" + SEP)
    print("STEP 2 -- M5 session features")
    print(SEP)

    m5 = load_m5()
    print(f"M5 loaded: {len(m5):,} bars  "
          f"{m5.index[0]} -> {m5.index[-1]}")

    m5ctx = attach_context(m5)

    # Attach D-1 regime to each M5 bar (no lookahead: use previous day's label)
    regime_prev = regime.shift(1)       # regime[D] -> available from D+1 onward
    m5ctx["_date"] = m5ctx.index.normalize()
    m5ctx = m5ctx.join(regime_prev.rename("regime"), on="_date")
    m5ctx = m5ctx.drop(columns=["_date"])

    n_with_regime = m5ctx["regime"].notna().sum()
    print(f"M5 bars with D-1 regime label: {n_with_regime:,} / {len(m5ctx):,}")

    # ------------------------------------------------------------------
    # 3. Signal detection + trade simulation
    # ------------------------------------------------------------------
    print("\n" + SEP)
    print("STEP 3 -- Signal detection + trade simulation")
    print(SEP)

    signals = detect_signals(m5ctx)
    print(f"Signals found: {len(signals):,}")
    if not signals.empty:
        counts = signals.groupby(["setup", "direction"]).size().reset_index(name="n")
        for _, r in counts.iterrows():
            print(f"  {r['setup']:<14} {r['direction']:<6}  {r['n']:>4}")

    trades = simulate(signals, m5ctx)
    print(f"\nTrades simulated: {len(trades):,}  "
          f"(after min-risk filter of {3.0} pts)")

    if trades.empty:
        print("No trades to analyse -- exiting.")
        return

    # P12 -- cost verification audit
    # Per-trade cost in R = COST_PTS / risk_pts (varies by trade; can't use avg risk_pts)
    from lab.expectancy import COST_PTS
    actual_cost   = (trades["gross_R"] - trades["net_R"])
    expected_cost = COST_PTS / trades["risk_pts"]
    max_err       = (actual_cost - expected_cost).abs().max()
    print(f"\nP12 cost check: COST_PTS={COST_PTS}pt  "
          f"avg gross_R={trades['gross_R'].mean():+.4f}  "
          f"avg net_R={trades['net_R'].mean():+.4f}  "
          f"avg cost={actual_cost.mean():+.4f}R  max residual={max_err:.6f}  "
          f"{'OK' if max_err < 0.001 else 'MISMATCH -- check net_R formula'}")

    # Save trade log
    trades.to_csv(OUT_DIR / "trade_log.csv", index=False)
    print(f"Trade log -> outputs/trade_log.csv")

    # ------------------------------------------------------------------
    # 4. Expectancy tables
    # ------------------------------------------------------------------
    print("\n" + SEP)
    print("STEP 4 -- Expectancy tables")
    print(SEP)

    tbl_regime  = expectancy_table(trades)
    tbl_session = session_table(trades)

    tbl_regime.to_csv( OUT_DIR / "expectancy_regime.csv",  index=False)
    tbl_session.to_csv(OUT_DIR / "expectancy_session.csv", index=False)

    # ── MAIN TABLE: setup x direction x regime ──────────────────────────
    print("\n=== REGIME-SLICED EXPECTANCY (2R target, costs deducted) ===\n")
    print(f"{'setup':<14} {'dir':<6} {'regime':<7} "
          f"{'n':>5}  {'hit%':>6}  {'avg_R':>7}  {'PF':>6}  "
          f"{'p95R':>6}  {'p05R':>7}")
    print("-" * 68)
    for _, r in tbl_regime.iterrows():
        pf_str = f"{r['profit_factor']:.2f}" if not np.isnan(r["profit_factor"]) else "  n/a"
        print(
            f"{r['setup']:<14} {r['direction']:<6} {r['regime_lbl']:<7} "
            f"{int(r['n']):>5}  {r['hit_%']:>6.1f}  {r['avg_R']:>7.3f}  "
            f"{pf_str:>6}  {r['p95_R']:>6.2f}  {r['p05_R']:>7.2f}"
        )

    # ── SECONDARY TABLE: setup x direction x session ─────────────────────
    print("\n=== SESSION BREAKDOWN (all regimes combined) ===\n")
    print(f"{'setup':<14} {'dir':<6} {'session':<10} "
          f"{'n':>5}  {'hit%':>6}  {'avg_R':>7}  {'PF':>6}")
    print("-" * 56)
    for _, r in tbl_session.iterrows():
        pf_str = f"{r['profit_factor']:.2f}" if not np.isnan(r["profit_factor"]) else "  n/a"
        print(
            f"{r['setup']:<14} {r['direction']:<6} {r['session']:<10} "
            f"{int(r['n']):>5}  {r['hit_%']:>6.1f}  {r['avg_R']:>7.3f}  {pf_str:>6}"
        )

    # ── AGGREGATE per setup+direction ────────────────────────────────────
    print("\n=== AGGREGATE (all regimes + sessions) ===\n")
    from lab.expectancy import _metrics
    agg = (
        trades.groupby(["setup", "direction"], observed=True)
              .apply(_metrics, include_groups=False)
              .reset_index()
    )
    print(f"{'setup':<14} {'dir':<6} "
          f"{'n':>5}  {'hit%':>6}  {'avg_R':>7}  {'PF':>6}")
    print("-" * 48)
    for _, r in agg.iterrows():
        pf_str = f"{r['profit_factor']:.2f}" if not np.isnan(r["profit_factor"]) else "  n/a"
        print(
            f"{r['setup']:<14} {r['direction']:<6} "
            f"{int(r['n']):>5}  {r['hit_%']:>6.1f}  {r['avg_R']:>7.3f}  {pf_str:>6}"
        )

    print(f"\nOutputs written to: {OUT_DIR}")
    print("Phase 1 / P0 complete.\n")


if __name__ == "__main__":
    main()
