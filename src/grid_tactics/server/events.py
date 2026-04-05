"""Socket.IO event handlers for PvP room system and game flow."""
from flask import request
from flask_socketio import emit, join_room as sio_join_room

from grid_tactics.actions import pass_action
from grid_tactics.action_resolver import resolve_action
from grid_tactics.enums import TurnPhase
from grid_tactics.legal_actions import legal_actions
from grid_tactics.server.action_codec import reconstruct_action, serialize_action
from grid_tactics.server.app import socketio
from grid_tactics.server.room_manager import RoomManager
from grid_tactics.server.view_filter import filter_state_for_player

_room_manager: RoomManager | None = None


def _build_card_defs(library):
    """Build a dict mapping numeric_id to card info for client rendering.

    Includes ALL CardDefinition fields needed for UI rendering:
    card_id, name, card_type, mana_cost, attack, health, attack_range,
    element, tribe, effects, react_condition, react_effect, react_mana_cost,
    promote_target.
    """
    defs = {}
    for nid in range(library.card_count):
        try:
            card = library.get_by_id(nid)
            # Serialize effects as list of dicts
            effects_list = [
                {
                    "type": int(e.effect_type),
                    "trigger": int(e.trigger),
                    "target": int(e.target),
                    "amount": e.amount,
                }
                for e in card.effects
            ]
            # Serialize react_effect as dict if present
            react_effect_dict = None
            if card.react_effect is not None:
                react_effect_dict = {
                    "type": int(card.react_effect.effect_type),
                    "trigger": int(card.react_effect.trigger),
                    "target": int(card.react_effect.target),
                    "amount": card.react_effect.amount,
                }
            defs[nid] = {
                "card_id": card.card_id,
                "name": card.name,
                "card_type": int(card.card_type),
                "mana_cost": card.mana_cost,
                "attack": card.attack,
                "health": card.health,
                "attack_range": card.attack_range,
                "element": int(card.element) if card.element is not None else None,
                "tribe": card.tribe,
                "effects": effects_list,
                "react_condition": int(card.react_condition) if card.react_condition is not None else None,
                "react_effect": react_effect_dict,
                "react_mana_cost": card.react_mana_cost,
                "promote_target": card.promote_target,
                "tutor_target": card.tutor_target,
                "summon_sacrifice_tribe": card.summon_sacrifice_tribe,
                "unique": getattr(card, 'unique', False),
                "deckable": getattr(card, 'deckable', True),
                "transform_options": [
                    {"target": t[0], "mana_cost": t[1]}
                    for t in (card.transform_options or ())
                ] or None,
                "flavour_text": getattr(card, 'flavour_text', None),
            }
        except (KeyError, IndexError):
            break
    return defs


def _emit_state_to_players(session, state):
    """Emit filtered state + legal actions to each player via their SID.

    Decision-maker gets the legal_actions list; opponent gets an empty list.
    REACT phase decision-maker is react_player_idx; ACTION phase is active_player_idx.
    """
    state_dict = state.to_dict()
    actions = legal_actions(state, session.library) if not state.is_game_over else ()
    serialized_actions = [serialize_action(a) for a in actions]

    # Determine decision-maker
    if state.phase == TurnPhase.REACT:
        decision_idx = state.react_player_idx
    else:
        decision_idx = state.active_player_idx

    for idx in (0, 1):
        filtered = filter_state_for_player(state_dict, idx)
        emit("state_update", {
            "state": filtered,
            "legal_actions": serialized_actions if idx == decision_idx else [],
            "your_player_idx": idx,
        }, to=session.player_sids[idx])


def _emit_game_over(session, state):
    """Emit game_over event with filtered final state to both players."""
    state_dict = state.to_dict()
    for idx in (0, 1):
        filtered = filter_state_for_player(state_dict, idx)
        emit("game_over", {
            "winner": int(state.winner) if state.winner is not None else None,
            "final_state": filtered,
            "your_player_idx": idx,
        }, to=session.player_sids[idx])


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

        # Extract optional deck from payload before marking ready
        deck_data = data.get("deck") if isinstance(data, dict) else None
        if deck_data and isinstance(deck_data, list) and len(deck_data) == 30:
            deck_tuple = tuple(int(x) for x in deck_data)
            room_code_lookup = _room_manager.get_room_code_by_token(token)
            room_for_deck = _room_manager.get_room(room_code_lookup) if room_code_lookup else None
            if room_for_deck:
                if room_for_deck.creator.token == token:
                    room_for_deck.creator.deck = deck_tuple
                elif room_for_deck.joiner and room_for_deck.joiner.token == token:
                    room_for_deck.joiner.deck = deck_tuple

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
            card_defs = _build_card_defs(session.library)
            initial_actions = legal_actions(session.state, session.library)
            serialized_actions = [serialize_action(a) for a in initial_actions]
            # Emit game_start to each player individually with filtered state
            for idx in (0, 1):
                opponent_idx = 1 - idx
                filtered = filter_state_for_player(state_dict, idx)
                emit(
                    "game_start",
                    {
                        "your_player_idx": idx,
                        "state": filtered,
                        "legal_actions": serialized_actions if idx == session.state.active_player_idx else [],
                        "opponent_name": session.player_names[opponent_idx],
                        "card_defs": card_defs,
                    },
                    to=session.player_sids[idx],
                )

    @socketio.on("get_card_defs")
    def handle_get_card_defs(data=None):
        defs = _build_card_defs(_room_manager._library)
        emit("card_defs", {"card_defs": defs})

    @socketio.on("submit_action")
    def handle_submit_action(data):
        # Step a: Look up token from SID
        token = _room_manager.get_token_by_sid(request.sid)
        if token is None:
            emit("error", {"msg": "Not in a game"})
            return

        # Step b: Look up room_code
        room_code = _room_manager.get_room_code_by_token(token)
        if room_code is None:
            emit("error", {"msg": "Room not found"})
            return

        # Step c: Get game session
        session = _room_manager.get_game(room_code)
        if session is None:
            emit("error", {"msg": "Game not found"})
            return

        # Step d: Get player_idx
        player_idx = session.get_player_idx(token)
        if player_idx is None:
            emit("error", {"msg": "Not a player in this game"})
            return

        # Step e: Check game over
        if session.state.is_game_over:
            emit("error", {"msg": "Game is already over"})
            return

        # Step f: Determine decision-maker
        if session.state.phase == TurnPhase.REACT:
            decision_idx = session.state.react_player_idx
        else:
            decision_idx = session.state.active_player_idx

        # Step g: Check turn
        if player_idx != decision_idx:
            emit("error", {"msg": "Not your turn"})
            return

        # Step h: Reconstruct action from client payload
        try:
            action = reconstruct_action(data)
        except (ValueError, KeyError, TypeError) as e:
            emit("error", {"msg": f"Invalid action: {e}"})
            return

        # Step i: Lock, validate, apply
        with session.lock:
            valid_actions = legal_actions(session.state, session.library)
            if action not in valid_actions:
                emit("error", {"msg": "Illegal action"})
                return

            session.state = resolve_action(session.state, action, session.library)

            # Auto-pass loop: when player has zero legal actions (fatigue bleed)
            while not session.state.is_game_over:
                next_actions = legal_actions(session.state, session.library)
                if len(next_actions) > 0:
                    break
                session.state = resolve_action(
                    session.state, pass_action(), session.library
                )

            new_state = session.state

        # Step j: Emit state to both players
        _emit_state_to_players(session, new_state)

        # Step k: If game over, emit game_over
        if new_state.is_game_over:
            _emit_game_over(session, new_state)
