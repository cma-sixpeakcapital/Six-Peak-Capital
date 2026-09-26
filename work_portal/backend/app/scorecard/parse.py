"""Turn the four CSV tabs into a validated scorecard model.

Validation follows spec section 7. Bad rows are never silently dropped: each one
becomes an entry in ``errors`` (tab, sheet row number, reason) that the portal
shows on the Scorecard. A rejected actuals row simply leaves that metric
"not reported" for the week.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

UNITS = {"number", "dollars", "percent", "count", "boolean"}
DIRECTIONS = {"higher_better", "lower_better", "binary"}
CADENCES = {"weekly", "monthly_reported_weekly"}

_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


@dataclass
class Model:
    metrics: list[dict[str, Any]] = field(default_factory=list)
    people: dict[str, dict[str, Any]] = field(default_factory=dict)
    # (metric_id, week_of) -> actual
    actuals: dict[tuple[str, date], dict[str, Any]] = field(default_factory=dict)
    # metric_id -> rows sorted by effective_date
    targets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def error(self, tab: str, row: int | None, reason: str, level: str = "error") -> None:
        self.errors.append({"tab": tab, "row": row, "reason": reason, "level": level})


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def parse_bool(raw: str) -> bool | None:
    s = (raw or "").strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return None


def parse_number(raw: str, unit: str = "number") -> float | None:
    """Blank -> None. Accepts $, commas, %, (negatives), and Yes/No for booleans.
    Raises ValueError on anything else."""
    s = (raw or "").strip()
    if not s:
        return None
    if unit == "boolean":
        b = parse_bool(s)
        if b is not None:
            return 1.0 if b else 0.0
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = s.replace("$", "").replace(",", "").replace("%", "").strip()
    val = float(s)  # raises ValueError
    return -val if neg else val


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y")


def parse_date(raw: str) -> date | None:
    """Blank -> None. Accepts ISO, US m/d/yyyy, and date-times. Raises ValueError."""
    s = (raw or "").strip()
    if not s:
        return None
    head = s.split(" ")[0] if (" " in s and ":" in s) else s
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {raw!r}")


def _rows(text: str) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Return (header, [(sheet_row_number, {col: value})]). Header is lowercased."""
    reader = csv.reader(io.StringIO(text or ""))
    all_rows = list(reader)
    if not all_rows:
        return [], []
    header = [h.strip().lower() for h in all_rows[0]]
    out = []
    for i, r in enumerate(all_rows[1:], start=2):
        if not any((c or "").strip() for c in r):
            continue  # fully blank row
        out.append((i, {header[j]: (r[j] if j < len(r) else "").strip()
                        for j in range(len(header)) if header[j]}))
    return header, out


def _require(model: Model, tab: str, header: list[str], cols: tuple[str, ...]) -> bool:
    missing = [c for c in cols if c not in header]
    if missing:
        model.error(tab, 1, f"missing column(s): {', '.join(missing)}")
        return False
    return True


