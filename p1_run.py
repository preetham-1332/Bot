"""
p1_run.py -- Phase 1 / P1 deliverable

Orthogonalised macro composite (PCA on dollar/rates cluster) and
session composite (price-structure signals at London open).

Run:
    python p1_run.py

Outputs
-------
  daily_panel.csv          -- updated with macro_composite + macro_score cols
  outputs/macro_loadings.csv  -- full PC loading matrix
  outputs/session_daily.csv   -- session composite snapshot per trading day
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from lab.loaders import load_panel, load_m5
from lab.pca import (
    fit_macro_pca,
    compute_macro_composite,
    macro_loadings_report,
    compute_session_composite,
    session_score_at_london_open,
    _quintile_score,
    _macro_feature_matrix,
)

OUT_DIR = ROOT / "outputs"
OUT_DIR.mkdir(exist_ok=True)

SEP  = "-" * 70
SEP2 = "=" * 70


def main():
    # ------------------------------------------------------------------
    # 1. Macro PCA on D1 panel
    # ------------------------------------------------------------------
    print(SEP2)
    print("STEP 1 -- Macro composite (D1 PCA on dollar/rates cluster)")
    print(SEP2)

    panel = load_panel()
    print(f"Panel: {len(panel):,} rows  "
          f"{panel.index[0].date()} -> {panel.index[-1].date()}")

    macro_ok = False
    mc = pd.Series(float("nan"), index=panel.index, name="macro_composite")
    try:
        pca, scaler, feats = fit_macro_pca(panel)
        macro_ok = True
    except ValueError as exc:
        print(f"\n  [WARN] Macro PCA skipped: {exc}")
        print("  macro_composite will be NaN this run.")
        print("  Session composite is unaffected -- continuing.\n")

    if macro_ok:
        # Variance explained
        exp_var = pca.explained_variance_ratio_
        print(f"\nVariance explained by each PC:")
        cumvar = 0.0
        for i, v in enumerate(exp_var):
            cumvar += v
            print(f"  PC{i+1}: {v*100:5.1f}%   cumulative: {cumvar*100:5.1f}%")

        print(f"\nPC1 captures {exp_var[0]*100:.1f}% of variance in the dollar/rates cluster")
        print(f"\n{macro_loadings_report(pca, exp_var)}")

        mc = compute_macro_composite(panel, pca, scaler)
        gold_ret20 = np.log(panel["xau_close"] / panel["xau_close"].shift(20))
        shared = mc.dropna().index.intersection(gold_ret20.dropna().index)
        corr = np.corrcoef(mc.reindex(shared), gold_ret20.reindex(shared))[0, 1]
        print(f"\nPC1 vs XAU 20D return correlation: {corr:+.4f}")

        feat_names = ["usd", "real10y", "nom10y", "eur", "jpy"]
        print("\nIndividual feature correlations with XAU 20D return:")
        for col, name in zip(feats.columns, feat_names):
            shared_f = feats[col].dropna().index.intersection(gold_ret20.dropna().index)
            c = np.corrcoef(feats[col].reindex(shared_f),
                            gold_ret20.reindex(shared_f))[0, 1]
            print(f"  {name:<10}  {c:+.4f}")

        load_df = pd.DataFrame(
            pca.components_,
            columns=feat_names,
            index=[f"PC{i+1}" for i in range(5)],
        )
        load_df.insert(0, "var_pct", exp_var * 100)
        load_df.to_csv(OUT_DIR / "macro_loadings.csv")
        print(f"\nLoadings -> outputs/macro_loadings.csv")

    # ------------------------------------------------------------------
    # 2. Score and update daily_panel.csv
    # ------------------------------------------------------------------
    print()
    print(SEP)
    print("STEP 2 -- Score macro composite and update daily_panel.csv")
    print(SEP)

    panel["macro_composite"] = mc
    panel["macro_score"]     = _quintile_score(mc) if macro_ok else float("nan")

    if macro_ok:
        from lab.regime import NAMES as RN
        recent = panel[["xau_close", "macro_composite", "macro_score",
                         "regime"]].dropna(subset=["macro_score"]).tail(10)
        print("\nMost recent 10 days:")
        print(f"  {'date':<12} {'xau_close':>10} {'macro_comp':>11} "
              f"{'macro_score':>12} {'regime':>7}")
        print(f"  {'-'*12} {'-'*10} {'-'*11} {'-'*12} {'-'*7}")
        for dt, row in recent.iterrows():
            reg = RN.get(int(row["regime"]), "?") if not np.isnan(row["regime"]) else "?"
            print(f"  {str(dt.date()):<12} {row['xau_close']:>10.2f} "
                  f"{row['macro_composite']:>+11.4f} "
                  f"{int(row['macro_score']):>+12}   {reg:>7}")

        sc = panel["macro_score"].dropna().astype(int)
        print("\nMacro score distribution:")
        for v in [-2, -1, 0, 1, 2]:
            n = (sc == v).sum()
            print(f"  {v:+d}  {n:>5}  ({100*n/len(sc):.1f}%)")

    panel.to_csv(ROOT / "daily_panel.csv")
    print("\ndaily_panel.csv updated with macro_composite + macro_score.")

    # ------------------------------------------------------------------
    # 3. Session composite (M5)
    # ------------------------------------------------------------------
    print()
    print(SEP)
    print("STEP 3 -- Session composite (M5 price-structure signals)")
    print(SEP)

    m5 = load_m5()
    print(f"M5: {len(m5):,} bars  {m5.index[0]} -> {m5.index[-1]}")

    from lab.features import attach_context
    m5ctx = attach_context(m5)

    sess_raw  = compute_session_composite(m5ctx)
    sess_daily = session_score_at_london_open(m5ctx)

    print(f"\nSession composite range: {sess_raw.min():.2f} to {sess_raw.max():.2f}")
    print(f"Pre-London snapshots: {len(sess_daily)} days")

    # Last 10 days
    sess_scored = _quintile_score(sess_daily, lookback=60)  # shorter window for M5
    recent_sess = pd.concat([
        sess_daily.rename("sess_composite"),
        sess_scored.rename("sess_score"),
    ], axis=1).dropna().tail(10)

    print("\nMost recent pre-London session snapshots:")
    print(f"  {'date':<12} {'sess_comp':>10} {'sess_score':>11}")
    print(f"  {'-'*12} {'-'*10} {'-'*11}")
    for dt, row in recent_sess.iterrows():
        print(f"  {str(dt):<12} {row['sess_composite']:>+10.3f} "
              f"{int(row['sess_score']) if not np.isnan(row['sess_score']) else '?':>+11}")

    sess_daily_df = pd.DataFrame({
        "session_composite": sess_daily,
        "session_score":     sess_scored,
    })
    sess_daily_df.to_csv(OUT_DIR / "session_daily.csv")
    print(f"\nSession daily snapshots -> outputs/session_daily.csv")

    # ------------------------------------------------------------------
    # 4. Combined signal summary
    # ------------------------------------------------------------------
    print()
    print(SEP)
    print("STEP 4 -- Combined macro x session signal summary")
    print(SEP)

    # Merge on date for the last 30 days
    macro_recent = panel[["macro_score", "regime"]].dropna(subset=["macro_score"]).tail(30)
    sess_recent  = sess_daily_df["session_score"].dropna()

    combined = macro_recent.join(sess_recent, how="inner")
    combined.index = combined.index.normalize()

    from lab.regime import NAMES as RN
    print("\nLast 10 combined signals (macro_score + session_score):")
    if not macro_ok:
        print("  [macro scores are NaN -- FRED unavailable; combined = session only]")
    print(f"  {'date':<12} {'macro':>7} {'session':>9} {'combined':>10} {'regime':>7}")
    print(f"  {'-'*12} {'-'*7} {'-'*9} {'-'*10} {'-'*7}")
    for dt, row in combined.tail(10).iterrows():
        reg = RN.get(int(row["regime"]), "?") if not np.isnan(row["regime"]) else "?"
        ms  = int(row["macro_score"]) if not np.isnan(row["macro_score"]) else 0
        ss  = int(row["session_score"]) if not np.isnan(row["session_score"]) else 0
        print(f"  {str(dt.date()):<12} {ms:>+7}  {ss:>+9}  {ms+ss:>+10}   {reg:>7}")

    print(f"\nOutputs written to: {OUT_DIR}")
    print("Phase 1 / P1 complete.\n")


if __name__ == "__main__":
    main()
