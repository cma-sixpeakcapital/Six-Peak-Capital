from flask import Flask

from .config import Config
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
    register_routes(app)
    return app
