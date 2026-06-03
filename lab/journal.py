"""
P4 — Locked journaling schema.

Every live trade and every backtest trade uses the SAME field names and
the SAME valid-value sets.  Forward live results are then directly
comparable to historical backtest stats without any remapping.

Schema fields
-------------
Required (backtest-compatible):
  trade_id      str   XAU-N  sequential identifier
  date          date  YYYY-MM-DD
  setup         str   LSE_SWEEP | TOKYO_BREAK | DRIFT
  direction     str   long | short
  session       str   tokyo | london | london_ny | ny | off
  regime        str   RANGE | TREND
  entry         float price
  stop          float price
  target        float price
  exit          float price (actual fill)
  risk_pts      float abs(entry - stop)
  outcome       str   win | loss | timeout
  gross_R       float (exit - entry) / risk_pts  (signed)
  net_R         float gross_R - cost_pts / risk_pts

Live-only (not in backtest):
  macro_score   int   -2..+2
  session_score int   -2..+2
  combined_score int  -4..+4
  signal_label  str   STRONG_LONG|MILD_LONG|NEUTRAL|MILD_SHORT|STRONG_SHORT
  confluence_n  int   number of confirming signals present (>= 3 required)
  overnight_iv  float O/N IV % at time of entry
  lots          float actual lot size traded
  pnl_usd       float realised P&L in USD
  notes         str   free text -- discretionary reasoning
"""

from __future__ import annotations
from dataclasses import dataclass, field, fields, asdict
from typing import Optional
import csv
import io

# ── Valid value sets (locked) ─────────────────────────────────────────────────

VALID_SETUPS     = {"LSE_SWEEP", "TOKYO_BREAK", "DRIFT"}
VALID_DIRECTIONS = {"long", "short"}
VALID_SESSIONS   = {"tokyo", "london", "london_ny", "ny", "off"}
VALID_REGIMES    = {"RANGE", "TREND"}
VALID_OUTCOMES   = {"win", "loss", "timeout"}
VALID_LABELS     = {"STRONG_LONG", "MILD_LONG", "NEUTRAL",
                    "MILD_SHORT", "STRONG_SHORT"}

COST_PTS = 0.50   # must match expectancy.py


# ── Schema dataclass ──────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    # ── backtest-compatible fields (required) ─────────────────────────────────
    trade_id:      str
    date:          str          # YYYY-MM-DD
    setup:         str
    direction:     str
    session:       str
    regime:        str
    entry:         float
    stop:          float
    target:        float
    exit:          float
    risk_pts:      float
    outcome:       str
    gross_R:       float
    net_R:         float
    # ── live-only fields (optional for backtest rows) ─────────────────────────
    macro_score:   Optional[int]   = None
    session_score: Optional[int]   = None
    combined_score:Optional[int]   = None
    signal_label:  Optional[str]   = None
    confluence_n:  Optional[int]   = None
    overnight_iv:  Optional[float] = None
    lots:          Optional[float] = None
    pnl_usd:       Optional[float] = None
    notes:         Optional[str]   = None


# ── Validation ────────────────────────────────────────────────────────────────

