"""Host-based WSGI router for the consolidated Six Peak portals.

All four meeting portals plus the apex hub run in ONE gunicorn process (the
``sixpeakapps`` Render service) so they're always-on under a single paid
instance. Requests are dispatched by HTTP ``Host`` header, so every portal
keeps its own subdomain and behaves exactly as it did when each ran as its own
service.

Two problems this solves:

1. Module-name collisions — every portal backend has its own ``app`` package
   and identically named modules. We import each under its unique namespaced
   path (``finance_portal.backend.app`` etc.) so Python's module cache never
   collapses them onto one another.

2. Env-var collisions — the portals read the SAME env names (APP_SECRET_KEY,
   PORTAL_API_KEY, DATABASE_URL, ...). In one process they share ``os.environ``,
   so each portal is built from a per-portal ``Config`` that reads PREFIXED env
   vars (FINANCE_*, IC_*, LVEXEC_*, L10_*) with a fallback to the bare name.
   See each portal's ``app/config.py`` ``Config.from_env(prefix=...)``.

Werkzeug's DispatcherMiddleware keys on URL *path* prefix, not host, so it can't
do subdomain routing — hence the explicit host-dispatch callable below.
"""

from sixpeakapps.app import app as hub_app

from finance_portal.backend.app import create_app as _finance_create_app
from finance_portal.backend.app.config import Config as FinanceConfig
from ic_portal.backend.app import create_app as _ic_create_app
from ic_portal.backend.app.config import Config as ICConfig
from lv_exec_portal.backend.app import create_app as _lvexec_create_app
from lv_exec_portal.backend.app.config import Config as LVExecConfig
from work_portal.backend.app import create_app as _l10_create_app
from work_portal.backend.app.config import Config as L10Config

# Build each portal once, from its own prefixed Config, so secrets/DB stay
# isolated. With gunicorn --preload this runs a single time before forking.
finance_app = _finance_create_app(FinanceConfig.from_env("FINANCE_"))
ic_app = _ic_create_app(ICConfig.from_env("IC_"))
lvexec_app = _lvexec_create_app(LVExecConfig.from_env("LVEXEC_"))
l10_app = _l10_create_app(L10Config.from_env("L10_"))

# Host header -> portal WSGI app. Apex (sixpeakapps.com) and any unmapped host
# fall through to the hub.
HOSTS = {
    "finance.sixpeakapps.com": finance_app,
    "ic.sixpeakapps.com": ic_app,
    "lvexec.sixpeakapps.com": lvexec_app,
    "l10.sixpeakapps.com": l10_app,
}


def app(environ, start_response):
    host = environ.get("HTTP_HOST", "").split(":")[0].lower()
    target = HOSTS.get(host, hub_app)
    return target(environ, start_response)
