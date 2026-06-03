"""
build_lse_v7.py
Transforms LSE v6.txt into LSE v7.txt by applying 6 targeted changes:

  [v7 ADD 1]  London Range tracking (07:00-12:55 UTC, locked at NY open)
  [v7 ADD 2]  NY_SWEEP detection: London Range sweep at NY open hour (long only)
  [v7 ADD 3]  inNYSweepLong state + P8 reclaim extended to NY_SWEEP
  [v7 ADD 4]  London Range plot lines (dashed, olive colour)
  [v7 ADD 5]  HUD row: LONDON RNG in SESSION section (table expanded 28->29)
  [v7 ADD 6]  entryTypeText shows "NY SWEEP" when inNYSweepLong

Run: python build_lse_v7.py
"""

from pathlib import Path

SRC = Path(__file__).parent / "LSE v6.txt"
DST = Path(__file__).parent / "LSE v7.txt"

text = SRC.read_text(encoding="utf-8")

# ── helper ─────────────────────────────────────────────────────────────────────
def replace_once(src: str, old: str, new: str) -> str:
    assert old in src, f"Pattern not found:\n{old[:120]}"
    return src.replace(old, new, 1)


# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 0 — version string in indicator() call and architecture block
# ══════════════════════════════════════════════════════════════════════════════

text = replace_once(text,
    'indicator("Liquidity Structure Engine v6"',
    'indicator("Liquidity Structure Engine v7"'
)

text = replace_once(text,
    '//  ARCHITECTURE v6  (changes from v5 marked with [v6])',
    '//  ARCHITECTURE v7  (changes from v6 marked with [v7])'
)

text = replace_once(text,
    '//  v6 changes (4 fixes, aligned with Python lab P0-P13 audit):\n'
    '//  [FIX 1] POC: loop starts at i=1 (was i=0) — confirmed bars only, no intrabar repaint\n'
    '//  [FIX 2] TOKYO_BREAK: compare close against asianHighCandidate[1] / asianLowCandidate[1]\n'
    '//          The old liveAsianHigh included current bar\'s high, making break impossible on the\n'
    '//          trigger bar itself (close <= high always). Aligns with Python lab behaviour.\n'
    '//  [FIX 3] P8 reclaim filter: for Asian sweep entries, if close re-crosses swept level by\n'
    '//          3+ pts within 4 bars → invalidated, exit immediately.\n'
    '//  [FIX 4] P9 structural VWAP exit: backstop now requires close past VWAP + structural\n'
    '//          confirmation (HTF bias flipped OR POC on wrong side of VWAP). Removes the old\n'
    '//          bearFlow/bullFlow volume requirement which was too restrictive.',

    '//  v6 changes (4 fixes, aligned with Python lab P0-P13 audit):\n'
    '//  [FIX 1] POC: loop starts at i=1 (was i=0) — confirmed bars only, no intrabar repaint\n'
    '//  [FIX 2] TOKYO_BREAK: compare close against asianHighCandidate[1] / asianLowCandidate[1]\n'
    '//          The old liveAsianHigh included current bar\'s high, making break impossible on the\n'
    '//          trigger bar itself (close <= high always). Aligns with Python lab behaviour.\n'
    '//  [FIX 3] P8 reclaim filter: for Asian sweep entries, if close re-crosses swept level by\n'
    '//          3+ pts within 4 bars → invalidated, exit immediately.\n'
    '//  [FIX 4] P9 structural VWAP exit: backstop now requires close past VWAP + structural\n'
    '//          confirmation (HTF bias flipped OR POC on wrong side of VWAP). Removes the old\n'
    '//          bearFlow/bullFlow volume requirement which was too restrictive.\n'
    '//\n'
    '//  v7 changes (1 new setup, Python lab P0-P13 + NY_SWEEP backtest):\n'
    '//  [v7 ADD] NY_SWEEP: London Range (07:00-12:55 UTC) locked at NY open (13:00).\n'
    '//           Detects sweep of London session low/high + reversal candle with flow gate.\n'
    '//           LONG ONLY — backtest (200k M5 bars 2023-2026) shows TREND long at\n'
    '//           41.7% hit / +0.517 avg_R / PF=2.26; short side negative in both regimes.\n'
    '//           P8 reclaim filter extended to NY_SWEEP using London low as reference.\n'
    '//           HUD: new LONDON RNG row in SESSION section.'
)

