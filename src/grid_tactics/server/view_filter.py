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
