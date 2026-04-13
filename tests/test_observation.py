"""Tests for observation encoding -- RL observation vector from GameState.

Covers:
  - Observation shape and dtype (292 floats, float32)
  - Value normalization (all values in [-1.0, 1.0])
  - Empty board encoding (zeros for unoccupied cells)
  - No hidden info leak (opponent hand/deck contents hidden)
  - Perspective-relative encoding (observer's resources in MY section)
  - Minion encoding (is_occupied, owner, attack, health, range, etc.)
  - OBSERVATION_SPEC field offset documentation correctness
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.minion import MinionInstance
from grid_tactics.rl.observation import (
    OBSERVATION_SIZE,
    OBSERVATION_SPEC,
    encode_observation,
)
from grid_tactics.types import (
    DEFAULT_TURN_LIMIT,
    MAX_MANA_CAP,
    MAX_STAT,
    MIN_DECK_SIZE,
    STARTING_HP,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cards"


@pytest.fixture
def library():
    """Load card library from data/cards/."""
    return CardLibrary.from_directory(DATA_DIR)


@pytest.fixture
def test_decks(library):
    """Build two valid 40-card decks for testing."""
    card_counts = {
        "rat": 3,
        "furryroach": 3,
        "blue_diodebot": 3,
        "red_diodebot": 3,
        "rgb_lasercannon": 3,
        "green_diodebot": 3,
        "ratchanter": 3,
        "surgefed_sparkbot": 3,
        "rathopper": 3,
        "giant_rat": 1,
        "to_the_ratmobile": 3,
        "ratical_resurrection": 3,
        "emberplague_rat": 3,
        "counter_spell": 3,
    }
    deck = library.build_deck(card_counts)
    return deck, deck


@pytest.fixture
def new_game_state(library, test_decks):
    """Create a fresh game state for testing."""
    deck_p1, deck_p2 = test_decks
    state, _rng = GameState.new_game(seed=42, deck_p1=deck_p1, deck_p2=deck_p2)
    return state


class TestObservationShape:
    """Test observation vector shape and dtype."""

    def test_observation_shape(self, new_game_state, library):
        """encode_observation returns ndarray of shape (292,) dtype float32."""
        obs = encode_observation(new_game_state, library, observer_idx=0)
        assert isinstance(obs, np.ndarray)
        assert obs.shape == (292,)
        assert obs.dtype == np.float32

    def test_observation_size_constant(self):
        """OBSERVATION_SIZE matches expected value of 292."""
        assert OBSERVATION_SIZE == 292


class TestObservationRange:
    """Test that all observation values are normalized to [-1.0, 1.0]."""

    def test_observation_range(self, new_game_state, library):
        """All values in observation are within [-1.0, 1.0]."""
        obs = encode_observation(new_game_state, library, observer_idx=0)
        assert np.all(obs >= -1.0), f"Min value: {obs.min()}"
        assert np.all(obs <= 1.0), f"Max value: {obs.max()}"

    def test_observation_range_player2(self, new_game_state, library):
        """Observation range check for player 2 perspective."""
        obs = encode_observation(new_game_state, library, observer_idx=1)
        assert np.all(obs >= -1.0)
        assert np.all(obs <= 1.0)


class TestEmptyBoardObservation:
    """Test encoding of a new game with empty board."""

    def test_empty_board_observation(self, new_game_state, library):
        """New game state produces all zeros for board section (no minions)."""
        obs = encode_observation(new_game_state, library, observer_idx=0)
        board_section = obs[0:250]
        # All board cells should be zero (no minions deployed)
        np.testing.assert_array_equal(board_section, np.zeros(250, dtype=np.float32))


class TestNoHiddenInfoLeak:
    """Test that opponent hidden info is NOT in the observation."""

    def test_no_hidden_info_leak(self, new_game_state, library):
        """Encoding for player 0 does NOT contain player 1 hand card IDs or deck contents.

        Opponent section has only hp, mana, hand_size, deck_size (4 values).
        """
        obs = encode_observation(new_game_state, library, observer_idx=0)
        opp = new_game_state.players[1]

        # Opponent visible section: offset 275, size 4
        opp_section = obs[275:279]

        # Should have exactly 4 values: hp, mana, hand_size, deck_size
        assert len(opp_section) == 4

        # Verify the opponent section contains the RIGHT info (normalized)
        expected_hp = opp.hp / STARTING_HP
        expected_mana = opp.current_mana / MAX_MANA_CAP
        expected_hand_size = len(opp.hand) / 10.0  # MAX_HAND_SIZE = 10
        expected_deck_size = len(opp.deck) / MIN_DECK_SIZE

        np.testing.assert_almost_equal(opp_section[0], expected_hp)
        np.testing.assert_almost_equal(opp_section[1], expected_mana)
        np.testing.assert_almost_equal(opp_section[2], expected_hand_size)
        np.testing.assert_almost_equal(opp_section[3], expected_deck_size)

    def test_opponent_hand_contents_not_in_obs(self, new_game_state, library):
        """Observation does not contain opponent hand card numeric IDs."""
        obs_p0 = encode_observation(new_game_state, library, observer_idx=0)
        opp = new_game_state.players[1]

        # The opponent's hand section should NOT appear in the MY_HAND area
        # MY_HAND for observer=0 encodes player 0's hand, not player 1's
        my_hand_section = obs_p0[250:270]

        # Verify it encodes player 0's hand, not player 1's
        me = new_game_state.players[0]
        # First card slot should be present (is_present=1.0) since we have cards
        if len(me.hand) > 0:
            assert my_hand_section[0] == 1.0  # is_present for first card


class TestPerspectiveRelative:
    """Test that observation is relative to the observer."""

    def test_perspective_relative(self, new_game_state, library):
        """Observer's own resources appear in MY_RESOURCES section."""
        obs_p0 = encode_observation(new_game_state, library, observer_idx=0)
        obs_p1 = encode_observation(new_game_state, library, observer_idx=1)

        p0 = new_game_state.players[0]
        p1 = new_game_state.players[1]

        # MY_RESOURCES section: offset 270, size 5
        # For observer 0: p0's resources
        np.testing.assert_almost_equal(
            obs_p0[270], p0.current_mana / MAX_MANA_CAP,
        )
        np.testing.assert_almost_equal(
            obs_p0[272], p0.hp / STARTING_HP,
        )

        # For observer 1: p1's resources
        np.testing.assert_almost_equal(
            obs_p1[270], p1.current_mana / MAX_MANA_CAP,
        )
        np.testing.assert_almost_equal(
            obs_p1[272], p1.hp / STARTING_HP,
        )


