"""Socket.IO event handlers for PvP room system and game flow."""
from dataclasses import fields as _dc_fields
from enum import IntEnum as _IntEnum

from flask import request
from flask_socketio import emit, join_room as sio_join_room

from grid_tactics.actions import pass_action
from grid_tactics.action_resolver import resolve_action
from grid_tactics.engine_events import EventStream
from grid_tactics.enums import TurnPhase
from grid_tactics.phase_contracts import OutOfPhaseError
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
    enrich_pending_trigger_for_viewer,
    enrich_pending_tutor_for_viewer,
    filter_engine_events_for_viewer,
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
                "destroy_ally_cost": getattr(card, 'destroy_ally_cost', False),
                # Legacy alias — old clients still read this key. Remove
                # once every client ships on 0.11.17+.
                "sacrifice_ally_cost": getattr(card, 'destroy_ally_cost', False),
                "hp_cost": getattr(card, 'hp_cost', None),
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


def _emit_state_to_players(
    session,
    state,
    prev_state=None,
    resolved_action=None,
    events=None,
):
    """Emit filtered state + legal actions to each player via their SID.

    Decision-maker gets the legal_actions list; opponent gets an empty list.
    REACT phase decision-maker is react_player_idx; ACTION phase is active_player_idx.

    If `prev_state` and `resolved_action` are provided, a `last_action` field
    (Phase 14.3-04) is enriched onto the serialized state so the client can
    drive attack animations + damage popups.

    Phase 14.8-03b: when ``events`` (a list of EngineEvent) is provided,
    ALSO emit a NEW ``engine_events`` socket message per viewer alongside
    the existing ``state_update``. The new message carries the per-viewer
    filtered event list, the same final-state snapshot for context, and
    the same legal_actions list. Both messages fire during this
    transitional phase; plan 14.8-05 drops ``state_update`` once all
    clients consume ``engine_events``.
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
        enrich_pending_trigger_for_viewer(state, filtered, idx, session.library)
        legal_for_viewer = serialized_actions if idx == decision_idx else []
        # Phase 14.8-05: the post-action ``state_update`` Socket.IO emit is
        # DELETED. DOM commits flow exclusively through the ``engine_events``
        # slot handlers on the client (plan 14.8-04b). The final_state field
        # on the engine_events payload below still ships the authoritative
        # state snapshot for error-recovery / reconnect parity (stashed to
        # window.__lastFinalState on the client).
        if events is not None:
            filtered_events = filter_engine_events_for_viewer(events, idx)
            emit("engine_events", {
                "events": [ev.to_dict() for ev in filtered_events],
                "final_state": filtered,
                "legal_actions": legal_for_viewer,
                "your_player_idx": idx,
            }, to=session.player_sids[idx])

    _fanout_state_to_spectators(session, state, state_dict, resolved_action, events=events)


def _fanout_state_to_spectators(
    session, state, base_state_dict, resolved_action,
    event_name="state_update", events=None,
):
    """Phase 14.4: emit filtered state to every spectator in the session's room.

    Phase 14.8-03b: when ``events`` is provided AND ``event_name ==
    "state_update"``, also emit a ``engine_events`` frame per spectator
    using god_mode-aware filtering. God spectators see all events
    unredacted; non-god spectators see the P1-perspective filter.
    """
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
            enrich_pending_trigger_for_viewer(state, spec_state, 0, session.library)
        if event_name == "state_update":
            # Phase 14.8-05: post-action ``state_update`` emit DELETED for
            # spectators too. DOM commits flow via ``engine_events`` slot
            # handlers; the final_state carried in the engine_events payload
            # below remains authoritative for reconnect / error-recovery.
            if events is not None:
                # God spectators bypass redaction; non-god uses P1
                # perspective per Phase 14.4 contract.
                spec_events = filter_engine_events_for_viewer(
                    events, 0, god_mode=slot.god_mode,
                )
                emit("engine_events", {
                    "events": [ev.to_dict() for ev in spec_events],
                    "final_state": spec_state,
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
        enrich_pending_trigger_for_viewer(state, filtered, idx, session.library)
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
            enrich_pending_trigger_for_viewer(session.state, spec_state, 0, session.library)
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


def _tests_results_path():
    """Resolve the filesystem path the test results log writes to.

    Railway mounts a persistent volume at /data/persist (configured via
    the Railway GraphQL API) so the log survives redeploys. The server
    reads TESTS_RESULTS_PATH from the environment so the deploy can swap
    this at runtime; local dev falls back to the repo-relative path.
    """
    import os
    from pathlib import Path
    env_path = os.environ.get("TESTS_RESULTS_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[3] / "data" / "tests" / "results.jsonl"


def _apply_test_op(sandbox, op):
    """Apply a single test-scenario setup op to the given sandbox session.

    Thin wrapper over SandboxSession primitives so test manifests stay
    declarative. Unknown ops raise ValueError.
    """
    name = op.get("op")
    if name == "reset":
        sandbox.reset()
        return
    if name == "set_player":
        sandbox.set_player_field(
            int(op["player_idx"]), str(op["field"]), int(op["value"])
        )
        return
    if name in ("add_to_hand", "add_to_zone"):
        zone = op.get("zone", "hand")
        card_id = op["card_id"]
        nid = sandbox.library.get_numeric_id(card_id)
        sandbox.add_card_to_zone(int(op["player_idx"]), nid, zone)
        return
    if name == "place":
        card_id = op["card_id"]
        nid = sandbox.library.get_numeric_id(card_id)
        sandbox.place_on_board(
            int(op["player_idx"]), nid, int(op["row"]), int(op["col"]),
        )
        # Optional post-placement DM injection (replaces the just-placed
        # minion with a copy carrying dark_matter_stacks). Kept as a direct
        # state edit rather than an engine call — tests need a way to seed
        # DM without having to chain buff cards for every scenario.
        dm = op.get("dark_matter")
        if dm is not None and dm > 0:
            from dataclasses import replace as _replace
            minions = list(sandbox._state.minions)
            if minions:
                last = minions[-1]
                minions[-1] = _replace(last, dark_matter_stacks=int(dm))
                sandbox._state = _replace(sandbox._state, minions=tuple(minions))
        # Optional starting health override — lets tests pre-damage a minion
        # without going through an attack. Caps at 1 to avoid placing a
        # corpse; overcap above base is allowed (caller's responsibility).
        ch = op.get("current_health")
        if ch is not None:
            from dataclasses import replace as _replace
            minions = list(sandbox._state.minions)
            if minions:
                last = minions[-1]
                minions[-1] = _replace(last, current_health=max(1, int(ch)))
                sandbox._state = _replace(sandbox._state, minions=tuple(minions))
        return
    if name == "set_active":
        sandbox.set_active_player(int(op["player_idx"]))
        return
    raise ValueError(f"Unknown test op: {name!r}")


def register_events(room_manager: RoomManager) -> None:
    """Register all Socket.IO event handlers with the given room manager."""
    global _room_manager
    _room_manager = room_manager

    def _broadcast_rooms_list() -> None:
        """Push the current open-rooms list to every connected client.
        Called after any room state change that might add/remove a row:
        create_room, join_room fills a slot, etc.
        """
        socketio.emit("rooms_list", {"rooms": _room_manager.list_open_rooms()})

    @socketio.on("list_rooms")
    def handle_list_rooms(_data=None):
        emit("rooms_list", {"rooms": _room_manager.list_open_rooms()})

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
        _broadcast_rooms_list()

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
        _broadcast_rooms_list()

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
        if deck_data and isinstance(deck_data, list) and len(deck_data) == 40:
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
                enrich_pending_trigger_for_viewer(session.state, filtered, idx, session.library)
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
                enrich_pending_trigger_for_viewer(session.state, spec_state, 0, session.library)
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
            enrich_pending_trigger_for_viewer(new_session.state, filtered, idx, new_session.library)
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

            saved_state = session.state  # Phase 14.8-05 M4: snapshot before resolve for OutOfPhaseError rollback
            # Phase 14.8-03b (M3): one EventStream per submit_action,
            # seeded from session.next_event_seq. Threaded through every
            # resolve_action / enter_*_of_turn helper inside the auto-
            # advance loop so the entire chain emits into ONE seq-
            # ordered stream. Persisted back to session.next_event_seq
            # on success.
            stream = EventStream(next_seq=session.next_event_seq)
            try:
                session.state = resolve_action(
                    session.state, action, session.library,
                    event_collector=stream,
                )

                # Auto-pass / auto-advance loop.
                # Two reasons to stay in the loop:
                #   (1) Fatigue bleed — legal_actions is empty during an
                #       ACTION phase. Submit PASS to resolve_action.
                #   (2) Phase 14.7-02: legal_actions is empty during
                #       START_OF_TURN / END_OF_TURN phases because those
                #       phases are placeholders. Call the react_stack
                #       helpers directly — resolve_action does NOT accept
                #       START/END phase inputs.
                # Safety counter: hard cap iterations to catch any
                # infinite-loop regressions (triggers a 500 rather than a
                # silent wedge).
                from grid_tactics.enums import TurnPhase as _TurnPhase
                from grid_tactics.react_stack import (
                    enter_end_of_turn as _enter_end_of_turn,
                    enter_start_of_turn as _enter_start_of_turn,
                )
                _auto_advance_counter = 0
                _AUTO_ADVANCE_MAX = 50
                while not session.state.is_game_over:
                    _auto_advance_counter += 1
                    if _auto_advance_counter > _AUTO_ADVANCE_MAX:
                        raise RuntimeError(
                            "Phase auto-advance loop exceeded safety counter "
                            f"({_AUTO_ADVANCE_MAX} iterations) — possible "
                            "infinite-loop regression in START/END phase "
                            "handling."
                        )
                    # 14.7-02 START/END placeholder phases take precedence
                    # over legal_actions (which returns () for them).
                    if session.state.phase == _TurnPhase.START_OF_TURN:
                        session.state = _enter_start_of_turn(
                            session.state, session.library,
                            event_collector=stream,
                        )
                        continue
                    if session.state.phase == _TurnPhase.END_OF_TURN:
                        session.state = _enter_end_of_turn(
                            session.state, session.library,
                            event_collector=stream,
                        )
                        continue
                    next_actions = legal_actions(session.state, session.library)
                    if len(next_actions) > 0:
                        break
                    # ACTION phase with no legal actions = fatigue bleed.
                    session.state = resolve_action(
                        session.state, pass_action(), session.library,
                        event_collector=stream,
                    )
            except OutOfPhaseError as e:
                # Phase 14.8-05: strict-mode contract violation. Roll the
                # session state back to the pre-resolve snapshot (M4), emit
                # a structured `error` frame so the client can surface the
                # violation, and continue serving — never crash the session
                # (orchestrator decision #2: soft failure).
                session.state = saved_state
                import logging as _logging
                _logging.getLogger("grid_tactics.server.events").error(
                    "OutOfPhaseError in handle_submit_action: source=%s phase=%s "
                    "allowed=%s pending_required=%s",
                    e.contract_source,
                    e.phase.name if e.phase else None,
                    sorted(p.name for p in (e.allowed_phases or [])),
                    e.pending_required,
                )
                emit("error", {
                    "error_type": "phase_contract_violation",
                    "contract_source": e.contract_source,
                    "phase": e.phase.name if e.phase else None,
                    "allowed_phases": [
                        p.name for p in (e.allowed_phases or [])
                    ],
                    "pending_required": e.pending_required,
                    "unknown_source": bool(getattr(e, "unknown_source", False)),
                    "msg": (
                        f"Action rejected: contract violation "
                        f"({e.contract_source!r} not allowed in phase "
                        f"{e.phase.name if e.phase else 'unknown'})."
                    ),
                })
                return
            except Exception as e:
                # Safety net: roll back state and surface the error so a single
                # broken effect doesn't crash the server or leave a partial state
                session.state = saved_state
                import traceback
                print(f"[ERROR] resolve_action raised: {e}", flush=True)
                traceback.print_exc()
                emit("error", {"msg": f"Server error resolving action: {e}"})
                return

            # M3: persist seq counter back to the session so the next
            # submit_action call's seq numbers continue monotonically.
            session.next_event_seq = stream.next_seq
            new_state = session.state
            collected_events = list(stream.events)

        # Step j: Emit state to both players (with last_action enrichment).
        # Phase 14.8-03b: also emit engine_events (per-viewer filtered).
        _emit_state_to_players(
            session, new_state,
            prev_state=saved_state, resolved_action=action,
            events=collected_events,
        )

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

    def _emit_sandbox_state(sandbox, sid, events=None, is_initial=False):
        """Single source of truth for sandbox state emission. God view, no filter.

        Enriches pending_tutor / pending_death / pending_post_move_attack /
        pending_revive so the sandbox UI can render modals and target
        highlights. Sandbox is god-mode — whichever player the engine says
        should pick, we enrich from THEIR POV so the UI shows full picker
        state (valid targets + banner) regardless of which player the user
        is currently viewing as.

        Phase 14.8-05: the ``sandbox_state`` Socket.IO emit is now gated on
        ``is_initial=True`` — only the first frame on sandbox create / load
        / reset / slot-load emits the snapshot, so the client has something
        to render before any events flow. Every subsequent mutation-driven
        call (apply_action, apply_sandbox_edit, undo, redo, ...) emits ONLY
        ``engine_events``; DOM commits flow through the client's eventQueue
        slot handlers, not the snapshot path. The engine_events payload
        still carries final_state as the authoritative reconnect / error-
        recovery reference (stashed to window.__lastFinalState).

        Phase 14.8-03b (superseded by 14.8-05): previously emitted both
        sandbox_state AND engine_events on every call — the snapshot path
        raced the eventQueue and DOM jumped to the post-drain state before
        animations played. Gate removed that race.
        """
        state = sandbox.state
        state_dict = state.to_dict()
        enrich_pending_post_move_attack(state, state_dict, sandbox.library)
        # Mirror the real-multiplayer emit path: attach `last_action`
        # (type + attacker_pos + target_pos + damage + killed) so the client
        # can drive engine-action animations — in particular the sacrifice
        # transcend animation, whose client dispatcher keys off
        # `last_action.type === 'SACRIFICE'`. Without this call the sandbox
        # state has no `last_action` field and the client falls through to
        # the legacy `pending_action` path which only covers PLAY_CARD /
        # MOVE / ATTACK, silently dropping SACRIFICE (and any other future
        # action-keyed animations). prev_state / action are None outside
        # an engine action (zone edits, cheats, undo/redo) — `enrich_last_action`
        # handles that case by setting `last_action = None`.
        enrich_last_action(
            state_dict,
            sandbox.last_prev_state,
            state,
            sandbox.last_action,
        )
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
        # Phase 14.7-05: sandbox view always picks the picker's own POV so
        # the full picker_options payload appears in the sandbox UI.
        trigger_viewer = (
            state.pending_trigger_picker_idx
            if state.pending_trigger_picker_idx is not None
            else 0
        )
        enrich_pending_trigger_for_viewer(state, state_dict, trigger_viewer, sandbox.library)
        actions = sandbox.legal_actions() if not sandbox.state.is_game_over else ()
        serialized = [serialize_action(a) for a in actions]
        # Phase 14.8-05: sandbox_state emit is gated on is_initial. Initial
        # frames (sandbox_create, sandbox_load, sandbox_reset, slot-load,
        # test-scenario-load) need a snapshot so the client can render the
        # board before any events flow. Subsequent mutation-driven calls
        # emit engine_events ONLY; the client's eventQueue commits DOM.
        if is_initial:
            emit("sandbox_state", {
                "state": state_dict,
                "legal_actions": serialized,
                "active_view_idx": sandbox.active_view_idx,
                "undo_depth": sandbox.undo_depth,
                "redo_depth": sandbox.redo_depth,
            })
        # engine_events frame (sandbox is god-mode so no per-viewer
        # filtering is applied — both hands are face-up). Empty event list
        # still emits so the client gets a uniform pipeline and final_state
        # stays stashed for reconnect parity.
        if events is not None or not is_initial:
            spec_events = (
                filter_engine_events_for_viewer(
                    events, sandbox.active_view_idx, god_mode=True,
                )
                if events is not None else []
            )
            emit("engine_events", {
                "events": [ev.to_dict() for ev in spec_events],
                "final_state": state_dict,
                "legal_actions": serialized,
                "active_view_idx": sandbox.active_view_idx,
                "undo_depth": sandbox.undo_depth,
                "redo_depth": sandbox.redo_depth,
                "is_sandbox": True,
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
        # Phase 14.8-05: initial snapshot emit (client has nothing to render
        # until the first sandbox_state lands).
        _emit_sandbox_state(sandbox, request.sid, is_initial=True)

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
        # Phase 14.8-03b: the per-frame on_frame hack from commit 9c414f9
        # is REMOVED. apply_action now returns the full event list across
        # the user action + every drained auto-PASS as a SINGLE
        # EventStream — pacing comes from animation_duration_ms on each
        # event, not from socket-frame cadence. The client's eventQueue
        # (plan 04a) consumes the event list in seq order and drives
        # spell-stage / blip / banner animations from the events.
        # Old client (pre-04a) ignores 'engine_events' and continues
        # rendering from sandbox_state — for that path we still emit
        # sandbox_state ONCE at the end (collapsed-frame view, identical
        # to pre-9c414f9 behavior). The transient-signal regressions that
        # 9c414f9 worked around (last_trigger_blip clobber, REACT-phase
        # entries / exits) are handled by the new event stream — those
        # transitions emit dedicated events that the new client picks up
        # without needing per-frame state replay.
        with sandbox.lock:
            # Phase 14.8-05 M4: snapshot the sandbox state before resolve so
            # we can roll back on OutOfPhaseError. SandboxSession.apply_action
            # calls _push_undo() before invoking resolve_action, so the undo
            # stack has a recoverable frame even if the OutOfPhaseError branch
            # never gets to finish the replace(). Explicit state snapshot
            # here is belt-and-braces: we'll restore from it AND pop the
            # polluting undo frame so the user's undo history stays clean.
            saved_sandbox_state = sandbox._state
            saved_last_prev = sandbox.last_prev_state
            saved_last_action = sandbox.last_action
            try:
                events = sandbox.apply_action(action)
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
            except OutOfPhaseError as e:
                # Phase 14.8-05: strict-mode contract violation in sandbox.
                # Rollback: restore the pre-action state + clear the undo
                # frame we pushed, then emit a structured error. Sandbox
                # itself tags its own edits with "sandbox:" which BYPASSES
                # enforcement — so this branch only fires for real engine
                # actions (PLAY_CARD / MOVE / ATTACK / ...) submitted via
                # sandbox_apply_action whose phase the engine refused.
                sandbox._state = saved_sandbox_state
                sandbox._last_prev_state = saved_last_prev
                sandbox._last_action = saved_last_action
                # Pop the polluting undo frame pushed by apply_action().
                try:
                    if sandbox._undo:
                        sandbox._undo.pop()
                except Exception:
                    pass
                import logging as _logging
                _logging.getLogger("grid_tactics.server.events").error(
                    "OutOfPhaseError in handle_sandbox_apply_action: "
                    "source=%s phase=%s allowed=%s pending_required=%s",
                    e.contract_source,
                    e.phase.name if e.phase else None,
                    sorted(p.name for p in (e.allowed_phases or [])),
                    e.pending_required,
                )
                emit("error", {
                    "error_type": "phase_contract_violation",
                    "contract_source": e.contract_source,
                    "phase": e.phase.name if e.phase else None,
                    "allowed_phases": [
                        p.name for p in (e.allowed_phases or [])
                    ],
                    "pending_required": e.pending_required,
                    "unknown_source": bool(getattr(e, "unknown_source", False)),
                    "msg": (
                        f"Sandbox action rejected: contract violation "
                        f"({e.contract_source!r} not allowed in phase "
                        f"{e.phase.name if e.phase else 'unknown'})."
                    ),
                })
                return
            except Exception as e:
                import traceback
                print(f"[ERROR] sandbox apply_action: {e}", flush=True)
                traceback.print_exc()
                emit("error", {"msg": f"Server error: {e}"})
                return
        # ONE sandbox_state + ONE engine_events emit per call regardless
        # of how many auto-PASSes drained. This is the architectural
        # improvement the per-frame hack was unable to deliver.
        _emit_sandbox_state(sandbox, request.sid, events=events)

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
                events = sandbox.apply_sandbox_edit("add_card_to_zone", {
                    "player_idx": player_idx,
                    "card_numeric_id": card_numeric_id,
                    "zone": zone,
                })
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        # Phase 14.8-05: zone edits are user-controlled state mutations; treat
        # as initial so the client snaps to the new state without waiting
        # on an events-driven animation replay.
        _emit_sandbox_state(sandbox, request.sid, events=events, is_initial=True)

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
                events = sandbox.apply_sandbox_edit("place_on_board", {
                    "player_idx": player_idx,
                    "card_numeric_id": card_numeric_id,
                    "row": row,
                    "col": col,
                })
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        _emit_sandbox_state(sandbox, request.sid, events=events, is_initial=True)

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
                events = sandbox.apply_sandbox_edit("move_card_between_zones", {
                    "player_idx": player_idx,
                    "card_numeric_id": card_numeric_id,
                    "src_zone": src_zone,
                    "dst_zone": dst_zone,
                })
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        _emit_sandbox_state(sandbox, request.sid, events=events, is_initial=True)

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
                events = sandbox.apply_sandbox_edit("import_deck", {
                    "player_idx": player_idx,
                    "deck_card_ids": deck,
                })
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        _emit_sandbox_state(sandbox, request.sid, events=events, is_initial=True)

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
                events = sandbox.apply_sandbox_edit("set_player_field", {
                    "player_idx": player_idx,
                    "field": field,
                    "value": value,
                })
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        _emit_sandbox_state(sandbox, request.sid, events=events, is_initial=True)

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
                events = sandbox.apply_sandbox_edit("set_active", {
                    "player_idx": player_idx,
                })
            except ValueError as e:
                emit("error", {"msg": str(e)})
                return
        _emit_sandbox_state(sandbox, request.sid, events=events, is_initial=True)

    @socketio.on("sandbox_undo")
    def handle_sandbox_undo(_data=None):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        with sandbox.lock:
            events = sandbox.apply_sandbox_edit("undo", {})
        # Phase 14.8-05: undo/redo/reset are wholesale state replacements —
        # treat as initial so the client re-renders the snapshot directly
        # instead of waiting for the eventQueue (which has few/no events to
        # drive a full board replay).
        _emit_sandbox_state(sandbox, request.sid, events=events, is_initial=True)

    @socketio.on("sandbox_redo")
    def handle_sandbox_redo(_data=None):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        with sandbox.lock:
            events = sandbox.apply_sandbox_edit("redo", {})
        _emit_sandbox_state(sandbox, request.sid, events=events, is_initial=True)

    @socketio.on("sandbox_reset")
    def handle_sandbox_reset(_data=None):
        sandbox = _get_sandbox_or_error()
        if sandbox is None:
            return
        with sandbox.lock:
            events = sandbox.apply_sandbox_edit("reset", {})
        _emit_sandbox_state(sandbox, request.sid, events=events, is_initial=True)

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
        # Phase 14.8-05: load is an initial frame (fresh state, no events to drain).
        _emit_sandbox_state(sandbox, request.sid, is_initial=True)

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
        # Phase 14.8-05: slot-load is an initial frame (fresh state).
        _emit_sandbox_state(sandbox, request.sid, is_initial=True)

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

    # --- Tests tab: structured UAT survey --------------------------------
    # Test manifest lives at data/tests/tests.json; each test has a setup
    # op list executed against a fresh sandbox session. Results append to
    # data/tests/results.jsonl on the server. Everything reuses existing
    # SandboxSession primitives so the board renders exactly like sandbox.

    @socketio.on("tests_list")
    def handle_tests_list(_data=None):
        import json
        from pathlib import Path
        path = Path(__file__).resolve().parents[3] / "data" / "tests" / "tests.json"
        try:
            with open(path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            emit("error", {"msg": f"Failed to load tests manifest: {e}"})
            return
        # Only send what the client needs per-test (server keeps setup ops).
        tests = [
            {"id": t["id"], "title": t["title"]}
            for t in manifest.get("tests", [])
        ]
        emit("tests_list_result", {"tests": tests})

    @socketio.on("tests_load")
    def handle_tests_load(data):
        import json
        from pathlib import Path
        test_id = (data or {}).get("id")
        if not test_id:
            emit("error", {"msg": "tests_load requires 'id'"})
            return
        path = Path(__file__).resolve().parents[3] / "data" / "tests" / "tests.json"
        try:
            with open(path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            emit("error", {"msg": f"Failed to load tests manifest: {e}"})
            return
        test = next((t for t in manifest.get("tests", []) if t["id"] == test_id), None)
        if test is None:
            emit("error", {"msg": f"Unknown test id: {test_id}"})
            return

        # Ensure a sandbox session exists for this SID and reset it.
        sandbox = _room_manager.get_sandbox(request.sid)
        if sandbox is None:
            sandbox = _room_manager.create_sandbox(request.sid)
        with sandbox.lock:
            try:
                sandbox.reset()
                for op in test.get("setup", []):
                    _apply_test_op(sandbox, op)
            except (ValueError, KeyError, TypeError) as e:
                emit("error", {"msg": f"Test setup failed: {e}"})
                return
        # Phase 14.8-05: test-scenario load is an initial frame — push the
        # full snapshot so the board renders before any subsequent actions.
        _emit_sandbox_state(sandbox, request.sid, is_initial=True)
        emit("tests_scenario_loaded", {
            "id": test["id"],
            "title": test["title"],
            "instructions": test.get("instructions", ""),
            "expected": test.get("expected", ""),
            # Optional client hint — e.g. `{ "sacrifice_animation": "shatter" }`
            # picks which of the four transcend variants fires on the next
            # SACRIFICE. The client sets window.__sacrificeVariant from this.
            "client_hints": test.get("client_hints") or {},
        })

    @socketio.on("tests_submit_result")
    def handle_tests_submit_result(data):
        import datetime as _dt
        import json as _json
        if not isinstance(data, dict):
            emit("error", {"msg": "tests_submit_result requires a dict"})
            return
        entry = {
            "test_id": data.get("id", ""),
            "result": data.get("result", ""),
            "comment": (data.get("comment") or "").strip(),
            "timestamp": _dt.datetime.utcnow().isoformat() + "Z",
            "session_sid": request.sid,
        }
        if entry["result"] not in ("pass", "fail", "skip"):
            emit("error", {"msg": "result must be pass/fail/skip"})
            return
        path = _tests_results_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(entry) + "\n")
        except OSError as e:
            emit("error", {"msg": f"Failed to write result: {e}"})
            return
        emit("tests_result_saved", {"id": entry["test_id"], "result": entry["result"]})

    @socketio.on("tests_fetch_results")
    def handle_tests_fetch_results(_data=None):
        """Read the entire test result log and emit it back.

        Debug helper so the harness can pull UAT results without shell
        access to the Railway container. Parses one JSON line per entry;
        malformed lines are skipped silently. Tail-caps at the most recent
        500 entries to keep the payload sane.
        """
        import json as _json
        path = _tests_results_path()
        entries: list[dict] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(_json.loads(line))
                    except _json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        except OSError as e:
            emit("error", {"msg": f"Failed to read results: {e}"})
            return
        emit("tests_results_snapshot", {"entries": entries[-500:], "total": len(entries)})

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