text = replace_once(text,
    '    table.cell(hud, 0, 0, "LSE v6"',
    '    table.cell(hud, 0, 0, "LSE v7"'
)

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 1 — London Range tracking (after Asian Range section, before Layer 17)
# ══════════════════════════════════════════════════════════════════════════════

text = replace_once(text,
    '// ═══════════════════════════════════════════════════════════════════════════\n'
    '//  LAYER 17 — INITIAL BALANCE (ASIAN / LONDON / NY)',

    '// ─────────────────────── LONDON RANGE (for NY_SWEEP) ───────────────────────\n'
    '// [v7 ADD 1] London Range = max/min of pre-NY London bars (07:00-12:55 UTC).\n'
    '// Locked at NY open exactly as Asian Range is locked at London open.\n'
    '\n'
    'var float londonHigh          = na\n'
    'var float londonLow           = na\n'
    'var float londonHighCandidate = na\n'
    'var float londonLowCandidate  = na\n'
    '\n'
    'if currentHour == londonOpen and currentHour[1] != londonOpen\n'
    '    londonHighCandidate := high\n'
    '    londonLowCandidate  := low\n'
    '\n'
    'if inLondon and currentHour < nyOpen\n'
    '    londonHighCandidate := na(londonHighCandidate) ? high : math.max(londonHighCandidate, high)\n'
    '    londonLowCandidate  := na(londonLowCandidate)  ? low  : math.min(londonLowCandidate,  low)\n'
    '\n'
    'if currentHour == nyOpen\n'
    '    londonHigh := londonHighCandidate\n'
    '    londonLow  := londonLowCandidate\n'
    '\n'
    '// ═══════════════════════════════════════════════════════════════════════════\n'
    '//  LAYER 17 — INITIAL BALANCE (ASIAN / LONDON / NY)'
)

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 2 — NY_SWEEP detection (after bearSweepAsian / bullSweepScore block)
# ══════════════════════════════════════════════════════════════════════════════

text = replace_once(text,
    'bullSweep = bullSweepLTF or bullSweepHTF or bullSweepAsian\n'
    'bearSweep = bearSweepLTF or bearSweepHTF or bearSweepAsian',

    'bullSweep = bullSweepLTF or bullSweepHTF or bullSweepAsian\n'
    'bearSweep = bearSweepLTF or bearSweepHTF or bearSweepAsian\n'
    '\n'
    '// [v7 ADD 2] NY_SWEEP — London Range sweep at NY open hour\n'
    '// LONG only: backtest shows short has no edge (negative avg_R in both regimes).\n'
    '// Same wick threshold as Asian sweep (sweepWickMin * 0.7).\n'
    'bullSweepNY = false\n'
    'if not na(londonLow) and nyTransition\n'
    '    bullSweepNY := low < londonLow and close > londonLow and\n'
    '         (londonLow - low) > atr * sweepWickMin * 0.7\n'
    '\n'
    'nySweepLong = bullSweepNY and (bullFlow or absorption) and not regimeDrift'
)

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 3a — add nySweepLong to longCondition
# ══════════════════════════════════════════════════════════════════════════════

text = replace_once(text,
    'longCondition =\n'
    '     (regimeVolatile and bullSweep and bullSweepScore >= minSweepScore and (bullFlow or absorption)) or\n'
    '     (regimeNeutral  and bullSweep and bullSweepScore == 3             and (bullFlow or absorption)) or\n'
    '     driftLong or\n'
    '     tokyoLong',

    'longCondition =\n'
    '     (regimeVolatile and bullSweep and bullSweepScore >= minSweepScore and (bullFlow or absorption)) or\n'
    '     (regimeNeutral  and bullSweep and bullSweepScore == 3             and (bullFlow or absorption)) or\n'
    '     driftLong or\n'
    '     tokyoLong or\n'
    '     nySweepLong    // [v7] NY_SWEEP: London Range sweep at NY open, long only'
)

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 3b — add inNYSweepLong state variable
# ══════════════════════════════════════════════════════════════════════════════