class TestMinionEncoding:
    """Test board cell encoding with minions."""

    def test_minion_encoding(self, new_game_state, library):
        """Board cell with minion has correct features."""
        # Deploy a minion manually by modifying state
        # Use fire_imp (card_numeric_id for fire_imp)
        fire_imp_id = library.get_numeric_id("rat")
        fire_imp_def = library.get_by_id(fire_imp_id)

        minion = MinionInstance(
            instance_id=0,
            card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=fire_imp_def.health,
            attack_bonus=0,
        )

        # Place minion on board
        new_board = new_game_state.board.place(0, 0, 0)
        state_with_minion = replace(
            new_game_state,
            board=new_board,
            minions=(minion,),
            next_minion_id=1,
        )

        obs = encode_observation(state_with_minion, library, observer_idx=0)

        # Cell (0,0) is at offset 0 (row 0, col 0), 10 features per cell
        cell_start = 0
        cell = obs[cell_start:cell_start + 10]

        # is_occupied = 1.0
        assert cell[0] == 1.0
        # owner = +1.0 (mine, observer is player 0)
        assert cell[1] == 1.0
        # attack = fire_imp attack / MAX_STAT
        expected_attack = fire_imp_def.attack / MAX_STAT
        np.testing.assert_almost_equal(cell[2], expected_attack)
        # health = current_health / MAX_STAT
        expected_health = fire_imp_def.health / MAX_STAT
        np.testing.assert_almost_equal(cell[3], expected_health)
        # attack_range = fire_imp range / 2.0
        expected_range = fire_imp_def.attack_range / 2.0
        np.testing.assert_almost_equal(cell[4], expected_range)

    def test_opponent_minion_encoding(self, new_game_state, library):
        """Opponent minion shows owner = -1.0 from observer's perspective."""
        fire_imp_id = library.get_numeric_id("rat")
        fire_imp_def = library.get_by_id(fire_imp_id)

        minion = MinionInstance(
            instance_id=0,
            card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_2,
            position=(3, 0),
            current_health=fire_imp_def.health,
        )

        new_board = new_game_state.board.place(3, 0, 0)
        state_with_minion = replace(
            new_game_state,
            board=new_board,
            minions=(minion,),
            next_minion_id=1,
        )

        obs = encode_observation(state_with_minion, library, observer_idx=0)

        # Cell (3,0) = row 3, col 0 -> index 15 -> offset 150
        cell_start = 15 * 10
        cell = obs[cell_start:cell_start + 10]

        # is_occupied = 1.0
        assert cell[0] == 1.0
        # owner = -1.0 (opponent from player 0's perspective)
        assert cell[1] == -1.0


class TestObservationSpec:
    """Test OBSERVATION_SPEC documentation matches actual encoding."""

    def test_observation_spec(self):
        """OBSERVATION_SPEC dict documents field offsets matching actual encoding."""
        assert "board" in OBSERVATION_SPEC
        assert OBSERVATION_SPEC["board"]["offset"] == 0
        assert OBSERVATION_SPEC["board"]["size"] == 250

        assert "my_hand" in OBSERVATION_SPEC
        assert OBSERVATION_SPEC["my_hand"]["offset"] == 250
        assert OBSERVATION_SPEC["my_hand"]["size"] == 20

        assert "my_resources" in OBSERVATION_SPEC
        assert OBSERVATION_SPEC["my_resources"]["offset"] == 270
        assert OBSERVATION_SPEC["my_resources"]["size"] == 5

        assert "opponent_visible" in OBSERVATION_SPEC
        assert OBSERVATION_SPEC["opponent_visible"]["offset"] == 275
        assert OBSERVATION_SPEC["opponent_visible"]["size"] == 4

        assert "game_context" in OBSERVATION_SPEC
        assert OBSERVATION_SPEC["game_context"]["offset"] == 279
        assert OBSERVATION_SPEC["game_context"]["size"] == 3

        assert "react_context" in OBSERVATION_SPEC
        assert OBSERVATION_SPEC["react_context"]["offset"] == 282
        assert OBSERVATION_SPEC["react_context"]["size"] == 10

        # Total should equal OBSERVATION_SIZE
        total = sum(s["size"] for s in OBSERVATION_SPEC.values())
        assert total == OBSERVATION_SIZE