def validate(t: TradeRecord) -> list[str]:
    """
    Return a list of validation error strings.
    Empty list = record is valid.
    """
    errs = []

    if t.setup not in VALID_SETUPS:
        errs.append(f"setup '{t.setup}' not in {VALID_SETUPS}")
    if t.direction not in VALID_DIRECTIONS:
        errs.append(f"direction '{t.direction}' not in {VALID_DIRECTIONS}")
    if t.session not in VALID_SESSIONS:
        errs.append(f"session '{t.session}' not in {VALID_SESSIONS}")
    if t.regime not in VALID_REGIMES:
        errs.append(f"regime '{t.regime}' not in {VALID_REGIMES}")
    if t.outcome not in VALID_OUTCOMES:
        errs.append(f"outcome '{t.outcome}' not in {VALID_OUTCOMES}")
    if t.risk_pts < 3.0:
        errs.append(f"risk_pts {t.risk_pts:.2f} < MIN_RISK_PTS 3.0")
    if abs(t.risk_pts - abs(t.entry - t.stop)) > 0.01:
        errs.append(f"risk_pts {t.risk_pts:.3f} does not match |entry-stop| "
                    f"{abs(t.entry - t.stop):.3f}")

    # net_R consistency
    expected_net = t.gross_R - COST_PTS / t.risk_pts
    if abs(t.net_R - expected_net) > 0.001:
        errs.append(f"net_R {t.net_R:.4f} inconsistent with gross_R {t.gross_R:.4f} "
                    f"and cost (expected {expected_net:.4f})")

    # live-only range checks (if provided)
    if t.macro_score is not None and not (-2 <= t.macro_score <= 2):
        errs.append(f"macro_score {t.macro_score} outside [-2, +2]")
    if t.session_score is not None and not (-2 <= t.session_score <= 2):
        errs.append(f"session_score {t.session_score} outside [-2, +2]")
    if t.combined_score is not None and not (-4 <= t.combined_score <= 4):
        errs.append(f"combined_score {t.combined_score} outside [-4, +4]")
    if t.signal_label is not None and t.signal_label not in VALID_LABELS:
        errs.append(f"signal_label '{t.signal_label}' not in {VALID_LABELS}")
    if t.confluence_n is not None and t.confluence_n < 3:
        errs.append(f"confluence_n {t.confluence_n} < 3 (hard rule: >= 3 signals required)")

    return errs


# ── Conversion helpers ────────────────────────────────────────────────────────

def from_backtest_row(row: dict, trade_id: str) -> TradeRecord:
    """
    Convert a row from trade_log.csv (backtest) into a TradeRecord.
    Live-only fields are left as None.
    """
    from lab.regime import NAMES as RN
    regime_raw = row.get("regime")
    try:
        regime_str = RN.get(int(float(regime_raw)), "RANGE")
    except (TypeError, ValueError):
        regime_str = "RANGE"

    return TradeRecord(
        trade_id  = trade_id,
        date      = str(row["date"])[:10],
        setup     = row["setup"],
        direction = row["direction"],
        session   = row["session"],
        regime    = regime_str,
        entry     = float(row["entry"]),
        stop      = float(row["stop"]),
        target    = float(row["target"]),
        exit      = float(row["exit"]),
        risk_pts  = float(row["risk_pts"]),
        outcome   = row["outcome"],
        gross_R   = float(row["gross_R"]),
        net_R     = float(row["net_R"]),
    )


def from_live_entry(trade_id: str,
                    date: str,
                    setup: str,
                    direction: str,
                    session: str,
                    regime: str,
                    entry: float,
                    stop: float,
                    target: float,
                    exit_price: float,
                    outcome: str,
                    lots: float,
                    macro_score: int,
                    session_score: int,
                    signal_label: str,
                    confluence_n: int,
                    overnight_iv: float = 0.0,
                    notes: str = "") -> TradeRecord:
    """
    Build a validated TradeRecord from a live trade fill.
    gross_R and net_R are computed automatically.
    """
    risk_pts  = abs(entry - stop)
    if direction == "long":
        gross_R = (exit_price - entry) / risk_pts if risk_pts > 0 else 0.0
    else:
        gross_R = (entry - exit_price) / risk_pts if risk_pts > 0 else 0.0
    net_R    = gross_R - COST_PTS / risk_pts if risk_pts > 0 else 0.0
    pnl_usd  = net_R * risk_pts * lots * 100   # $100/lot/point for XAU

    return TradeRecord(
        trade_id      = trade_id,
        date          = date,
        setup         = setup,
        direction     = direction,
        session       = session,
        regime        = regime,
        entry         = round(entry, 3),
        stop          = round(stop, 3),
        target        = round(target, 3),
        exit          = round(exit_price, 3),
        risk_pts      = round(risk_pts, 3),
        outcome       = outcome,
        gross_R       = round(gross_R, 4),
        net_R         = round(net_R, 4),
        macro_score   = macro_score,
        session_score = session_score,
        combined_score= macro_score + session_score,
        signal_label  = signal_label,
        confluence_n  = confluence_n,
        overnight_iv  = overnight_iv,
        lots          = lots,
        pnl_usd       = round(pnl_usd, 2),
        notes         = notes,
    )


