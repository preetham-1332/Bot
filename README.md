# Project X — XAU/USD Discretionary Trading System

A Python research lab for a discretionary XAU/USD (gold) trading system built for a **FundingPips $10,000 challenge**. The lab measures edge and enforces risk; all execution stays manual on TradingView.

---

## Architecture

| Surface | Tool | Role |
|---------|------|------|
| **Execution** | TradingView (LSE v5 Pine HUD) | Live entry signals — manual only |
| **Lab** | Python (this repo) | Regime model, feature engine, expectancy harness |
| **Daily Brief** | `daily_brief.py` | Scored bias + risk envelope, read before each session |

---

## Quick Start

### 1. Install dependencies
```bash
pip install pandas numpy requests scikit-learn hmmlearn matplotlib
```

### 2. Build the data panel
```bash
python build_panel.py
```
Ingests broker D1/M5 CSVs from `historical data/` and pulls FRED series (DGS10, DFII10, DTWEXBGS) automatically. Produces `daily_panel.csv`.

### 3. Run the lab phases
```bash
python p0_run.py       # HMM regime model + expectancy table
python p1_run.py       # Macro PCA composite + session composite
python p3_p4_run.py    # Scoring thresholds + journal schema
python p5_p9_run.py    # Signal cleanup (decouple, COT, shock, P8/P9 filters)
```

### 4. Read the morning brief
```bash
python daily_brief.py
python daily_brief.py --pnl -120.50 --balance 9880 --iv 28
```

---

## Lab Phases (P0–P13)

| Phase | Module | What it does |
|-------|--------|-------------|
| P0 | `lab/regime.py` | 2-state GaussianHMM (RANGE / TREND) on D1 |
| P0 | `lab/features.py` | M5 feature engine: IB, VWAP, pseudo-POC, HTF bias |
| P0 | `lab/expectancy.py` | Signal detection + backtester (costs always on) |
| P1 | `lab/pca.py` | Macro PCA composite + session composite |
| P2 | `lab/risk.py` | Fixed-fractional sizing, circuit breakers, Kelly |
| P3 | `lab/scoring.py` | Symmetric ±3 thresholds, TREND regime boost |
| P4 | `lab/journal.py` | Trade record schema, validation, backtest bridge |
| P5 | `lab/correlation.py` | Rolling corr monitor + decouple flag |
| P6 | `lab/cot.py` | CFTC COT download + FRED staleness check |
| P7 | `lab/shock.py` | Fresh-shock detector (2.5× ATR threshold) |
| P8 | `lab/expectancy.py` | LSE_SWEEP reclaim filter (4-bar / 3-pt) |
| P9 | `lab/expectancy.py` | Structural VWAP exit (VWAP cross + HTF/POC flip) |
| P10 | `lab/staleness.py` | Per-column freshness flags for all panel inputs |
| P11 | `lab/events.py` | Economic event calendar + blackout windows |
| P12 | `p0_run.py` | Cost audit: verifies 0.50pt round-trip on every trade |
| P13 | `lab/risk.py` | Broker overnight IV ≠ CBOE GVZ (labelled correctly) |

---

## The Three Setups

| Setup | Window | Edge |
|-------|--------|------|
| **LSE_SWEEP** | London open hour (07:00–07:59 UTC) | Asian range sweep + reversal |
| **TOKYO_BREAK** | Tokyo session (01:00–08:59 UTC) | 2nd consecutive close beyond running range |
| **DRIFT** | Any session, ATR ratio < 0.7 | 7-condition micro-structure alignment |

All setups: 2R target, 0.50pt round-trip cost, 3pt minimum risk, 48-bar max hold.

---

## Daily Brief Blocks

```
[ 0 ] Event blackout banner     — prominent warning if a release is live now
[ 1 ] Market regime             — HMM state + ATR volatility axis
[ 2 ] Composite signals         — macro PCA score + session score + combined
[ 3 ] Contextual filters        — decouple (P5), COT (P6), shock (P7)
[ 4 ] Event calendar            — next 4 events + exact blackout windows
[ 5 ] Risk envelope             — lot table at common stop distances
[ 6 ] Circuit breaker           — daily P&L + total drawdown status
[ 7 ] Kelly sizer               — parked until n ≥ 100 per regime cell
[ 8 ] Session notes             — active session + hard rules checklist
[10 ] Data freshness            — staleness flag for every input column
```

---

## Hard Rules

1. **Event blackout** — no new entries within NFP/CPI/PCE/PPI/FOMC windows
2. **Broker IV > 30%** — use half-lot column (broker margin rate, not CBOE GVZ)
3. **IB building** — no entry in first 30–60 min of any session
4. **3+ confluent signals** — required before any entry
5. **Correlated exposure** — XAU + XAG + SHORT_USD = one bet
6. **Circuit breaker** — YELLOW = STRONG signals only; RED = stop trading
7. **P8 reclaim filter** — LSE_SWEEP invalidated if price reclaims 3+ pts within 4 bars
8. **P9 structural VWAP exit** — exit on VWAP cross + HTF flip OR POC crossing VWAP
9. **2R target / 48-bar timeout** — no exceptions

---

## Key Constants

| Parameter | Value |
|-----------|-------|
| Account | $10,000 (FundingPips challenge) |
| Risk per trade | 0.5% ($50) |
| Daily hard stop | 4% ($400) |
| Total DD limit | 10% ($1,000) |
| Round-trip cost | 0.50 pt |
| Min risk | 3.0 pt |
| Target | 2R |
| Max hold | 48 bars (4 hours) |

---

## Repository Structure

```
├── lab/
│   ├── regime.py        # P0 HMM
│   ├── features.py      # P0 feature engine
│   ├── expectancy.py    # P0 + P8 + P9 backtester
│   ├── loaders.py       # data ingestion helpers
│   ├── risk.py          # P2 risk rails
│   ├── pca.py           # P1 composites
│   ├── scoring.py       # P3 thresholds
│   ├── journal.py       # P4 schema
│   ├── correlation.py   # P5 decouple
│   ├── cot.py           # P6 COT + FRED
│   ├── shock.py         # P7 shock detector
│   ├── staleness.py     # P10 freshness
│   └── events.py        # P11 event calendar
├── p0_run.py            # regime + expectancy runner
├── p1_run.py            # PCA + session composite runner
├── p3_p4_run.py         # scoring + journal runner
├── p5_p9_run.py         # signal cleanup runner
├── daily_brief.py       # morning brief
├── build_panel.py       # data pipeline
├── LSE v5.txt           # Pine HUD source
└── XAU_USD_Trading_System_Bible.md  # AI operating prompt v3.0
```

---

## Data Requirements

Broker CSV exports (not included — place in `historical data/`):

| File | Timeframe | Used for |
|------|-----------|---------|
| `D1/XAUUSD_D1.csv` | Daily | Regime, macro panel |
| `D1/XAGUSD_D1.csv` | Daily | XAG correlation factor |
| `D1/EURUSD_D1.csv` | Daily | EUR factor |
| `D1/USDJPY_D1.csv` | Daily | JPY factor |
| `m5/XAUUSD_M5.csv` | 5-minute | Signal detection + backtesting |

CSV format: tab-separated, `thousands=' '`, 7 columns (date as index).

FRED data (DGS10, DFII10, DTWEXBGS) is pulled automatically by `build_panel.py` — no API key required.

---

*Not financial advice. This is an engineering and measurement project.*
