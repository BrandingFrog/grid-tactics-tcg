"""Per-player state view filter -- hides opponent hand, both decks, and seed.

Implements VIEW-01: hidden information filtering before every emission.
Same filter applies at game over as during gameplay (D-02).

Usage:
    state_dict = game_state.to_dict()
    filtered = filter_state_for_player(state_dict, viewer_idx=0)
    # filtered is safe to send to player 0
"""

from __future__ import annotations

import copy

from grid_tactics.board import Board
from grid_tactics.types import (
    BACK_ROW_P1, BACK_ROW_P2, GRID_COLS, GRID_ROWS,
    PLAYER_1_ROWS, PLAYER_2_ROWS,
)


def filter_state_for_player(state_dict: dict, viewer_idx: int) -> dict:
    """Filter a GameState dict for a specific player's view.

    Hides:
      - Opponent's hand contents (replaced with empty list + hand_count)
      - Both players' deck contents (replaced with empty list + deck_count)
      - RNG seed (removed entirely)

    Preserves:
      - Board, minions, HP, mana, phase, turn_number,
        active_player_idx, react_player_idx, pending_action,
        fatigue_counts, winner, is_game_over, next_minion_id,
        react_stack -- all public info.
      - Phase 14.5: BOTH players' ``graveyard`` and ``exhaust`` piles are
        serialized PUBLICLY as full card_numeric_id lists to every viewer.
        These piles are face-up info in Grid Tactics; only the opponent's
        hand (and both decks) remain hidden.

    Args:
        state_dict: Output of GameState.to_dict().
        viewer_idx: 0 or 1 -- which player is viewing.

    Returns:
        Deep-copied and filtered dict safe to send to the viewer.
    """
    filtered = copy.deepcopy(state_dict)

    opponent_idx = 1 - viewer_idx

    # Hide opponent hand: store count, then clear
    opp_player = filtered["players"][opponent_idx]
    opp_player["hand_count"] = len(opp_player["hand"])
    opp_player["hand"] = []

    # Hide both decks: store counts, then clear
    for player_dict in filtered["players"]:
        player_dict["deck_count"] = len(player_dict["deck"])
        player_dict["deck"] = []

    # Strip seed
    filtered.pop("seed", None)

    return filtered


def _is_orthogonal(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] == b[0] or a[1] == b[1]


def _tile_in_attack_range(
    a_pos: tuple[int, int], d_pos: tuple[int, int], attack_range: int
) -> bool:
    """Mirror of action_resolver._can_attack geometry, parameterized by range only.

    Melee (range=0): orthogonal-adjacent (manhattan == 1).
    Ranged (range>=1): star footprint -- orthogonal arm manhattan<=range+1
        OR diagonal arm |dr|==|dc| with chebyshev<=range.
    """
    if a_pos == d_pos:
        return False
    dr = abs(a_pos[0] - d_pos[0])
    dc = abs(a_pos[1] - d_pos[1])
    manhattan = dr + dc
    chebyshev = dr if dr > dc else dc
    if attack_range == 0:
        return manhattan == 1 and _is_orthogonal(a_pos, d_pos)
    orthogonal_in_range = _is_orthogonal(a_pos, d_pos) and manhattan <= attack_range + 1
    on_diagonal = dr == dc and dr >= 1 and chebyshev <= attack_range
    return orthogonal_in_range or on_diagonal


