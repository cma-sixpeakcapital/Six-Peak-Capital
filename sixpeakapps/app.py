import os

from flask import Flask, render_template, send_from_directory

app = Flask(__name__)

MAY5_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "may5meeting")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/may5meeting")
@app.route("/may5meeting/")
def may5meeting():
    return send_from_directory(MAY5_DIR, "index.html")


@app.route("/may5meeting/<path:path>")
def may5meeting_assets(path):
    # Strip trailing slash so subdirectory requests resolve to their index.html
    clean_path = path.rstrip("/")
    full_path = os.path.join(MAY5_DIR, clean_path)

    # If the resolved path is a directory, serve its index.html
    if os.path.isdir(full_path):
        return send_from_directory(MAY5_DIR, os.path.join(clean_path, "index.html"))

    return send_from_directory(MAY5_DIR, clean_path)


if __name__ == "__main__":
    app.run(debug=True, port=5003)
