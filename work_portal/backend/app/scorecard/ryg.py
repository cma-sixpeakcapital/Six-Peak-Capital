"""Target resolution, Red / Yellow / Green, streaks and the Scorecard view.

Rules (spec section 5.1, as amended 9/25/2026):
- No entry for the week          -> RED, "not reported"
- higher_better                  -> GREEN >= target; YELLOW >= yellow_floor; else RED
- lower_better                   -> GREEN <= target; YELLOW <= yellow_floor; else RED
- binary                         -> GREEN if 1 else RED
- blank yellow_floor             -> no yellow band (green or red)
- no target at all               -> GREY, "no target set" (never red)
- monthly_reported_weekly        -> last value carried forward (greyed, "as of"),
                                    RED "stale" once it is more than 45 days old
- weeks before the first live week are blank, not red

Targets: rows on the `targets` tab override metrics.target / yellow_floor. For a
given week the latest row on or before it applies; if the NEXT row has
interpolate=TRUE the target is a straight line between the two rows (a
glidepath). After the last row the target holds. A metric with target rows but
a week before the first row has no target.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .parse import Model, monday_of

GREEN, YELLOW, RED, GREY = "green", "yellow", "red", "grey"
STALE_DAYS = 45
STREAK_WEEKS = 3


def resolve_target(metric: dict[str, Any], rows: list[dict[str, Any]] | None,
                   week: date) -> tuple[float | None, float | None, bool]:
    """Return (target, yellow_floor, is_glidepath) for this metric and week."""
    if not rows:
        return metric.get("target"), metric.get("yellow_floor"), False
    prev = None
    nxt = None
    for r in rows:
        if r["effective_date"] <= week:
            prev = r
        elif nxt is None:
            nxt = r
    if prev is None:
        return None, None, False
    target = prev["target"]
    glide = False
    if (nxt is not None and nxt.get("interpolate") and prev["target"] is not None
            and nxt["target"] is not None):
        span = (nxt["effective_date"] - prev["effective_date"]).days
        if span > 0:
            frac = (week - prev["effective_date"]).days / span
            target = prev["target"] + (nxt["target"] - prev["target"]) * frac
            glide = True
    return target, prev.get("yellow_floor"), glide


def color_for(direction: str, value: float, target: float | None,
              yellow: float | None) -> str:
    if direction == "binary":
        return GREEN if value == 1 else RED
    if target is None:
        return GREY
    if direction == "higher_better":
        if value >= target:
            return GREEN
        if yellow is not None and value >= yellow:
            return YELLOW
        return RED
    if direction == "lower_better":
        if value <= target:
            return GREEN
        if yellow is not None and value <= yellow:
            return YELLOW
        return RED
    return GREY


def fmt_value(value: float | None, unit: str) -> str:
    if value is None:
        return ""
    if unit == "boolean":
        return "Yes" if value == 1 else "No"
    if unit == "dollars":
        a = abs(value)
        sign = "-" if value < 0 else ""
        if a >= 1_000_000:
            return f"{sign}${a / 1_000_000:.1f}M".replace(".0M", "M")
        if a >= 1_000:
            return f"{sign}${a / 1_000:.0f}K"
        return f"{sign}${a:,.0f}"
    if unit == "percent":
        return f"{value:g}%"
    if unit == "count":
        return f"{value:.1f}".rstrip("0").rstrip(".") if value != int(value) else f"{int(value)}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def fmt_target(metric: dict[str, Any], target: float | None, glide: bool) -> str:
    if metric["direction"] == "binary":
        return "Yes"
    if target is None:
        return "no target set"
    sym = "≥" if metric["direction"] == "higher_better" else "≤"
    shown = target
    if glide and metric["unit"] == "count":
        shown = round(target, 1)
    return f"{sym} {fmt_value(shown, metric['unit'])}"


def _cell(metric: dict[str, Any], model: Model, week: date, start_week: date) -> dict[str, Any]:
    target, yellow, glide = resolve_target(metric, model.targets.get(metric["metric_id"]), week)
    if week < start_week:
        return {"week": week, "state": "pre", "color": None, "target": target,
                "yellow_floor": yellow, "glide": glide,
                "target_display": fmt_target(metric, target, glide)}
    actual = None
    carried = False
    if metric["cadence"] == "weekly":
        actual = model.actuals.get((metric["metric_id"], week))
    else:
        best = None
        for (mid, wk), a in model.actuals.items():
            if mid == metric["metric_id"] and wk <= week and (best is None or wk > best["week_of"]):
                best = a
        actual = best
        carried = best is not None and best["week_of"] != week
    base = {"week": week, "target": target, "yellow_floor": yellow, "glide": glide,
            "target_display": fmt_target(metric, target, glide)}
    if actual is None:
        return {**base, "state": "missing", "color": RED, "label": "not reported"}
    value = actual["value"]
    if carried and (week - actual["week_of"]).days > STALE_DAYS:
        return {**base, "state": "stale", "color": RED, "value": value,
                "display": fmt_value(value, metric["unit"]), "as_of": actual["week_of"],
                "label": f"stale (as of {actual['week_of'].month}/{actual['week_of'].day})"}
    return {**base, "state": "carried" if carried else "reported",
            "color": color_for(metric["direction"], value, target, yellow),
            "value": value, "display": fmt_value(value, metric["unit"]),
            "as_of": actual["week_of"], "note": actual.get("note", ""),
            "entered_at": actual.get("entered_at", ""), "entered_by": actual.get("entered_by", "")}


def _trend_down(metric: dict[str, Any], cells: list[dict[str, Any]]) -> bool:
    """Two consecutive weeks of deterioration while still green (advance warning)."""
    last3 = cells[-3:]
    if len(last3) < 3 or any(c.get("state") != "reported" for c in last3):
        return False
    if last3[-1]["color"] != GREEN:
        return False
    a, b, c = (x["value"] for x in last3)
    if metric["direction"] == "higher_better":
        return c < b < a
    if metric["direction"] == "lower_better":
        return c > b > a
    return False


def build_view(model: Model, ref: date, start_week: date, weeks: int = 6) -> dict[str, Any]:
    current = monday_of(ref)
    week_list = [current - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    cat_order: dict[str, float] = {}
    for mt in model.metrics:
        cat_order[mt["category"]] = min(cat_order.get(mt["category"], 1e9), mt["sort_order"])
    rows = []
    counts = {GREEN: 0, YELLOW: 0, RED: 0, GREY: 0, "missing": 0}
    missing_by_owner: dict[str, list[str]] = {}
    for mt in sorted(model.metrics, key=lambda x: (cat_order[x["category"]], x["sort_order"])):
        cells = [_cell(mt, model, w, start_week) for w in week_list]
        cur = cells[-1]
        streak = 0
        for c in reversed(cells):
            if c.get("color") == RED:
                streak += 1
            else:
                break
        latest_entry = max((a for (mid, _), a in model.actuals.items() if mid == mt["metric_id"]),
                           key=lambda a: (a["week_of"], a.get("entered_at") or ""), default=None)
        if cur["state"] != "pre":
            counts[cur["color"]] += 1
            if cur["state"] == "missing":
                counts["missing"] += 1
                missing_by_owner.setdefault(mt["owner_name"], []).append(mt["name"])
        rows.append({
            **mt,
            "cells": cells,
            "current": cur,
            "streak": streak,
            "streak_flag": streak >= STREAK_WEEKS,
            "trend_down": _trend_down(mt, cells),
            "last_updated": (latest_entry.get("entered_at") or latest_entry["week_of"].isoformat())
            if latest_entry else "",
        })
    categories: list[dict[str, Any]] = []
    for r in rows:
        if not categories or categories[-1]["name"] != r["category"]:
            categories.append({"name": r["category"], "rows": []})
        categories[-1]["rows"].append(r)
    return {
        "week_of": current,
        "weeks": week_list,
        "start_week": start_week,
        "pre_launch": current < start_week,
        "categories": categories,
        "metric_count": len(rows),
        "counts": counts,
        "missing_by_owner": missing_by_owner,
        "errors": [e for e in model.errors if e["level"] == "error"],
        "warnings": [e for e in model.errors if e["level"] == "warning"],
    }
