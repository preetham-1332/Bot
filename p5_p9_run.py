"""
p5_p9_run.py -- Phase 4 signal-cleanup deliverable (P5-P9)

P5  Rolling correlation monitor + decouple flag
P6  COT net-spec positioning + FRED staleness check
P7  Fresh-shock detector
P8  LSE_SWEEP reclaim filter (backtested impact)
P9  Structural VWAP exit (backtested impact)

Run:
    python p5_p9_run.py

Outputs
-------
  daily_panel.csv              -- updated: corr_20d_macro, decouple,
                                           shock_fresh, shock_priced,
                                           cot_score (if download OK)
  outputs/cot_gold.csv         -- COT history (if download OK)
  outputs/p8_p9_comparison.csv -- old vs new expectancy by setup/direction
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from lab.loaders      import load_panel, load_m5
from lab.features     import attach_context
from lab.expectancy   import detect_signals, simulate, expectancy_table, _metrics
from lab.correlation  import (compute_rolling_corr, compute_decouple_flag,
                               decouple_summary)
from lab.cot          import (download_cot, align_cot_to_panel,
                               fred_staleness_report)
from lab.shock        import compute_shock, combine_shock, shock_summary

OUT_DIR = ROOT / "outputs"
OUT_DIR.mkdir(exist_ok=True)

SEP  = "-" * 70
SEP2 = "=" * 70


# ── helpers ───────────────────────────────────────────────────────────────────

def _compare_tables(old: pd.DataFrame, new: pd.DataFrame,
                    label: str) -> pd.DataFrame:
    """
    Merge old and new expectancy tables; compute delta columns.
    Returns a comparison DataFrame.
    """
    if old.empty or new.empty:
        return pd.DataFrame()
    key = ["setup", "direction"]
    o = old.groupby(key, observed=True).apply(_metrics, include_groups=False).reset_index()
    n_ = new.groupby(key, observed=True).apply(_metrics, include_groups=False).reset_index()
    merged = o.merge(n_, on=key, suffixes=("_base", f"_{label}"))
    merged[f"delta_hit%"]  = merged[f"hit_%_{label}"]  - merged["hit_%_base"]
    merged[f"delta_avgR"]  = merged[f"avg_R_{label}"]  - merged["avg_R_base"]
    merged[f"delta_n"]     = merged[f"n_{label}"]      - merged["n_base"]
    return merged


def _print_comparison(comp: pd.DataFrame, label: str) -> None:
    if comp.empty:
        print("  No comparison data.")
        return
    print(f"  {'setup':<14} {'dir':<6} "
          f"{'n_base':>7} {'n_new':>6} "
          f"{'hit_base':>9} {'hit_new':>8} {'dhit':>6}  "
          f"{'aR_base':>8} {'aR_new':>7} {'daR':>7}")
    print(f"  {'-'*14} {'-'*6} "
          f"{'-'*7} {'-'*6} "
          f"{'-'*9} {'-'*8} {'-'*6}  "
          f"{'-'*8} {'-'*7} {'-'*7}")
    for _, r in comp.iterrows():
        print(f"  {r['setup']:<14} {r['direction']:<6} "
              f"{int(r['n_base']):>7} {int(r[f'n_{label}']):>6} "
              f"{r['hit_%_base']:>9.1f} {r[f'hit_%_{label}']:>8.1f} "
              f"{r['delta_hit%']:>+6.1f}  "
              f"{r['avg_R_base']:>8.3f} {r[f'avg_R_{label}']:>7.3f} "
              f"{r['delta_avgR']:>+7.3f}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    panel = load_panel()

    # ------------------------------------------------------------------
    # P5 -- Rolling correlation monitor
    # ------------------------------------------------------------------
    print(SEP2)
    print("P5 -- Rolling correlation monitor")
    print(SEP2)

    roll_corr = compute_rolling_corr(panel)
    decouple  = compute_decouple_flag(panel)

    print("\nLatest 20-day rolling correlations (XAU vs signed macro factors):")
    last_corr = roll_corr.dropna().iloc[-1]
    factors   = ["usd", "real10y", "nom10y", "eur", "jpy", "xag"]
    for f in factors:
        key = f"corr_20d_{f}"
        if key in last_corr.index:
            print(f"  {f:<10} {last_corr[key]:+.3f}")

    print()
    print(decouple_summary(decouple))

    # Add to panel
    panel["corr_20d_macro"] = decouple["corr_20d_macro"]
    panel["decouple"]       = decouple["decouple"]

    # ------------------------------------------------------------------
    # P6 -- COT + FRED freshness
    # ------------------------------------------------------------------
    print()
    print(SEP2)
    print("P6 -- COT reconciliation + FRED staleness")
    print(SEP2)

    print()
    print(fred_staleness_report(panel))

    print("\nDownloading COT data from CFTC...")
    cot_path = OUT_DIR / "cot_gold.csv"
    cot      = download_cot(cache_path=cot_path)

    if not cot.empty:
        aligned_cot = align_cot_to_panel(cot, panel)
        panel["cot_net_spec_pct"] = aligned_cot["net_spec_pct"]
        panel["cot_pct_rank"]     = aligned_cot["cot_pct_rank"]
        panel["cot_score"]        = aligned_cot["cot_score"]

        last_cot = cot.dropna(subset=["net_spec_pct"]).iloc[-1]
        print(f"\n  Latest COT ({last_cot['date'].date()}):")
        print(f"    Net spec pct  : {last_cot['net_spec_pct']:+.1f}%  of OI")
        print(f"    Pct rank      : {last_cot['cot_pct_rank']:.0f}th percentile")
        score_label = {1: "CROWDED SHORT (squeeze risk)", -1: "CROWDED LONG (fade risk)",
                       0: "NEUTRAL"}.get(int(last_cot["cot_score"]), "?")
        print(f"    COT signal    : {score_label}")
        print(f"  COT history ({len(cot)} weeks) -> outputs/cot_gold.csv")
    else:
        print("  COT download failed -- panel not updated with COT columns.")
        print("  Manual download instructions printed above.")

    # ------------------------------------------------------------------
    # P7 -- Fresh-shock detector
    # ------------------------------------------------------------------
    print()
    print(SEP2)
    print("P7 -- Geopolitical fresh-shock detector")
    print(SEP2)

    shock_df     = compute_shock(panel)
    shock_signal = combine_shock(shock_df, panel)

    print()
    print(shock_summary(shock_df, panel))

    panel["shock_bar"]    = shock_df["shock_bar"]
    panel["shock_fresh"]  = shock_df["shock_fresh"]
    panel["shock_priced"] = shock_df["shock_priced"]

    # ------------------------------------------------------------------
    # Save updated panel
    # ------------------------------------------------------------------
    panel.to_csv(ROOT / "daily_panel.csv")
    print(f"\ndaily_panel.csv updated with P5/P6/P7 columns.")

    # ------------------------------------------------------------------
    # P8 -- LSE_SWEEP reclaim filter
    # ------------------------------------------------------------------
    print()
    print(SEP2)
    print("P8 -- LSE_SWEEP reclaim filter (backtested impact)")
    print(SEP2)

    print("\nLoading M5 data and running signals...")
    m5    = load_m5()
    m5ctx = attach_context(m5)

    regime_prev = panel["regime"].shift(1)
    m5ctx["_date"] = m5ctx.index.normalize()
    m5ctx = m5ctx.join(regime_prev.rename("regime"), on="_date").drop(columns=["_date"])

    signals = detect_signals(m5ctx)
    print(f"Signals: {len(signals)}")

    trades_base    = simulate(signals, m5ctx,
                               reclaim_filter=False, vwap_exit=False)
    trades_p8      = simulate(signals, m5ctx,
                               reclaim_filter=True,  vwap_exit=False)

    print(f"\nBase trades : {len(trades_base)}")
    print(f"P8 trades   : {len(trades_p8)}  "
          f"({len(trades_base)-len(trades_p8)} removed by reclaim filter)")

    comp_p8 = _compare_tables(trades_base, trades_p8, "p8")

    from lab.expectancy import RECLAIM_BARS, RECLAIM_PTS
    print(f"\nReclaim filter: within {RECLAIM_BARS} bars OR "
          f"{RECLAIM_PTS:.1f}pts back through swept level")
    print(f"\nImpact on LSE_SWEEP only:")
    comp_lse = comp_p8[comp_p8["setup"] == "LSE_SWEEP"] if not comp_p8.empty else comp_p8
    _print_comparison(comp_lse, "p8")
    if not comp_p8.empty:
        print(f"\nAll setups (TOKYO_BREAK/DRIFT unaffected):")
        _print_comparison(comp_p8, "p8")

    # ------------------------------------------------------------------
    # P9 -- Structural VWAP exit
    # ------------------------------------------------------------------
    print()
    print(SEP2)
    print("P9 -- Structural VWAP exit (backtested impact)")
    print(SEP2)

    trades_p9 = simulate(signals, m5ctx,
                          reclaim_filter=False, vwap_exit=True)
    trades_p8p9 = simulate(signals, m5ctx,
                            reclaim_filter=True,  vwap_exit=True)

    vwap_exits = (trades_p9["outcome"] == "vwap_exit").sum()
    print(f"\nP9 trades (VWAP exit enabled): {len(trades_p9)}")
    print(f"  VWAP exits triggered: {vwap_exits} / {len(trades_p9)} "
          f"({100*vwap_exits/max(len(trades_p9),1):.1f}%)")

    # R distribution of VWAP exits
    ve = trades_p9[trades_p9["outcome"] == "vwap_exit"]["net_R"]
    if not ve.empty:
        print(f"  VWAP exit net_R : mean={ve.mean():+.3f}  "
              f"min={ve.min():+.3f}  max={ve.max():+.3f}")

    print(f"\nExpectancy comparison (base vs P9):")
    comp_p9 = _compare_tables(trades_base, trades_p9, "p9")
    _print_comparison(comp_p9, "p9")

    print(f"\nExpectancy comparison (base vs P8+P9 combined):")
    comp_both = _compare_tables(trades_base, trades_p8p9, "p8p9")
    _print_comparison(comp_both, "p8p9")

    # ------------------------------------------------------------------
    # Save comparison CSV + best-combined trade log
    # ------------------------------------------------------------------
    all_comps = []
    for comp, label in [(comp_p8, "P8_only"),
                        (comp_p9, "P9_only"),
                        (comp_both, "P8+P9")]:
        if not comp.empty:
            comp["variant"] = label
            all_comps.append(comp)
    if all_comps:
        pd.concat(all_comps).to_csv(OUT_DIR / "p8_p9_comparison.csv", index=False)
        print(f"\nComparison table -> outputs/p8_p9_comparison.csv")

    trades_p8p9.to_csv(OUT_DIR / "trade_log_p8p9.csv", index=False)
    print(f"Best-combined trade log -> outputs/trade_log_p8p9.csv")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    print(SEP)
    print("P5-P9 complete.")
    print(SEP)
    print(f"\nNew panel columns (daily_panel.csv):")
    print(f"  corr_20d_macro   -- rolling 20D XAU vs macro composite correlation")
    print(f"  decouple         -- +1 bull / -1 bear / 0 normal")
    print(f"  shock_bar        -- +1/-1 on shock days (|ret| > {2.5}x ATR)")
    print(f"  shock_fresh      -- +1/-1 within 10 days of shock")
    print(f"  shock_priced     -- +1/-1 between 10-25 days")
    if "cot_score" in panel.columns:
        print(f"  cot_score        -- +1 (crowded short) / -1 (crowded long) / 0")
    print(f"\nInstructions:")
    print(f"  P5: Check decouple flag before entry -- divergence adds +-1 to combined score")
    print(f"  P6: COT score flags crowding; add to session composite manually")
    print(f"  P7: shock_fresh adds +-1 to combined score (same direction = bonus)")
    print(f"  P8: Pass reclaim_filter=True to simulate() -- live default should be True")
    print(f"  P9: Pass vwap_exit=True   to simulate() -- exit on VWAP + structure flip")


if __name__ == "__main__":
    main()
