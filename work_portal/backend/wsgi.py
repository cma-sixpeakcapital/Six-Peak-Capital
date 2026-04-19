import os

from app import create_app

if __name__ == "__main__":
    os.environ.setdefault("PORTAL_API_KEY", "dev-portal-key")
    app = create_app()
    app.run(host="0.0.0.0", port=5001, debug=True)
else:
    app = create_app()