text = replace_once(text,
    '// [v6 FIX 3] P8 reclaim filter state\n'
    'var bool  inSweepLong   = false',

    '// [v6 FIX 3] P8 reclaim filter state\n'
    'var bool  inNYSweepLong = false    // [v7] NY_SWEEP entry tracker\n'
    'var bool  inSweepLong   = false'
)

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 3c — track inNYSweepLong on entry (pos == 0 → long branch)
# ══════════════════════════════════════════════════════════════════════════════

text = replace_once(text,
    '        // [v6 FIX 3] Track Asian sweep entries for P8 reclaim check\n'
    '        inSweepLong     := bullSweepAsian\n'
    '        inSweepShort    := false\n'
    '        if bullSweepAsian\n'
    '            sweepRefLo    := asianLow\n'
    '            sweepEntryBar := bar_index',

    '        // [v6 FIX 3] Track Asian sweep entries; [v7] also track NY_SWEEP entries\n'
    '        inSweepLong     := bullSweepAsian\n'
    '        inSweepShort    := false\n'
    '        inNYSweepLong   := nySweepLong\n'
    '        if bullSweepAsian\n'
    '            sweepRefLo    := asianLow\n'
    '            sweepEntryBar := bar_index\n'
    '        if nySweepLong\n'
    '            sweepRefLo    := londonLow    // [v7] P8 reference = London low\n'
    '            sweepEntryBar := bar_index'
)

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 3d — reset inNYSweepLong on all pos==1 exits
#   There are 3 exit paths in pos==1:
#     (a) primaryExit / cons / ob / tokyo / reclaim → sets pos=0
#     (b) backstopLong → sets pos=0
#     (c) shortCondition flip → sets pos=-1
# ══════════════════════════════════════════════════════════════════════════════

# Exit path (a) — primary exits
text = replace_once(text,
    '    if primaryExitLong or consExitLong or obExitLong or tokyoExitLong or reclaimLong\n'
    '        exitLong        := true\n'
    '        pos             := 0\n'
    '        longTargetLevel := na\n'
    '        inDriftLong     := false\n'
    '        inTokyoLong     := false\n'
    '        inSweepLong     := false   // [v6] reset P8 state\n'
    '        sweepRefLo      := na',

    '    // [v7] P8 reclaim filter extended to NY_SWEEP\n'
    '    reclaimNYSweep = inNYSweepLong and not na(sweepRefLo) and\n'
    '         (bar_index - sweepEntryBar) <= reclaimBars and\n'
    '         close < sweepRefLo - reclaimPts\n'
    '\n'
    '    if primaryExitLong or consExitLong or obExitLong or tokyoExitLong or reclaimLong or reclaimNYSweep\n'
    '        exitLong        := true\n'
    '        pos             := 0\n'
    '        longTargetLevel := na\n'
    '        inDriftLong     := false\n'
    '        inTokyoLong     := false\n'
    '        inSweepLong     := false   // [v6] reset P8 state\n'
    '        inNYSweepLong   := false   // [v7]\n'
    '        sweepRefLo      := na'
)

# Exit path (b) — backstop
text = replace_once(text,
    '    else if backstopLong\n'
    '        exitLong        := true\n'
    '        pos             := 0\n'
    '        longTargetLevel := na\n'
    '        inDriftLong     := false\n'
    '        inTokyoLong     := false\n'
    '        inSweepLong     := false   // [v6] reset P8 state\n'
    '        sweepRefLo      := na\n'
    '\n'
    '    if pos == 1 and shortCondition',

    '    else if backstopLong\n'
    '        exitLong        := true\n'
    '        pos             := 0\n'
    '        longTargetLevel := na\n'
    '        inDriftLong     := false\n'
    '        inTokyoLong     := false\n'
    '        inSweepLong     := false   // [v6] reset P8 state\n'
    '        inNYSweepLong   := false   // [v7]\n'
    '        sweepRefLo      := na\n'
    '\n'
    '    if pos == 1 and shortCondition'
)

