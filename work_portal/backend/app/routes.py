from functools import wraps
from typing import Any, Callable

from flask import Flask, abort, current_app, jsonify, render_template, request

from datetime import date, datetime

from .audit import actor_name, register_audit
from .ingest import IngestService, ensure_topics
from .readai import ReadAIClient
from .rock_files import FileArchivedError, FileValidationError
from .scoring import scoreboard as build_scoreboard, current_quarter, quarters as list_quarters
from .storage import bullet_split
from .summarizer import Summarizer, clean_topics
from .scorecard.service import ET, ScorecardService
from .scorecard.sheet import SheetFetchError, make_fetcher, parse_gids


def _group_by_category(rocks_data: dict[str, Any]) -> list[dict[str, Any]]:
    team_names = [p["name"] for p in rocks_data.get("team", [])]
    rocks_map: dict[str, list[dict[str, Any]]] = rocks_data.get("rocks", {}) or {}
    for owner in rocks_map:
        if owner not in team_names:
            team_names.append(owner)

    category_order: list[str] = []
    owner_order: dict[str, list[str]] = {}
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for owner in team_names:
        for rock in rocks_map.get(owner, []):
            category = rock.get("category") or "Uncategorized"
            if category not in grouped:
                grouped[category] = {}
                category_order.append(category)
                owner_order[category] = []
            if owner not in grouped[category]:
                grouped[category][owner] = []
                owner_order[category].append(owner)
            grouped[category][owner].append(rock)

    return [
        {
            "name": cat,
            "owners": [
                {"name": owner, "rocks": grouped[cat][owner]}
                for owner in owner_order[cat]
            ],
        }
        for cat in category_order
    ]


_PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}


