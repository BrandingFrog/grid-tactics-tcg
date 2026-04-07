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
from grid_tactics.types import GRID_COLS, GRID_ROWS


def filter_state_for_player(state_dict: dict, viewer_idx: int) -> dict:
    """Filter a GameState dict for a specific player's view.

    Hides:
      - Opponent's hand contents (replaced with empty list + hand_count)
      - Both players' deck contents (replaced with empty list + deck_count)
      - RNG seed (removed entirely)

    Preserves:
      - Board, minions, HP, mana, graveyard, phase, turn_number,
        active_player_idx, react_player_idx, pending_action,
        fatigue_counts, winner, is_game_over, next_minion_id,
        react_stack -- all public info.

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
    Ranged (range>=1): orthogonal up to N tiles OR diagonal-adjacent.
    """
    if a_pos == d_pos:
        return False
    manhattan = Board.manhattan_distance(a_pos, d_pos)
    chebyshev = Board.chebyshev_distance(a_pos, d_pos)
    if attack_range == 0:
        return manhattan == 1 and _is_orthogonal(a_pos, d_pos)
    orthogonal_in_range = _is_orthogonal(a_pos, d_pos) and manhattan <= attack_range
    diagonal_adjacent = chebyshev == 1 and not _is_orthogonal(a_pos, d_pos)
    return orthogonal_in_range or diagonal_adjacent


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
