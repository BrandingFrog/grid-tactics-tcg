"""Tests for Phase 12 Plan 01: View filter, action codec, and auto-draw fix.

Tests VIEW-01 requirements:
  - filter_state_for_player: hidden info filtering
  - serialize_action / reconstruct_action: JSON round-trip
  - Auto-draw bug fix with AUTO_DRAW_ENABLED guard
"""
from pathlib import Path

import pytest

from grid_tactics.actions import Action
from grid_tactics.enums import ActionType
from grid_tactics.game_state import GameState
from grid_tactics.server.view_filter import filter_state_for_player
from grid_tactics.server.action_codec import serialize_action, reconstruct_action


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state_dict() -> dict:
    """Create a minimal state dict matching GameState.to_dict() output."""
    return {
        "board": [0] * 25,
        "players": [
            {
                "side": 0,
                "hp": 100,
                "current_mana": 3,
                "max_mana": 5,
                "hand": [1, 2, 3],
                "deck": [4, 5, 6, 7],
                "graveyard": [8],
            },
            {
                "side": 1,
                "hp": 95,
                "current_mana": 2,
                "max_mana": 4,
                "hand": [10, 11],
                "deck": [12, 13, 14],
                "graveyard": [],
            },
        ],
        "active_player_idx": 0,
        "phase": 0,
        "turn_number": 5,
        "seed": 42,
        "minions": [
            {
                "instance_id": 0,
                "card_numeric_id": 1,
                "owner": 0,
                "position": [2, 3],
                "current_health": 3,
                "attack_bonus": 0,
            }
        ],
        "next_minion_id": 1,
        "react_stack": [],
        "react_player_idx": None,
        "pending_action": None,
        "winner": None,
        "is_game_over": False,
        "fatigue_counts": [0, 0],
    }


# ---------------------------------------------------------------------------
# View Filter tests
# ---------------------------------------------------------------------------


class TestFilterStateForPlayer:
    """Tests for filter_state_for_player."""

    def test_opponent_hand_hidden_when_viewer_is_p0(self):
        """Opponent (P1) hand replaced with empty list + hand_count."""
        state = _make_state_dict()
        filtered = filter_state_for_player(state, viewer_idx=0)
        # Opponent is player 1
        opp = filtered["players"][1]
        assert opp["hand"] == []
        assert opp["hand_count"] == 2  # original had [10, 11]

    def test_opponent_hand_hidden_when_viewer_is_p1(self):
        """Opponent (P0) hand replaced with empty list + hand_count."""
        state = _make_state_dict()
        filtered = filter_state_for_player(state, viewer_idx=1)
        # Opponent is player 0
        opp = filtered["players"][0]
        assert opp["hand"] == []
        assert opp["hand_count"] == 3  # original had [1, 2, 3]

    def test_own_hand_intact(self):
        """Viewer's own hand remains with all card numeric IDs."""
        state = _make_state_dict()
        filtered = filter_state_for_player(state, viewer_idx=0)
        own = filtered["players"][0]
        assert own["hand"] == [1, 2, 3]

    def test_deck_hidden_for_both_players(self):
        """Both players' decks replaced with empty list + deck_count."""
        state = _make_state_dict()
        filtered = filter_state_for_player(state, viewer_idx=0)
        p0 = filtered["players"][0]
        p1 = filtered["players"][1]
        assert p0["deck"] == []
        assert p0["deck_count"] == 4  # original had [4, 5, 6, 7]
        assert p1["deck"] == []
        assert p1["deck_count"] == 3  # original had [12, 13, 14]

    def test_seed_removed(self):
        """Seed key stripped from filtered output."""
        state = _make_state_dict()
        filtered = filter_state_for_player(state, viewer_idx=0)
        assert "seed" not in filtered

    def test_public_fields_preserved(self):
        """Board, minions, HP, mana, graveyard, phase, turn_number, active_player_idx all preserved."""
        state = _make_state_dict()
        filtered = filter_state_for_player(state, viewer_idx=0)
        assert filtered["board"] == [0] * 25
        assert filtered["active_player_idx"] == 0
        assert filtered["phase"] == 0
        assert filtered["turn_number"] == 5
        assert len(filtered["minions"]) == 1
        assert filtered["minions"][0]["instance_id"] == 0
        # HP and mana preserved
        assert filtered["players"][0]["hp"] == 100
        assert filtered["players"][0]["current_mana"] == 3
        assert filtered["players"][0]["max_mana"] == 5
        assert filtered["players"][1]["hp"] == 95
        # Graveyard preserved
        assert filtered["players"][0]["graveyard"] == [8]
        assert filtered["players"][1]["graveyard"] == []
        # Fatigue counts preserved
        assert filtered["fatigue_counts"] == [0, 0]
        # Winner and game over preserved
        assert filtered["winner"] is None
        assert filtered["is_game_over"] is False

    def test_game_over_filter_same(self):
        """Same filtering applies when state.is_game_over is True (D-02)."""
        state = _make_state_dict()
        state["is_game_over"] = True
        state["winner"] = 0
        filtered = filter_state_for_player(state, viewer_idx=0)
        # Opponent hand still hidden at game over
        opp = filtered["players"][1]
        assert opp["hand"] == []
        assert opp["hand_count"] == 2
        # Seed still removed
        assert "seed" not in filtered
        # Decks still hidden
        assert filtered["players"][0]["deck"] == []
        assert filtered["players"][1]["deck"] == []

    def test_react_player_idx_preserved(self):
        """react_player_idx preserved (needed by client)."""
        state = _make_state_dict()
        state["react_player_idx"] = 1
        filtered = filter_state_for_player(state, viewer_idx=0)
        assert filtered["react_player_idx"] == 1

    def test_pending_action_preserved(self):
        """pending_action preserved (needed by client)."""
        state = _make_state_dict()
        state["pending_action"] = {"action_type": 0, "card_index": 2}
        filtered = filter_state_for_player(state, viewer_idx=0)
        assert filtered["pending_action"] == {"action_type": 0, "card_index": 2}

    def test_original_state_not_mutated(self):
        """Filtering does not modify the original state dict."""
        state = _make_state_dict()
        original_hand = list(state["players"][1]["hand"])
        original_deck = list(state["players"][0]["deck"])
        filter_state_for_player(state, viewer_idx=0)
        assert state["players"][1]["hand"] == original_hand
        assert state["players"][0]["deck"] == original_deck
        assert "seed" in state


