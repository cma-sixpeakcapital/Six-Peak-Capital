"""To-do numbers for the Hit Rate tab (Bob's 9/26/2026 spec, Chris-approved).

Definitions (every percentage is shown with its fraction):
  7-day mark      created date + 7 days (ET dates).
  7-day rate      to-dos whose 7-day mark fell in the window; share completed by
                  their mark. Dropped to-dos are excluded. Headline window = the
                  last 7 days; standard = 90%.
  On-time         to-dos whose ORIGINAL due date fell in the quarter to date and
                  has passed (or that are already done); share completed on or
                  before the original due. Pushing the due date doesn't help.
  Open / overdue  open = on the list and not done; overdue = open and past the
                  CURRENT due date.
  Age             days since creation, for open to-dos; buckets 0-7, 8-14,
                  15-30, 31+.
  Dropped         counted separately (this quarter); never in any rate.
  Per owner       each named owner is credited on a shared to-do; names not on
                  the roster fall into "Unassigned". Ranked by trailing-13-week
                  7-day rate, only with >= MIN_RANKED items; others listed below.
  Trend           13 weekly points; week ending on each Tuesday (the L10).
Nothing before TRACKING_FROM is scored: completion times were not kept then.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from . import todos as T

STANDARD_PCT = 90
MIN_RANKED = 5
TREND_WEEKS = 13
TRACKING_FROM = date(2026, 9, 26)
BUCKETS = [("0–7", 0, 7), ("8–14", 8, 14), ("15–30", 15, 30), ("31+", 31, 10 ** 6)]
UNASSIGNED = "Unassigned"


def _pct(n: int, d: int) -> int | None:
    return round(100 * n / d) if d else None


def _frac(n: int, d: int) -> dict[str, Any]:
    return {"n": n, "d": d, "pct": _pct(n, d)}


def _mark(t: dict[str, Any]) -> date | None:
    c = T.et_date(t.get("created_at"))
    return c + timedelta(days=7) if c else None


def _done_date(t: dict[str, Any]) -> date | None:
    return T.et_date(t.get("completed_at")) if t.get("completed") else None


def seven_day(todos: Iterable[dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    """7-day rate for to-dos whose mark is in (start, end]."""
    n = d = 0
    for t in todos:
        if T.is_dropped(t):
            continue
        m = _mark(t)
        if m is None or not (start < m <= end) or m < TRACKING_FROM:
            continue
        done = _done_date(t)
        if t.get("completed") and done is None:
            continue  # checked off before completion times were kept: no verdict
        d += 1
        if done is not None and done <= m:
            n += 1
    return _frac(n, d)


def on_time(todos: Iterable[dict[str, Any]], q_start: date, today: date) -> dict[str, Any]:
    n = d = 0
    lo = max(q_start, TRACKING_FROM)
    for t in todos:
        if T.is_dropped(t):
            continue
        orig = T.parse_due(t.get("original_due"))
        if orig is None or orig < lo:
            continue
        done = _done_date(t)
        if t.get("completed") and done is None:
            continue  # checked off before completion times were kept: no verdict
        if orig >= today and done is None:
            continue  # not due yet and not done: no verdict
        d += 1
        if done is not None and done <= orig:
            n += 1
    return _frac(n, d)


def _open_stats(todos: list[dict[str, Any]], today: date) -> dict[str, Any]:
    open_ = [t for t in todos if T.is_open(t)]
    ages = [(today - (T.et_date(t.get("created_at")) or today)).days for t in open_]
    overdue = [t for t in open_ if (T.parse_due(t.get("due")) or date.max) < today]
    return {
        "open": len(open_),
        "overdue": len(overdue),
        "avg_age": round(sum(ages) / len(ages), 1) if ages else None,
        "oldest_age": max(ages) if ages else None,
        "buckets": [{"label": lbl, "count": sum(1 for a in ages if lo <= a <= hi)}
                    for lbl, lo, hi in BUCKETS],
    }


def _dropped_count(todos: list[dict[str, Any]], q_start: date) -> int:
    return sum(1 for t in todos if T.is_dropped(t) and (T.et_date(t["dropped_at"]) or date.min) >= q_start)


def _tuesday_on_or_before(d: date) -> date:
    return d - timedelta(days=(d.weekday() - 1) % 7)


def trend(todos: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    last = _tuesday_on_or_before(today)
    out = []
    for i in range(TREND_WEEKS - 1, -1, -1):
        end = last - timedelta(weeks=i)
        f = seven_day(todos, end - timedelta(days=7), end)
        out.append({"week_ending": end.isoformat(), **f})
    return out


def build(todos: list[dict[str, Any]], today: date, quarter: dict[str, Any] | None,
          people: Iterable[str]) -> dict[str, Any]:
    people = list(people)
    q_start = T.parse_due((quarter or {}).get("start")) or (today - timedelta(days=90))
    headline = seven_day(todos, today - timedelta(days=7), today)
    trail_start = today - timedelta(weeks=TREND_WEEKS)

    by_owner: dict[str, list[dict[str, Any]]] = {p: [] for p in people}
    by_owner[UNASSIGNED] = []
    for t in todos:
        names = [n for n in T.owner_list(t, people) if n in by_owner and n != UNASSIGNED]
        for n in names or [UNASSIGNED]:
            by_owner[n].append(t)

    rows = []
    for name, items in by_owner.items():
        if not items:
            continue
        s = _open_stats(items, today)
        rate = seven_day(items, trail_start, today)
        rows.append({
            "owner": name, "rate": rate,
            "on_time": on_time(items, q_start, today),
            "open": s["open"], "overdue": s["overdue"], "oldest_age": s["oldest_age"],
            "dropped": _dropped_count(items, q_start),
            "ranked": name != UNASSIGNED and rate["d"] >= MIN_RANKED,
        })
    ranked = sorted([r for r in rows if r["ranked"]],
                    key=lambda r: (-(r["rate"]["pct"] or 0), -r["rate"]["d"], r["owner"].lower()))
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    rest = sorted([r for r in rows if not r["ranked"]],
                  key=lambda r: (r["owner"] == UNASSIGNED, -r["rate"]["d"], r["owner"].lower()))

    return {
        "standard_pct": STANDARD_PCT,
        "min_ranked": MIN_RANKED,
        "tracking_from": TRACKING_FROM.isoformat(),
        "as_of": today.isoformat(),
        "headline": headline,
        "headline_hit": headline["pct"] is not None and headline["pct"] >= STANDARD_PCT,
        "on_time": on_time(todos, q_start, today),
        **_open_stats(todos, today),
        "dropped": _dropped_count(todos, q_start),
        "owners": ranked + rest,
        "trend": trend(todos, today),
    }
