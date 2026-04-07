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
from grid_tactics.server.view_filter import (
    enrich_last_action,
    enrich_pending_post_move_attack,
    enrich_pending_tutor_for_viewer,
    filter_state_for_player,
    filter_state_for_spectator,
)

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
                "react_requires_no_friendly_minions": getattr(card, 'react_requires_no_friendly_minions', False),
                "summon_token_target": getattr(card, 'summon_token_target', None),
                "summon_token_cost": getattr(card, 'summon_token_cost', None),
                "conjure_buff": getattr(card, 'conjure_buff', None),
                "activated_ability": (
                    {
                        "name": card.activated_ability.name,
                        "mana_cost": card.activated_ability.mana_cost,
                        "effect_type": card.activated_ability.effect_type,
                        "summon_card_id": card.activated_ability.summon_card_id,
                        "target": card.activated_ability.target,
                    }
                    if getattr(card, 'activated_ability', None) is not None
                    else None
                ),
            }
        except (KeyError, IndexError):
            break
    return defs


def _emit_state_to_players(session, state, prev_state=None, resolved_action=None):
    """Emit filtered state + legal actions to each player via their SID.

    Decision-maker gets the legal_actions list; opponent gets an empty list.
    REACT phase decision-maker is react_player_idx; ACTION phase is active_player_idx.

    If `prev_state` and `resolved_action` are provided, a `last_action` field
    (Phase 14.3-04) is enriched onto the serialized state so the client can
    drive attack animations + damage popups.
    """
    state_dict = state.to_dict()
    enrich_pending_post_move_attack(state, state_dict, session.library)
    enrich_last_action(state_dict, prev_state, state, resolved_action)
    actions = legal_actions(state, session.library) if not state.is_game_over else ()
    serialized_actions = [serialize_action(a) for a in actions]

    # Determine decision-maker
    if state.phase == TurnPhase.REACT:
        decision_idx = state.react_player_idx
    else:
        decision_idx = state.active_player_idx

    for idx in (0, 1):
        filtered = filter_state_for_player(state_dict, idx)
        enrich_pending_tutor_for_viewer(state, filtered, idx, session.library)
        emit("state_update", {
            "state": filtered,
            "legal_actions": serialized_actions if idx == decision_idx else [],
            "your_player_idx": idx,
        }, to=session.player_sids[idx])

    _fanout_state_to_spectators(session, state, state_dict, resolved_action)


def _fanout_state_to_spectators(session, state, base_state_dict, resolved_action, event_name="state_update"):
    """Phase 14.4: emit filtered state to every spectator in the session's room."""
    if _room_manager is None:
        return
    room_code = _room_manager.get_room_code_by_token(session.player_tokens[0])
    if room_code is None:
        return
    spec_tokens = _room_manager.get_spectator_tokens(room_code)
    if not spec_tokens:
        return
    for spec_token in spec_tokens:
        slot = _room_manager.get_spectator(spec_token)
        if slot is None:
            continue
        spec_state = filter_state_for_spectator(
            base_state_dict, god_mode=slot.god_mode, perspective_idx=0,
        )
        # Spectators inherit the same pending-tutor enrichment as their perspective seat.
        if not slot.god_mode:
            enrich_pending_tutor_for_viewer(state, spec_state, 0, session.library)
        if event_name == "state_update":
            emit("state_update", {
                "state": spec_state,
                "legal_actions": [],
                "your_player_idx": 0,
                "is_spectator": True,
            }, to=slot.sid)
        elif event_name == "game_over":
            emit("game_over", {
                "winner": int(state.winner) if state.winner is not None else None,
                "final_state": spec_state,
                "your_player_idx": 0,
                "is_spectator": True,
            }, to=slot.sid)


def _emit_game_over(session, state):
    """Emit game_over event with filtered final state to both players."""
    state_dict = state.to_dict()
    enrich_pending_post_move_attack(state, state_dict, session.library)
    for idx in (0, 1):
        filtered = filter_state_for_player(state_dict, idx)
        enrich_pending_tutor_for_viewer(state, filtered, idx, session.library)
        emit("game_over", {
            "winner": int(state.winner) if state.winner is not None else None,
            "final_state": filtered,
            "your_player_idx": idx,
        }, to=session.player_sids[idx])

    _fanout_state_to_spectators(session, state, state_dict, None, event_name="game_over")


