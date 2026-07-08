"""Flask application factory with Socket.IO setup."""
import mimetypes
import os

from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO

from grid_tactics.server import deck_store
from grid_tactics.server.auth_discord import (
    current_user,
    discord_enabled,
    register_auth,
)
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
    # Session cookies (Discord login) are signed with this key — set a real
    # one in prod via env; the dev fallback only matters locally.
    app.config["SECRET_KEY"] = (
        os.environ.get("FLASK_SECRET_KEY", "").strip() or "dev-secret-key"
    )
    app.config["TESTING"] = testing
    # OAuth redirect returns via a top-level GET, so Lax (not Strict) is
    # required for the session cookie to survive the round trip.
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Secure cookie only when served over HTTPS (Railway); off for localhost.
    app.config["SESSION_COOKIE_SECURE"] = (
        os.environ.get("SESSION_COOKIE_SECURE", "").strip() == "1"
    )
    # Don't let Flask stamp a long max-age on static files.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    @app.route("/")
    def index():
        return send_from_directory(static_dir, "game.html")

    register_auth(app)

    @app.route("/api/me")
    def api_me():
        """Client bootstrap: whether login is available + who's logged in."""
        u = current_user()
        return jsonify(
            {
                "login_available": discord_enabled(),
                "cloud_decks": deck_store.available(),
                "logged_in": u is not None,
                "user": u,
            }
        )

    @app.route("/api/decks", methods=["GET"])
    def api_get_decks():
        u = current_user()
        if u is None:
            return jsonify({"decks": [], "logged_in": False})
        return jsonify(
            {"decks": deck_store.get_decks(u["discord_id"]), "logged_in": True}
        )

    @app.route("/api/decks", methods=["PUT"])
    def api_save_deck():
        u = current_user()
        if u is None:
            return jsonify({"ok": False, "error": "not_logged_in"}), 401
        data = request.get_json(silent=True) or {}
        try:
            slot = int(data.get("slot"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "bad_slot"}), 400
        # Ensure the user row exists (FK target) before writing a deck.
        deck_store.upsert_user(u)
        ok = deck_store.save_deck(
            u["discord_id"], slot, data.get("name", ""), data.get("cards", {})
        )
        return jsonify({"ok": ok})

    @app.route("/api/decks/<int:slot>", methods=["DELETE"])
    def api_delete_deck(slot):
        u = current_user()
        if u is None:
            return jsonify({"ok": False, "error": "not_logged_in"}), 401
        return jsonify({"ok": deck_store.delete_deck(u["discord_id"], slot)})

    @app.route("/api/decks/import", methods=["POST"])
    def api_import_decks():
        """First-login migration: upload the browser's local deck slots."""
        u = current_user()
        if u is None:
            return jsonify({"ok": False, "error": "not_logged_in"}), 401
        data = request.get_json(silent=True) or {}
        slots = data.get("slots") or []
        deck_store.upsert_user(u)
        ok = deck_store.replace_all(u["discord_id"], slots)
        return jsonify({"ok": ok, "decks": deck_store.get_decks(u["discord_id"])})

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
