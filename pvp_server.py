"""Entry point for the Grid Tactics PvP server.

Usage: python pvp_server.py
"""
import os
from pathlib import Path

# Rules experiment (user 2026-07-10): the LIVE server runs the manual-draw
# variant by default (no auto-draw, Draw is an action, PASS = +1 mana now,
# Handshake = both draw). Set GT_MANUAL_DRAW=0 in the environment to run
# the 2026-07 standard rules instead. setdefault — an explicit env value
# (e.g. on Railway) always wins.
os.environ.setdefault("GT_MANUAL_DRAW", "1")

from grid_tactics.card_library import CardLibrary
from grid_tactics.server.app import create_app, socketio
from grid_tactics.server.events import register_events
from grid_tactics.server.room_manager import RoomManager


def main():
    import os
    app = create_app()
    library = CardLibrary.from_directory(Path("data/cards"))
    room_manager = RoomManager(library)
    register_events(room_manager)

    # Lobby quick view (testing): live-game snapshots, public info only.
    from flask import jsonify

    @app.route("/api/quickview")
    def quickview():
        return jsonify(room_manager.list_live_games())

    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("RAILWAY_ENVIRONMENT") is None  # debug only locally
    print(f"Grid Tactics PvP Server starting on http://0.0.0.0:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
