"""Tests for action space encoding, decoding, masking, and reward.

Covers:
  - ACTION_SPACE_SIZE = 1287
  - Encode/decode round-trip for all 7 action types
  - Action mask shape and dtype
  - Mask matches legal_actions() for random states
  - PASS is always legal (mask always has at least one True bit)
  - Reward signal: +1 win, -1 loss, 0 in-progress/draw
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from grid_tactics.actions import (
    Action,
    attack_action,
    draw_action,
    move_action,
    pass_action,
    play_card_action,
    play_react_action,
    sacrifice_action,
)
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.rl.action_space import (
    ACTION_SPACE_SIZE,
    ActionEncoder,
    build_action_mask,
)
from grid_tactics.rl.reward import compute_reward
from grid_tactics.types import MIN_DECK_SIZE

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cards"


@pytest.fixture
def library():
    """Load card library from data/cards/."""
    return CardLibrary.from_directory(DATA_DIR)


@pytest.fixture
def encoder():
    """Create an ActionEncoder instance."""
    return ActionEncoder()


@pytest.fixture
def test_decks(library):
    """Build two valid 40-card decks for testing."""
    card_counts = {
        "fire_imp": 3,
        "shadow_stalker": 3,
        "dark_assassin": 3,
        "light_cleric": 3,
        "wind_archer": 3,
        "dark_sentinel": 3,
        "holy_paladin": 3,
        "iron_guardian": 3,
        "shadow_knight": 3,
        "stone_golem": 1,
        "fireball": 3,
        "holy_light": 3,
        "dark_drain": 3,
        "shield_block": 3,
    }
    deck = library.build_deck(card_counts)
    return deck, deck


@pytest.fixture
def new_game_state(library, test_decks):
    """Create a fresh game state for testing."""
    deck_p1, deck_p2 = test_decks
    state, _rng = GameState.new_game(seed=42, deck_p1=deck_p1, deck_p2=deck_p2)
    return state


@pytest.fixture
def new_game_rng(library, test_decks):
    """Create a fresh game state and return (state, rng) tuple."""
    deck_p1, deck_p2 = test_decks
    return GameState.new_game(seed=42, deck_p1=deck_p1, deck_p2=deck_p2)


class TestActionSpaceSize:
    """Test action space size constant."""

    def test_action_space_size(self):
        """ACTION_SPACE_SIZE == 1287 (1262 base + 25 ACTIVATE_ABILITY slots)."""
        assert ACTION_SPACE_SIZE == 1287


class TestEncodeDecodePASS:
    """Test PASS action encode/decode round-trip."""

    def test_encode_decode_pass(self, encoder, new_game_state):
        """PASS encodes to 1001, decodes back to Action(PASS)."""
        action = pass_action()
        encoded = encoder.encode(action, new_game_state)
        assert encoded == 1001

        decoded = encoder.decode(encoded, new_game_state, None)
        assert decoded.action_type == ActionType.PASS


class TestEncodeDecodeDRAW:
    """Test DRAW action encode/decode round-trip."""

    def test_encode_decode_draw(self, encoder, new_game_state):
        """DRAW encodes to 1000, decodes back to Action(DRAW)."""
        action = draw_action()
        encoded = encoder.encode(action, new_game_state)
        assert encoded == 1000

        decoded = encoder.decode(encoded, new_game_state, None)
        assert decoded.action_type == ActionType.DRAW


class TestEncodeDecodeMOVE:
    """Test MOVE action encode/decode round-trip."""

    def test_encode_decode_move(self, encoder, library):
        """MOVE at (1,2) direction down encodes/decodes correctly."""
        # Create a state with a minion at (1,2)
        fire_imp_id = library.get_numeric_id("fire_imp")
        fire_imp_def = library.get_by_id(fire_imp_id)

        minion = MinionInstance(
            instance_id=0,
            card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1,
            position=(1, 2),
            current_health=fire_imp_def.health,
        )

        from grid_tactics.board import Board
        from grid_tactics.player import Player
        from grid_tactics.types import STARTING_HP, STARTING_MANA

        board = Board.empty().place(1, 2, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=STARTING_MANA,
            max_mana=STARTING_MANA, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=STARTING_MANA,
            max_mana=STARTING_MANA, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2), active_player_idx=0,
            phase=TurnPhase.ACTION, turn_number=1, seed=42,
            minions=(minion,), next_minion_id=1,
        )

        # Move from (1,2) to (2,2) -- direction down (1,0) = dir index 1
        action = move_action(minion_id=0, position=(2, 2))
        encoded = encoder.encode(action, state)

        # source_flat = 1*5 + 2 = 7, direction = 1 (down)
        # expected = MOVE_BASE + source_flat * 4 + direction = 250 + 7*4 + 1 = 279
        assert encoded == 279

        decoded = encoder.decode(encoded, state, library)
        assert decoded.action_type == ActionType.MOVE
        assert decoded.minion_id == 0
        assert decoded.position == (2, 2)


class TestEncodeDecodeATTACK:
    """Test ATTACK action encode/decode round-trip."""

    def test_encode_decode_attack(self, encoder, library):
        """ATTACK from (1,2) to (2,2) encodes/decodes correctly."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        fire_imp_def = library.get_by_id(fire_imp_id)

        attacker = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2),
            current_health=fire_imp_def.health,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_2, position=(2, 2),
            current_health=fire_imp_def.health,
        )

        from grid_tactics.board import Board
        from grid_tactics.player import Player
        from grid_tactics.types import STARTING_HP, STARTING_MANA

        board = Board.empty().place(1, 2, 0).place(2, 2, 1)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=STARTING_MANA,
            max_mana=STARTING_MANA, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=STARTING_MANA,
            max_mana=STARTING_MANA, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2), active_player_idx=0,
            phase=TurnPhase.ACTION, turn_number=1, seed=42,
            minions=(attacker, defender), next_minion_id=2,
        )

        action = attack_action(minion_id=0, target_id=1)
        encoded = encoder.encode(action, state)

        # source_flat = 1*5+2 = 7, target_flat = 2*5+2 = 12
        # expected = ATTACK_BASE + source_flat*25 + target_flat = 350 + 7*25 + 12 = 537
        assert encoded == 537

        decoded = encoder.decode(encoded, state, library)
        assert decoded.action_type == ActionType.ATTACK
        assert decoded.minion_id == 0
        assert decoded.target_id == 1


