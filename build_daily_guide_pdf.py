"""
build_daily_guide_pdf.py
Generates "Project X -- Daily Operating Guide.pdf" in the project root.
Run once: python build_daily_guide_pdf.py
"""

from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.platypus import ListFlowable, ListItem

# ── colours ────────────────────────────────────────────────────────────────
GOLD       = colors.HexColor("#C9A84C")
DARK_GOLD  = colors.HexColor("#8B6914")
NEAR_BLACK = colors.HexColor("#1A1A1A")
DARK_GREY  = colors.HexColor("#333333")
MID_GREY   = colors.HexColor("#666666")
LIGHT_GREY = colors.HexColor("#F4F4F4")
RED_SOFT   = colors.HexColor("#C0392B")
GREEN_SOFT = colors.HexColor("#1E7E34")
BG_DARK    = colors.HexColor("#2C2C2C")

W, H = A4
MARGIN = 2.0 * cm

# ── styles ──────────────────────────────────────────────────────────────────
def make_styles():
    base = getSampleStyleSheet()

    styles = {}

    styles["cover_title"] = ParagraphStyle(
        "cover_title",
        fontName="Helvetica-Bold",
        fontSize=28,
        textColor=GOLD,
        leading=34,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    styles["cover_sub"] = ParagraphStyle(
        "cover_sub",
        fontName="Helvetica",
        fontSize=13,
        textColor=MID_GREY,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    styles["section_header"] = ParagraphStyle(
        "section_header",
        fontName="Helvetica-Bold",
        fontSize=14,
        textColor=GOLD,
        leading=18,
        spaceBefore=18,
        spaceAfter=4,
    )
    styles["subsection"] = ParagraphStyle(
        "subsection",
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=NEAR_BLACK,
        leading=15,
        spaceBefore=10,
        spaceAfter=3,
    )
    styles["body"] = ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=10,
        textColor=DARK_GREY,
        leading=15,
        spaceAfter=4,
    )
    styles["mono"] = ParagraphStyle(
        "mono",
        fontName="Courier",
        fontSize=9,
        textColor=NEAR_BLACK,
        leading=13,
        leftIndent=12,
        spaceAfter=2,
    )
    styles["mono_block"] = ParagraphStyle(
        "mono_block",
        fontName="Courier",
        fontSize=9,
        textColor=colors.white,
        backColor=BG_DARK,
        leading=13,
        leftIndent=10,
        rightIndent=10,
        spaceBefore=4,
        spaceAfter=4,
    )
    styles["note"] = ParagraphStyle(
        "note",
        fontName="Helvetica-Oblique",
        fontSize=9,
        textColor=MID_GREY,
        leading=13,
        leftIndent=12,
        spaceAfter=6,
    )
    styles["rule_item"] = ParagraphStyle(
        "rule_item",
        fontName="Helvetica",
        fontSize=10,
        textColor=DARK_GREY,
        leading=14,
        leftIndent=20,
        spaceAfter=3,
    )
    styles["stop_banner"] = ParagraphStyle(
        "stop_banner",
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.white,
        backColor=RED_SOFT,
        leading=16,
        leftIndent=8,
        rightIndent=8,
        spaceBefore=6,
        spaceAfter=6,
        alignment=TA_CENTER,
    )
    styles["go_banner"] = ParagraphStyle(
        "go_banner",
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.white,
        backColor=GREEN_SOFT,
        leading=16,
        leftIndent=8,
        rightIndent=8,
        spaceBefore=6,
        spaceAfter=6,
        alignment=TA_CENTER,
    )
    styles["footer"] = ParagraphStyle(
        "footer",
        fontName="Helvetica-Oblique",
        fontSize=8,
        textColor=MID_GREY,
        alignment=TA_CENTER,
    )
    return styles


def hr(thickness=0.8, color=GOLD):
    return HRFlowable(
        width="100%", thickness=thickness, color=color, spaceAfter=6, spaceBefore=6
    )


def thin_hr():
    return HRFlowable(
        width="100%", thickness=0.4, color=colors.HexColor("#DDDDDD"),
        spaceAfter=4, spaceBefore=4
    )


def code_block(lines, s):
    items = []
    for line in lines:
        items.append(Paragraph(line, s["mono_block"]))
    return items


# ── table helpers ────────────────────────────────────────────────────────────
def two_col_table(rows, col_widths, s, header=None):
    data = []
    if header:
        data.append([
            Paragraph(f"<b>{header[0]}</b>", s["body"]),
            Paragraph(f"<b>{header[1]}</b>", s["body"]),
        ])
    for left, right in rows:
        data.append([
            Paragraph(left,  s["body"]),
            Paragraph(right, s["body"]),
        ])
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0 if header else -1), LIGHT_GREY),
        ("TEXTCOLOR",  (0, 0), (-1, -1), DARK_GREY),
        ("FONTNAME",   (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1),
         [colors.white, LIGHT_GREY]),
    ])
    if header:
        style.add("BACKGROUND", (0, 0), (-1, 0), DARK_GOLD)
        style.add("TEXTCOLOR",  (0, 0), (-1, 0), colors.white)
        style.add("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold")
    return Table(data, colWidths=col_widths, style=style, hAlign="LEFT")


