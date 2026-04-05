"""Socket.IO event handlers for PvP room system."""
from flask import request
from flask_socketio import emit, join_room as sio_join_room

from grid_tactics.server.app import socketio
from grid_tactics.server.room_manager import RoomManager

_room_manager: RoomManager | None = None


def register_events(room_manager: RoomManager) -> None:
    """Register all Socket.IO event handlers with the given room manager."""
    global _room_manager
    _room_manager = room_manager

    @socketio.on("create_room")
    def handle_create_room(data):
        display_name = data.get("display_name", "").strip() if data else ""
        if not display_name:
            emit("error", {"msg": "display_name is required"})
            return
        code, token = _room_manager.create_room(display_name, request.sid)
        sio_join_room(code)
        emit("room_created", {
            "room_code": code,
            "session_token": token,
        })

    @socketio.on("join_room")
    def handle_join_room(data):
        display_name = data.get("display_name", "").strip() if data else ""
        room_code = data.get("room_code", "").strip().upper() if data else ""
        if not display_name:
            emit("error", {"msg": "display_name is required"})
            return
        if not room_code:
            emit("error", {"msg": "room_code is required"})
            return
        try:
            token, room = _room_manager.join_room(
                room_code, display_name, request.sid
            )
        except ValueError as e:
            emit("error", {"msg": str(e)})
            return
        sio_join_room(room_code)
        # Emit to joiner
        players = [
            {"name": room.creator.name, "ready": room.creator.ready},
            {"name": display_name, "ready": False},
        ]
        emit("room_joined", {
            "room_code": room_code,
            "players": players,
            "session_token": token,
        })
        # Notify creator
        emit("player_joined", {"display_name": display_name}, to=room.creator.sid)

    @socketio.on("ready")
    def handle_ready(data):
        token = _room_manager.get_token_by_sid(request.sid)
        if token is None:
            emit("error", {"msg": "Not in a room"})
            return
        try:
            room_code, room, both_ready = _room_manager.set_ready(token)
        except ValueError as e:
            emit("error", {"msg": str(e)})
            return
        # Find this player's name for the notification
        if room.creator.token == token:
            player_name = room.creator.name
        elif room.joiner and room.joiner.token == token:
            player_name = room.joiner.name
        else:
            player_name = "Unknown"
        emit("player_ready", {"player_name": player_name}, to=room_code)

        if both_ready:
            session = _room_manager.start_game(room_code)
            state_dict = session.state.to_dict()
            # Emit game_start to each player individually with their player index
            for idx in (0, 1):
                opponent_idx = 1 - idx
                emit(
                    "game_start",
                    {
                        "your_player_idx": idx,
                        "state": state_dict,
                        "opponent_name": session.player_names[opponent_idx],
                    },
                    to=session.player_sids[idx],
                )