def _fanout_game_start_to_spectators(session, base_state_dict, card_defs):
    """Phase 14.4: emit game_start to spectators of this session's room."""
    if _room_manager is None:
        return
    room_code = _room_manager.get_room_code_by_token(session.player_tokens[0])
    if room_code is None:
        return
    for spec_token in _room_manager.get_spectator_tokens(room_code):
        slot = _room_manager.get_spectator(spec_token)
        if slot is None:
            continue
        spec_state = filter_state_for_spectator(
            base_state_dict, god_mode=slot.god_mode, perspective_idx=0,
        )
        if not slot.god_mode:
            enrich_pending_tutor_for_viewer(session.state, spec_state, 0, session.library)
        emit(
            "game_start",
            {
                "your_player_idx": 0,
                "state": spec_state,
                "legal_actions": [],
                "opponent_name": session.player_names[1],
                "card_defs": card_defs,
                "is_spectator": True,
            },
            to=slot.sid,
        )


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
            enrich_pending_post_move_attack(session.state, state_dict, session.library)
            card_defs = _build_card_defs(session.library)
            initial_actions = legal_actions(session.state, session.library)
            serialized_actions = [serialize_action(a) for a in initial_actions]
            # Emit game_start to each player individually with filtered state
            for idx in (0, 1):
                opponent_idx = 1 - idx
                filtered = filter_state_for_player(state_dict, idx)
                enrich_pending_tutor_for_viewer(session.state, filtered, idx, session.library)
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

    @socketio.on("request_rematch")
    def handle_request_rematch(data=None):
        """Handle a player requesting a rematch after game over."""
        token = _room_manager.get_token_by_sid(request.sid)
        if token is None:
            emit("error", {"msg": "Not in a game"})
            return
        room_code = _room_manager.get_room_code_by_token(token)
        if room_code is None:
            emit("error", {"msg": "Room not found"})
            return

        status, old_session, new_session = _room_manager.request_rematch(token)

        if status == 'no_game':
            emit("error", {"msg": "No active game to rematch"})
            return

        if status == 'waiting':
            # Tell the requester they're waiting
            emit("rematch_waiting", {"requester": "self"})
            # Tell the opponent that the other player wants a rematch
            requester_idx = old_session.get_player_idx(token)
            opponent_idx = 1 - requester_idx
            opponent_sid = old_session.player_sids[opponent_idx]
            if opponent_sid:
                emit(
                    "rematch_waiting",
                    {"requester": "opponent", "name": old_session.player_names[requester_idx]},
                    to=opponent_sid,
                )
            return

        # status == 'started' -- emit game_start to both players with the fresh state
        state_dict = new_session.state.to_dict()
        enrich_pending_post_move_attack(new_session.state, state_dict, new_session.library)
        card_defs = _build_card_defs(new_session.library)
        initial_actions = legal_actions(new_session.state, new_session.library)
        serialized_actions = [serialize_action(a) for a in initial_actions]
        for idx in (0, 1):
            opponent_idx = 1 - idx
            filtered = filter_state_for_player(state_dict, idx)
            enrich_pending_tutor_for_viewer(new_session.state, filtered, idx, new_session.library)
            sid = new_session.player_sids[idx]
            if sid is None:
                continue
            emit(
                "game_start",
                {
                    "your_player_idx": idx,
                    "state": filtered,
                    "legal_actions": serialized_actions if idx == new_session.state.active_player_idx else [],
                    "opponent_name": new_session.player_names[opponent_idx],
                    "card_defs": card_defs,
                },
                to=sid,
            )

    @socketio.on("chat_message")
    def handle_chat_message(data):
        """Broadcast a chat message to both players in the room (works in lobby and active game)."""
        token = _room_manager.get_token_by_sid(request.sid)
        if token is None:
            return
        room_code = _room_manager.get_room_code_by_token(token)
        if room_code is None:
            return
        # Validate and trim message first
        if not isinstance(data, dict):
            return
        text = data.get("text", "")
        if not isinstance(text, str):
            return
        text = text.strip()[:200]
        if not text:
            return
        # Determine sender name from active game or waiting room
        sender_name = "Unknown"
        session = _room_manager.get_game(room_code)
        if session is not None:
            player_idx = session.get_player_idx(token)
            if player_idx is not None:
                sender_name = session.player_names[player_idx]
        else:
            room = _room_manager.get_room(room_code)
            if room is not None:
                if room.creator and room.creator.token == token:
                    sender_name = room.creator.name
                elif room.joiner and room.joiner.token == token:
                    sender_name = room.joiner.name
        emit(
            "chat_message",
            {"author": sender_name, "text": text},
            to=room_code,
        )

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

            saved_state = session.state
            try:
                session.state = resolve_action(session.state, action, session.library)

                # Auto-pass loop: when player has zero legal actions (fatigue bleed)
                while not session.state.is_game_over:
                    next_actions = legal_actions(session.state, session.library)
                    if len(next_actions) > 0:
                        break
                    session.state = resolve_action(
                        session.state, pass_action(), session.library
                    )
            except Exception as e:
                # Safety net: roll back state and surface the error so a single
                # broken effect doesn't crash the server or leave a partial state
                session.state = saved_state
                import traceback
                print(f"[ERROR] resolve_action raised: {e}", flush=True)
                traceback.print_exc()
                emit("error", {"msg": f"Server error resolving action: {e}"})
                return

            new_state = session.state

        # Step j: Emit state to both players (with last_action enrichment)
        _emit_state_to_players(session, new_state, prev_state=saved_state, resolved_action=action)

        # Step k: If game over, emit game_over
        if new_state.is_game_over:
            _emit_game_over(session, new_state)