class TestEncodeDecodePLAY_CARD:
    """Test PLAY_CARD action encode/decode round-trip."""

    def test_encode_decode_play_card(self, encoder, new_game_state, library):
        """PLAY_CARD for minion deploy encodes/decodes with correct position."""
        # Player 0 plays card at hand index 0 to position (0, 0)
        action = play_card_action(card_index=0, position=(0, 0))
        encoded = encoder.encode(action, new_game_state)

        # PLAY_CARD_BASE + hand_idx*25 + cell
        # = 0 + 0*25 + (0*5+0) = 0
        assert encoded == 0

        decoded = encoder.decode(encoded, new_game_state, library)
        assert decoded.action_type == ActionType.PLAY_CARD
        assert decoded.card_index == 0

    def test_encode_decode_play_card_magic_targeted(self, encoder, library):
        """PLAY_CARD for targeted magic encodes/decodes with target_pos."""
        # Create state where player has fireball in hand and enemy on board
        fireball_id = library.get_numeric_id("fireball")
        fire_imp_id = library.get_numeric_id("fire_imp")
        fire_imp_def = library.get_by_id(fire_imp_id)

        enemy_minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_2, position=(3, 0),
            current_health=fire_imp_def.health,
        )

        from grid_tactics.board import Board
        from grid_tactics.player import Player
        from grid_tactics.types import STARTING_HP

        board = Board.empty().place(3, 0, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=5,
            max_mana=5, hand=(fireball_id,), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=1,
            max_mana=1, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2), active_player_idx=0,
            phase=TurnPhase.ACTION, turn_number=1, seed=42,
            minions=(enemy_minion,), next_minion_id=1,
        )

        # Play fireball (hand index 0) targeting (3, 0)
        action = play_card_action(card_index=0, target_pos=(3, 0))
        encoded = encoder.encode(action, state)

        # PLAY_CARD_BASE + hand_idx*25 + cell = 0 + 0*25 + 15 = 15
        assert encoded == 15

        decoded = encoder.decode(encoded, state, library)
        assert decoded.action_type == ActionType.PLAY_CARD
        assert decoded.card_index == 0


