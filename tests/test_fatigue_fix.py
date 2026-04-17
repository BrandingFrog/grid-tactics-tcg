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


class TestFatigueEscalates:
    """Tests that each PASS applies flat FATIGUE_DAMAGE (currently 5)."""

    def test_fatigue_escalates(self):
        """3 consecutive PASS actions each deal FATIGUE_DAMAGE."""
        from grid_tactics.card_library import CardLibrary
        from pathlib import Path
        from grid_tactics.action_resolver import _apply_pass, FATIGUE_DAMAGE

        CardLibrary.from_directory(Path("data/cards"))
        state = _make_minimal_state()

        initial_hp = state.players[0].hp

        state1 = _apply_pass(state)
        assert state1.players[0].hp == initial_hp - FATIGUE_DAMAGE
        assert state1.fatigue_counts == (1, 0)

        state2 = _apply_pass(replace(state1, phase=TurnPhase.ACTION))
        assert state2.players[0].hp == initial_hp - 2 * FATIGUE_DAMAGE
        assert state2.fatigue_counts == (2, 0)

        state3 = _apply_pass(replace(state2, phase=TurnPhase.ACTION))
        assert state3.players[0].hp == initial_hp - 3 * FATIGUE_DAMAGE
        assert state3.fatigue_counts == (3, 0)


class TestFatigueIndependentGames:
    """Tests that two GameStates with same seed have independent fatigue."""

    def test_fatigue_independent_games(self):
        """Applying PASS to one game should NOT affect another game's fatigue."""
        from grid_tactics.action_resolver import _apply_pass

        game_a = _make_minimal_state(seed=42)
        game_b = _make_minimal_state(seed=42)

        # Apply PASS to game_a only
        game_a = _apply_pass(game_a)
        assert game_a.fatigue_counts == (1, 0)

        # game_b should be completely unaffected
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