def checklist_table(items, s):
    data = [[
        Paragraph("<font color='#C9A84C'><b>☐</b></font>", s["body"]),
        Paragraph(item, s["body"]),
    ] for item in items]
    style = TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT_GREY]),
    ])
    usable = W - 2 * MARGIN
    return Table(data, colWidths=[0.6 * cm, usable - 0.6 * cm],
                 style=style, hAlign="LEFT")


# ── document builder ─────────────────────────────────────────────────────────
def build(out_path: Path):
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN,  bottomMargin=MARGIN,
        title="Project X -- Daily Operating Guide",
        author="B.V. Preetham Reddy",
    )

    s = make_styles()
    story = []
    usable = W - 2 * MARGIN

    # ── COVER ────────────────────────────────────────────────────────────────
    story += [
        Spacer(1, 2.5 * cm),
        Paragraph("PROJECT X", s["cover_title"]),
        Paragraph("XAU/USD Discretionary Trading System", s["cover_sub"]),
        Paragraph("Daily Operating Guide", s["cover_sub"]),
        Spacer(1, 0.4 * cm),
        hr(thickness=2),
        Spacer(1, 0.3 * cm),
        Paragraph(
            "FundingPips $10,000 Challenge  |  Manual execution on TradingView  |  "
            "Lab: Python (P0-P13)",
            s["note"],
        ),
        Paragraph(
            "LSE v6 Pine HUD + Python lab. Not financial advice. "
            "Engineering and measurement only.",
            s["note"],
        ),
        Spacer(1, 3.5 * cm),
    ]

    # ── KEY CONSTANTS BOX ────────────────────────────────────────────────────
    constants = [
        ("Account",          "$10,000 (FundingPips)"),
        ("Risk / trade",     "0.5% = $50"),
        ("Daily hard stop",  "4% = $400"),
        ("Total DD limit",   "10% = $1,000"),
        ("Round-trip cost",  "0.50 pt  (modelled every trade)"),
        ("Min risk",         "3.0 pt"),
        ("Target",           "2R"),
        ("Max hold",         "48 bars = 4 hours"),
    ]
    story.append(
        two_col_table(constants, [usable * 0.42, usable * 0.58], s,
                      header=["Parameter", "Value"])
    )
    story.append(Spacer(1, 0.4 * cm))
    story.append(hr())

    # ── SECTION 1: MORNING ROUTINE ────────────────────────────────────────────
    story.append(Paragraph("1.  Morning Routine  (Before London Open)", s["section_header"]))
    story.append(Paragraph(
        "Do these three steps every morning before the London session opens "
        "(07:00 UTC). Budget 3-5 minutes.",
        s["body"],
    ))

    story.append(Paragraph("Step 1 -- Update the data panel  (daily, always)", s["subsection"]))
    story.append(Paragraph(
        'Open a terminal in the project folder '
        '(<font face="Courier">D:\\e drive\\8th semester\\Finance\\Project X</font>) '
        'and run:',
        s["body"],
    ))
    story += code_block([
        'cd "D:\\e drive\\8th semester\\Finance\\Project X"',
        "python build_panel.py",
    ], s)
    story.append(Paragraph(
        "Pulls latest FRED data (10Y nominal, 10Y real, USD broad index) and "
        "re-merges with broker CSV exports. Updates daily_panel.csv. Takes ~30 s.",
        s["note"],
    ))

    story.append(Paragraph("Step 2 -- Refresh lab scores  (daily, or if &gt;24 h since last run)", s["subsection"]))
    story += code_block([
        "python p1_run.py       # macro PCA + session composite",
        "python p5_p9_run.py    # decouple (P5), COT (P6), shock (P7)",
    ], s)
    story.append(Paragraph(
        "p0_run.py (HMM regime) only needs to run weekly. "
        "Run it on Monday morning or whenever you see 'regime' flagged stale in the brief.",
        s["note"],
    ))

    story.append(Paragraph("Step 3 -- Read the brief", s["subsection"]))
    story += code_block([
        "python daily_brief.py",
        "",
        "# Or with live account state:",
        "python daily_brief.py --pnl -120.50 --balance 9880 --iv 28",
    ], s)
    story.append(Paragraph(
        "--pnl = running P&amp;L today in USD (0 if no trades yet)  |  "
        "--balance = account balance if drifted from $10,000  |  "
        "--iv = broker overnight margin IV % (check broker platform, NOT CBOE GVZ)",
        s["note"],
    ))

    # ── SECTION 2: READING THE BRIEF ─────────────────────────────────────────
    story.append(hr())
    story.append(Paragraph("2.  Reading the Brief -- What to Actually Look At", s["section_header"]))

    story.append(Paragraph(
        "STOP immediately if either of these is active:",
        s["subsection"],
    ))
    story.append(Paragraph(
        "[ 4 ] shows BLACKOUT ACTIVE  -- no new entries today",
        s["stop_banner"],
    ))
    story.append(Paragraph(
        "[ 6 ] shows RED  -- daily loss limit hit, stop trading",
        s["stop_banner"],
    ))

    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph("Then work through the brief blocks in order:", s["subsection"]))

    brief_blocks = [
        ("[ 0 ]", "Event blackout banner",
         "Bright warning if a scheduled release is live RIGHT NOW."),
        ("[ 1 ]", "Market regime",
         "TREND or RANGE? TREND = LSE_SWEEP + TOKYO_BREAK have extra edge. "
         "VOLATILE / NEUTRAL / DRIFT on the ATR axis."),
        ("[ 2 ]", "Composite signals",
         "Macro PCA score + session score + combined. "
         "STRONG (>=2) = trade. MILD (1) = only best setups. "
         "NEUTRAL (0) = wait. WAIT (<0) = do not trade."),
        ("[ 3 ]", "Contextual filters",
         "Decouple flag (gold/DXY z-score <-1), COT net positioning, "
         "fresh-shock flag. Each adds +/-1 to your mental score."),
        ("[ 4 ]", "Event calendar",
         "Next 4 scheduled releases with exact blackout windows "
         "(NFP/CPI/PCE/PPI = -15/+60 min; FOMC = all day)."),
        ("[ 5 ]", "Risk envelope",
         "Lot table at common stop distances. "
         "Use the 'Broker IV>30%' column when --iv >=30."),
        ("[ 6 ]", "Circuit breaker",
         "YELLOW = strong signals only. RED = stop trading. "
         "Resets at midnight broker time."),
        ("[ 7 ]", "Kelly sizer",
         "Parked until you have >=100 trades per regime cell. Ignore until then."),
        ("[ 8 ]", "Session notes",
         "Active session label + hard-rules checklist. "
         "Read this before every entry."),
        ("[ 10 ]", "Data freshness",
         "Staleness flags for every panel input. "
         "Any STALE flag = re-run build_panel.py + affected runner before trading."),
    ]

    data = []
    for blk, name, desc in brief_blocks:
        data.append([
            Paragraph(f"<font face='Courier' color='#8B6914'><b>{blk}</b></font>", s["body"]),
            Paragraph(f"<b>{name}</b>", s["body"]),
            Paragraph(desc, s["body"]),
        ])

    tbl_style = TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT_GREY]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("BACKGROUND", (0, 0), (-1, 0), DARK_GOLD),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
    ])
    story.append(
        Table(data, colWidths=[usable * 0.09, usable * 0.22, usable * 0.69],
              style=tbl_style, hAlign="LEFT")
    )

    # ── SECTION 3: AT THE SESSION ─────────────────────────────────────────────
    story.append(hr())
    story.append(Paragraph("3.  At the Session -- Entry Checklist", s["section_header"]))
    story.append(Paragraph(
        "Open TradingView with the LSE v6 Pine HUD. "
        "The brief gives you the daily bias; the HUD gives you the live entry trigger. "
        "You need both. Before entering any trade, tick all six mentally:",
        s["body"],
    ))

    entry_checks = [
        "Combined score says tradeable  (MILD = cautious; STRONG = full conviction)",
        "HTF Bias on HUD agrees with intended direction",
        "IB is LOCKED  (not BUILDING -- no entries in first 30-60 min of session)",
        "Bookmap CVD agrees with direction  (imbalance on your side)",
        "3 or more signals aligned  (at least MILD on composite)",
        "Not inside a blackout window  (check [ 4 ] in the brief)",
    ]
    story.append(checklist_table(entry_checks, s))

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "<b>STRONG signal</b> = open position at MILD risk ($50).   "
        "<b>MILD signal</b> = reduce to $25 or skip.   "
        "<b>NEUTRAL / WAIT</b> = close TradingView.",
        s["go_banner"],
    ))

    story.append(Paragraph("Setup windows:", s["subsection"]))
    setups = [
        ("LSE_SWEEP",     "07:00-07:59 UTC",
         "Asian range sweep + reversal during London open hour. "
         "Best in TREND regime. "
         "P8: invalidated if price reclaims 3+ pts within 4 bars."),
        ("TOKYO_BREAK",   "01:00-08:59 UTC",
         "2nd consecutive close beyond running Tokyo range. "
         "Needs body > ATR threshold. "
         "Fixed in v6: uses confirmed prior bar high/low."),
        ("DRIFT",         "Any session, ATR ratio < 0.7",
         "7-condition micro-structure alignment. "
         "Works in RANGE regime. "
         "All 7 conditions required."),
    ]
    story.append(
        two_col_table(
            [(f"<b>{n}</b>  ({w})", d) for n, w, d in setups],
            [usable * 0.30, usable * 0.70],
            s,
        )
    )

    story.append(Paragraph("P9 structural exit (backstop):", s["subsection"]))
    story.append(Paragraph(
        "If you are in a LONG and price crosses VWAP AND either "
        "(a) HTF bias has flipped bearish OR (b) POC is now below VWAP -- exit. "
        "Mirror for SHORT. This exits before the 48-bar timeout when structure breaks.",
        s["body"],
    ))

    # ── SECTION 4: AFTER A TRADE ──────────────────────────────────────────────
    story.append(hr())
    story.append(Paragraph("4.  After a Trade -- Logging", s["section_header"]))
    story.append(Paragraph(
        "Log every trade in <font face='Courier'>outputs/journal_template_blank.csv</font>. "
        "Required fields:",
        s["body"],
    ))
    journal_fields = [
        ("setup",      "LSE_SWEEP / TOKYO_BREAK / DRIFT"),
        ("direction",  "LONG / SHORT"),
        ("entry",      "Fill price in XAU/USD pts"),
        ("stop",       "Stop price"),
        ("target",     "Target price"),
        ("exit",       "Actual exit price"),
        ("outcome",    "WIN / LOSS / BE"),
        ("net_R",      "gross_R - 0.50 / risk_pts  (formula pre-filled in template)"),
        ("regime",     "RANGE or TREND at time of entry"),
        ("session",    "LONDON / NEW_YORK / TOKYO / OVERNIGHT"),
        ("notes",      "Any qualitative notes (optional)"),
    ]
    story.append(
        two_col_table(journal_fields, [usable * 0.22, usable * 0.78], s,
                      header=["Field", "Value"])
    )
    story.append(Paragraph(
        "Kelly sizing activates once you have >=100 logged trades per regime cell "
        "(RANGE-LONG, RANGE-SHORT, TREND-LONG, TREND-SHORT). "
        "Until then the $50 fixed risk is the rule.",
        s["note"],
    ))

    # ── SECTION 5: WEEKLY ─────────────────────────────────────────────────────
    story.append(hr())
    story.append(Paragraph("5.  Weekly Maintenance  (~5 minutes, Monday morning)", s["section_header"]))
    story += code_block([
        "# Re-fit HMM regime model with latest week of D1 data",
        "python p0_run.py",
        "",
        "# Re-run signal cleanup (also retries COT download)",
        "python p5_p9_run.py",
    ], s)
    story.append(Paragraph(
        "After running: open <font face='Courier'>lab/events.py</font> "
        "and add any newly published NFP / CPI / FOMC dates for the next 4 weeks. "
        "The EVENTS list at the top of the file takes "
        "<font face='Courier'>Event(date_utc, time_utc, name, category, note)</font> entries.",
        s["body"],
    ))
    story.append(Paragraph(
        "If COT download fails (CFTC server timeout): go to "
        "cftc.gov > Market Reports > COT > Disaggregated Futures-Only > View History, "
        "download the annual CSV for gold (contract code 088691), "
        "save as <font face='Courier'>outputs/cot_gold.csv</font>.",
        s["note"],
    ))

    # ── SECTION 6: HARD RULES ─────────────────────────────────────────────────
    story.append(hr())
    story.append(Paragraph("6.  Hard Rules -- No Exceptions", s["section_header"]))
    story.append(Paragraph(
        "These override every other signal or opinion:",
        s["body"],
    ))

    hard_rules = [
        "<b>Event blackout</b> -- no new entries within NFP/CPI/PCE/PPI/FOMC windows "
        "(see [ 4 ] in brief for exact times).",
        "<b>Broker IV &gt; 30%</b> -- use half-lot column. "
        "This is the broker overnight margin rate, NOT CBOE GVZ.",
        "<b>IB building</b> -- no entry in first 30-60 min of any session.",
        "<b>3+ confluent signals required</b> -- below 3, skip the trade.",
        "<b>Correlated exposure</b> -- XAU + XAG + SHORT USD = one bet. "
        "Do not stack all three simultaneously.",
        "<b>Circuit breaker</b> -- YELLOW = strong signals only; RED = stop trading for the day.",
        "<b>P8 reclaim filter</b> -- LSE_SWEEP invalidated if price reclaims "
        "3+ pts within 4 bars of entry.",
        "<b>P9 structural VWAP exit</b> -- exit on VWAP cross + HTF flip OR POC crossing VWAP.",
        "<b>2R target / 48-bar timeout</b> -- no exceptions; close at bar 48 regardless.",
    ]
    for i, rule in enumerate(hard_rules, 1):
        story.append(Paragraph(f"{i}.  {rule}", s["rule_item"]))
        story.append(Spacer(1, 0.05 * cm))

    # ── SECTION 7: LSE v6 CHANGES ─────────────────────────────────────────────
    story.append(hr())
    story.append(Paragraph("7.  What Changed in LSE v6 (vs v5)", s["section_header"]))
    story.append(Paragraph(
        "Four targeted fixes applied from the P0-P13 Python lab audit:",
        s["body"],
    ))

    v6_changes = [
        (
            "FIX 1 -- POC no intrabar repaint",
            "POC loop now starts at i=1 (confirmed bars only), "
            "skipping the still-forming current bar. "
            "In v5, the POC could shift intrabar, making live readings unreliable.",
        ),
        (
            "FIX 2 -- TOKYO_BREAK actually fires",
            "v5 compared close > liveAsianHigh, but liveAsianHigh already "
            "included the current bar's high -- making the condition mathematically "
            "impossible to trigger on the break bar. "
            "v6 uses asianHighCandidate[1] (previous bar's confirmed value). "
            "Expect more TOKYO_BREAK signals in live trading.",
        ),
        (
            "FIX 3 -- P8 reclaim filter live",
            "New inputs: Reclaim Window = 4 bars, Reclaim Distance = 3 pts. "
            "After a SWEEP entry, if price re-closes through the swept level by "
            "3+ pts within 4 bars, the trade is exited immediately. "
            "Protects against false sweeps. Both values are adjustable in inputs.",
        ),
        (
            "FIX 4 -- P9 structural VWAP exit",
            "Removed the old bearFlow / bullFlow volume requirement "
            "(it was masking valid structural exits). "
            "New logic: exit long if close < VWAP AND (HTF bias flipped bearish "
            "OR POC < VWAP). Catches structural breakdown without waiting for "
            "volume confirmation that often arrives too late.",
        ),
    ]

    for title, desc in v6_changes:
        story.append(KeepTogether([
            Paragraph(title, s["subsection"]),
            Paragraph(desc, s["body"]),
        ]))

    # ── SECTION 8: ONE-LINE SUMMARY ───────────────────────────────────────────
    story.append(hr(thickness=2))
    story.append(Paragraph("One-Line Summary", s["section_header"]))
    story.append(Paragraph(
        "Run <font face='Courier'>build_panel.py</font> then "
        "<font face='Courier'>p1_run.py</font> then "
        "<font face='Courier'>daily_brief.py</font> every morning. "
        "Read the brief top to bottom. "
        "If it says WAIT or BLACKOUT, close the charts. "
        "If it says STRONG or MILD, open TradingView and wait for LSE v6 to confirm entry. "
        "Never enter without both the brief bias AND the HUD trigger aligned.",
        s["body"],
    ))

    # ── FOOTER ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.5 * cm))
    story.append(hr(thickness=0.4, color=MID_GREY))
    story.append(Paragraph(
        "Project X -- XAU/USD Discretionary Trading System  |  "
        "Not financial advice. Engineering and measurement only.",
        s["footer"],
    ))

    doc.build(story)
    print(f"PDF written -> {out_path}")


if __name__ == "__main__":
    out = Path(__file__).parent / "Project X -- Daily Operating Guide.pdf"
    build(out)
