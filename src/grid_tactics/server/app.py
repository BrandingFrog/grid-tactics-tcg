"""Flask application factory with Socket.IO setup."""
import mimetypes
import os

from flask import Flask, request, send_from_directory
from flask_socketio import SocketIO

from grid_tactics.server.bug_report import register_bug_report

# Python stdlib's mimetypes table doesn't include image/webp on every
# platform; Flask falls back to application/octet-stream which
# browsers still render correctly via magic-bytes sniffing but breaks
# proper Content-Type headers / caching middleware. Register it once
# at import time.
mimetypes.add_type("image/webp", ".webp")

socketio = SocketIO()


def create_app(testing: bool = False) -> Flask:
    """Create and configure the Flask application.

    Args:
        testing: If True, enables testing mode.

    Returns:
        Configured Flask app with SocketIO initialized.
    """
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app = Flask(__name__, static_folder=static_dir)
    app.config["SECRET_KEY"] = "dev-secret-key"
    app.config["TESTING"] = testing
    # Don't let Flask stamp a long max-age on static files.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    @app.route("/")
    def index():
        return send_from_directory(static_dir, "game.html")

    @app.after_request
    def _revalidate_client_assets(resp):
        # Beta ships often; force browsers to REVALIDATE the client
        # (HTML/CSS/JS) every load so a new deploy shows immediately instead
        # of serving a stale cached game.css/game.js. Flask still sends
        # ETag/Last-Modified, so unchanged files return a cheap 304.
        path = request.path or ""
        if path == "/" or path.endswith((".html", ".css", ".js")):
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

    register_bug_report(app)

    socketio.init_app(
        app,
        async_mode="threading",
        cors_allowed_origins="*",
    )
    return app