# Exit path (c) — flip to short
text = replace_once(text,
    '        inSweepLong      := false   // [v6] reset P8 state\n'
    '        sweepRefLo       := na\n'
    '        longTargetLevel  := na\n'
    '        shortEntryPrice  := close\n'
    '        shortTargetLevel := f_shortTarget(close)\n'
    '        inSweepShort     := bearSweepAsian\n'
    '        if bearSweepAsian\n'
    '            sweepRefHi    := asianHigh\n'
    '            sweepEntryBar := bar_index',

    '        inSweepLong      := false   // [v6] reset P8 state\n'
    '        inNYSweepLong    := false   // [v7]\n'
    '        sweepRefLo       := na\n'
    '        longTargetLevel  := na\n'
    '        shortEntryPrice  := close\n'
    '        shortTargetLevel := f_shortTarget(close)\n'
    '        inSweepShort     := bearSweepAsian\n'
    '        if bearSweepAsian\n'
    '            sweepRefHi    := asianHigh\n'
    '            sweepEntryBar := bar_index'
)

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 4 — London Range plot (after Asian Range plots)
# ══════════════════════════════════════════════════════════════════════════════

text = replace_once(text,
    'plot(inTokyo ? asianHighCandidate : na, "Asian High (Live)", color=color.new(color.orange, 20), style=plot.style_linebr, linewidth=1)\n'
    'plot(inTokyo ? asianLowCandidate  : na, "Asian Low  (Live)", color=color.new(color.aqua,   20), style=plot.style_linebr, linewidth=1)',

    'plot(inTokyo ? asianHighCandidate : na, "Asian High (Live)", color=color.new(color.orange, 20), style=plot.style_linebr, linewidth=1)\n'
    'plot(inTokyo ? asianLowCandidate  : na, "Asian Low  (Live)", color=color.new(color.aqua,   20), style=plot.style_linebr, linewidth=1)\n'
    '\n'
    '// [v7 ADD 4] London Range lines — olive/yellow-green, dashed\n'
    'plot(londonHigh, "London High (Locked)", color=color.rgb(180, 200, 55, 40), style=plot.style_linebr, linewidth=1)\n'
    'plot(londonLow,  "London Low  (Locked)", color=color.rgb(180, 200, 55, 40), style=plot.style_linebr, linewidth=1)\n'
    'plot(inLondon and currentHour < nyOpen ? londonHighCandidate : na,\n'
    '     "London High (Live)", color=color.rgb(180, 200, 55, 15), style=plot.style_linebr, linewidth=1)\n'
    'plot(inLondon and currentHour < nyOpen ? londonLowCandidate  : na,\n'
    '     "London Low  (Live)", color=color.rgb(180, 200, 55, 15), style=plot.style_linebr, linewidth=1)'
)

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 5a — NY_SWEEP plotshape marker (after Tokyo markers)
# ══════════════════════════════════════════════════════════════════════════════

text = replace_once(text,
    '// Drift markers\n'
    'plotshape(driftLong  and pos == 1,',

    '// NY_SWEEP marker  [v7]\n'
    'plotshape(nySweepLong,\n'
    '     location=location.belowbar, style=shape.triangleup,\n'
    '     color=color.rgb(180, 200, 55, 0), size=size.small, text="NYS")\n'
    '\n'
    '// Drift markers\n'
    'plotshape(driftLong  and pos == 1,'
)

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 5b — HUD table: expand to 29 rows (was 28)
# ══════════════════════════════════════════════════════════════════════════════

text = replace_once(text,
    'var table hud = table.new(\n'
    '     hudPosition, 2, 28,',
    'var table hud = table.new(\n'
    '     hudPosition, 2, 29,    // [v7] +1 row for LONDON RNG'
)

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 5c — Insert LONDON RNG row (row 14) after ASIA RNG (row 13)
#             and shift all rows 14+ to 15+
# ══════════════════════════════════════════════════════════════════════════════

