from functools import wraps
from typing import Any, Callable

from flask import Flask, abort, current_app, jsonify, render_template, request

from .ingest import IngestService
from .readai import ReadAIClient
from .storage import Storage
from .summarizer import Summarizer


def _group_by_category(rocks_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pivot rocks into [{name, owners: [{name, rocks}]}] ordered by team order."""
    team_names = [p["name"] for p in rocks_data.get("team", [])]
    rocks_map: dict[str, list[dict[str, Any]]] = rocks_data.get("rocks", {}) or {}
    # Include any owner present in rocks_map but missing from team (edge case)
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


def _get_storage() -> Storage:
    return Storage(data_dir=current_app.config["APP_CONFIG"].data_dir)


def _get_ingest_service() -> IngestService:
    cfg = current_app.config["APP_CONFIG"]
    storage = _get_storage()
    summarizer = current_app.config.get("SUMMARIZER") or Summarizer(
        api_key=cfg.anthropic_api_key, model=cfg.summarizer_model
    )
    readai_client = current_app.config.get("READAI_CLIENT")
    if readai_client is None and cfg.readai_api_key:
        readai_client = ReadAIClient(api_key=cfg.readai_api_key, base_url=cfg.readai_base_url)
    return IngestService(storage=storage, summarizer=summarizer, readai=readai_client)


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
        return render_template(
            "portal.html",
            team=rocks_data.get("team", []),
            rocks=rocks_data.get("rocks", {}),
            company_rocks=rocks_data.get("company_rocks", []),
            categorized=_group_by_category(rocks_data),
            latest=latest,
            history=history,
        )

    @app.route("/meetings/<meeting_id>")
    def meeting_detail(meeting_id: str) -> Any:
        storage = _get_storage()
        meeting = storage.get_meeting(meeting_id)
        if not meeting:
            abort(404)
        return render_template("meeting.html", meeting=meeting)

    @app.route("/api/meetings")
    def api_meetings() -> Any:
        storage = _get_storage()
        return jsonify({"meetings": storage.list_meetings(limit=20)})

    @app.route("/api/meetings/<meeting_id>")
    def api_meeting(meeting_id: str) -> Any:
        storage = _get_storage()
        meeting = storage.get_meeting(meeting_id)
        if not meeting:
            abort(404)
        return jsonify(meeting)

    @app.route("/api/rocks")
    def api_rocks() -> Any:
        return jsonify(_get_storage().load_rocks())

    @app.route("/api/rocks/<person>", methods=["PUT"])
    @require_api_key
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
    @require_api_key
    def api_toggle_rock(rock_id: str) -> Any:
        rock = _get_storage().toggle_rock(rock_id)
        if rock is None:
            abort(404, description="rock not found")
        return jsonify(rock)

    @app.route("/api/company_rocks", methods=["PUT"])
    @require_api_key
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

    @app.route("/api/ingest/readai", methods=["POST"])
    @require_api_key
    def api_ingest_readai() -> Any:
        payload = request.get_json(silent=True) or {}
        meeting = _get_ingest_service().ingest_webhook(payload)
        return jsonify({"status": "ok", "meeting": meeting})

    @app.route("/api/refresh", methods=["POST"])
    @require_api_key
    def api_refresh() -> Any:
        service = _get_ingest_service()
        if service.readai is None:
            abort(503, description="Read.ai client not configured")
        saved = service.refresh_from_readai()
        return jsonify({"status": "ok", "ingested": len(saved), "meetings": saved})
