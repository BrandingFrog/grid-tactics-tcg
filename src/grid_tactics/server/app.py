"""Flask application factory with Socket.IO setup."""
import mimetypes
import os

from flask import Flask, send_from_directory
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

    @app.route("/")
    def index():
        return send_from_directory(static_dir, "game.html")

    register_bug_report(app)

    socketio.init_app(
        app,
        async_mode="threading",
        cors_allowed_origins="*",
    )
    return app
