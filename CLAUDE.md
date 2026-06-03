# Project X — XAU/USD System Rebuild

## What this project is

Rebuilding a **discretionary** XAU/USD (gold) trading system for a FundingPips challenge, supported by a Python research/decision lab. **NOTHING is automated against the broker** — execution stays manual on TradingView. The lab's job is to measure where the edge actually is and enforce a risk envelope.

## Read these first (source of truth)

- BUILD\_ROADMAP.md — phased plan, requirements, status. **START HERE.**  
- XAU\_USD\_Trading\_System\_Bible.md — full framework (Master Context v2.0).  
- audit.md — the P0–P13 backlog this rebuild executes.  
- LSE\_v5.pine — the live Pine HUD (execution surface; do NOT auto-trade off it).  
- build\_panel.py — ingests broker CSVs \+ FRED → daily\_panel.csv.

## Architecture (the frozen / fluid line)

Three surfaces:

1. **Execution** \= Pine HUD on TradingView, manual.  
2. **Lab** \= Python offline: regime model \+ feature engine \+ expectancy harness.  
3. **Daily Brief** \= scored bias \+ risk envelope, read alongside the HUD.  
- **Frozen** (set once, leave alone): risk rails, journaling schema, data pipeline, event calendar.  
- **Fluid** (change freely): factors, thresholds, regime definitions, setup variants.

## Non-negotiable disciplines

1. **No lookahead** — confirmed bar values only. The Pine HTF bias and the pseudo-POC both repaint intrabar; naive use inflates backtests.  
2. **Costs always on** — every backtested trade pays modeled spread \+ slippage BEFORE its R is counted (P12).  
3. **Thresholds are HYPOTHESES** until validated on data. Only n=1 live trade so far.

## Data

- Broker CSVs live in ./historical data/.  
  - **Tab-separated** (NOT comma), despite the "Excel (CSV)" label.  
  - **Volume uses a SPACE thousands separator**: 1 553 means 1553. Load with pd.read\_csv(path, sep="\\t", thousands=" ").  
  - Timestamps are **GMT/UTC** — matches the session framework, no offset needed.  
- Files: XAUUSD\_D1, XAGUSD\_D1, EURUSD\_D1, USDJPY\_D1 (daily factors); XAUUSD\_M5 (\~3y, session structure); XAUUSD\_M1 (\~7mo, sweep micro-timing).  
- FRED (pulled automatically by build\_panel.py, no API key): DGS10 → us10y\_nominal, DFII10 → us10y\_real, DTWEXBGS → usd\_broad.

## Current status & immediate task

Phase 1 not started. **Immediate task:**

1. Confirm Python \+ deps installed: pandas numpy requests scikit-learn matplotlib.  
2. Run build\_panel.py pointed at ./historical data/ → produce daily\_panel.csv.  
3. Report back: row count, date span, column list, NaN counts, tail.

Then **P0**: fit a **2-state (Range/Trend)** regime classifier on D1 (recommended; keep the existing ATR-ratio as a SEPARATE volatility axis), and produce the first **regime-sliced expectancy table** over M5 history. That table is the goal.

## Build order (do not jump phases without the user's approval)

P0 (regime) → feature engine \+ expectancy harness → P2 (risk rails) → P1 (PCA composites) \+ P3 (symmetric thresholds) \+ P4 (expectancy tracking) → P5–P9 (signal cleanup) → P10–P13 (hygiene) → rewrite the AI operating prompt.

## How to work with the user

- Phase-gated: finish and show a phase's deliverable, get approval, then proceed.  
- Flag conflicting signals honestly — that's the system's edge, not a flaw.  
- Not financial advice; this is engineering/measurement support.

