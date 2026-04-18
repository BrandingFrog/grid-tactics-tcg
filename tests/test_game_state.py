"""Tests for GameState dataclass."""

import dataclasses
import json

import pytest

from grid_tactics.actions import Action, pass_action
from grid_tactics.board import Board
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.types import (
    STARTING_HAND_P1,
    STARTING_HAND_P2,
    STARTING_HP,
    STARTING_MANA,
)


# Standard test decks (40 cards each, per deck size rules)
DECK_P1 = tuple(range(1, 41))
DECK_P2 = tuple(range(101, 141))


class TestNewGame:
    """Tests for GameState.new_game() factory."""

    def test_new_game_creates_valid_state(self):
        """new_game creates a state with empty board, correct HP and mana.

        Both players start their first action with STARTING_MANA. P2's
        first-turn regen is suppressed in react_stack so both players
        get the same mana on their first action (P1 turn 1, P2 turn 2).
        """
        state, rng = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.board == Board.empty()
        for player in state.players:
            assert player.hp == STARTING_HP
            assert player.max_mana == STARTING_MANA
            assert player.current_mana == STARTING_MANA

    def test_new_game_starting_hands(self):
        """Audit-followup: P1 draws STARTING_HAND_P1 (3), P2 draws STARTING_HAND_P2 (4)."""
        state, rng = GameState.new_game(42, DECK_P1, DECK_P2)
        assert len(state.players[0].hand) == STARTING_HAND_P1
        assert len(state.players[1].hand) == STARTING_HAND_P2

    def test_new_game_deck_reduced(self):
        """Audit-followup: deck reduced by P1/P2 starting-hand sizes."""
        state, rng = GameState.new_game(42, DECK_P1, DECK_P2)
        assert len(state.players[0].deck) == len(DECK_P1) - STARTING_HAND_P1
        assert len(state.players[1].deck) == len(DECK_P2) - STARTING_HAND_P2

    def test_new_game_turn_1(self):
        """New game starts at turn 1, ACTION phase, player 0 active."""
        state, rng = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.turn_number == 1
        assert state.phase == TurnPhase.ACTION
        assert state.active_player_idx == 0

    def test_new_game_deterministic_same_seed(self):
        """Same seed produces identical GameState (ENG-11)."""
        state1, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        state2, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state1 == state2

    def test_new_game_deterministic_different_seed(self):
        """Different seeds produce different deck orderings."""
        state1, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        state2, _ = GameState.new_game(99, DECK_P1, DECK_P2)
        # Decks and/or hands should differ
        assert (
            state1.players[0].hand != state2.players[0].hand
            or state1.players[0].deck != state2.players[0].deck
        )

    def test_seed_stored(self):
        """state.seed equals the seed passed to new_game."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.seed == 42

    def test_new_game_player_sides(self):
        """Player 1 has PLAYER_1 side, Player 2 has PLAYER_2 side."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.players[0].side == PlayerSide.PLAYER_1
        assert state.players[1].side == PlayerSide.PLAYER_2


class TestGameStateImmutability:
    """Tests for frozen dataclass behavior."""

    def test_game_state_is_frozen(self):
        """Attribute assignment raises FrozenInstanceError."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        with pytest.raises(AttributeError):
            state.turn_number = 5  # type: ignore[misc]

    def test_game_state_is_frozen_board(self):
        """Cannot reassign board field."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        with pytest.raises(AttributeError):
            state.board = Board.empty()  # type: ignore[misc]


class TestProperties:
    """Tests for active/inactive player properties."""

    def test_active_player_property(self):
        """active_player returns correct player based on active_player_idx."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.active_player == state.players[0]
        assert state.active_player.side == PlayerSide.PLAYER_1

    def test_inactive_player_property(self):
        """inactive_player returns the other player."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.inactive_player == state.players[1]
        assert state.inactive_player.side == PlayerSide.PLAYER_2


