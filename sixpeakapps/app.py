import os

from flask import Flask, redirect, render_template, send_from_directory

app = Flask(__name__)

MAY5_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "may5meeting")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/may5meeting")
def may5meeting_root_redirect():
    # Without the trailing slash, relative URLs in the landing index.html
    # (e.g. href="spc-update/") resolve to /spc-update/ instead of
    # /may5meeting/spc-update/. Force a trailing slash so the deck links work.
    return redirect("/may5meeting/", code=301)


@app.route("/may5meeting/")
def may5meeting():
    return send_from_directory(MAY5_DIR, "index.html")


@app.route("/may5meeting/<path:path>")
def may5meeting_assets(path):
    has_trailing = path.endswith("/")
    clean_path = path.rstrip("/")
    full_path = os.path.join(MAY5_DIR, clean_path)

    # Directory paths must have a trailing slash so relative URLs inside the
    # served index.html resolve correctly (e.g. ../, assets/foo.jpg).
    if os.path.isdir(full_path) and not has_trailing:
        return redirect(f"/may5meeting/{clean_path}/", code=301)

    if os.path.isdir(full_path):
        return send_from_directory(MAY5_DIR, os.path.join(clean_path, "index.html"))

    return send_from_directory(MAY5_DIR, clean_path)


if __name__ == "__main__":
    app.run(debug=True, port=5003)