def enrich_last_action(
    state_dict: dict,
    prev_state,
    new_state,
    action,
) -> None:
    """Phase 14.3-04: Expose the just-resolved action to the client.

    Mutates state_dict in place. Adds a `last_action` field shaped as:

        {
            "type": "PLAY_CARD" | "MOVE" | "ATTACK" | "PASS" | ... ,
            "attacker_pos": [r, c] | None,
            "target_pos":   [r, c] | None,
            "damage":       int   | None,
            "killed":       bool,
        }

    For ATTACK actions we also compute the actual damage dealt and whether
    the target was killed by diffing the target minion between prev/new
    state. For non-attack actions damage/killed remain None/False but the
    field still flows so the client can branch on `type`.

    Safe to call with `prev_state=None` and/or `action=None` (e.g. initial
    frame, lobby/meta frames). In those cases `last_action` is set to None.
    """
    if action is None or prev_state is None:
        state_dict["last_action"] = None
        return

    try:
        atype = action.action_type
        atype_name = atype.name if hasattr(atype, "name") else str(atype)
    except Exception:
        state_dict["last_action"] = None
        return

    attacker_pos = None
    target_pos = None
    damage = None
    killed = False

    # Resolve attacker minion position from prev_state via minion_id when present.
    try:
        if action.minion_id is not None:
            m = prev_state.get_minion(action.minion_id)
            if m is not None:
                attacker_pos = [int(m.position[0]), int(m.position[1])]
    except Exception:
        pass

    if atype_name == "ATTACK":
        try:
            target_prev = prev_state.get_minion(action.target_id) if action.target_id is not None else None
            if target_prev is not None:
                target_pos = [int(target_prev.position[0]), int(target_prev.position[1])]
                target_new = new_state.get_minion(action.target_id) if new_state is not None else None
                if target_new is None:
                    damage = int(target_prev.current_health)
                    killed = True
                else:
                    delta = int(target_prev.current_health) - int(target_new.current_health)
                    damage = max(0, delta)
                    killed = False
        except Exception:
            pass
    elif atype_name == "MOVE":
        try:
            if action.position is not None:
                target_pos = [int(action.position[0]), int(action.position[1])]
        except Exception:
            pass
    elif atype_name == "PLAY_CARD":
        try:
            if action.position is not None:
                target_pos = [int(action.position[0]), int(action.position[1])]
        except Exception:
            pass

    state_dict["last_action"] = {
        "type": atype_name,
        "attacker_pos": attacker_pos,
        "target_pos": target_pos,
        "damage": damage,
        "killed": bool(killed),
    }


def enrich_pending_post_move_attack(state, state_dict: dict, library) -> None:
    """Add Phase 14.1 pending-post-move-attack fields to a serialized state dict.

    Mutates state_dict in place. Adds:
      - pending_post_move_attacker_id: int | None
      - pending_attack_range_tiles: list[[row, col]]  -- educational footprint
      - pending_attack_valid_targets: list[[row, col]] -- clickable enemy tiles

    When no pending state, attacker_id is None and the lists are empty.
    """
    pending_id = getattr(state, "pending_post_move_attacker_id", None)
    state_dict["pending_post_move_attacker_id"] = pending_id
    state_dict["pending_attack_range_tiles"] = []
    state_dict["pending_attack_valid_targets"] = []

    if pending_id is None:
        return

    attacker = state.get_minion(pending_id)
    if attacker is None:
        return
    try:
        card = library.get_by_id(attacker.card_numeric_id)
    except Exception:
        return
    attack_range = card.attack_range
    a_pos = tuple(attacker.position)

    range_tiles: list[list[int]] = []
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            if _tile_in_attack_range(a_pos, (r, c), attack_range):
                range_tiles.append([r, c])
    state_dict["pending_attack_range_tiles"] = range_tiles

    # Valid targets: subset of range tiles containing an enemy minion.
    valid_targets: list[list[int]] = []
    for m in state.minions:
        if m.owner == attacker.owner:
            continue
        m_pos = tuple(m.position)
        if _tile_in_attack_range(a_pos, m_pos, attack_range):
            valid_targets.append([m_pos[0], m_pos[1]])
    state_dict["pending_attack_valid_targets"] = valid_targets