class TestSerialization:
    """Tests for to_dict/from_dict round-trip."""

    def test_to_dict_round_trip(self):
        """to_dict() then from_dict() produces equal GameState."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert restored == state

    def test_to_dict_is_json_serializable(self):
        """json.dumps(state.to_dict()) does not raise."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = state.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

    def test_from_dict_reconstructs_types(self):
        """from_dict correctly reconstructs enums and tuples."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert isinstance(restored.phase, TurnPhase)
        assert isinstance(restored.players[0].side, PlayerSide)
        assert isinstance(restored.players[0].hand, tuple)
        assert isinstance(restored.board.cells, tuple)


class TestSerializationPhase14_7_02:
    """Phase 14.7-02: react_context + react_return_phase round-trip."""

    def test_defaults_none(self):
        """Fresh game has both fields default to None."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.react_context is None
        assert state.react_return_phase is None

    def test_serialize_new_phase_fields(self):
        """A state mid-react with context + return_phase round-trips."""
        from grid_tactics.enums import ReactContext

        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        state = dataclasses.replace(
            state,
            phase=TurnPhase.REACT,
            react_context=ReactContext.AFTER_ACTION,
            react_return_phase=TurnPhase.ACTION,
        )

        d = state.to_dict()
        # JSON-serializable
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        # Verify raw dict uses ints
        assert d["react_context"] == int(ReactContext.AFTER_ACTION)
        assert d["react_return_phase"] == int(TurnPhase.ACTION)

        restored = GameState.from_dict(d)
        assert restored.react_context == ReactContext.AFTER_ACTION
        assert isinstance(restored.react_context, ReactContext)
        assert restored.react_return_phase == TurnPhase.ACTION
        assert isinstance(restored.react_return_phase, TurnPhase)
        assert restored == state

    def test_serialize_new_phase_fields_none_preserved(self):
        """None round-trips as None (no KeyError on old dicts)."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = state.to_dict()
        # Omit the keys (simulates an older dict)
        d.pop("react_context", None)
        d.pop("react_return_phase", None)
        restored = GameState.from_dict(d)
        assert restored.react_context is None
        assert restored.react_return_phase is None

    def test_serialize_end_of_turn_return(self):
        """react_return_phase=END_OF_TURN round-trips (new enum value)."""
        from grid_tactics.enums import ReactContext

        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        state = dataclasses.replace(
            state,
            phase=TurnPhase.REACT,
            react_context=ReactContext.BEFORE_END_OF_TURN,
            react_return_phase=TurnPhase.END_OF_TURN,
        )
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert restored.react_context == ReactContext.BEFORE_END_OF_TURN
        assert restored.react_return_phase == TurnPhase.END_OF_TURN


# ---------------------------------------------------------------------------
# Phase 3: Extended GameState tests
# ---------------------------------------------------------------------------


class TestGameStatePhase3Defaults:
    """Tests for the Phase 3 fields and their default values."""

    def test_new_game_empty_minions(self):
        """new_game() returns state with empty minions tuple."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.minions == ()

    def test_new_game_next_minion_id_zero(self):
        """new_game() returns state with next_minion_id=0."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.next_minion_id == 0

    def test_new_game_empty_react_stack(self):
        """new_game() returns state with empty react_stack."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.react_stack == ()

    def test_new_game_react_player_idx_none(self):
        """new_game() returns state with react_player_idx=None."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.react_player_idx is None

    def test_new_game_pending_action_none(self):
        """new_game() returns state with pending_action=None."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.pending_action is None


class TestGameStateWithMinions:
    """Tests for GameState with minions added via replace()."""

    def test_replace_adds_minions(self):
        """dataclasses.replace() can add minions to the state."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=5,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=3,
        )
        new_state = dataclasses.replace(state, minions=(m,), next_minion_id=1)
        assert len(new_state.minions) == 1
        assert new_state.minions[0] == m
        assert new_state.next_minion_id == 1

    def test_replace_preserves_other_fields(self):
        """Adding minions via replace() does not alter other fields."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m = MinionInstance(0, 0, PlayerSide.PLAYER_1, (0, 0), 3)
        new_state = dataclasses.replace(state, minions=(m,))
        assert new_state.board == state.board
        assert new_state.players == state.players
        assert new_state.turn_number == state.turn_number


