"""Socket.IO event handlers for PvP room system and game flow."""
from dataclasses import fields as _dc_fields
from enum import IntEnum as _IntEnum

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
    enrich_pending_conjure_deploy,
    enrich_pending_death_target,
    enrich_pending_post_move_attack,
    enrich_pending_revive,
    enrich_pending_tutor_for_viewer,
    filter_state_for_player,
    filter_state_for_spectator,
)

_room_manager: RoomManager | None = None


# Field-name remap for the client: the engine uses clearer names, the
# client expects the JSON names. Keep this list minimal — everything else
# is passed through by reflection below.
_EFFECT_CLIENT_KEY = {
    "effect_type": "type",
}


def _serialize_effect(effect):
    """Serialize an EffectDefinition by reflecting its dataclass fields.

    New fields added to EffectDefinition propagate to the client
    automatically — no need to update an allowlist. Enum values are
    coerced to ints, ``None`` and default values are dropped to keep
    the payload compact.
    """
    if effect is None:
        return None
    out = {}
    for f in _dc_fields(effect):
        value = getattr(effect, f.name)
        if value is None:
            continue
        # Skip default scalars so payload stays lean.
        default = f.default
        if default is not None and value == default:
            # Keep core positional fields (type/trigger/target/amount) even
            # if they match their default — the client always expects them.
            if f.name not in ("effect_type", "trigger", "target", "amount"):
                continue
        if isinstance(value, _IntEnum):
            value = int(value)
        key = _EFFECT_CLIENT_KEY.get(f.name, f.name)
        out[key] = value
    return out


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
            # Serialize effects via reflection so new EffectDefinition
            # fields don't need a matching edit here.
            effects_list = [_serialize_effect(e) for e in card.effects]
            react_effect_dict = _serialize_effect(card.react_effect)
            defs[nid] = {
                "card_id": card.card_id,
                "stable_id": card.stable_id,
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
                "discard_cost_tribe": card.discard_cost_tribe,
                "discard_cost_count": card.discard_cost_count,
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
                "cost_reduction": getattr(card, 'cost_reduction', None),
                "play_condition": getattr(card, 'play_condition', None),
                "sacrifice_ally_cost": getattr(card, 'sacrifice_ally_cost', False),
                "revive_card_id": getattr(card, 'revive_card_id', None),
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

    # Determine decision-maker. Pending death-target overrides phase because
    # a death modal routes control to the dying minion's owner (which may
    # not be the active player nor the react player).
    if getattr(state, "pending_death_target", None) is not None:
        decision_idx = int(state.pending_death_target.owner_idx)
    elif state.phase == TurnPhase.REACT:
        decision_idx = state.react_player_idx
    else:
        decision_idx = state.active_player_idx

    for idx in (0, 1):
        filtered = filter_state_for_player(state_dict, idx)
        enrich_pending_tutor_for_viewer(state, filtered, idx, session.library)
        enrich_pending_conjure_deploy(state, filtered, idx, session.library)
        enrich_pending_death_target(state, filtered, idx, session.library)
        enrich_pending_revive(state, filtered, idx, session.library)
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
        # Spectators inherit the same pending-tutor/conjure enrichment as their perspective seat.
        if not slot.god_mode:
            enrich_pending_tutor_for_viewer(state, spec_state, 0, session.library)
            enrich_pending_conjure_deploy(state, spec_state, 0, session.library)
            enrich_pending_death_target(state, spec_state, 0, session.library)
            enrich_pending_revive(state, spec_state, 0, session.library)
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
        enrich_pending_conjure_deploy(state, filtered, idx, session.library)
        enrich_pending_death_target(state, filtered, idx, session.library)
        enrich_pending_revive(state, filtered, idx, session.library)
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
            enrich_pending_conjure_deploy(session.state, spec_state, 0, session.library)
            enrich_pending_death_target(session.state, spec_state, 0, session.library)
            enrich_pending_revive(session.state, spec_state, 0, session.library)
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

        # Extract optional deck from payload before marking ready.
        # Server-side validation — rejects decks with non-deckable cards,
        # wrong size, too many copies, or unknown IDs.
        deck_data = data.get("deck") if isinstance(data, dict) else None
        if deck_data and isinstance(deck_data, list) and len(deck_data) == 30:
            deck_tuple = tuple(int(x) for x in deck_data)
            errors = _room_manager._library.validate_deck(deck_tuple)
            if errors:
                emit("error", {"msg": "Invalid deck: " + "; ".join(errors)})
                return
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
                enrich_pending_conjure_deploy(session.state, filtered, idx, session.library)
                enrich_pending_death_target(session.state, filtered, idx, session.library)
                enrich_pending_revive(session.state, filtered, idx, session.library)
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
            _fanout_game_start_to_spectators(session, state_dict, card_defs)

    @socketio.on("spectate_room")
    def handle_spectate_room(data):
        data = data or {}
        display_name = (data.get("display_name") or "").strip()
        room_code = (data.get("room_code") or "").strip().upper()
        god_mode = bool(data.get("god_mode", False))
        if not display_name:
            emit("error", {"msg": "display_name is required"})
            return
        if not room_code:
            emit("error", {"msg": "room_code is required"})
            return
        try:
            token, _ = _room_manager.join_as_spectator(
                room_code, display_name, request.sid, god_mode
            )
        except ValueError as e:
            emit("error", {"msg": str(e)})
            return
        sio_join_room(room_code)
        emit("spectator_joined", {
            "room_code": room_code,
            "session_token": token,
            "god_mode": god_mode,
        })
        # If a game is already underway, immediately push current state.
        session = _room_manager.get_game(room_code)
        if session is not None:
            state_dict = session.state.to_dict()
            enrich_pending_post_move_attack(session.state, state_dict, session.library)
            spec_state = filter_state_for_spectator(
                state_dict, god_mode=god_mode, perspective_idx=0,
            )
            if not god_mode:
                enrich_pending_tutor_for_viewer(session.state, spec_state, 0, session.library)
                enrich_pending_conjure_deploy(session.state, spec_state, 0, session.library)
                enrich_pending_death_target(session.state, spec_state, 0, session.library)
                enrich_pending_revive(session.state, spec_state, 0, session.library)
            card_defs = _build_card_defs(session.library)
            emit("game_start", {
                "your_player_idx": 0,
                "state": spec_state,
                "legal_actions": [],
                "opponent_name": session.player_names[1],
                "card_defs": card_defs,
                "is_spectator": True,
            })

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
            enrich_pending_conjure_deploy(new_session.state, filtered, idx, new_session.library)
            enrich_pending_death_target(new_session.state, filtered, idx, new_session.library)
            enrich_pending_revive(new_session.state, filtered, idx, new_session.library)
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
        _fanout_game_start_to_spectators(new_session, state_dict, card_defs)

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
        # Determine sender name from active game, waiting room, or spectator slot
        sender_name = "Unknown"
        if _room_manager.get_role(token) == "spectator":
            spec = _room_manager.get_spectator(token)
            if spec is not None:
                sender_name = spec.name
        else:
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

        # Phase 14.4: spectators cannot submit actions
        if _room_manager.get_role(token) == "spectator":
            emit("error", {"msg": "Spectators cannot submit actions"})
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

        # Step f: Determine decision-maker. Pending death-target overrides
        # phase because a death modal routes control to the dying minion's
        # owner (which may not be the active player nor the react player).
        if getattr(session.state, "pending_death_target", None) is not None:
            decision_idx = int(session.state.pending_death_target.owner_idx)
        elif session.state.phase == TurnPhase.REACT:
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

    # ------------------------------------------------------------------
    # Sandbox Mode (Phase 14.6)
    # ------------------------------------------------------------------
    # Sandboxes run in a parallel dict on RoomManager keyed by SID. They
    # NEVER touch the real-game code path (submit_action, view_filter,
    # spectator fanout). Every handler loads the sandbox via _get_sandbox_or_error,
    # mutates through SandboxSession (which validates real actions through
    # legal_actions/resolve_action and edits zones via dataclasses.replace),
    # and re-emits the full god-view state via _emit_sandbox_state.

    def _emit_sandbox_state(sandbox, sid):
        """Single source of truth for sandbox state emission. God view, no filter.

        Enriches pending_tutor / pending_death / pending_post_move_attack /
        pending_revive so the sandbox UI can render modals and target
        highlights. Sandbox is god-mode — whichever player the engine says
        should pick, we enrich from THEIR POV so the UI shows full picker
        state (valid targets + banner) regardless of which player the user
        is currently viewing as.
        """
        state = sandbox.state
        state_dict = state.to_dict()
        enrich_pending_post_move_attack(state, state_dict, sandbox.library)
        # For revive/tutor/death, the picker is the owner of the pending
        # state; enrich from their POV so the sandbox always gets the full
        # picker payload (valid_targets, matches, etc.).
        revive_viewer = state.pending_revive_player_idx if state.pending_revive_player_idx is not None else 0
        tutor_viewer = state.pending_tutor_player_idx if state.pending_tutor_player_idx is not None else 0
        death_target = getattr(state, "pending_death_target", None)
        death_viewer = int(death_target.owner_idx) if death_target is not None else 0
        conjure_viewer = state.pending_conjure_deploy_player_idx if state.pending_conjure_deploy_player_idx is not None else 0
        enrich_pending_revive(state, state_dict, revive_viewer, sandbox.library)
        enrich_pending_tutor_for_viewer(state, state_dict, tutor_viewer, sandbox.library)
        enrich_pending_death_target(state, state_dict, death_viewer, sandbox.library)
        enrich_pending_conjure_deploy(state, state_dict, conjure_viewer, sandbox.library)
        actions = sandbox.legal_actions() if not sandbox.state.is_game_over else ()
        serialized = [serialize_action(a) for a in actions]
        emit("sandbox_state", {
            "state": state_dict,
            "legal_actions": serialized,
            "active_view_idx": sandbox.active_view_idx,
            "undo_depth": sandbox.undo_depth,
            "redo_depth": sandbox.redo_depth,
        })

    def _get_sandbox_or_error():
        sandbox = _room_manager.get_sandbox(request.sid)
        if sandbox is None:
            emit("error", {"msg": "No sandbox session"})
            return None
        return sandbox

    @socketio.on("sandbox_create")
    def handle_sandbox_create(_data=None):
        sandbox = _room_manager.create_sandbox(request.sid)
        emit("sandbox_card_defs", {"card_defs": _build_card_defs(sandbox.library)})
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_apply_action")
    def handle_sandbox_apply_action(data):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        try:
            action = reconstruct_action(data)
        except (ValueError, KeyError, TypeError) as e:
            emit("error", {"msg": f"Invalid action: {e}"})
            return
        with sandbox.lock:
            try:
                sandbox.apply_action(action)
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
            except Exception as e:
                import traceback
                print(f"[ERROR] sandbox apply_action: {e}", flush=True)
                traceback.print_exc()
                emit("error", {"msg": f"Server error: {e}"})
                return
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_add_card_to_zone")
    def handle_sandbox_add_card_to_zone(data):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        try:
            player_idx = int(data["player_idx"])
            card_numeric_id = int(data["card_numeric_id"])
            zone = str(data["zone"])
        except (KeyError, TypeError, ValueError):
            emit("error", {"msg": "Invalid sandbox_add_card_to_zone payload"})
            return
        with sandbox.lock:
            try:
                sandbox.add_card_to_zone(player_idx, card_numeric_id, zone)
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_place_on_board")
    def handle_sandbox_place_on_board(data):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        try:
            player_idx = int(data["player_idx"])
            card_numeric_id = int(data["card_numeric_id"])
            row = int(data["row"])
            col = int(data["col"])
        except (KeyError, TypeError, ValueError):
            emit("error", {"msg": "Invalid sandbox_place_on_board payload"})
            return
        with sandbox.lock:
            try:
                sandbox.place_on_board(player_idx, card_numeric_id, row, col)
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_move_card")
    def handle_sandbox_move_card(data):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        try:
            player_idx = int(data["player_idx"])
            card_numeric_id = int(data["card_numeric_id"])
            src_zone = str(data["src_zone"])
            dst_zone = str(data["dst_zone"])
        except (KeyError, TypeError, ValueError):
            emit("error", {"msg": "Invalid sandbox_move_card payload"})
            return
        with sandbox.lock:
            try:
                sandbox.move_card_between_zones(player_idx, card_numeric_id, src_zone, dst_zone)
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_import_deck")
    def handle_sandbox_import_deck(data):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        try:
            player_idx = int(data["player_idx"])
            deck = data["deck_card_ids"]
            if not isinstance(deck, list):
                raise ValueError("deck_card_ids must be a list")
        except (KeyError, TypeError, ValueError) as e:
            emit("error", {"msg": f"Invalid sandbox_import_deck payload: {e}"})
            return
        with sandbox.lock:
            try:
                sandbox.import_deck(player_idx, deck)
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_set_player_field")
    def handle_sandbox_set_player_field(data):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        try:
            player_idx = int(data["player_idx"])
            field = str(data["field"])
            value = int(data["value"])
        except (KeyError, TypeError, ValueError):
            emit("error", {"msg": "Invalid sandbox_set_player_field payload"})
            return
        with sandbox.lock:
            try:
                sandbox.set_player_field(player_idx, field, value)
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_set_active_player")
    def handle_sandbox_set_active_player(data):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        try:
            player_idx = int(data["player_idx"])
        except (KeyError, TypeError, ValueError):
            emit("error", {"msg": "Invalid payload"})
            return
        with sandbox.lock:
            try:
                sandbox.set_active_player(player_idx)
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_undo")
    def handle_sandbox_undo(_data=None):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        with sandbox.lock:
            sandbox.undo()
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_redo")
    def handle_sandbox_redo(_data=None):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        with sandbox.lock:
            sandbox.redo()
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_reset")
    def handle_sandbox_reset(_data=None):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        with sandbox.lock:
            sandbox.reset()
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_save")
    def handle_sandbox_save(_data=None):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        emit("sandbox_save_blob", {"payload": sandbox.to_dict()})

    @socketio.on("sandbox_load")
    def handle_sandbox_load(data):
        sandbox = _room_manager.get_sandbox(request.sid)
        if sandbox is None:
            sandbox = _room_manager.create_sandbox(request.sid)
            emit("sandbox_card_defs", {"card_defs": _build_card_defs(sandbox.library)})
        try:
            payload = data["payload"]
        except (KeyError, TypeError):
            emit("error", {"msg": "Invalid sandbox_load payload"})
            return
        with sandbox.lock:
            try:
                sandbox.load_dict(payload)
            except Exception as e:
                emit("error", {"msg": f"Failed to load: {e}"})
                return
        _emit_sandbox_state(sandbox, request.sid)

    # ----- Server-side save slots (DEV-08) -------------------------------

    @socketio.on("sandbox_save_slot")
    def handle_sandbox_save_slot(data):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        try:
            slot_name = str(data["slot_name"])
        except (KeyError, TypeError):
            emit("error", {"msg": "Invalid sandbox_save_slot payload"})
            return
        with sandbox.lock:
            try:
                sandbox.save_to_slot(slot_name)
            except (ValueError, OSError) as e:
                emit("error", {"msg": f"Failed to save slot: {e}"})
                return
        emit("sandbox_slot_saved", {"slot_name": slot_name})
        # Also send refreshed slot list so the client UI doesn't need a separate roundtrip
        emit("sandbox_slot_list", {"slots": sandbox.list_slots()})

    @socketio.on("sandbox_load_slot")
    def handle_sandbox_load_slot(data):
        sandbox = _room_manager.get_sandbox(request.sid)
        if sandbox is None:
            sandbox = _room_manager.create_sandbox(request.sid)
            emit("sandbox_card_defs", {"card_defs": _build_card_defs(sandbox.library)})
        try:
            slot_name = str(data["slot_name"])
        except (KeyError, TypeError):
            emit("error", {"msg": "Invalid sandbox_load_slot payload"})
            return
        with sandbox.lock:
            try:
                sandbox.load_from_slot(slot_name)
            except FileNotFoundError:
                emit("error", {"msg": f"Slot not found: {slot_name}"})
                return
            except (ValueError, OSError) as e:
                emit("error", {"msg": f"Failed to load slot: {e}"})
                return
        _emit_sandbox_state(sandbox, request.sid)

    @socketio.on("sandbox_list_slots")
    def handle_sandbox_list_slots(_data=None):
        from grid_tactics.server.sandbox_session import SandboxSession
        try:
            slots = SandboxSession.list_slots()
        except OSError as e:
            emit("error", {"msg": f"Failed to list slots: {e}"})
            return
        emit("sandbox_slot_list", {"slots": slots})

    @socketio.on("sandbox_delete_slot")
    def handle_sandbox_delete_slot(data):
        from grid_tactics.server.sandbox_session import SandboxSession
        try:
            slot_name = str(data["slot_name"])
        except (KeyError, TypeError):
            emit("error", {"msg": "Invalid sandbox_delete_slot payload"})
            return
        try:
            existed = SandboxSession.delete_slot(slot_name)
        except (ValueError, OSError) as e:
            emit("error", {"msg": f"Failed to delete slot: {e}"})
            return
        emit("sandbox_slot_deleted", {"slot_name": slot_name, "existed": existed})
        emit("sandbox_slot_list", {"slots": SandboxSession.list_slots()})

    @socketio.on("disconnect")
    def handle_disconnect():
        """Phase 14.4: clean up spectator entries on disconnect.

        Player disconnect cleanup is intentionally NOT implemented here — Phase
        15 (reconnection) will handle player sid churn. Spectators have no
        reconnection story, so we drop them eagerly.
        """
        token = _room_manager.get_token_by_sid(request.sid)
        if token is not None and _room_manager.get_role(token) == "spectator":
            _room_manager.remove_spectator(token)
        # Phase 14.6: drop any sandbox attached to this SID (sandbox users have
        # no session token, so cleanup must run regardless of the token path).
        _room_manager.remove_sandbox(request.sid)
