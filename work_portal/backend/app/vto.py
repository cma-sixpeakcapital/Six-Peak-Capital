"""V/TO and Accountability Chart on the L10 portal.

Off-site to-dos (Bob Kennedy and Chris Aiello, Oct 2026): "link the core values and VTO on the
L10 portal (bottom section) so they are visible weekly" and "add the accountability chart to the
L10 portal for quarterly review at the rocks session". Built 11/1/2026.

Content lives in the rocks document under ``vto`` (history, restore and the change log come for
free) and is seeded from Chris Aiello's 10/16/2026 redline of the 8/31/2026 VTO plus Bob's
off-site session changes to the chart (to-do td_98c4656908). Editing is open, like the rest of
the portal. Items still open on the off-site Issues List are shown as proposed, not adopted.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .scorecard.service import ET

VTO_DOC_URL = "https://docs.google.com/document/d/1iulqyxIFavkfNoukZNAZfGlJqZ0A3FAk6kyREJAmkew/edit"

SEED_VTO: dict[str, Any] = {
    "as_of": "8/31/2026 VTO; Chris Aiello redline 10/16/2026; off-site Day 1 notes (BK)",
    "doc_url": VTO_DOC_URL,
    "core_values": [
        "Radical transparency and alignment",
        "Integrity and doing things the right way",
        "Relationship-first, partnership-driven value creation",
        "Relentless execution, urgency, and accountability",
        "Technology-forward, AI-enabled operating mindset",
        "Entrepreneurial creativity, flexibility, and willingness to pivot",
    ],
    "purpose": ("Build a durable, technology-forward real estate development and construction platform that "
                "solves hard execution problems, creates value for partners, and gives Six Peak a resilient "
                "operating base through market cycles."),
    "niche": ("California development and construction expertise, especially relationship-based, "
              "partnership-level construction and development opportunities where Six Peak / LV can solve "
              "execution, credit, bonding, development, or delivery constraints for entrepreneurial owners "
              "and developers. (Off-site Day 1: \"no-bid\" removed; \"Los Angeles\" broadened to \"California\".)"),
    "say_no_to": [
        "High-politics, high-process opportunities",
        "Speculative pursuits",
        "Competitive hard-bid GC work",
        "Proposed: deals that require developer-level time and effort to win a GC-only fee (final wording to confirm)",
        "Proposed: hard GMP commitments based on incomplete plans (final wording to confirm)",
    ],
    "ten_year_target": ("Approximately five markets, roughly $100MM of annual construction billings per market, "
                        "approximately $25MM of business-level earnings, 80/20 profit mix weighted to GC."),
    "ten_year_date": "Proposed: December 31, 2036 (not settled; whether five markets still holds is on the Issues List, #11)",
    "three_year": {
        "date": "December 31, 2029 (straw man)",
        "items": [
            "Revenue: ~$166MM annual construction billings (working target from Day 1; straw man was ~$147MM) and the matching GC revenue, to confirm",
            "Profit: ~$8.5MM consolidated net income; ~$9.2MM ending cash net of tax distributions (aspirational)",
            "Headcount: about 43 at 11/30/2029 (LV 36: field crew 27 = 12 supers, 8 asst supers, 4 APMs, 3 PMs, plus 9 office/operations; "
            "Six Peak 7); FY 2029 average ~46, peak 47 (field peaks at 31, 15 jobs). From the Target Business Plan, Sept close; "
            "office and HoldCo seats held flat (CMA 11/1)",
            "Measurables: signed backlog, qualified pipeline, months of runway, active-job gross margin; 2029 targets to be calculated offline (Issues List #22)",
            "LV backlog: signed backlog at or above trailing-12-month GC revenue",
            "LIHTC pipeline: GC-only at full fee; no unpaid developer scope",
            "Steyn relationship: operating business self-funding; at least one capital source beyond Steyn's onshore capital",
            "Capital structure: ownership sits with the people who run the business day to day in Los Angeles (Issues List #13)",
            "Direct bonding program in place, independent of Krueger",
            "Core processes documented; LV on one finance operating system",
            "Business development led from inside the LA market; every seat owns a weekly number",
            "Accountability Chart reviewed every quarter; a defined development strategy that supports fundraising",
            "A defined path on acquisitions (out-of-market GCs, Southern California trades) and modular",
        ],
    },
    "marketing": [
        {"label": "Target market", "text": "Proposed: entrepreneurial owners and developers building in California who need a partner to solve execution, credit, bonding, development or delivery constraints, with LV as GC at full fee. BD builds and owns the list. Not final."},
        {"label": "Three uniques", "text": "Proposed, not agreed (Issues List #12): 1) expert-level LA multifamily development experience, land through construction, with an in-house GC; 2) GC with capital markets knowledge and underwriting; 3) expert-level construction execution at LV, elite talent at the top and a deep bench."},
        {"label": "Proven process", "text": "Proposed, not agreed (Issues List #12): LV's Path, ROM from LV's bid library, GMP, buyout, execution."},
        {"label": "Guarantee", "text": "Left open (Issues List #12): candidate is pricing certainty with LV holding its GMP for a stated period; not promised until LV can deliver it."},
    ],
}

SEED_CHART: dict[str, Any] = {
    "as_of": "April 15 chart, Bob's 10/16 draft (HoldCo only; LV seats stay on LV's chart under Grady), with the off-site session changes applied (BK to-do 11/4)",
    "seats": [
        {"seat": "Visionary", "person": "Bob Kennedy",
         "roles": ["Long-term direction and the VTO", "Capital raising and cost of capital", "Closings, legal, and guarantees",
                   "Major outside relationships (MRK, lenders, and partners)", "LV expansion / acquisition (added at the off-site)"],
         "gwc": "Y / Y / Y", "flag": ""},
        {"seat": "Integrator + LV Interface (one consolidated seat)", "person": "Chris Aiello",
         "roles": ["Leadership team execution and accountability", "Parent priorities to LV; LV capacity against the pipeline",
                   "LV oversight; Grady's escalation point", "Pre-con resource approvals", "Bonding and LV capacity strategy"],
         "gwc": "Y / Y / Y",
         "flag": "Concern: capacity. Chris also builds the tools (estimating, CRM, portals). Board portal, Steyn reporting, consolidated P&L and LV board reporting moved to the CFO at the off-site."},
        {"seat": "Business Development", "person": "Tom Taggart",
         "roles": ["Source third-party GC work before bid", "Qualify and track the pipeline in the CRM", "Convert leads to signed contracts",
                   "Own Qualified Pipeline and signed backlog on the scorecard", "Monthly sourcing cadence with three or more providers"],
         "gwc": "Y / Y / Y", "flag": ""},
        {"seat": "Development", "person": "Derek Sanders",
         "roles": ["Entitlements and permits", "City agencies and utilities (LADBS, LAHD, and LADWP)", "Project readiness and design management",
                   "Owner-side construction management and draws (Francis)", "Development budgets and schedules",
                   "Development management consulting (BD assistance)"],
         "gwc": "Y / Y / Y", "flag": "Concern: no repeatable utilities process; the portfolio depends on one city."},
        {"seat": "Developer-in-Residence (Special Situations)", "person": "Schuyler Dietz",
         "roles": ["Small Lots, Big Impacts", "Landowner and partner sourcing", "Fundraising support", "Team logistics and events",
                   "LV Construction sales and marketing (SFD 1-year plan candidate)"],
         "gwc": "Discuss", "flag": "Seat being rewritten per the off-site (Bob). Uplifters is closed; depends on the SLBI outcome."},
        {"seat": "CFO", "person": "Chris Andresen",
         "roles": ["Budget, forecasting, and FP&A", "Cash and liquidity", "Capital sourcing and cost of capital (revolver and Steyn loan)",
                   "Board portal, Steyn reporting, consolidated P&L and the investor narrative, LV board reporting (moved from the Integrator at the off-site); investor and lender reporting (R4 and Citi)",
                   "Accounting, controls, and finance systems (LV finance operating system build)"],
         "gwc": "Y / Y / Y", "flag": ""},
        {"seat": "Accounting (reports to CFO)", "person": "Robert Carrega",
         "roles": ["Monthly close and financial statements", "LV pay apps and payables", "Lien-release tracking", "Finance SOPs and checklists",
                   "Finance and pay-app automation"],
         "gwc": "Y / Y / Y", "flag": "Open: Robert works across HoldCo and LV; a second accounting seat under the CFO is proposed."},
    ],
    "proposed_changes": [
        "Add an accounting seat under the CFO (decision needed)",
        "Name one owner for the LV finance operating system build (decision needed)",
        "Every seat owns one weekly scorecard number (decision needed)",
        "Clarify the Developer-in-Residence seat for FY 2027 (decision needed)",
        "Review the Accountability Chart at every quarterly Rock Session",
    ],
    "reviews": [],   # [{"quarter": "Q4 2026", "at": iso, "by": name}]
}


def _s(v: Any, n: int = 2000) -> str:
    return str(v or "").strip()[:n]


def _lines(v: Any, n: int = 40, each: int = 400) -> list[str]:
    if isinstance(v, str):
        v = v.splitlines()
    return [_s(x, each) for x in (v or []) if _s(x, each)][:n]


def get_doc(data: dict[str, Any]) -> dict[str, Any]:
    doc = data.get("vto")
    if not isinstance(doc, dict):
        doc = {"vto": _copy(SEED_VTO), "chart": _copy(SEED_CHART)}
        data["vto"] = doc
    doc.setdefault("vto", _copy(SEED_VTO))
    doc.setdefault("chart", _copy(SEED_CHART))
    doc["chart"].setdefault("reviews", [])
    return doc


def _copy(x: Any) -> Any:
    import json
    return json.loads(json.dumps(x))


def set_vto(doc: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    v = doc["vto"]
    v["as_of"] = _s(body.get("as_of"), 300) or v.get("as_of", "")
    url = _s(body.get("doc_url"), 500)
    if url and not url.startswith("https://"):
        raise ValueError("doc_url must start with https://")
    v["doc_url"] = url or v.get("doc_url", "")
    v["core_values"] = _lines(body.get("core_values"), 12, 200)
    if not v["core_values"]:
        raise ValueError("at least one core value is required")
    for k in ("purpose", "niche", "ten_year_target", "ten_year_date"):
        v[k] = _s(body.get(k))
    v["say_no_to"] = _lines(body.get("say_no_to"), 12)
    three = body.get("three_year") or {}
    v["three_year"] = {"date": _s(three.get("date"), 200), "items": _lines(three.get("items"), 20)}
    mk = []
    for m in body.get("marketing") or []:
        label, text = _s(m.get("label"), 60), _s(m.get("text"))
        if label:
            mk.append({"label": label, "text": text})
    v["marketing"] = mk[:8]
    return v


def set_chart(doc: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    c = doc["chart"]
    c["as_of"] = _s(body.get("as_of"), 300) or c.get("as_of", "")
    seats = []
    for r in body.get("seats") or []:
        seat = _s(r.get("seat"), 120)
        if not seat:
            continue
        seats.append({"seat": seat, "person": _s(r.get("person"), 80), "roles": _lines(r.get("roles"), 8, 300),
                      "gwc": _s(r.get("gwc"), 40), "flag": _s(r.get("flag"), 400)})
    if not seats:
        raise ValueError("at least one seat is required")
    c["seats"] = seats[:20]
    c["proposed_changes"] = _lines(body.get("proposed_changes"), 15)
    return c


def mark_reviewed(doc: dict[str, Any], by: str, quarter: str) -> dict[str, Any]:
    c = doc["chart"]
    entry = {"quarter": _s(quarter, 20), "at": datetime.now(ET).isoformat(timespec="seconds"), "by": _s(by, 60)}
    c.setdefault("reviews", []).append(entry)
    c["reviews"] = c["reviews"][-12:]
    return entry