class TestGetMinion:
    """Tests for GameState.get_minion() helper."""

    def test_get_existing_minion(self):
        """get_minion returns the MinionInstance with matching instance_id."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m1 = MinionInstance(0, 5, PlayerSide.PLAYER_1, (0, 0), 3)
        m2 = MinionInstance(1, 6, PlayerSide.PLAYER_2, (4, 4), 4)
        state = dataclasses.replace(state, minions=(m1, m2))
        assert state.get_minion(0) == m1
        assert state.get_minion(1) == m2

    def test_get_nonexistent_minion(self):
        """get_minion returns None for non-existent instance_id."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.get_minion(99) is None

    def test_get_minion_empty_state(self):
        """get_minion returns None on a state with no minions."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.get_minion(0) is None


class TestGetMinionsForSide:
    """Tests for GameState.get_minions_for_side() helper."""

    def test_get_minions_for_player_1(self):
        """get_minions_for_side returns only Player 1's minions."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m1 = MinionInstance(0, 5, PlayerSide.PLAYER_1, (0, 0), 3)
        m2 = MinionInstance(1, 6, PlayerSide.PLAYER_2, (4, 4), 4)
        m3 = MinionInstance(2, 7, PlayerSide.PLAYER_1, (1, 1), 2)
        state = dataclasses.replace(state, minions=(m1, m2, m3))
        result = state.get_minions_for_side(PlayerSide.PLAYER_1)
        assert len(result) == 2
        assert m1 in result
        assert m3 in result

    def test_get_minions_for_empty_side(self):
        """get_minions_for_side returns empty tuple if no minions for that side."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m1 = MinionInstance(0, 5, PlayerSide.PLAYER_1, (0, 0), 3)
        state = dataclasses.replace(state, minions=(m1,))
        result = state.get_minions_for_side(PlayerSide.PLAYER_2)
        assert result == ()

    def test_get_minions_for_side_no_minions(self):
        """get_minions_for_side returns empty tuple on empty state."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.get_minions_for_side(PlayerSide.PLAYER_1) == ()


class TestSerializationPhase3:
    """Tests for to_dict/from_dict with Phase 3 fields."""

    def test_round_trip_with_minions(self):
        """to_dict/from_dict round-trip preserves minions."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m = MinionInstance(0, 5, PlayerSide.PLAYER_1, (0, 0), 3, attack_bonus=1)
        board = state.board.place(0, 0, 0)
        state = dataclasses.replace(
            state,
            board=board,
            minions=(m,),
            next_minion_id=1,
        )
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert restored.minions == state.minions
        assert restored.next_minion_id == state.next_minion_id
        assert restored.minions[0].attack_bonus == 1

    def test_round_trip_with_pending_action(self):
        """to_dict/from_dict round-trip preserves pending_action."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        action = Action(ActionType.MOVE, minion_id=1, position=(2, 3))
        state = dataclasses.replace(state, pending_action=action)
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert restored.pending_action == action
        assert restored.pending_action.action_type == ActionType.MOVE
        assert restored.pending_action.minion_id == 1
        assert restored.pending_action.position == (2, 3)

    def test_round_trip_no_pending_action(self):
        """to_dict/from_dict round-trip preserves None pending_action."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert restored.pending_action is None

    def test_round_trip_with_react_fields(self):
        """to_dict/from_dict round-trip preserves react fields."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        state = dataclasses.replace(state, react_player_idx=1)
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert restored.react_player_idx == 1

    def test_round_trip_json_serializable_with_minions(self):
        """json.dumps works with Phase 3 fields populated."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m = MinionInstance(0, 5, PlayerSide.PLAYER_1, (0, 0), 3)
        board = state.board.place(0, 0, 0)
        state = dataclasses.replace(state, board=board, minions=(m,))
        d = state.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

    def test_from_dict_backward_compatible(self):
        """from_dict handles dicts without Phase 3 fields (backward compat)."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = {
            "board": list(state.board.cells),
            "players": [
                {
                    "side": int(p.side),
                    "hp": p.hp,
                    "current_mana": p.current_mana,
                    "max_mana": p.max_mana,
                    "hand": list(p.hand),
                    "deck": list(p.deck),
                    "grave": list(p.grave),
                }
                for p in state.players
            ],
            "active_player_idx": state.active_player_idx,
            "phase": int(state.phase),
            "turn_number": state.turn_number,
            "seed": state.seed,
        }
        restored = GameState.from_dict(d)
        assert restored.minions == ()
        assert restored.next_minion_id == 0
        assert restored.react_stack == ()
        assert restored.react_player_idx is None
        assert restored.pending_action is None

    def test_react_entry_roundtrip_preserves_originator_fields(self):
        """Phase 14.7-01: to_dict/from_dict round-trips ReactEntry originator fields.

        Covers a stack with:
          - One standard react entry (is_originator=False, legacy fields only)
          - One magic_cast originator (is_originator=True, full payload)
        Asserts every new field survives JSON round-trip (dict -> json -> dict).
        """
        from grid_tactics.react_stack import ReactEntry

        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)

        # Standard react entry (pre-14.7 shape)
        react_entry = ReactEntry(
            player_idx=1,
            card_index=2,
            card_numeric_id=99,
            target_pos=(3, 4),
        )

        # Magic-cast originator (14.7-01 shape)
        originator = ReactEntry(
            player_idx=0,
            card_index=-1,
            card_numeric_id=46,  # acidic_rain stable_id
            target_pos=None,
            is_originator=True,
            origin_kind="magic_cast",
            source_minion_id=None,
            effect_payload=(
                (0, None, 0),
                (1, (2, 3), 0),
            ),
            destroyed_attack=5,
            destroyed_dm=2,
        )

        state = dataclasses.replace(
            state,
            react_stack=(originator, react_entry),
            react_player_idx=1,
            phase=TurnPhase.REACT,
        )

        # Round-trip through JSON to verify the payload is wire-safe.
        d = state.to_dict()
        json_str = json.dumps(d)
        restored_d = json.loads(json_str)
        restored = GameState.from_dict(restored_d)

        assert len(restored.react_stack) == 2
        r_origin, r_react = restored.react_stack

        # Originator round-trip
        assert r_origin.is_originator is True
        assert r_origin.origin_kind == "magic_cast"
        assert r_origin.source_minion_id is None
        assert r_origin.card_numeric_id == 46
        assert r_origin.card_index == -1
        assert r_origin.target_pos is None
        assert r_origin.effect_payload == (
            (0, None, 0),
            (1, (2, 3), 0),
        )
        assert r_origin.destroyed_attack == 5
        assert r_origin.destroyed_dm == 2

        # Standard react entry round-trip — new fields default to legacy values
        assert r_react.is_originator is False
        assert r_react.origin_kind is None
        assert r_react.source_minion_id is None
        assert r_react.effect_payload is None
        assert r_react.destroyed_attack == 0
        assert r_react.destroyed_dm == 0
        assert r_react.player_idx == 1
        assert r_react.card_index == 2
        assert r_react.card_numeric_id == 99
        assert r_react.target_pos == (3, 4)


