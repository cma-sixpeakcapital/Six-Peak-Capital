import logging
from datetime import date

from flask import Flask

from .config import Config
from .rock_files import linkify
from .routes import register_routes
from .storage import Storage


def make_storage(cfg: Config):
    """Pick storage backend based on config. Postgres if DATABASE_URL is set."""
    if cfg.database_url:
        from .storage_pg import PostgresStorage
        return PostgresStorage(dsn=cfg.database_url)
    return Storage(data_dir=cfg.data_dir)


def create_app(config: Config | None = None) -> Flask:
    cfg = config or Config.from_env()
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["APP_CONFIG"] = cfg
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["STORAGE"] = make_storage(cfg)
    try:  # dated to-do schema (9/26/2026); idempotent, never blocks startup
        migrate = getattr(app.config["STORAGE"], "migrate_todos", None)
        if migrate:
            migrate()
    except Exception:  # pragma: no cover
        logging.getLogger(__name__).exception("to-do migration failed")
    app.jinja_env.filters["linkify"] = linkify

    @app.context_processor
    def inject_today():
        today = date.today()
        # Format: "Monday, April 20, 2026" (cross-platform — strip zero-pad manually)
        display = today.strftime("%A, %B {day}, %Y").replace("{day}", str(today.day))
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today_et = datetime.now(ZoneInfo("America/New_York")).date()
        return {"today_display": display, "today_iso": today_et.isoformat(),
                "todo_people": []}

    register_routes(app)
    return app
