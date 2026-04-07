# Server

Flask-SocketIO server for real-time PvP. Located in `src/grid_tactics/server/`.

## Components
- `room_manager.py` — code-based room creation/join, session tokens
- `game_session.py` — wraps the [[Game Engine (Python)]]
- `events.py` — Socket.IO event handlers (`create_room`, `join_room`, `submit_action`, `join_as_spectator`, `chat`)
- `view_filter.py` — see [[View Filter]]
- `static/` — frontend ([[Frontend]])

## Entry
- `pvp_server.py`

## Phases
- [[../Phases/v1.1/Phase 11 Server Foundation Room System]]
- [[../Phases/v1.1/Phase 12 State Serialization Game Flow]]