# Insert LONDON RNG after ASIA RNG row
text = replace_once(text,
    '    tokyoBreakText =\n'
    '         tokyoBullBreakCount > 0 ? "BULL " + str.tostring(tokyoBullBreakCount) + "/" + str.tostring(tokyoConfBars) :\n'
    '         tokyoBearBreakCount > 0 ? "BEAR " + str.tostring(tokyoBearBreakCount) + "/" + str.tostring(tokyoConfBars) :\n'
    '         "--"\n'
    '    tokyoBreakColor =\n'
    '         tokyoBullBreakCount > 0 ? color.rgb(0, 220, 200, 0) :\n'
    '         tokyoBearBreakCount > 0 ? color.rgb(0, 220, 200, 0) :\n'
    '         C_DIM\n'
    '    table.cell(hud, 0, 14, "TKY BREAK",\n'
    '         text_color=C_LABEL, text_size=size.small, bgcolor=C_BG_LABEL, text_halign=text.align_right)\n'
    '    table.cell(hud, 1, 14, tokyoBreakText,\n'
    '         text_color=tokyoBreakColor, text_size=size.small, bgcolor=C_BG_VAL, text_halign=text.align_left)',

    '    // [v7 ADD 5] LONDON RNG row (row 14)\n'
    '    lrText = not na(londonHigh) ?\n'
    '         str.tostring(londonHigh, "#.##") + " / " + str.tostring(londonLow, "#.##") :\n'
    '         inLondon and currentHour < nyOpen ? "Building..." : "--"\n'
    '    table.cell(hud, 0, 14, "LONDON RNG",\n'
    '         text_color=C_LABEL, text_size=size.small, bgcolor=C_BG_LABEL, text_halign=text.align_right)\n'
    '    table.cell(hud, 1, 14, lrText,\n'
    '         text_color=color.rgb(180, 200, 55, 0), text_size=size.small, bgcolor=C_BG_VAL, text_halign=text.align_left)\n'
    '\n'
    '    tokyoBreakText =\n'
    '         tokyoBullBreakCount > 0 ? "BULL " + str.tostring(tokyoBullBreakCount) + "/" + str.tostring(tokyoConfBars) :\n'
    '         tokyoBearBreakCount > 0 ? "BEAR " + str.tostring(tokyoBearBreakCount) + "/" + str.tostring(tokyoConfBars) :\n'
    '         "--"\n'
    '    tokyoBreakColor =\n'
    '         tokyoBullBreakCount > 0 ? color.rgb(0, 220, 200, 0) :\n'
    '         tokyoBearBreakCount > 0 ? color.rgb(0, 220, 200, 0) :\n'
    '         C_DIM\n'
    '    table.cell(hud, 0, 15, "TKY BREAK",\n'
    '         text_color=C_LABEL, text_size=size.small, bgcolor=C_BG_LABEL, text_halign=text.align_right)\n'
    '    table.cell(hud, 1, 15, tokyoBreakText,\n'
    '         text_color=tokyoBreakColor, text_size=size.small, bgcolor=C_BG_VAL, text_halign=text.align_left)'
)

# Shift INIT BAL section  15→16, inner rows 16-19→17-20
text = replace_once(text,
    '    // ── INIT BAL / Layer 17 (rows 15–19) ──────────────────────────────────\n'
    '    table.cell(hud, 0, 15, "INIT BAL", text_color=color.rgb(180, 100, 255, 0),\n'
    '         text_size=size.tiny, bgcolor=C_BG_SECTION, text_halign=text.align_left)\n'
    '    table.cell(hud, 1, 15, "", bgcolor=C_BG_SECTION)',

    '    // ── INIT BAL / Layer 17 (rows 16–20) ──────────────────────────────────\n'
    '    table.cell(hud, 0, 16, "INIT BAL", text_color=color.rgb(180, 100, 255, 0),\n'
    '         text_size=size.tiny, bgcolor=C_BG_SECTION, text_halign=text.align_left)\n'
    '    table.cell(hud, 1, 16, "", bgcolor=C_BG_SECTION)'
)

