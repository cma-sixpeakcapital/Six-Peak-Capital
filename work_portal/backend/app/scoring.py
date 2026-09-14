"""Rock scoreboard — pure functions over the ``rocks_doc`` dict.

Rules (Bob's Traction rules, binary):
  * complete = 1; carry_forward / task / killed = 0.
  * Deferred rocks are excluded from the denominator.
  * Rocks converted to to-dos in the pre-EOS Q2 rollover (``converted=true``)
    are excluded; Q2 rocks in general are shown as history, never scored.
  * A company rock is credited to its named ``owner`` (that is how
    "Chris 7 for 7" in Q3 was computed: 2 company + 5 individual).
  * For a CLOSED quarter, the ``result`` field is the record. For the OPEN
    quarter the live ``status`` is used (complete = 1, everything else 0 so far).
  * Only the canonical roster is ranked; joint-owner keys from Q2
    ("Bob Kennedy & Chris Aiello") never appear on the leaderboard.
"""
from __future__ import annotations

from datetime import date
from typing import Any

SCORED_FROM = "Q3 2026"  # first quarter run in EOS format (priority + done-def); Q2 is history

ROSTER = [
    "Bob Kennedy", "Chris Aiello", "Chris Andresen", "Derek Sanders",
    "Grady Lakamp", "Robert Carrega", "Schuyler Dietz", "Tom Taggart",
]

TARGET_PCT = 80  # EOS benchmark for rock completion


def _q_sort_key(qid: str) -> tuple[int, int]:
    """'Q3 2026' -> (2026, 3). Unknown strings sort first."""
    try:
        q, y = qid.split()
        return int(y), int(q[1:])
    except (ValueError, AttributeError):
        return (0, 0)


