"""
P11 -- Economic event blackout windows.

Hard rule: do not OPEN new positions within the blackout window of a
scheduled high-impact macro event.  Existing positions follow normal
stop/target rules; this only blocks NEW entries.

Blackout windows (all times UTC):
  NFP / CPI / PCE / PPI   : -15 min to +60 min around release
  FOMC meeting days        : full-day blackout
  Fed Chair speech         : -15 min to +30 min

Maintenance: update EVENTS weekly from the BLS / Fed economic calendar.
The FOMC schedule is published a year in advance at federalreserve.gov.
"""

from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

BLACKOUT_PRE_NORMAL   = 15    # minutes before release: no new entries
BLACKOUT_POST_NORMAL  = 60    # minutes after release: no new entries
BLACKOUT_POST_SPEECH  = 30    # minutes after Fed speech


class Event(NamedTuple):
    date_utc:  date
    time_utc:  str    # "HH:MM" or "ALL_DAY"
    name:      str
    category:  str    # NFP | CPI | PCE | PPI | FOMC | FED_SPEECH | OTHER
    note:      str = ""


# ── Event calendar (update weekly) ───────────────────────────────────────────

EVENTS: list[Event] = [
    # ── June 2026 ────────────────────────────────────────────────────────────
    Event(date(2026, 6, 11), "12:30", "US CPI May",      "CPI"),
    Event(date(2026, 6, 12), "12:30", "US PPI May",      "PPI"),
    Event(date(2026, 6, 17), "ALL_DAY", "FOMC Day 1 (Warsh)", "FOMC",
          "Warsh first meeting as Chair. Full-day blackout both days."),
    Event(date(2026, 6, 18), "18:00", "FOMC Decision + Presser", "FOMC",
          "Decision 18:00 UTC; press conference 18:30 UTC."),
    Event(date(2026, 6, 27), "12:30", "PCE May",         "PCE"),

    # ── July 2026 ────────────────────────────────────────────────────────────
    Event(date(2026, 7,  2), "12:30", "US NFP June",     "NFP"),
    Event(date(2026, 7, 10), "12:30", "US CPI June",     "CPI"),
    Event(date(2026, 7, 11), "12:30", "US PPI June",     "PPI"),
    Event(date(2026, 7, 25), "ALL_DAY", "FOMC Day 1",    "FOMC"),
    Event(date(2026, 7, 26), "18:00", "FOMC Decision",   "FOMC"),

    # ── August 2026 ──────────────────────────────────────────────────────────
    Event(date(2026, 8,  7), "12:30", "US NFP July",     "NFP"),
]

# ─────────────────────────────────────────────────────────────────────────────


def _pre_post(ev: Event) -> tuple[int, int]:
    """Return (pre_min, post_min) for a given event category."""
    if ev.category == "FED_SPEECH":
        return BLACKOUT_PRE_NORMAL, BLACKOUT_POST_SPEECH
    return BLACKOUT_PRE_NORMAL, BLACKOUT_POST_NORMAL


def _window(ev: Event) -> tuple[datetime, datetime] | None:
    """Return (start_utc, end_utc) or None for ALL_DAY events."""
    if ev.time_utc == "ALL_DAY":
        return None
    h, m = map(int, ev.time_utc.split(":"))
    release = datetime(ev.date_utc.year, ev.date_utc.month, ev.date_utc.day,
                       h, m, tzinfo=timezone.utc)
    pre, post = _pre_post(ev)
    return (release - timedelta(minutes=pre),
            release + timedelta(minutes=post))


def is_blackout(dt: datetime | None = None) -> tuple[bool, list[Event]]:
    """
    Return (True, [active events]) if dt falls inside any blackout window.
    dt defaults to now (UTC).
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    today  = dt.date()
    active = []
    for ev in EVENTS:
        if ev.time_utc == "ALL_DAY":
            if ev.date_utc == today:
                active.append(ev)
        else:
            w = _window(ev)
            if w and w[0] <= dt <= w[1]:
                active.append(ev)
    return bool(active), active


def next_events(dt: datetime | None = None, n: int = 4) -> list[tuple[Event, str]]:
    """
    Return the next n upcoming events with their countdown strings.
    Each item: (Event, countdown_str).
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    today = dt.date()
    results = []
    for ev in sorted(EVENTS, key=lambda e: (e.date_utc, e.time_utc)):
        if ev.date_utc < today:
            continue
        if ev.time_utc == "ALL_DAY":
            ev_dt = datetime(ev.date_utc.year, ev.date_utc.month, ev.date_utc.day,
                             0, 0, tzinfo=timezone.utc)
        else:
            h, m  = map(int, ev.time_utc.split(":"))
            ev_dt = datetime(ev.date_utc.year, ev.date_utc.month, ev.date_utc.day,
                             h, m, tzinfo=timezone.utc)
        if ev_dt <= dt:
            continue
        delta = ev_dt - dt
        days  = delta.days
        hours = delta.seconds // 3600
        if days > 0:
            cd = f"in {days}d {hours}h"
        else:
            mins = (delta.seconds % 3600) // 60
            cd = f"in {hours}h {mins}m"
        results.append((ev, cd))
        if len(results) >= n:
            break
    return results


def event_calendar_report(dt: datetime | None = None) -> str:
    """Human-readable event + blackout status for daily_brief.py."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    blacked, active = is_blackout(dt)
    upcoming        = next_events(dt, n=4)

    lines = ["Event calendar (P11):"]
    if blacked:
        lines.append("  [!!!] BLACKOUT ACTIVE -- NO NEW POSITIONS")
        for ev in active:
            lines.append(f"        {ev.name}  [{ev.category}]")
            if ev.note:
                lines.append(f"        {ev.note}")
    else:
        lines.append("  Status: clear -- no active blackout")

    if upcoming:
        lines.append("")
        lines.append("  Upcoming events:")
        for ev, cd in upcoming:
            time_str = ev.time_utc if ev.time_utc != "ALL_DAY" else "ALL DAY"
            lines.append(f"    {ev.date_utc}  {time_str} UTC  ({cd})  "
                         f"{ev.name:<32}  [{ev.category}]")
            w = _window(ev)
            if w:
                pre  = w[0].strftime("%H:%M")
                post = w[1].strftime("%H:%M")
                lines.append(f"    {'':<36}  blackout {pre}-{post} UTC")
    else:
        lines.append("")
        lines.append("  No upcoming events -- update EVENTS list in lab/events.py")

    return "\n".join(lines)