def enrich_pending_tutor_for_viewer(
    state, filtered_dict: dict, viewer_idx: int, library
) -> None:
    """Add Phase 14.2 pending_tutor fields to a per-viewer filtered state dict.

    Asymmetric: the caster (whose turn-to-pick it is) gets the resolved match
    list with full card identities; the opponent only sees a count and the
    caster's player index. Always sets `pending_tutor_player_idx` so any
    client can detect that a tutor selection is in progress.

    Mutates filtered_dict in place. Adds:
      - pending_tutor_player_idx: int | None
      - pending_tutor_match_count: int                       (always)
      - pending_tutor_matches: list[{card_numeric_id, deck_idx, match_idx}]
            (caster only; empty list for opponent or when no pending)
      - pending_tutor_total_copies_owned: dict[str(card_id) -> int]
            (caster only; counts copies of each matching card across the
             caster's whole pool — deck + hand + board minions — at the
             moment the tutor was triggered)
    """
    pending_idx = getattr(state, "pending_tutor_player_idx", None)
    matches = getattr(state, "pending_tutor_matches", ()) or ()

    filtered_dict["pending_tutor_player_idx"] = pending_idx
    filtered_dict["pending_tutor_match_count"] = len(matches)
    filtered_dict["pending_tutor_matches"] = []
    filtered_dict["pending_tutor_total_copies_owned"] = {}

    if pending_idx is None or not matches:
        return

    if viewer_idx != pending_idx:
        # Opponent view — only the count is exposed.
        return

    caster = state.players[pending_idx]
    deck = list(caster.deck)

    resolved: list[dict] = []
    matching_card_ids: set[int] = set()
    for match_idx, deck_idx in enumerate(matches):
        if 0 <= deck_idx < len(deck):
            numeric_id = int(deck[deck_idx])
            resolved.append(
                {
                    "card_numeric_id": numeric_id,
                    "deck_idx": int(deck_idx),
                    "match_idx": int(match_idx),
                }
            )
            matching_card_ids.add(numeric_id)
    filtered_dict["pending_tutor_matches"] = resolved

    # Total copies owned across the caster's whole pool: deck + hand + board.
    # Used by the modal to render "X of Y copies remaining in deck".
    totals: dict[str, int] = {}
    pool: list[int] = []
    pool.extend(int(x) for x in caster.deck)
    pool.extend(int(x) for x in caster.hand)
    for m in state.minions:
        if m.owner == pending_idx:
            pool.append(int(m.card_numeric_id))
    for nid in pool:
        if nid in matching_card_ids:
            key = str(nid)
            totals[key] = totals.get(key, 0) + 1
    filtered_dict["pending_tutor_total_copies_owned"] = totals


def enrich_pending_conjure_deploy(
    state, filtered_dict: dict, viewer_idx: int, library
) -> None:
    """Add Phase 14.6 pending_conjure_deploy fields to a per-viewer filtered state dict.

    The deploying player sees which card they're placing and the valid deploy
    tiles. The opponent sees only that a conjure deploy is in progress.

    Mutates filtered_dict in place. Adds:
      - pending_conjure_deploy_player_idx: int | None
      - pending_conjure_deploy_card: int | None  (deployer only)
      - pending_conjure_deploy_positions: list[[row, col]]  (deployer only)
    """
    pending_idx = getattr(state, "pending_conjure_deploy_player_idx", None)
    card_nid = getattr(state, "pending_conjure_deploy_card", None)

    filtered_dict["pending_conjure_deploy_player_idx"] = pending_idx
    filtered_dict["pending_conjure_deploy_card"] = None
    filtered_dict["pending_conjure_deploy_positions"] = []

    if pending_idx is None or card_nid is None:
        return

    if viewer_idx != pending_idx:
        # Opponent view — only player index exposed.
        return

    filtered_dict["pending_conjure_deploy_card"] = card_nid

    # Compute valid deploy positions for the conjured card.
    try:
        card_def = library.get_by_id(card_nid)
    except Exception:
        return

    deployer_side = state.players[pending_idx].side
    if card_def.attack_range == 0:
        rows = PLAYER_1_ROWS if deployer_side.value == 0 else PLAYER_2_ROWS
    else:
        back_row = BACK_ROW_P1 if deployer_side.value == 0 else BACK_ROW_P2
        rows = (back_row,)

    positions: list[list[int]] = []
    for row in rows:
        for col in range(GRID_COLS):
            if state.board.get(row, col) is None:
                positions.append([row, col])
    filtered_dict["pending_conjure_deploy_positions"] = positions


def filter_state_for_spectator(
    state_dict: dict, god_mode: bool, perspective_idx: int = 0
) -> dict:
    """Filter game state for a spectator (Phase 14.4-02).

    god_mode=True: return a deep copy of the full state with no filtering.
      Both hands, both decks (with card order), and any pending tutor
      matches all remain visible. Adds top-level flag
      ``spectator_god_mode=True`` for client UI.

    god_mode=False: delegate to ``filter_state_for_player(state, perspective_idx)``.
      The spectator sees exactly what player ``perspective_idx`` sees
      (default 0 = Player 1's perspective). Inherits all hidden-info
      filtering rules including pending-tutor opponent stripping.

    Always adds top-level ``is_spectator=True`` so the client knows to
    enter spectator mode, plus ``spectator_perspective`` to record which
    seat the (non-god) view is anchored to.
    """
    if god_mode:
        filtered = copy.deepcopy(state_dict)
    else:
        filtered = filter_state_for_player(state_dict, perspective_idx)
    filtered["is_spectator"] = True
    filtered["spectator_god_mode"] = god_mode
    filtered["spectator_perspective"] = perspective_idx
    return filtered