def parse_sheet(csvs: dict[str, str]) -> Model:
    m = Model()

    # ---- people ------------------------------------------------------------
    header, rows = _rows(csvs.get("people", ""))
    if _require(m, "people", header, ("name", "email")):
        for rn, r in rows:
            email = r.get("email", "").lower()
            if not email:
                m.error("people", rn, "blank email")
                continue
            active = parse_bool(r.get("active", "TRUE"))
            m.people[email] = {"name": r.get("name") or email, "email": email,
                               "role": r.get("role", ""), "active": active is not False}

    # ---- metrics -----------------------------------------------------------
    header, rows = _rows(csvs.get("metrics", ""))
    seen: set[str] = set()
    if _require(m, "metrics", header, ("metric_id", "metric_name", "owner_email", "unit",
                                       "direction", "target")):
        for rn, r in rows:
            mid = r.get("metric_id", "")
            if not mid:
                m.error("metrics", rn, "blank metric_id")
                continue
            if mid in seen:
                m.error("metrics", rn, f"duplicate metric_id '{mid}' (first row kept)")
                continue
            active = parse_bool(r.get("active", ""))
            if active is None:
                m.error("metrics", rn, f"'{mid}': active must be TRUE or FALSE (treated as TRUE)",
                        "warning")
                active = True
            unit = r.get("unit", "").lower()
            direction = r.get("direction", "").lower()
            cadence = (r.get("cadence", "") or "weekly").lower()
            problems = []
            if unit not in UNITS:
                problems.append(f"unit '{unit}'")
            if direction not in DIRECTIONS:
                problems.append(f"direction '{direction}'")
            if cadence not in CADENCES:
                problems.append(f"cadence '{cadence}'")
            if problems:
                m.error("metrics", rn, f"'{mid}': invalid {', '.join(problems)}")
                continue
            try:
                target = parse_number(r.get("target", ""), unit)
                yellow = parse_number(r.get("yellow_floor", ""), unit)
            except ValueError:
                m.error("metrics", rn, f"'{mid}': target / yellow_floor must be numbers")
                continue
            try:
                sort_order = float(r.get("sort_order") or 999)
            except ValueError:
                sort_order = 999.0
            owner = r.get("owner_email", "").lower()
            if owner not in m.people:
                m.error("metrics", rn, f"'{mid}': owner_email '{owner}' is not on the people tab",
                        "warning")
            seen.add(mid)
            if not active:
                continue
            m.metrics.append({
                "metric_id": mid,
                "category": r.get("category", "") or "Other",
                "name": r.get("metric_name") or mid,
                "owner_email": owner,
                "owner_name": (m.people.get(owner) or {}).get("name") or owner,
                "unit": unit,
                "direction": direction,
                "target": target,
                "yellow_floor": yellow,
                "cadence": cadence,
                "sort_order": sort_order,
                "definition": r.get("definition", ""),
                "row": rn,
            })
    active_ids = {x["metric_id"]: x for x in m.metrics}

    # ---- targets -----------------------------------------------------------
    header, rows = _rows(csvs.get("targets", ""))
    if rows and _require(m, "targets", header, ("metric_id", "effective_date", "target")):
        for rn, r in rows:
            mid = r.get("metric_id", "")
            if mid not in active_ids:
                m.error("targets", rn, f"unknown or inactive metric_id '{mid}'")
                continue
            unit = active_ids[mid]["unit"]
            try:
                eff = parse_date(r.get("effective_date", ""))
            except ValueError:
                eff = None
            if eff is None:
                m.error("targets", rn, f"'{mid}': effective_date is not a date")
                continue
            try:
                tgt = parse_number(r.get("target", ""), unit)
                yf = parse_number(r.get("yellow_floor", ""), unit)
            except ValueError:
                m.error("targets", rn, f"'{mid}': target / yellow_floor must be numbers")
                continue
            interp = parse_bool(r.get("interpolate", "")) is True
            m.targets.setdefault(mid, []).append({
                "effective_date": eff, "target": tgt, "yellow_floor": yf,
                "interpolate": interp, "note": r.get("note", ""), "row": rn,
            })
        for lst in m.targets.values():
            lst.sort(key=lambda t: t["effective_date"])

    # ---- actuals -----------------------------------------------------------
    header, rows = _rows(csvs.get("actuals", ""))
    if _require(m, "actuals", header, ("metric_id", "week_of", "value")):
        for rn, r in rows:
            mid = r.get("metric_id", "")
            raw_val = r.get("value", "")
            if not raw_val.strip():
                continue  # placeholder row with no number yet: not an error
            if mid not in active_ids:
                m.error("actuals", rn, f"unknown or inactive metric_id '{mid}'")
                continue
            try:
                wk = parse_date(r.get("week_of", ""))
            except ValueError:
                wk = None
            if wk is None:
                m.error("actuals", rn, f"'{mid}': week_of is not a date")
                continue
            monday = monday_of(wk)
            if monday != wk:
                m.error("actuals", rn,
                        f"'{mid}': week_of {wk.isoformat()} is not a Monday; counted as week of "
                        f"{monday.isoformat()}", "warning")
            try:
                val = parse_number(raw_val, active_ids[mid]["unit"])
            except ValueError:
                m.error("actuals", rn, f"'{mid}': value '{raw_val}' is not a number (reads as not reported)")
                continue
            entered_at = r.get("entered_at", "")
            key = (mid, monday)
            prev = m.actuals.get(key)
            if prev is not None:
                # Latest entered_at wins; with no stamps, the lower row wins.
                keep_new = (entered_at or "") >= (prev.get("entered_at") or "")
                m.error("actuals", rn,
                        f"'{mid}' week of {monday.isoformat()} entered twice (rows {prev['row']} and "
                        f"{rn}); using row {rn if keep_new else prev['row']}", "warning")
                if not keep_new:
                    continue
            m.actuals[key] = {"value": val, "week_of": monday, "entered_by": r.get("entered_by", ""),
                              "entered_at": entered_at, "note": r.get("note", ""), "row": rn}
    return m
