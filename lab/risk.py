"""
Risk rails — frozen per P2 spec.

Four components:
  1. Fixed-fractional sizer (0.5% per trade, $50 on $10k)
  2. Daily circuit breaker  (soft stop 3% / hard limit 4%)
  3. Correlated-exposure cap (XAU + XAG + SHORT_USD = one bet)
  4. Fractional-Kelly sizer  (INFORMATIONAL only — parked until
                               Phase 1 delivers a reliable edge estimate)

Broker: FundingPips $10k challenge
  Daily loss hard limit : 4%  = $400
  Max total drawdown    : 10% = $1,000
  Internal soft stop    : 3%  = $300 daily (100 USD buffer below hard limit)

XAU/USD pip value: 1 standard lot = 100 oz; $1 price move = $100 P&L.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

# ── Configuration (frozen) ────────────────────────────────────────────────────

@dataclass(frozen=True)
class RiskConfig:
    account_balance:     float = 10_000.0    # USD, FundingPips challenge
    risk_pct:            float = 0.5         # % of balance per trade

    # FundingPips hard limits
    daily_loss_limit_pct: float = 4.0        # % => $400
    total_dd_limit_pct:   float = 10.0       # % => $1,000

    # Internal soft stop: stop trading when this is hit, before the hard limit
    daily_soft_stop_pct: float = 3.0         # % => $300

    # P13 -- broker overnight margin IV modifier (Bible §6 hard rule)
    # This is the broker's overnight margin requirement %, NOT CBOE GVZ.
    # GVZ (Gold Volatility Index) is related but not equal; do not substitute.
    # Source: broker platform -> Account -> Overnight margin rate for XAU/USD.
    iv_high_threshold:   float = 30.0        # broker O/N IV % threshold
    iv_size_reduction:   float = 0.5         # multiply lots by this when IV is high

    # Correlated set: only one open position allowed across these
    correlated_instruments: tuple = ("XAU", "XAG", "SHORT_USD")

    # XAU/USD: USD P&L per 1-point move per 1 standard lot
    pip_value_per_lot: float = 100.0


DEFAULT = RiskConfig()


# ── 1. Fixed-fractional sizer ─────────────────────────────────────────────────

def position_size(entry: float,
                  stop: float,
                  overnight_iv_pct: float = 0.0,
                  config: RiskConfig = DEFAULT) -> dict:
    """
    Compute lot size using fixed-fractional risk.

        risk_amount = account_balance * (risk_pct / 100)
        lots        = risk_amount / (risk_pts * pip_value_per_lot)

    If overnight_iv_pct > iv_high_threshold, lots are halved (Bible Rule 2).

    Returns dict with lots, risk_amount_usd, risk_pts, iv_flag.
    """
    risk_pts = abs(entry - stop)
    if risk_pts < 1e-6:
        return {"lots": 0.0, "risk_pts": 0.0, "risk_amount_usd": 0.0,
                "iv_flag": False, "note": "stop == entry"}

    risk_amount = config.account_balance * config.risk_pct / 100.0
    lots        = risk_amount / (risk_pts * config.pip_value_per_lot)

    iv_flag = overnight_iv_pct >= config.iv_high_threshold
    if iv_flag:
        lots *= config.iv_size_reduction

    return {
        "lots":            round(lots, 2),
        "risk_pts":        round(risk_pts, 3),
        "risk_amount_usd": round(risk_amount * (config.iv_size_reduction if iv_flag else 1.0), 2),
        "iv_flag":         iv_flag,
        "note":            "IV >30% — size halved" if iv_flag else "",
    }


def lot_table(config: RiskConfig = DEFAULT,
              stop_pts: tuple = (5, 8, 10, 12, 15, 20, 25)) -> list[dict]:
    """Quick-reference table: lot size for common stop distances."""
    risk_amount = config.account_balance * config.risk_pct / 100.0
    rows = []
    for sp in stop_pts:
        lots = risk_amount / (sp * config.pip_value_per_lot)
        rows.append({
            "stop_pts":  sp,
            "lots":      round(lots, 2),
            "lots_iv":   round(lots * config.iv_size_reduction, 2),
            "usd_risk":  round(risk_amount, 0),
        })
    return rows


# ── 2. Daily circuit breaker ──────────────────────────────────────────────────

def daily_loss_status(daily_pnl_usd: float,
                      config: RiskConfig = DEFAULT) -> dict:
    """
    Check whether today's session is still tradeable.

    daily_pnl_usd: sum of realised P&L for today (negative = loss).

    Returns:
      can_trade      bool  — False if soft stop is hit
      status         str   — GREEN / YELLOW / RED
      daily_loss_usd float — loss so far today (negative number)
      remaining_usd  float — USD remaining before soft stop
      pct_used       float — % of hard daily limit consumed
    """
    loss        = min(daily_pnl_usd, 0.0)
    soft_limit  = config.account_balance * config.daily_soft_stop_pct  / 100.0
    hard_limit  = config.account_balance * config.daily_loss_limit_pct / 100.0
    remaining   = soft_limit - abs(loss)
    pct_used    = abs(loss) / hard_limit * 100.0

    if abs(loss) >= soft_limit:
        status = "RED    -- STOP TRADING (soft stop hit)"
    elif remaining < config.account_balance * 0.01:   # within $100 of soft stop
        status = "YELLOW -- WARNING (within $100 of soft stop)"
    else:
        status = "GREEN  -- OK"

    return {
        "can_trade":       abs(loss) < soft_limit,
        "status":          status,
        "daily_loss_usd":  round(loss, 2),
        "remaining_usd":   round(remaining, 2),
        "pct_used":        round(pct_used, 1),
        "soft_limit_usd":  round(soft_limit, 2),
        "hard_limit_usd":  round(hard_limit, 2),
    }


def total_dd_status(peak_balance: float,
                    current_balance: float,
                    config: RiskConfig = DEFAULT) -> dict:
    """
    Check total drawdown from peak balance.

    Returns can_trade bool and context.
    """
    dd          = current_balance - peak_balance          # negative = drawdown
    hard_limit  = config.account_balance * config.total_dd_limit_pct / 100.0
    remaining   = hard_limit - abs(dd)
    dd_pct      = abs(dd) / config.account_balance * 100.0

    return {
        "can_trade":       abs(dd) < hard_limit,
        "dd_usd":          round(dd, 2),
        "dd_pct":          round(dd_pct, 2),
        "remaining_usd":   round(remaining, 2),
        "hard_limit_usd":  round(hard_limit, 2),
    }


# ── 3. Correlated-exposure cap ────────────────────────────────────────────────

def exposure_check(open_instruments: list[str],
                   new_instrument: str,
                   config: RiskConfig = DEFAULT) -> dict:
    """
    Gold + Silver + any short-USD position = one correlated bet.
    Block adding a new correlated position if one is already open.

    open_instruments: list of strings, e.g. ["XAU"].
    new_instrument:   string, e.g. "XAG".
    """
    corr     = set(config.correlated_instruments)
    on_corr  = [i for i in open_instruments if i in corr]
    is_corr  = new_instrument in corr
    blocked  = is_corr and len(on_corr) > 0

    return {
        "can_add":         not blocked,
        "open_correlated": on_corr,
        "blocked_reason":  (f"Correlated exposure: {on_corr} already open"
                            if blocked else None),
    }


# ── 4. Fractional-Kelly sizer (INFORMATIONAL — parked) ───────────────────────

def kelly_fraction(hit_rate: float,
                   avg_win_R: float,
                   avg_loss_R: float) -> float:
    """
    Kelly fraction for discrete R-multiple bets:
        f* = p - (1-p) / (avg_win_R / |avg_loss_R|)

    Returns a NEGATIVE value when the edge is below the breakeven threshold.
    Breakeven for a 2R target: hit_rate >= 1/3 = 33.3%.

    NOTE: This is the FULL Kelly. Use at most 25% of this (fractional Kelly).
    """
    if avg_win_R <= 0.0 or avg_loss_R >= 0.0:
        return float("nan")
    b = avg_win_R / abs(avg_loss_R)
    return round(hit_rate - (1.0 - hit_rate) / b, 4)


def kelly_size_info(hit_rate: float,
                    avg_win_R: float,
                    avg_loss_R: float,
                    frac: float = 0.25,
                    config: RiskConfig = DEFAULT) -> dict:
    """
    INFORMATIONAL — not for live use until edge is statistically reliable.

    Converts fractional Kelly into a lot size for a given entry/stop distance.
    Returns status and context; does NOT return a lot size (use fixed-fractional).
    """
    kf = kelly_fraction(hit_rate, avg_win_R, avg_loss_R)

    if np.isnan(kf):
        return {"status": "UNDEFINED — invalid inputs", "kelly_f": float("nan"),
                "fractional_pct": float("nan")}
    if kf <= 0.0:
        return {"status": f"NEGATIVE EDGE ({kf:.4f}) -- Kelly undefined; use fixed-fractional",
                "kelly_f": kf, "fractional_pct": 0.0}

    frac_pct = kf * frac * 100.0
    capped   = min(frac_pct, config.risk_pct * 2.0)
    return {
        "status":          "INFORMATIONAL — not yet statistically reliable",
        "kelly_f":         kf,
        "full_kelly_pct":  round(kf * 100.0, 2),
        "fractional_pct":  round(capped, 3),
        "cap_applied":     capped < frac_pct,
        "note":            "Parked until n >= 100 per cell in expectancy table",
    }
