from flask import Flask

from .config import Config
from .routes import register_routes


def create_app(config: Config | None = None) -> Flask:
    cfg = config or Config.from_env()
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["APP_CONFIG"] = cfg
    app.config["SECRET_KEY"] = cfg.secret_key
    register_routes(app)
    return app