# ── Comparison: live vs backtest ──────────────────────────────────────────────

def compare_live_to_backtest(live: list[TradeRecord],
                              backtest_path: str) -> dict:
    """
    Compare live trade metrics against the backtest expectancy table.
    Returns a dict with per-setup breakdown and aggregate stats.
    """
    import pandas as pd
    import numpy as np

    bt = pd.read_csv(backtest_path)

    live_df = pd.DataFrame([asdict(t) for t in live])
    if live_df.empty:
        return {"error": "no live trades"}

    results = {}
    for (setup, direction), grp in live_df.groupby(["setup", "direction"]):
        bt_row = bt[(bt["setup"] == setup) & (bt["direction"] == direction)]
        live_hit = (grp["outcome"] == "win").mean() * 100
        live_avg = grp["net_R"].mean()
        live_n   = len(grp)

        bt_hit = float(bt_row["hit_%"].mean()) if not bt_row.empty else None
        bt_avg = float(bt_row["avg_R"].mean()) if not bt_row.empty else None
        bt_n   = int(bt_row["n"].sum()) if not bt_row.empty else None

        results[f"{setup}/{direction}"] = {
            "live_n":    live_n,
            "live_hit%": round(live_hit, 1),
            "live_avgR": round(live_avg, 3),
            "bt_n":      bt_n,
            "bt_hit%":   round(bt_hit, 1) if bt_hit is not None else None,
            "bt_avgR":   round(bt_avg, 3) if bt_avg is not None else None,
        }

    return results


# ── Template generation ───────────────────────────────────────────────────────

def generate_template_csv(path: str) -> None:
    """
    Write a blank CSV template with all schema fields and descriptions
    that the trader fills in after each live trade.
    """
    FIELDS = [
        ("trade_id",       "XAU-N sequential ID",                        "XAU-11"),
        ("date",           "YYYY-MM-DD",                                  "2026-06-03"),
        ("setup",          "LSE_SWEEP | TOKYO_BREAK | DRIFT",             "TOKYO_BREAK"),
        ("direction",      "long | short",                                "long"),
        ("session",        "tokyo | london | london_ny | ny | off",       "tokyo"),
        ("regime",         "RANGE | TREND  (from daily brief)",           "TREND"),
        ("entry",          "actual fill price",                           "4510.00"),
        ("stop",           "stop loss price",                             "4495.00"),
        ("target",         "2R target price",                             "4540.00"),
        ("exit",           "actual exit price",                           "4540.00"),
        ("risk_pts",       "abs(entry - stop)",                           "15.00"),
        ("outcome",        "win | loss | timeout",                        "win"),
        ("gross_R",        "auto: (exit-entry)/risk_pts",                 "2.00"),
        ("net_R",          "auto: gross_R - 0.50/risk_pts",               "1.97"),
        ("macro_score",    "-2..+2  from daily brief",                    "1"),
        ("session_score",  "-2..+2  from daily brief",                    "2"),
        ("combined_score", "macro + session",                             "3"),
        ("signal_label",   "STRONG_LONG|MILD_LONG|NEUTRAL|MILD_SHORT|STRONG_SHORT", "STRONG_LONG"),
        ("confluence_n",   "count of confirming signals (>= 3 required)", "4"),
        ("overnight_iv",   "O/N IV %% at entry time",                    "18.5"),
        ("lots",           "actual lot size traded",                      "0.05"),
        ("pnl_usd",        "auto: net_R * risk_pts * lots * 100",         "147.50"),
        ("notes",          "discretionary reasoning / observations",      ""),
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["field", "description", "example"])
        for fname, desc, ex in FIELDS:
            w.writerow([fname, desc, ex])

    # Also write the actual blank data template (separate sheet-style CSV)
    blank_path = path.replace("_schema", "_blank")
    with open(blank_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([f[0] for f in FIELDS])
        # One blank row with placeholders
        w.writerow(["XAU-??" if i == 0 else "" for i in range(len(FIELDS))])