for old_r, new_r in [("16,", "17,"), ("17,", "18,"), ("18,", "19,"), ("19,", "20,")]:
    # Replace row references in the IB STATE / ASIAN IB / LONDON IB / NY IB rows
    for prefix in ['hud, 0, ', 'hud, 1, ']:
        old = f'{prefix}{old_r}'
        new = f'{prefix}{new_r}'
        # Only replace in the INIT BAL section — do targeted replaces
        text = text.replace(
            f'table.cell(hud, 0, {old_r[:-1]}, "IB STATE"',
            f'table.cell(hud, 0, {new_r[:-1]}, "IB STATE"', 1
        )
        text = text.replace(
            f'table.cell(hud, 1, {old_r[:-1]}, ibStateText',
            f'table.cell(hud, 1, {new_r[:-1]}, ibStateText', 1
        )
        text = text.replace(
            f'table.cell(hud, 0, {old_r[:-1]}, "ASIAN IB"',
            f'table.cell(hud, 0, {new_r[:-1]}, "ASIAN IB"', 1
        )
        text = text.replace(
            f'table.cell(hud, 1, {old_r[:-1]}, asianIBText',
            f'table.cell(hud, 1, {new_r[:-1]}, asianIBText', 1
        )
        text = text.replace(
            f'table.cell(hud, 0, {old_r[:-1]}, "LONDON IB"',
            f'table.cell(hud, 0, {new_r[:-1]}, "LONDON IB"', 1
        )
        text = text.replace(
            f'table.cell(hud, 1, {old_r[:-1]}, londonIBText',
            f'table.cell(hud, 1, {new_r[:-1]}, londonIBText', 1
        )
        text = text.replace(
            f'table.cell(hud, 0, {old_r[:-1]}, "NY IB"',
            f'table.cell(hud, 0, {new_r[:-1]}, "NY IB"', 1
        )
        text = text.replace(
            f'table.cell(hud, 1, {old_r[:-1]}, nyIBText',
            f'table.cell(hud, 1, {new_r[:-1]}, nyIBText', 1
        )

# Shift SIGNALS section  20→21, inner rows 21-24→22-25
text = replace_once(text,
    '    // ── SIGNALS (rows 20–24) ──────────────────────────────────────────────\n'
    '    table.cell(hud, 0, 20, "SIGNALS", text_color=color.rgb(70, 90, 150, 0),\n'
    '         text_size=size.tiny, bgcolor=C_BG_SECTION, text_halign=text.align_left)\n'
    '    table.cell(hud, 1, 20, "", bgcolor=C_BG_SECTION)',

    '    // ── SIGNALS (rows 21–25) ──────────────────────────────────────────────\n'
    '    table.cell(hud, 0, 21, "SIGNALS", text_color=color.rgb(70, 90, 150, 0),\n'
    '         text_size=size.tiny, bgcolor=C_BG_SECTION, text_halign=text.align_left)\n'
    '    table.cell(hud, 1, 21, "", bgcolor=C_BG_SECTION)'
)

for old_n, new_n in [(21, 22), (22, 23), (23, 24), (24, 25)]:
    text = text.replace(
        f'table.cell(hud, 0, {old_n}, "VOL RANK"',
        f'table.cell(hud, 0, {new_n}, "VOL RANK"', 1
    )
    text = text.replace(
        f'table.cell(hud, 1, {old_n}, str.tostring(math.round(volRank))',
        f'table.cell(hud, 1, {new_n}, str.tostring(math.round(volRank))', 1
    )
    text = text.replace(
        f'table.cell(hud, 0, {old_n}, "DRIFT"',
        f'table.cell(hud, 0, {new_n}, "DRIFT"', 1
    )
    text = text.replace(
        f'table.cell(hud, 1, {old_n}, driftText',
        f'table.cell(hud, 1, {new_n}, driftText', 1
    )
    text = text.replace(
        f'table.cell(hud, 0, {old_n}, "BUY SWEEP"',
        f'table.cell(hud, 0, {new_n}, "BUY SWEEP"', 1
    )
    text = text.replace(
        f'table.cell(hud, 1, {old_n},\n         bullSweep ?',
        f'table.cell(hud, 1, {new_n},\n         bullSweep ?', 1
    )
    text = text.replace(
        f'table.cell(hud, 0, {old_n}, "SELL SWEEP"',
        f'table.cell(hud, 0, {new_n}, "SELL SWEEP"', 1
    )
    text = text.replace(
        f'table.cell(hud, 1, {old_n},\n         bearSweep ?',
        f'table.cell(hud, 1, {new_n},\n         bearSweep ?', 1
    )

