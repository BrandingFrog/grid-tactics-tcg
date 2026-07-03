"""Tests for fatigue fix: fatigue_counts moved from module global to GameState.

Proves:
  - GameState has fatigue_counts field defaulting to (0, 0)
  - Fatigue escalates correctly per player
  - Two independent GameStates have independent fatigue counters
  - Serialization roundtrip preserves fatigue_counts
  - Module-level _fatigue global no longer exists in action_resolver
"""

from dataclasses import replace

import pytest

from grid_tactics.board import Board
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.player import Player
from grid_tactics.types import STARTING_HP, STARTING_MANA


def _make_minimal_state(seed: int = 42, **overrides) -> GameState:
    """Create a minimal GameState for fatigue testing."""
    p1 = Player(
        side=PlayerSide.PLAYER_1,
        hp=STARTING_HP,
        current_mana=STARTING_MANA,
        max_mana=STARTING_MANA,
        hand=(),
        deck=(),
        grave=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2,
        hp=STARTING_HP,
        current_mana=STARTING_MANA,
        max_mana=STARTING_MANA,
        hand=(),
        deck=(),
        grave=(),
    )
    defaults = dict(
        board=Board.empty(),
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=seed,
    )
    defaults.update(overrides)
    return GameState(**defaults)


class TestFatigueInGameState:
    """Tests that fatigue_counts field exists and defaults correctly."""

    def test_fatigue_in_gamestate_defaults(self):
        """GameState should have fatigue_counts defaulting to (0, 0)."""
        state = _make_minimal_state()
        assert hasattr(state, "fatigue_counts")
        assert state.fatigue_counts == (0, 0)

    def test_fatigue_counts_is_tuple(self):
        """fatigue_counts should be a tuple for immutability."""
        state = _make_minimal_state()
        assert isinstance(state.fatigue_counts, tuple)


class TestPassIsFree:
    """Turn-structure redesign 2026-07: PASS is FREE — no fatigue damage
    and no fatigue_counts movement on pass. Fatigue now exists ONLY for
    empty-deck turn-start draws (escalating 10/20/30 via fatigue_counts;
    covered in tests/test_new_turn_structure.py)."""

    def test_pass_is_free_and_does_not_touch_fatigue(self):
        """Consecutive PASS actions deal NO damage and never move
        fatigue_counts. Two passes make a Handshake instead."""
        from grid_tactics.action_resolver import _apply_pass

        state = _make_minimal_state()
        initial_hp = state.players[0].hp

        state1 = _apply_pass(state)
        assert state1.players[0].hp == initial_hp
        assert state1.fatigue_counts == (0, 0)
        assert state1.consecutive_passes == 1

        state2 = _apply_pass(replace(state1, phase=TurnPhase.ACTION))
        assert state2.players[0].hp == initial_hp
        assert state2.fatigue_counts == (0, 0)
        # Second consecutive pass → Handshake detected, streak resets.
        assert state2.handshake_pending is True
        assert state2.consecutive_passes == 0

    def test_no_fatigue_constant_left(self):
        """The flat PASS fatigue constant was deleted with the behavior."""
        import grid_tactics.action_resolver as ar
        assert not hasattr(ar, "FATIGUE_DAMAGE")


class TestFatigueIndependentGames:
    """Tests that two GameStates with same seed have independent state."""

    def test_pass_streak_independent_games(self):
        """Applying PASS to one game should NOT affect another game."""
        from grid_tactics.action_resolver import _apply_pass

        game_a = _make_minimal_state(seed=42)
        game_b = _make_minimal_state(seed=42)

        # Apply PASS to game_a only
        game_a = _apply_pass(game_a)
        assert game_a.consecutive_passes == 1

        # game_b should be completely unaffected
        assert game_b.consecutive_passes == 0
        assert game_b.fatigue_counts == (0, 0)


class TestFatigueSerialization:
    """Tests that fatigue_counts roundtrips through to_dict/from_dict."""

    def test_fatigue_serialization(self):
        """fatigue_counts should survive to_dict -> from_dict roundtrip."""
        state = _make_minimal_state(fatigue_counts=(2, 1))
        d = state.to_dict()
        assert d["fatigue_counts"] == [2, 1]

        restored = GameState.from_dict(d)
        assert restored.fatigue_counts == (2, 1)

    def test_fatigue_deserialization_default(self):
        """from_dict with missing fatigue_counts should default to (0, 0)."""
        state = _make_minimal_state()
        d = state.to_dict()
        del d["fatigue_counts"]

        restored = GameState.from_dict(d)
        assert restored.fatigue_counts == (0, 0)


class TestNoGlobalFatigueDict:
    """Tests that the module-level _fatigue dict is gone."""

    def test_no_global_fatigue_dict(self):
        """action_resolver should NOT have a module-level _fatigue attribute."""
        import grid_tactics.action_resolver as ar
        assert not hasattr(ar, "_fatigue"), (
            "_fatigue module-level dict still exists -- should be removed"
        )
