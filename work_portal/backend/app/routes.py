from functools import wraps
from typing import Any, Callable

from flask import Flask, abort, current_app, jsonify, render_template, request

from .ingest import IngestService
from .readai import ReadAIClient
from .storage import bullet_split
from .summarizer import Summarizer


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
    @app.route("/health")
    def health() -> Any:
        return {"status": "ok"}

    @app.route("/")
    def portal() -> Any:
        storage = _get_storage()
        rocks_data = storage.load_rocks()
        latest = storage.latest_meeting()
        history = storage.list_meetings(limit=12)
        summary_bullets = bullet_split(latest.get("summary", "")) if latest else []
        return render_template(
            "portal.html",
            team=rocks_data.get("team", []),
            rocks=rocks_data.get("rocks", {}),
            company_rocks=rocks_data.get("company_rocks", []),
            categorized=_group_by_category(rocks_data),
            todos=rocks_data.get("todos", []),
            latest=latest,
            summary_bullets=summary_bullets,
            history=history,
        )

    @app.route("/meetings/<meeting_id>")
    def meeting_detail(meeting_id: str) -> Any:
        storage = _get_storage()
        meeting = storage.get_meeting(meeting_id)
        if not meeting:
            abort(404)
        summary_bullets = bullet_split(meeting.get("summary", ""))
        return render_template("meeting.html", meeting=meeting, summary_bullets=summary_bullets)

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
        rock = _get_storage().update_rock(rock_id, body)
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
        gmail_override = current_app.config.get("FOLLOWUPS_GMAIL_SERVICE")
        cal_override = current_app.config.get("FOLLOWUPS_CALENDAR_SERVICE")
        result = run(
            storage=storage,
            cfg=cfg,
            dry_run=dry_run,
            gmail_service=gmail_override,
            calendar_service=cal_override,
        )
        return jsonify({"status": "ok", "dry_run": dry_run, **result})