# Shift POSITION section  25→26, inner rows 26-27→27-28
text = replace_once(text,
    '    // ── POSITION (rows 25–27) ─────────────────────────────────────────────\n'
    '    table.cell(hud, 0, 25, "POSITION", text_color=color.rgb(70, 90, 150, 0),\n'
    '         text_size=size.tiny, bgcolor=C_BG_SECTION, text_halign=text.align_left)\n'
    '    table.cell(hud, 1, 25, "", bgcolor=C_BG_SECTION)',

    '    // ── POSITION (rows 26–28) ─────────────────────────────────────────────\n'
    '    table.cell(hud, 0, 26, "POSITION", text_color=color.rgb(70, 90, 150, 0),\n'
    '         text_size=size.tiny, bgcolor=C_BG_SECTION, text_halign=text.align_left)\n'
    '    table.cell(hud, 1, 26, "", bgcolor=C_BG_SECTION)'
)

for old_n, new_n in [(26, 27), (27, 28)]:
    text = text.replace(
        f'table.cell(hud, 0, {old_n}, "ENTRY TYPE"',
        f'table.cell(hud, 0, {new_n}, "ENTRY TYPE"', 1
    )
    text = text.replace(
        f'table.cell(hud, 1, {old_n}, entryTypeText',
        f'table.cell(hud, 1, {new_n}, entryTypeText', 1
    )
    text = text.replace(
        f'table.cell(hud, 0, {old_n}, "STATUS"',
        f'table.cell(hud, 0, {new_n}, "STATUS"', 1
    )
    text = text.replace(
        f'table.cell(hud, 1, {old_n}, posText',
        f'table.cell(hud, 1, {new_n}, posText', 1
    )

# ══════════════════════════════════════════════════════════════════════════════
# CHANGE 6 — entryTypeText: add "NY SWEEP" case
# ══════════════════════════════════════════════════════════════════════════════

text = replace_once(text,
    '    entryTypeText =\n'
    '         inTokyoLong  or inTokyoShort  ? "TOKYO EXP" :\n'
    '         inDriftLong  or inDriftShort  ? "DRIFT"     :\n'
    '         inSweepLong  or inSweepShort  ? "LSE SWEEP" :\n'
    '         pos != 0                      ? "SWEEP"     : "--"\n'
    '    entryTypeColor =\n'
    '         inTokyoLong or inTokyoShort ? color.rgb(0,   220, 200, 0) :\n'
    '         inDriftLong or inDriftShort ? color.rgb(70,  200, 255, 0) :\n'
    '         inSweepLong or inSweepShort ? color.rgb(255, 160,  40, 0) :\n'
    '         pos != 0                    ? color.rgb(255, 210,  55, 0) :\n'
    '         C_DIM',

    '    entryTypeText =\n'
    '         inTokyoLong  or inTokyoShort  ? "TOKYO EXP" :\n'
    '         inDriftLong  or inDriftShort  ? "DRIFT"     :\n'
    '         inNYSweepLong                 ? "NY SWEEP"  :    // [v7]\n'
    '         inSweepLong  or inSweepShort  ? "LSE SWEEP" :\n'
    '         pos != 0                      ? "SWEEP"     : "--"\n'
    '    entryTypeColor =\n'
    '         inTokyoLong  or inTokyoShort  ? color.rgb(0,   220, 200, 0) :\n'
    '         inDriftLong  or inDriftShort  ? color.rgb(70,  200, 255, 0) :\n'
    '         inNYSweepLong                 ? color.rgb(180, 200,  55, 0) :    // [v7] olive\n'
    '         inSweepLong  or inSweepShort  ? color.rgb(255, 160,  40, 0) :\n'
    '         pos != 0                      ? color.rgb(255, 210,  55, 0) :\n'
    '         C_DIM'
)

# ── write output ───────────────────────────────────────────────────────────────
DST.write_text(text, encoding="utf-8")
lines = text.count("\n") + 1
print(f"LSE v7.txt written: {lines} lines  ({DST.stat().st_size:,} bytes)")
print("Verify by pasting into TradingView Pine Editor.")
