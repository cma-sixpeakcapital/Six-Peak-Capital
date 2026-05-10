from functools import wraps
from typing import Any, Callable

from flask import Flask, abort, current_app, jsonify, render_template, request

from .ingest import IngestService
from .readai import ReadAIClient
from .storage import bullet_split
from .summarizer import Summarizer


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
        doc = storage.load_doc()
        latest = storage.latest_meeting()
        history = storage.list_meetings(limit=12)
        summary_bullets = bullet_split(latest.get("summary", "")) if latest else []
        return render_template(
            "portal.html",
            goals=doc.get("goals", []),
            todos=doc.get("todos", []),
            latest=latest,
            summary_bullets=summary_bullets,
            history=history,
        )

    @app.route("/meetings/<meeting_id>")
    def meeting_detail(meeting_id: str) -> Any:
        meeting = _get_storage().get_meeting(meeting_id)
        if not meeting:
            abort(404)
        summary_bullets = bullet_split(meeting.get("summary", ""))
        return render_template("meeting.html", meeting=meeting, summary_bullets=summary_bullets)

    # --- Read endpoints ---

    @app.route("/api/meetings")
    def api_meetings() -> Any:
        return jsonify({"meetings": _get_storage().list_meetings(limit=20)})

    @app.route("/api/meetings/<meeting_id>")
    def api_meeting(meeting_id: str) -> Any:
        meeting = _get_storage().get_meeting(meeting_id)
        if not meeting:
            abort(404)
        return jsonify(meeting)

    @app.route("/api/goals")
    def api_goals_list() -> Any:
        return jsonify({"goals": _get_storage().list_goals()})

    @app.route("/api/todos")
    def api_todos_list() -> Any:
        return jsonify({"todos": _get_storage().list_todos()})

    # --- Goals UX writes (no API key, internal portal) ---

    @app.route("/api/goals", methods=["PUT"])
    def api_goals_replace() -> Any:
        body = request.get_json(silent=True) or {}
        goals = body.get("goals")
        if not isinstance(goals, list):
            abort(400, description="body must include 'goals' as a list")
        try:
            data = _get_storage().set_goals(goals)
        except ValueError as exc:
            abort(400, description=str(exc))
        return jsonify(data)

    @app.route("/api/goals/add", methods=["POST"])
    def api_goal_add() -> Any:
        body = request.get_json(silent=True) or {}
        title = (body.get("title") or "").strip()
        if not title:
            abort(400, description="'title' is required")
        goal = _get_storage().add_goal({
            "title": title,
            "notes": (body.get("notes") or "").strip(),
            "due": (body.get("due") or "").strip(),
            "link": (body.get("link") or "").strip(),
        })
        return jsonify(goal)

    @app.route("/api/goals/<goal_id>/toggle", methods=["POST"])
    def api_goal_toggle(goal_id: str) -> Any:
        goal = _get_storage().toggle_goal(goal_id)
        if goal is None:
            abort(404)
        return jsonify(goal)

    @app.route("/api/goals/<goal_id>/move", methods=["POST"])
    def api_goal_move(goal_id: str) -> Any:
        todo = _get_storage().move_goal_to_todos(goal_id)
        if todo is None:
            abort(404)
        return jsonify(todo)

    @app.route("/api/goals/<goal_id>", methods=["PATCH"])
    def api_goal_update(goal_id: str) -> Any:
        body = request.get_json(silent=True) or {}
        goal = _get_storage().update_goal(goal_id, body)
        if goal is None:
            abort(404)
        return jsonify(goal)

    @app.route("/api/goals/<goal_id>", methods=["DELETE"])
    def api_goal_delete(goal_id: str) -> Any:
        if not _get_storage().delete_goal(goal_id):
            abort(404)
        return jsonify({"status": "deleted", "id": goal_id})

    # --- Todos UX writes ---

    @app.route("/api/todos", methods=["POST"])
    def api_todo_add() -> Any:
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

    # --- Action items inside the latest meeting ---

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

    # --- External webhooks (still require API key) ---

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
        from .jobs.send_followups import run
        cfg = current_app.config["APP_CONFIG"]
        storage = _get_storage()
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