class TestSerializationPhase14_7_05:
    """Phase 14.7-05: pending_trigger_queue_{turn,other} + picker_idx round-trip."""

    def test_defaults_empty(self):
        """Fresh game has empty queues and picker_idx=None."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.pending_trigger_queue_turn == ()
        assert state.pending_trigger_queue_other == ()
        assert state.pending_trigger_picker_idx is None

    def test_serialize_pending_trigger_queue(self):
        """Round-trip a state carrying queue entries + picker_idx."""
        from grid_tactics.game_state import PendingTrigger

        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        turn_trigger = PendingTrigger(
            trigger_kind="start_of_turn",
            source_minion_id=5,
            source_card_numeric_id=9,
            effect_idx=0,
            owner_idx=0,
            captured_position=(2, 3),
            target_pos=None,
        )
        other_trigger = PendingTrigger(
            trigger_kind="end_of_turn",
            source_minion_id=7,
            source_card_numeric_id=11,
            effect_idx=1,
            owner_idx=1,
            captured_position=(4, 2),
            target_pos=(0, 1),
        )
        state = dataclasses.replace(
            state,
            pending_trigger_queue_turn=(turn_trigger,),
            pending_trigger_queue_other=(other_trigger,),
            pending_trigger_picker_idx=0,
        )

        d = state.to_dict()
        # JSON-serializable
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

        restored = GameState.from_dict(d)
        # Whole-state equality — strict round-trip
        assert restored == state
        # Spot-check nested fields
        assert restored.pending_trigger_picker_idx == 0
        assert len(restored.pending_trigger_queue_turn) == 1
        assert len(restored.pending_trigger_queue_other) == 1
        assert isinstance(restored.pending_trigger_queue_turn[0], PendingTrigger)
        assert restored.pending_trigger_queue_turn[0].source_card_numeric_id == 9
        assert restored.pending_trigger_queue_turn[0].captured_position == (2, 3)
        assert restored.pending_trigger_queue_other[0].target_pos == (0, 1)

    def test_from_dict_backward_compatible_missing_keys(self):
        """Old dicts without the new keys reconstruct with empty defaults."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = state.to_dict()
        d.pop("pending_trigger_queue_turn", None)
        d.pop("pending_trigger_queue_other", None)
        d.pop("pending_trigger_picker_idx", None)
        restored = GameState.from_dict(d)
        assert restored.pending_trigger_queue_turn == ()
        assert restored.pending_trigger_queue_other == ()
        assert restored.pending_trigger_picker_idx is None