def quarters(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Registry entries sorted chronologically, synthesised from rock tags if absent."""
    reg = {q.get("id"): dict(q) for q in (data.get("quarters") or []) if q.get("id")}
    for _owner, rock in _iter(data):
        qid = rock.get("quarter")
        if qid and qid not in reg:
            reg[qid] = {"id": qid, "label": qid, "closed": bool(rock.get("archived"))}
    out = sorted(reg.values(), key=lambda q: _q_sort_key(q["id"]))
    return out


def current_quarter(data: dict[str, Any]) -> dict[str, Any] | None:
    open_qs = [q for q in quarters(data) if not q.get("closed")]
    return open_qs[-1] if open_qs else None


def _iter(data: dict[str, Any]):
    for rock in data.get("company_rocks", []) or []:
        yield rock.get("owner") or "", rock
    for owner, rocks in (data.get("rocks", {}) or {}).items():
        for rock in rocks:
            yield rock.get("owner") or owner, rock


def _scorable(rock: dict[str, Any]) -> bool:
    if rock.get("deferred") or rock.get("converted"):
        return False
    if rock.get("result") == "deferred":
        return False
    return True


def _is_hit(rock: dict[str, Any], closed: bool) -> bool:
    if closed and rock.get("result"):
        return rock["result"] == "complete"
    return rock.get("status") == "complete"


def score_quarter(data: dict[str, Any], qid: str) -> dict[str, Any]:
    """Team + per-owner tallies for one quarter."""
    qinfo = next((q for q in quarters(data) if q["id"] == qid), {"id": qid, "closed": False})
    closed = bool(qinfo.get("closed"))
    owners: dict[str, dict[str, Any]] = {}
    company_hit = company_total = ind_hit = ind_total = 0
    results: dict[str, int] = {}
    for owner, rock in _iter(data):
        if rock.get("quarter") != qid or not _scorable(rock):
            continue
        hit = _is_hit(rock, closed)
        is_company = rock.get("level") == "company" or (rock in (data.get("company_rocks") or []))
        if is_company:
            company_total += 1
            company_hit += hit
        else:
            ind_total += 1
            ind_hit += hit
        r = rock.get("result") or ("complete" if hit else "open")
        results[r] = results.get(r, 0) + 1
        o = owners.setdefault(owner, {"owner": owner, "owned": 0, "complete": 0, "rocks": []})
        o["owned"] += 1
        o["complete"] += hit
        o["rocks"].append({"id": rock.get("id"), "title": rock.get("title"), "hit": hit,
                           "level": "company" if is_company else "individual",
                           "result": rock.get("result"), "status": rock.get("status")})
    total = company_total + ind_total
    hits = company_hit + ind_hit
    for o in owners.values():
        o["pct"] = round(100 * o["complete"] / o["owned"]) if o["owned"] else None
    return {
        "quarter": qid, "label": qinfo.get("label", qid), "closed": closed,
        "total": total, "complete": hits, "pct": round(100 * hits / total) if total else None,
        "company_total": company_total, "company_complete": company_hit,
        "company_pct": round(100 * company_hit / company_total) if company_total else None,
        "individual_total": ind_total, "individual_complete": ind_hit,
        "results": results,
        "owners": sorted(owners.values(), key=lambda o: o["owner"].lower()),
        "official": qinfo.get("official_score"),
    }


def scored_quarters(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Quarter scores from SCORED_FROM onward, chronological (open quarter last)."""
    out = []
    for q in quarters(data):
        if _q_sort_key(q["id"]) < _q_sort_key(SCORED_FROM):
            continue
        s = score_quarter(data, q["id"])
        if s["total"] == 0:
            continue
        out.append(s)
    return out


def leaderboard(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per roster member: closed-quarter cumulative + the open quarter in flight."""
    rows = {name: {"owner": name, "cum_owned": 0, "cum_complete": 0, "streak": 0,
                   "quarters": [], "live": None} for name in ROSTER}
    for s in scored_quarters(data):
        by_owner = {o["owner"]: o for o in s["owners"]}
        for name, row in rows.items():
            o = by_owner.get(name)
            if s["closed"]:
                if o:
                    row["cum_owned"] += o["owned"]
                    row["cum_complete"] += o["complete"]
                    row["quarters"].append({"quarter": s["quarter"], "owned": o["owned"],
                                            "complete": o["complete"], "pct": o["pct"]})
                    row["streak"] = row["streak"] + 1 if o["complete"] == o["owned"] else 0
                else:
                    row["quarters"].append({"quarter": s["quarter"], "owned": 0, "complete": 0, "pct": None})
            else:
                row["live"] = ({"quarter": s["quarter"], "owned": o["owned"], "complete": o["complete"],
                                "pct": o["pct"]} if o else
                               {"quarter": s["quarter"], "owned": 0, "complete": 0, "pct": None})
    out = []
    for row in rows.values():
        row["cum_pct"] = (round(100 * row["cum_complete"] / row["cum_owned"])
                          if row["cum_owned"] else None)
        out.append(row)
    # Rank: cumulative % desc (None last), then rocks owned desc, then name.
    out.sort(key=lambda r: (-(r["cum_pct"] if r["cum_pct"] is not None else -1),
                            -r["cum_owned"], r["owner"].lower()))
    for i, r in enumerate(out, start=1):
        r["rank"] = i
    return out


def milestone_strip(qinfo: dict[str, Any] | None, today: date | None = None) -> dict[str, Any] | None:
    """Position of today within the quarter for the 30/60/90 strip."""
    if not qinfo or not qinfo.get("start") or not qinfo.get("end"):
        return None
    today = today or date.today()
    try:
        start = date.fromisoformat(qinfo["start"])
        end = date.fromisoformat(qinfo["end"])
    except ValueError:
        return None
    span = max((end - start).days, 1)
    elapsed = (today - start).days
    pct = max(0, min(100, round(100 * elapsed / span)))
    days_left = max((end - today).days, 0)
    return {"start": start.isoformat(), "end": end.isoformat(), "pct": pct,
            "days_left": days_left, "today": today.isoformat(),
            "marks": [{"label": "30", "pct": 33}, {"label": "60", "pct": 67}, {"label": "90", "pct": 100}]}


def postmortem(data: dict[str, Any], qid: str) -> list[dict[str, Any]]:
    """Rows for the last closed quarter's 'why' table: every non-complete scorable rock."""
    rows = []
    succ_titles = {}
    for _o, rock in _iter(data):
        succ_titles[rock.get("id")] = rock.get("title")
    for owner, rock in _iter(data):
        if rock.get("quarter") != qid or not _scorable(rock):
            continue
        if (rock.get("result") or "") in ("", "complete"):
            continue
        rows.append({
            "owner": owner, "title": rock.get("title"), "result": rock.get("result"),
            "root_cause": rock.get("root_cause", ""), "note": rock.get("result_note", ""),
            "successor": succ_titles.get(rock.get("successor_id")) or rock.get("successor_title", ""),
            "level": rock.get("level") or ("company" if rock in (data.get("company_rocks") or []) else "individual"),
        })
    order = {"carry_forward": 0, "task": 1, "killed": 2}
    rows.sort(key=lambda r: (order.get(r["result"], 9), r["owner"].lower(), r["title"].lower()))
    return rows


def scoreboard(data: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Everything the Scoreboard tab needs, in one dict (also served at /api/scoreboard)."""
    qs = scored_quarters(data)
    cur = current_quarter(data)
    closed = [s for s in qs if s["closed"]]
    last_closed = closed[-1] if closed else None
    live = next((s for s in qs if not s["closed"]), None)
    return {
        "target_pct": TARGET_PCT,
        "quarters": qs,
        "current": cur,
        "live": live,
        "last_closed": last_closed,
        "leaderboard": leaderboard(data),
        "milestones": milestone_strip(cur, today),
        "postmortem": postmortem(data, last_closed["quarter"]) if last_closed else [],
    }