class TestEncodeDecodeSACRIFICE:
    """Test SACRIFICE action encode/decode round-trip."""

    def test_encode_decode_sacrifice(self, encoder, library):
        """SACRIFICE at (4,3) encodes/decodes correctly."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        fire_imp_def = library.get_by_id(fire_imp_id)

        minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(4, 3),
            current_health=fire_imp_def.health,
        )

        from grid_tactics.board import Board
        from grid_tactics.player import Player
        from grid_tactics.types import STARTING_HP, STARTING_MANA

        board = Board.empty().place(4, 3, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=STARTING_MANA,
            max_mana=STARTING_MANA, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=STARTING_MANA,
            max_mana=STARTING_MANA, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2), active_player_idx=0,
            phase=TurnPhase.ACTION, turn_number=1, seed=42,
            minions=(minion,), next_minion_id=1,
        )

        action = sacrifice_action(minion_id=0)
        encoded = encoder.encode(action, state)

        # SACRIFICE_BASE + source_flat = 975 + (4*5+3) = 975 + 23 = 998
        assert encoded == 998

        decoded = encoder.decode(encoded, state, library)
        assert decoded.action_type == ActionType.SACRIFICE
        assert decoded.minion_id == 0


class TestEncodeDecodeREACT:
    """Test PLAY_REACT action encode/decode round-trip."""

    def test_encode_decode_react_targeted(self, encoder, library):
        """PLAY_REACT targeted encodes/decodes correctly."""
        # Create state in REACT phase with react card in hand
        counter_spell_id = library.get_numeric_id("counter_spell")
        fire_imp_id = library.get_numeric_id("fire_imp")
        fire_imp_def = library.get_by_id(fire_imp_id)

        enemy_minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 0),
            current_health=fire_imp_def.health,
        )

        from grid_tactics.board import Board
        from grid_tactics.player import Player
        from grid_tactics.types import STARTING_HP

        board = Board.empty().place(1, 0, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=5,
            max_mana=5, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=5,
            max_mana=5, hand=(counter_spell_id,), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2), active_player_idx=0,
            phase=TurnPhase.REACT, turn_number=1, seed=42,
            minions=(enemy_minion,), next_minion_id=1,
            react_player_idx=1,
        )

        # React with hand index 0, targeting (1,0)
        action = play_react_action(card_index=0, target_pos=(1, 0))
        encoded = encoder.encode(action, state)

        # REACT_BASE + hand_idx*26 + target_flat = 1002 + 0*26 + 5 = 1007
        assert encoded == 1007

        decoded = encoder.decode(encoded, state, library)
        assert decoded.action_type == ActionType.PLAY_REACT
        assert decoded.card_index == 0
        assert decoded.target_pos == (1, 0)

    def test_encode_decode_react_untargeted(self, encoder, library):
        """PLAY_REACT untargeted encodes/decodes correctly."""
        counter_spell_id = library.get_numeric_id("counter_spell")

        from grid_tactics.board import Board
        from grid_tactics.player import Player
        from grid_tactics.types import STARTING_HP

        board = Board.empty()
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=5,
            max_mana=5, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=5,
            max_mana=5, hand=(counter_spell_id,), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2), active_player_idx=0,
            phase=TurnPhase.REACT, turn_number=1, seed=42,
            react_player_idx=1,
        )

        # React with hand index 0, no target
        action = play_react_action(card_index=0)
        encoded = encoder.encode(action, state)

        # REACT_BASE + hand_idx*26 + 25 = 1002 + 0*26 + 25 = 1027
        assert encoded == 1027

        decoded = encoder.decode(encoded, state, library)
        assert decoded.action_type == ActionType.PLAY_REACT
        assert decoded.card_index == 0
        assert decoded.target_pos is None


class TestMaskShape:
    """Test action mask shape and dtype."""

    def test_mask_shape(self, new_game_state, library, encoder):
        """build_action_mask returns ndarray shape (1287,) dtype bool."""
        mask = build_action_mask(new_game_state, library, encoder)
        assert isinstance(mask, np.ndarray)
        assert mask.shape == (1287,)
        assert mask.dtype == np.bool_


class TestMaskMatchesLegal:
    """Test that mask matches legal_actions() for many game states."""

    def test_mask_matches_legal(self, library, encoder):
        """For 100 random game states, mask matches legal_actions() exactly."""
        card_counts = {
            "fire_imp": 3, "shadow_stalker": 3,
            "dark_assassin": 3, "light_cleric": 3,
            "wind_archer": 3, "dark_sentinel": 3,
            "holy_paladin": 3, "iron_guardian": 3,
            "shadow_knight": 3, "stone_golem": 1,
            "fireball": 3, "holy_light": 3,
            "dark_drain": 3, "shield_block": 3,
        }
        deck = library.build_deck(card_counts)

        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.rng import GameRNG

        for seed in range(100):
            state, rng = GameState.new_game(seed=seed, deck_p1=deck, deck_p2=deck)

            # Play a few random moves to get interesting states
            for _ in range(min(seed % 10 + 1, 20)):
                if state.is_game_over:
                    break
                actions = legal_actions(state, library)
                action = rng.choice(actions)
                state = resolve_action(state, action, library)

            if state.is_game_over:
                continue

            # Now test mask
            mask = build_action_mask(state, library, encoder)
            actions = legal_actions(state, library)

            # Count of unique encoded actions should match mask True bits
            # (multiple legal actions can map to same slot for targeted deploys)
            unique_encoded = set(encoder.encode(a, state) for a in actions)
            assert mask.sum() == len(unique_encoded), (
                f"Seed {seed}: mask has {mask.sum()} True bits "
                f"but {len(unique_encoded)} unique encoded actions "
                f"({len(actions)} raw legal actions)"
            )

            # Every legal action should have mask[encode(action)] == True
            for action in actions:
                idx = encoder.encode(action, state)
                assert mask[idx], (
                    f"Seed {seed}: legal action {action} encoded to {idx} "
                    f"but mask[{idx}] is False"
                )


class TestAlwaysHasLegal:
    """Test that mask always has at least one True bit."""

    def test_always_has_legal(self, new_game_state, library, encoder):
        """Mask always has at least one True bit (PASS is always legal)."""
        mask = build_action_mask(new_game_state, library, encoder)
        assert mask.any(), "Mask has no True bits"
        # Specifically, PASS (index 1001) should always be True
        assert mask[1001], "PASS action is not masked as legal"


class TestRewardSparse:
    """Test sparse reward signal."""

    def test_reward_in_progress(self, new_game_state):
        """In-progress game returns 0.0 reward."""
        reward = compute_reward(new_game_state, player_idx=0)
        assert reward == 0.0

    def test_reward_win(self, new_game_state):
        """Player who won gets +1.0 reward."""
        terminal_state = replace(
            new_game_state,
            is_game_over=True,
            winner=PlayerSide.PLAYER_1,
        )
        assert compute_reward(terminal_state, player_idx=0) == 1.0

    def test_reward_loss(self, new_game_state):
        """Player who lost gets -1.0 reward."""
        terminal_state = replace(
            new_game_state,
            is_game_over=True,
            winner=PlayerSide.PLAYER_1,
        )
        assert compute_reward(terminal_state, player_idx=1) == -1.0

    def test_reward_draw(self, new_game_state):
        """Draw returns 0.0 reward."""
        terminal_state = replace(
            new_game_state,
            is_game_over=True,
            winner=None,  # Draw
        )
        assert compute_reward(terminal_state, player_idx=0) == 0.0
        assert compute_reward(terminal_state, player_idx=1) == 0.0
