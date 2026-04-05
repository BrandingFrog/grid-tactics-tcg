"""Entry point for the Grid Tactics PvP server.

Usage: python pvp_server.py
"""
from pathlib import Path

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

    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("RAILWAY_ENVIRONMENT") is None  # debug only locally
    print(f"Grid Tactics PvP Server starting on http://0.0.0.0:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=debug)


if __name__ == "__main__":
    main()
