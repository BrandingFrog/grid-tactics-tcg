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
                "grave": [8],
                "exhaust": [15, 16],
            },
            {
                "side": 1,
                "hp": 95,
                "current_mana": 2,
                "max_mana": 4,
                "hand": [10, 11],
                "deck": [12, 13, 14],
                "grave": [17, 18, 19],
                "exhaust": [],
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
        """Board, minions, HP, mana, grave, phase, turn_number, active_player_idx all preserved."""
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
        # Grave preserved
        assert filtered["players"][0]["grave"] == [8]
        assert filtered["players"][1]["grave"] == [17, 18, 19]
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

    # -- Phase 14.5-03: piles serialization -------------------------------

    def test_view_filter_emits_both_graves(self):
        """Both players' graves are serialized as public card_numeric_id lists."""
        state = _make_state_dict()
        # Viewer is P0; both own and opponent grave must be present.
        filtered_p0 = filter_state_for_player(state, viewer_idx=0)
        assert filtered_p0["players"][0]["grave"] == [8]
        assert filtered_p0["players"][1]["grave"] == [17, 18, 19]
        # Symmetric from P1 perspective.
        filtered_p1 = filter_state_for_player(state, viewer_idx=1)
        assert filtered_p1["players"][0]["grave"] == [8]
        assert filtered_p1["players"][1]["grave"] == [17, 18, 19]

    def test_view_filter_emits_both_exhausts(self):
        """Both players' exhaust piles are serialized as public card_numeric_id lists."""
        state = _make_state_dict()
        filtered_p0 = filter_state_for_player(state, viewer_idx=0)
        assert filtered_p0["players"][0]["exhaust"] == [15, 16]
        assert filtered_p0["players"][1]["exhaust"] == []
        filtered_p1 = filter_state_for_player(state, viewer_idx=1)
        assert filtered_p1["players"][0]["exhaust"] == [15, 16]
        assert filtered_p1["players"][1]["exhaust"] == []

    def test_view_filter_hides_opponent_hand_ids(self):
        """Opponent hand must be count-only — no card identities leak.

        Hidden-info security property: under no code path does the filtered
        output contain the opponent's hand card ids. Only a hand_count int.
        """
        state = _make_state_dict()
        # P0 viewer — P1 hand must be stripped.
        filtered = filter_state_for_player(state, viewer_idx=0)
        opp = filtered["players"][1]
        assert opp["hand"] == []
        assert opp["hand_count"] == 2
        for leaked in (10, 11):
            assert leaked not in opp["hand"]
        # Symmetric P1 viewer — P0 hand must be stripped.
        filtered = filter_state_for_player(state, viewer_idx=1)
        opp = filtered["players"][0]
        assert opp["hand"] == []
        assert opp["hand_count"] == 3
        for leaked in (1, 2, 3):
            assert leaked not in opp["hand"]

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


# ---------------------------------------------------------------------------
# Auto-draw bug fix test (D-04/D-05)
# ---------------------------------------------------------------------------


class TestNoAutoDraw:
    """Verify auto-draw is guarded by AUTO_DRAW_ENABLED."""

    def test_no_auto_draw_on_turn_transition(self):
        """After turn transition, hand size does NOT increase when AUTO_DRAW_ENABLED=False.

        D-04/D-05: The auto-draw code in react_stack.resolve_react_stack must
        be guarded by AUTO_DRAW_ENABLED. With it False (default), no card is
        drawn at turn start during react resolution.
        """
        from pathlib import Path

        from grid_tactics import types as game_types
        from grid_tactics.actions import Action
        from grid_tactics.card_library import CardLibrary
        from grid_tactics.enums import ActionType, TurnPhase
        from grid_tactics.game_state import GameState
        from grid_tactics.react_stack import resolve_react_stack

        # Ensure AUTO_DRAW_ENABLED is False (the default)
        assert game_types.AUTO_DRAW_ENABLED is False

        library = CardLibrary.from_directory(Path("data/cards"))

        # Create a game and set up for react resolution
        deck = tuple(range(21)) * 2  # 42 cards for safety
        state, _rng = GameState.new_game(seed=99, deck_p1=deck, deck_p2=deck)

        # Record hand sizes BEFORE react resolution (which does the turn transition)
        # P0 is active. After resolve_react_stack, P1 becomes active.
        p1_hand_before = len(state.players[1].hand)
        p1_deck_before = len(state.players[1].deck)

        # Put state into REACT phase with empty stack (just a PASS resolve)
        from dataclasses import replace
        state = replace(
            state,
            phase=TurnPhase.REACT,
            react_player_idx=1,
            react_stack=(),
            pending_action=Action(action_type=ActionType.PASS),
        )

        # Resolve (PASS on empty stack -> advance turn)
        new_state = resolve_react_stack(state, library)

        # New active player should be P1 (was P0)
        assert new_state.active_player_idx == 1

        # P1's hand size should NOT have increased (no auto-draw)
        p1_hand_after = len(new_state.players[1].hand)
        assert p1_hand_after == p1_hand_before, (
            f"Hand grew from {p1_hand_before} to {p1_hand_after} -- "
            f"auto-draw fired when AUTO_DRAW_ENABLED=False"
        )

        # Deck size also unchanged (no card drawn)
        p1_deck_after = len(new_state.players[1].deck)
        assert p1_deck_after == p1_deck_before