# ---------------------------------------------------------------------------
# Action Codec tests
# ---------------------------------------------------------------------------


class TestActionCodec:
    """Tests for serialize_action and reconstruct_action."""

    def test_round_trip_pass(self):
        """PASS action round-trips (serialize then reconstruct equals original)."""
        action = Action(action_type=ActionType.PASS)
        data = serialize_action(action)
        result = reconstruct_action(data)
        assert result == action

    def test_round_trip_draw(self):
        """DRAW action round-trips."""
        action = Action(action_type=ActionType.DRAW)
        data = serialize_action(action)
        result = reconstruct_action(data)
        assert result == action

    def test_round_trip_play_card(self):
        """PLAY_CARD with card_index and position round-trips."""
        action = Action(
            action_type=ActionType.PLAY_CARD,
            card_index=2,
            position=(1, 3),
        )
        data = serialize_action(action)
        result = reconstruct_action(data)
        assert result == action

    def test_round_trip_move(self):
        """MOVE with minion_id and position round-trips."""
        action = Action(
            action_type=ActionType.MOVE,
            minion_id=5,
            position=(3, 2),
        )
        data = serialize_action(action)
        result = reconstruct_action(data)
        assert result == action

    def test_round_trip_attack(self):
        """ATTACK with minion_id and target_id round-trips."""
        action = Action(
            action_type=ActionType.ATTACK,
            minion_id=1,
            target_id=7,
        )
        data = serialize_action(action)
        result = reconstruct_action(data)
        assert result == action

    def test_round_trip_sacrifice(self):
        """SACRIFICE with minion_id round-trips."""
        action = Action(
            action_type=ActionType.SACRIFICE,
            minion_id=3,
        )
        data = serialize_action(action)
        result = reconstruct_action(data)
        assert result == action

    def test_round_trip_play_react(self):
        """PLAY_REACT with card_index round-trips."""
        action = Action(
            action_type=ActionType.PLAY_REACT,
            card_index=0,
        )
        data = serialize_action(action)
        result = reconstruct_action(data)
        assert result == action

    def test_round_trip_play_react_with_target(self):
        """PLAY_REACT with card_index and target_pos round-trips."""
        action = Action(
            action_type=ActionType.PLAY_REACT,
            card_index=1,
            target_pos=(4, 2),
        )
        data = serialize_action(action)
        result = reconstruct_action(data)
        assert result == action

    def test_round_trip_play_card_all_fields(self):
        """PLAY_CARD with card_index, position, and target_pos round-trips."""
        action = Action(
            action_type=ActionType.PLAY_CARD,
            card_index=0,
            position=(0, 1),
            target_pos=(3, 3),
        )
        data = serialize_action(action)
        result = reconstruct_action(data)
        assert result == action

    def test_reconstruct_raises_on_missing_action_type(self):
        """reconstruct_action raises ValueError on missing action_type."""
        with pytest.raises(ValueError, match="action_type"):
            reconstruct_action({"card_index": 2})

    def test_reconstruct_raises_on_non_dict(self):
        """reconstruct_action raises ValueError on non-dict input."""
        with pytest.raises(ValueError):
            reconstruct_action("not a dict")
        with pytest.raises(ValueError):
            reconstruct_action(42)
        with pytest.raises(ValueError):
            reconstruct_action(None)

    def test_serialize_omits_none_fields(self):
        """serialize_action omits None fields (compact JSON)."""
        action = Action(action_type=ActionType.PASS)
        data = serialize_action(action)
        assert "action_type" in data
        assert "card_index" not in data
        assert "position" not in data
        assert "minion_id" not in data
        assert "target_id" not in data
        assert "target_pos" not in data

    def test_serialize_converts_tuples_to_lists(self):
        """serialize_action converts tuple positions to lists for JSON."""
        action = Action(
            action_type=ActionType.PLAY_CARD,
            card_index=0,
            position=(1, 2),
            target_pos=(3, 4),
        )
        data = serialize_action(action)
        assert data["position"] == [1, 2]
        assert data["target_pos"] == [3, 4]