def _group_active_by_owner(rocks_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Active (non-archived, non-deferred) individual rocks grouped by owner.

    EOS-standard grouping for the Q3 set: one card per person, owners
    alphabetical, each person's rocks ordered High→Medium→Low then by due.
    Each group also carries ``company_rocks`` — the active company rocks this
    person owns — so their card can show a checkable reference to the shared
    Company Rock they're accountable for (details stay in the Company section).
    """
    rocks_map: dict[str, list[dict[str, Any]]] = rocks_data.get("rocks", {}) or {}

    # Active company rocks indexed by their (individual) owner.
    company_by_owner: dict[str, list[dict[str, Any]]] = {}
    for r in rocks_data.get("company_rocks", []) or []:
        if r.get("archived") or r.get("deferred"):
            continue
        owner = r.get("owner") or ""
        if owner:
            company_by_owner.setdefault(owner, []).append(r)

    active_by_owner: dict[str, list[dict[str, Any]]] = {}
    for owner, rocks in rocks_map.items():
        active = [r for r in rocks if not r.get("archived") and not r.get("deferred")]
        if active:
            active_by_owner[owner] = active

    # A card appears for anyone with active individual rocks OR who owns a
    # company rock (so an accountable owner is never missing a card).
    owner_names = set(active_by_owner) | set(company_by_owner)
    groups: list[dict[str, Any]] = []
    for owner in sorted(owner_names, key=lambda s: s.lower()):
        active = active_by_owner.get(owner, [])
        active.sort(key=lambda r: (_PRIORITY_RANK.get(r.get("priority"), 9),
                                   str(r.get("due") or "")))
        groups.append({
            "name": owner,
            "rocks": active,
            "company_rocks": company_by_owner.get(owner, []),
        })
    return groups


def _split_company_rocks(rocks_data: dict[str, Any]) -> tuple[list, list]:
    """Return (active_company_rocks, deferred_company_rocks), archived excluded.

    Active company rocks are ordered by force-rank (Q4+), then by insertion.
    """
    active, deferred = [], []
    for r in rocks_data.get("company_rocks", []) or []:
        if r.get("archived"):
            continue
        (deferred if r.get("deferred") else active).append(r)
    active.sort(key=lambda r: (r.get("rank") is None, r.get("rank") or 0))
    return active, deferred


def _quarter_view(rocks_data: dict[str, Any], qid: str) -> dict[str, Any]:
    """Read-only view of one archived quarter: company rocks + individual by owner."""
    company = [r for r in (rocks_data.get("company_rocks") or []) if r.get("quarter") == qid]
    company.sort(key=lambda r: (r.get("rank") is None, r.get("rank") or 0))
    by_owner: dict[str, list] = {}
    for owner, rocks in (rocks_data.get("rocks", {}) or {}).items():
        for r in rocks:
            if r.get("quarter") == qid and not r.get("converted"):
                by_owner.setdefault(r.get("owner") or owner, []).append(r)
    groups = [{"name": o, "rocks": rs} for o, rs in sorted(by_owner.items(), key=lambda kv: kv[0].lower())]
    return {"id": qid, "company_rocks": company, "owner_groups": groups}


def _kpis(rocks_data: dict[str, Any], latest: dict[str, Any] | None) -> dict[str, Any]:
    """Server-side KPI band (the old template counted DOM nodes client-side)."""
    active = [r for r in (rocks_data.get("company_rocks") or [])
              if not r.get("archived") and not r.get("deferred")]
    owners = set()
    for owner, rocks in (rocks_data.get("rocks", {}) or {}).items():
        for r in rocks:
            if not r.get("archived") and not r.get("deferred"):
                active.append(r)
                owners.add(r.get("owner") or owner)
    for r in rocks_data.get("company_rocks") or []:
        if not r.get("archived") and not r.get("deferred") and r.get("owner"):
            owners.add(r["owner"])
    done = len([r for r in active if r.get("status") == "complete"])
    todos = rocks_data.get("todos") or []
    todos_open = len([t for t in todos if not t.get("completed")])
    actions = (latest or {}).get("action_items") or []
    actions_done = len([a for a in actions if a.get("completed")])
    return {
        "rocks_total": len(active), "rocks_done": done,
        "rocks_pct": round(100 * done / len(active)) if active else 0,
        "actions_total": len(actions), "actions_done": actions_done,
        "actions_pct": round(100 * actions_done / len(actions)) if actions else 100,
        "todos_open": todos_open, "todos_total": len(todos),
        "todos_pct": round(100 * todos_open / len(todos)) if todos else 0,
        "owners": len(owners),
    }


def _collect_archive(rocks_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Archived old rocks for the 'Past quarters' section (converted excluded).

    Converted rocks live on as active to-dos, so they're retained in the doc
    but not surfaced here. Returns flat {owner, title, status, quarter} dicts.
    """
    out: list[dict[str, Any]] = []
    for r in rocks_data.get("company_rocks", []) or []:
        if r.get("archived") and not r.get("converted"):
            out.append({"owner": "Company", "title": r.get("title", ""),
                        "status": r.get("status"), "quarter": r.get("quarter", ""),
                        "result": r.get("result"), "files": r.get("files") or []})
    for owner, rocks in (rocks_data.get("rocks", {}) or {}).items():
        for r in rocks:
            if r.get("archived") and not r.get("converted"):
                out.append({"owner": owner, "title": r.get("title", ""),
                            "status": r.get("status"), "quarter": r.get("quarter", ""),
                            "result": r.get("result"), "files": r.get("files") or []})
    out.sort(key=lambda a: (a["quarter"], a["owner"].lower(), a["title"].lower()))
    return out


def _actor_names(rocks_data: dict[str, Any]) -> list[str]:
    """Names offered in the "You are" picker: the roster on the rocks document."""
    names = [p.get("name") for p in rocks_data.get("team", []) or [] if p.get("name")]
    for owner in (rocks_data.get("rocks") or {}):
        if owner not in names:
            names.append(owner)
    return sorted(set(names), key=str.lower)


def _get_storage():
    return current_app.config["STORAGE"]


def _get_ingest_service() -> IngestService:
    cfg = current_app.config["APP_CONFIG"]
    storage = _get_storage()
    summarizer = current_app.config.get("SUMMARIZER") or Summarizer(
        api_key=cfg.anthropic_api_key, model=cfg.summarizer_model
    )
    readai_client = current_app.config.get("READAI_CLIENT")
    if readai_client is None and cfg.readai_api_key:
        readai_client = ReadAIClient(api_key=cfg.readai_api_key, base_url=cfg.readai_base_url)
    return IngestService(
        storage=storage,
        summarizer=summarizer,
        readai=readai_client,
        title_pattern=cfg.ingest_title_pattern,
    )


def _get_scorecard_service() -> ScorecardService:
    cfg = current_app.config["APP_CONFIG"]
    fetcher = current_app.config.get("SCORECARD_FETCHER")
    if fetcher is None and cfg.sheet_pub_url:
        fetcher = make_fetcher(cfg.sheet_pub_url, parse_gids(cfg.sheet_gids))
    try:
        start = date.fromisoformat(cfg.scorecard_start_week)
    except ValueError:
        start = date(2026, 9, 28)
    return ScorecardService(
        storage=_get_storage(), fetcher=fetcher, start_week=start,
        now_fn=current_app.config.get("SCORECARD_NOW"),
    )


def _scorecard_or_error() -> dict[str, Any]:
    """The Scorecard must never take the page down."""
    try:
        return _get_scorecard_service().current()
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.exception("scorecard failed")
        return {"available": False, "fetch_error": f"{type(exc).__name__}: {exc}"}


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


def _with_topics(meeting: dict[str, Any] | None) -> dict[str, Any] | None:
    """Make sure the meeting summary is grouped by topic (one Claude call per
    meeting, then stored). Never breaks the page: on any failure the plain
    bullet list is shown instead."""
    if not meeting or meeting.get("topics") or meeting.get("topics_error"):
        return meeting
    cfg = current_app.config["APP_CONFIG"]
    summarizer = current_app.config.get("SUMMARIZER")
    if summarizer is None:
        if not cfg.anthropic_api_key:
            return meeting
        summarizer = Summarizer(api_key=cfg.anthropic_api_key, model=cfg.summarizer_model)
    try:
        if ensure_topics(meeting, summarizer):
            _get_storage().save_meeting(meeting)
    except Exception:  # pragma: no cover - defensive
        current_app.logger.exception("topic grouping failed")
    return meeting


def _truthy(value: Any) -> bool:
    """Parse a query-string flag like ?preview=true into a bool."""
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def require_api_key(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        expected = current_app.config["APP_CONFIG"].api_key
        if not expected:
            abort(503, description="PORTAL_API_KEY not configured")
        provided = request.headers.get("X-API-Key") or request.args.get("api_key")
        if provided != expected:
            abort(401, description="invalid or missing API key")
        return fn(*args, **kwargs)

    return wrapper


def register_routes(app: Flask) -> None:
    register_audit(app, _get_storage)

    @app.route("/health")
    def health() -> Any:
        return {"status": "ok"}

    @app.route("/")
    def portal() -> Any:
        storage = _get_storage()
        rocks_data = storage.load_rocks()
        latest = _with_topics(storage.latest_meeting())
        history = storage.list_meetings(limit=12)
        summary_bullets = bullet_split(latest.get("summary", "")) if latest else []
        company_active, company_deferred = _split_company_rocks(rocks_data)
        sb = build_scoreboard(rocks_data)
        cur_q = current_quarter(rocks_data)
        scored_ids = {q["quarter"] for q in sb["quarters"] if q["closed"]}
        closed_qs = [q for q in list_quarters(rocks_data) if q.get("closed") and q["id"] in scored_ids]
        closed_qs.reverse()  # newest first; pre-EOS quarters (Q2) stay in the "Earlier" list
        return render_template(
            "portal.html",
            team=rocks_data.get("team", []),
            rocks=rocks_data.get("rocks", {}),
            company_rocks=company_active,
            company_deferred=company_deferred,
            owner_groups=_group_active_by_owner(rocks_data),
            archived_rocks=_collect_archive(rocks_data),
            todos=rocks_data.get("todos", []),
            latest=latest,
            summary_bullets=summary_bullets,
            history=history,
            kpis=_kpis(rocks_data, latest),
            scoreboard=sb,
            current_quarter=cur_q,
            closed_quarters=closed_qs,
            quarter_views=[_quarter_view(rocks_data, q["id"]) for q in closed_qs],
            parked_issues=rocks_data.get("parked_issues") or [],
            scorecard=_scorecard_or_error(),
            sheet_edit_url=current_app.config["APP_CONFIG"].sheet_edit_url,
            actor_names=_actor_names(rocks_data),
        )

    @app.route("/api/scorecard")
    def api_scorecard() -> Any:
        return jsonify(_jsonable(_scorecard_or_error()))

    @app.route("/api/scorecard/refresh", methods=["POST"])
    def api_scorecard_refresh() -> Any:
        try:
            meta = _get_scorecard_service().refresh(actor_name())
        except SheetFetchError as exc:
            abort(502, description=f"Could not read the Sheet: {exc}")
        return jsonify({"status": "ok", "snapshot": meta})

    @app.route("/api/jobs/ingest_scorecard", methods=["POST"])
    @require_api_key
    def api_ingest_scorecard() -> Any:
        """Tuesday meeting freeze (kind=meeting, default) or an on-demand pull
        (kind=manual). Called hourly by the GitHub Action; the freeze acts once,
        on Tuesday at/after 8:00 a.m. ET. ?force=true freezes now."""
        svc = _get_scorecard_service()
        kind = (request.args.get("kind") or "meeting").strip()
        try:
            if kind == "meeting":
                result = svc.freeze(force=_truthy(request.args.get("force")))
            else:
                result = {"status": "fetched", "snapshot": svc.refresh("api")}
        except SheetFetchError as exc:
            abort(502, description=f"Could not read the Sheet: {exc}")
        return jsonify(result)

    @app.route("/changes")
    def changes_page() -> Any:
        args = request.args
        since = (args.get("since") or "").strip()
        until = (args.get("until") or "").strip()
        rows = _get_storage().list_audit(
            limit=int(args.get("limit") or 300),
            actor=(args.get("actor") or "").strip() or None,
            text=(args.get("item") or "").strip() or None,
            since=since or None,
            until=(until + "T23:59:59") if until and "T" not in until else (until or None),
        )
        for r in rows:
            try:
                at = datetime.fromisoformat(r["at"]).astimezone(ET)
                r["at_display"] = at.strftime("%a %b ") + str(at.day) + at.strftime(", %I:%M %p").replace(" 0", " ")
            except (ValueError, TypeError):
                r["at_display"] = r.get("at", "")
        history = _get_storage().list_rocks_history(limit=10)
        return render_template("changes.html", rows=rows, args=args, history=history)

    @app.route("/api/changes")
    def api_changes() -> Any:
        return jsonify({"changes": _get_storage().list_audit(limit=int(request.args.get("limit") or 100))})

    @app.route("/meetings/<meeting_id>")
    def meeting_detail(meeting_id: str) -> Any:
        storage = _get_storage()
        meeting = _with_topics(storage.get_meeting(meeting_id))
        if not meeting:
            abort(404)
        summary_bullets = bullet_split(meeting.get("summary", ""))
        return render_template("meeting.html", meeting=meeting, summary_bullets=summary_bullets)

    @app.route("/api/meetings/<meeting_id>/topics", methods=["PUT"])
    def api_meeting_set_topics(meeting_id: str) -> Any:
        """Store a topic grouping produced outside the portal (the weekly
        scheduled Claude task; there is no Anthropic key on the server).
        Open like every other edit, and recorded in the change log."""
        storage = _get_storage()
        meeting = storage.get_meeting(meeting_id)
        if not meeting:
            abort(404)
        body = request.get_json(silent=True) or {}
        topics = clean_topics(body.get("topics"))
        if not topics:
            abort(400, description="'topics' must be a list of {topic, notes[]} with at least one note")
        meeting["topics"] = topics
        meeting.pop("topics_error", None)
        meeting["topics_source"] = (body.get("source") or "external")[:60]
        storage.save_meeting(meeting)
        return jsonify({"status": "ok", "id": meeting_id, "topics": topics})

    @app.route("/api/meetings/<meeting_id>/topics", methods=["POST"])
    @require_api_key
    def api_meeting_regroup(meeting_id: str) -> Any:
        """Re-run the topic grouping for one meeting (clears the stored result)."""
        storage = _get_storage()
        meeting = storage.get_meeting(meeting_id)
        if not meeting:
            abort(404)
        meeting.pop("topics", None)
        meeting.pop("topics_error", None)
        meeting = _with_topics(meeting)
        return jsonify({"topics": meeting.get("topics") or [], "error": meeting.get("topics_error")})

    @app.route("/api/meetings")
    def api_meetings() -> Any:
        return jsonify({"meetings": _get_storage().list_meetings(limit=20)})

    @app.route("/api/meetings/<meeting_id>")
    def api_meeting(meeting_id: str) -> Any:
        meeting = _get_storage().get_meeting(meeting_id)
        if not meeting:
            abort(404)
        return jsonify(meeting)

    @app.route("/api/rocks")
    def api_rocks() -> Any:
        return jsonify(_get_storage().load_rocks())

    @app.route("/api/scoreboard")
    def api_scoreboard() -> Any:
        return jsonify(build_scoreboard(_get_storage().load_rocks()))

    @app.route("/api/quarters")
    def api_quarters() -> Any:
        data = _get_storage().load_rocks()
        return jsonify({"quarters": list_quarters(data), "current": current_quarter(data),
                        "parked_issues": data.get("parked_issues") or []})

    @app.route("/api/rocks/<person>", methods=["PUT"])
    def api_update_rocks(person: str) -> Any:
        body = request.get_json(silent=True) or {}
        rocks = body.get("rocks")
        if not isinstance(rocks, list):
            abort(400, description="body must include 'rocks' as a list")
        try:
            data = _get_storage().set_person_rocks(person, rocks)
        except ValueError as exc:
            abort(400, description=str(exc))
        return jsonify(data)

    @app.route("/api/rocks/<rock_id>/toggle", methods=["POST"])
    def api_toggle_rock(rock_id: str) -> Any:
        rock = _get_storage().toggle_rock(rock_id)
        if rock is None:
            abort(404, description="rock not found")
        return jsonify(rock)

    @app.route("/api/rocks/<rock_id>", methods=["PATCH"])
    def api_rock_update(rock_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        try:
            rock = _get_storage().update_rock(rock_id, body)
        except ValueError as exc:
            abort(400, description=str(exc))
        if rock is None:
            abort(404)
        return jsonify(rock)

    @app.route("/api/rocks/<rock_id>", methods=["DELETE"])
    def api_rock_delete(rock_id: str) -> Any:
        if not _get_storage().delete_rock(rock_id):
            abort(404)
        return jsonify({"status": "deleted", "id": rock_id})

    @app.route("/api/rocks/<rock_id>/move", methods=["POST"])
    def api_rock_move(rock_id: str) -> Any:
        todo = _get_storage().move_rock_to_todos(rock_id)
        if todo is None:
            abort(404)
        return jsonify(todo)

    @app.route("/api/rocks/<rock_id>/files", methods=["POST"])
    def api_rock_file_add(rock_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        try:
            entry = _get_storage().add_rock_file(
                rock_id, body.get("url", ""), body.get("label"), body.get("added_by"),
            )
        except FileArchivedError as exc:
            abort(403, description=str(exc))
        except FileValidationError as exc:
            abort(400, description=str(exc))
        if entry is None:
            abort(404, description="rock not found")
        return jsonify(entry)

    @app.route("/api/rocks/<rock_id>/files/<file_id>", methods=["PATCH"])
    def api_rock_file_update(rock_id: str, file_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        try:
            entry = _get_storage().update_rock_file(
                rock_id, file_id, body.get("url"), body.get("label"),
            )
        except FileArchivedError as exc:
            abort(403, description=str(exc))
        except FileValidationError as exc:
            abort(400, description=str(exc))
        if entry is None:
            abort(404, description="rock or file not found")
        return jsonify(entry)

    @app.route("/api/rocks/<rock_id>/files/<file_id>", methods=["DELETE"])
    def api_rock_file_delete(rock_id: str, file_id: str) -> Any:
        try:
            removed = _get_storage().remove_rock_file(rock_id, file_id)
        except FileArchivedError as exc:
            abort(403, description=str(exc))
        if not removed:
            abort(404, description="rock or file not found")
        return jsonify({"status": "deleted", "id": file_id})

    @app.route("/api/rocks/<person>/add", methods=["POST"])
    def api_rock_add(person: str) -> Any:
        body = request.get_json(silent=True) or {}
        title = (body.get("title") or "").strip()
        if not title:
            abort(400, description="'title' is required")
        rock = _get_storage().add_person_rock(person, {
            "title": title,
            "notes": (body.get("notes") or "").strip(),
            "due": (body.get("due") or "").strip(),
            "category": (body.get("category") or "").strip(),
        })
        return jsonify(rock)

    @app.route("/api/company_rocks", methods=["PUT"])
    def api_update_company_rocks() -> Any:
        body = request.get_json(silent=True) or {}
        rocks = body.get("rocks")
        if not isinstance(rocks, list):
            abort(400, description="body must include 'rocks' as a list")
        try:
            data = _get_storage().set_company_rocks(rocks)
        except ValueError as exc:
            abort(400, description=str(exc))
        return jsonify(data)

    @app.route("/api/company_rocks/add", methods=["POST"])
    def api_company_rock_add() -> Any:
        body = request.get_json(silent=True) or {}
        title = (body.get("title") or "").strip()
        if not title:
            abort(400, description="'title' is required")
        rock = _get_storage().add_company_rock({
            "title": title,
            "notes": (body.get("notes") or "").strip(),
            "due": (body.get("due") or "").strip(),
        })
        return jsonify(rock)

    @app.route("/api/todos")
    def api_todos() -> Any:
        return jsonify({"todos": _get_storage().list_todos()})

    @app.route("/api/todos", methods=["POST"])
    def api_todos_add() -> Any:
        body = request.get_json(silent=True) or {}
        task = (body.get("task") or "").strip()
        if not task:
            abort(400, description="'task' is required")
        todo = _get_storage().add_todo({
            "owner": (body.get("owner") or "").strip(),
            "task": task,
            "due": (body.get("due") or "").strip(),
        })
        return jsonify(todo)

    @app.route("/api/todos/<todo_id>", methods=["PATCH"])
    def api_todo_update(todo_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        todo = _get_storage().update_todo(todo_id, body)
        if todo is None:
            abort(404)
        return jsonify(todo)

    @app.route("/api/todos/<todo_id>/toggle", methods=["POST"])
    def api_todo_toggle(todo_id: str) -> Any:
        todo = _get_storage().toggle_todo(todo_id)
        if todo is None:
            abort(404)
        return jsonify(todo)

    @app.route("/api/todos/<todo_id>", methods=["DELETE"])
    def api_todo_delete(todo_id: str) -> Any:
        if not _get_storage().delete_todo(todo_id):
            abort(404)
        return jsonify({"status": "deleted", "id": todo_id})

    @app.route("/api/action/<meeting_id>/<action_id>/toggle", methods=["POST"])
    def api_action_toggle(meeting_id: str, action_id: str) -> Any:
        item = _get_storage().toggle_action_item(meeting_id, action_id)
        if item is None:
            abort(404)
        return jsonify(item)

    @app.route("/api/action/<meeting_id>/<action_id>/move", methods=["POST"])
    def api_action_move(meeting_id: str, action_id: str) -> Any:
        todo = _get_storage().move_action_item_to_todos(meeting_id, action_id)
        if todo is None:
            abort(404)
        return jsonify(todo)

    @app.route("/api/ingest/readai", methods=["POST"])
    @require_api_key
    def api_ingest_readai() -> Any:
        payload = request.get_json(silent=True) or {}
        result = _get_ingest_service().ingest_webhook(payload)
        if isinstance(result, dict) and result.get("status") == "ignored":
            return jsonify({"status": "ignored", "reason": result.get("reason", "")})
        return jsonify({"status": "ok", "meeting": result})

    @app.route("/api/refresh", methods=["POST"])
    @require_api_key
    def api_refresh() -> Any:
        service = _get_ingest_service()
        if service.readai is None:
            abort(503, description="Read.ai client not configured")
        saved = service.refresh_from_readai()
        return jsonify({"status": "ok", "ingested": len(saved), "meetings": saved})

    @app.route("/api/jobs/send_followups", methods=["POST"])
    @require_api_key
    def api_send_followups() -> Any:
        # Local import so the rest of the app boots even if google libs
        # aren't installed yet during partial deploys.
        from .jobs.send_followups import run
        cfg = current_app.config["APP_CONFIG"]
        storage = _get_storage()
        # Allow overriding dry_run via query param for ad-hoc testing
        # (e.g., curl ...?dry_run=true). Defaults to the configured value.
        dry_param = request.args.get("dry_run")
        if dry_param is not None:
            dry_run = dry_param.strip().lower() in {"1", "true", "yes", "on"}
        else:
            dry_run = cfg.followup_dry_run
        # Non-consuming preview: ?preview=true returns who WOULD receive each
        # due recap without claiming/sending. &include_claimed=true also
        # surfaces in-window meetings already blocked by followup_sent_at.
        preview = _truthy(request.args.get("preview"))
        include_claimed = _truthy(request.args.get("include_claimed"))
        gmail_override = current_app.config.get("FOLLOWUPS_GMAIL_SERVICE")
        cal_override = current_app.config.get("FOLLOWUPS_CALENDAR_SERVICE")
        result = run(
            storage=storage,
            cfg=cfg,
            dry_run=dry_run,
            gmail_service=gmail_override,
            calendar_service=cal_override,
            preview=preview,
            include_claimed=include_claimed,
        )
        return jsonify({"status": "ok", "dry_run": dry_run, "preview": preview, **result})

    @app.route("/api/jobs/send_reminders", methods=["POST"])
    @require_api_key
    def api_send_reminders() -> Any:
        from .jobs.send_reminders import run
        cfg = current_app.config["APP_CONFIG"]
        storage = _get_storage()
        dry_param = request.args.get("dry_run")
        if dry_param is not None:
            dry_run = dry_param.strip().lower() in {"1", "true", "yes", "on"}
        else:
            dry_run = cfg.followup_reminder_dry_run
        preview = _truthy(request.args.get("preview"))
        include_claimed = _truthy(request.args.get("include_claimed"))
        gmail_override = current_app.config.get("FOLLOWUPS_GMAIL_SERVICE")
        cal_override = current_app.config.get("FOLLOWUPS_CALENDAR_SERVICE")
        result = run(
            storage=storage,
            cfg=cfg,
            dry_run=dry_run,
            gmail_service=gmail_override,
            calendar_service=cal_override,
            preview=preview,
            include_claimed=include_claimed,
        )
        return jsonify({"status": "ok", "dry_run": dry_run, "preview": preview, **result})
