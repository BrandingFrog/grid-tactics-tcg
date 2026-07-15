# PvP server

This package hosts the Flask-SocketIO application used by local and Railway PvP play.

- `app.py` creates the Flask application and HTTP routes.
- `events.py` registers socket events and advances multiplayer game flow.
- `room_manager.py` and `game_session.py` own rooms and active sessions.
- `view_filter.py` produces player-safe and spectator-safe state views.
- `preview_ai.py` drives AI and AI-vs-AI preview games.
- `sandbox_session.py` implements the local sandbox mode.
- `debug_log.py` writes bounded local JSONL diagnostics. Rejected actions are
  recorded in `logs/illegal-actions.jsonl`; set `GT_SERVER_LOG_DIR` or
  `GT_ILLEGAL_ACTION_LOG_PATH` to place the file on a persistent server volume.
- `deck_store.py`, `preset_deck.py`, and `auth_discord.py` support accounts and decks.
- `static/` contains the complete browser client.

Server changes should normally include tests under `tests/server/` or `tests/test_pvp_server.py`.
