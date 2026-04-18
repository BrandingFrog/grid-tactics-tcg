"""Tests for react_stack.py -- ReactEntry, handle_react_action, resolve_react_stack.

Covers:
  - ReactEntry construction and immutability
  - PASS during react resolves empty stack and advances turn
  - PASS during react resolves non-empty stack in LIFO order
  - Playing a React card pushes to stack and switches react_player_idx
  - Playing a multi-purpose card's react effect during react window
  - Insufficient mana for react card raises ValueError
  - Non-react card during react raises ValueError
  - Stack depth cap (MAX_REACT_STACK_DEPTH) enforced
  - Full chaining: P1 acts -> P2 reacts -> P1 counter-reacts -> P2 passes -> resolve LIFO
  - After resolution: turn advances, active player flips, turn_number increments
  - Mana regenerates for new active player at turn start
  - React effects actually apply to minions/players
"""

from dataclasses import replace, FrozenInstanceError

import pytest

from grid_tactics.actions import pass_action, play_card_action, play_react_action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import (
    ActionType,
    CardType,
    PlayerSide,
    TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.react_stack import ReactEntry, handle_react_action, resolve_react_stack
from grid_tactics.types import (
    MAX_REACT_STACK_DEPTH,
    STARTING_HP,
    STARTING_MANA,
)


# ---------------------------------------------------------------------------
# Helpers -- set up game states in REACT phase for testing
# ---------------------------------------------------------------------------

@pytest.fixture
def library():
    """Load the real card library from data/cards."""
    from pathlib import Path
    return CardLibrary.from_directory(Path("data/cards"))


@pytest.fixture
def react_state_empty_stack(library):
    """A GameState in REACT phase with empty stack.

    P1 just played a magic card (active_player_idx=0), react window open for P2 (react_player_idx=1).
    P2 has counter_spell (react to magic) and surgefed_sparkbot (multi-purpose, react to sacrifice) in hand.
    """
    counter_spell_id = library.get_numeric_id("prohibition")
    sparkbot_id = library.get_numeric_id("surgefed_sparkbot")
    rat_id = library.get_numeric_id("rat")

    p1 = Player(
        side=PlayerSide.PLAYER_1,
        hp=STARTING_HP,
        current_mana=5,
        max_mana=5,
        hand=(counter_spell_id, rat_id),
        deck=(),
        grave=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2,
        hp=STARTING_HP,
        current_mana=5,
        max_mana=5,
        hand=(counter_spell_id, sparkbot_id, rat_id),
        deck=(),
        grave=(),
    )

    # Place a P1 minion on the board for targeting
    minion = MinionInstance(
        instance_id=0,
        card_numeric_id=library.get_numeric_id("rat"),
        owner=PlayerSide.PLAYER_1,
        position=(1, 2),
        current_health=5,
    )
    board = Board.empty().place(1, 2, 0)

    # P1 played a magic card — triggers counter_spell's OPPONENT_PLAYS_MAGIC condition
    pending = play_card_action(card_index=0)

    return GameState(
        board=board,
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.REACT,
        turn_number=1,
        seed=42,
        minions=(minion,),
        next_minion_id=1,
        react_stack=(),
        react_player_idx=1,
        pending_action=pending,
    )


# ---------------------------------------------------------------------------
# ReactEntry construction and immutability
# ---------------------------------------------------------------------------


class TestReactEntry:
    def test_construction(self):
        entry = ReactEntry(player_idx=1, card_index=0, card_numeric_id=5)
        assert entry.player_idx == 1
        assert entry.card_index == 0
        assert entry.card_numeric_id == 5
        assert entry.target_pos is None

    def test_construction_with_target(self):
        entry = ReactEntry(player_idx=0, card_index=2, card_numeric_id=3, target_pos=(1, 2))
        assert entry.target_pos == (1, 2)

    def test_immutability(self):
        entry = ReactEntry(player_idx=1, card_index=0, card_numeric_id=5)
        with pytest.raises(FrozenInstanceError):
            entry.player_idx = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PASS during react
# ---------------------------------------------------------------------------


class TestReactPass:
    def test_pass_empty_stack_advances_turn(self, react_state_empty_stack, library):
        """PASS on empty react stack resolves and advances turn."""
        state = react_state_empty_stack
        result = handle_react_action(state, pass_action(), library)

        # Turn should advance: active player flips, turn increments
        assert result.active_player_idx == 1
        assert result.turn_number == 2
        assert result.phase == TurnPhase.ACTION
        assert result.react_stack == ()
        assert result.react_player_idx is None
        assert result.pending_action is None

    def test_pass_resolves_stack_lifo(self, react_state_empty_stack, library):
        """PASS with entries on stack resolves them in LIFO order."""
        counter_spell_id = library.get_numeric_id("prohibition")

        # Manually push a counter_spell (NEGATE) entry onto the stack
        entry = ReactEntry(
            player_idx=1,
            card_index=0,
            card_numeric_id=counter_spell_id,
        )
        state = replace(react_state_empty_stack, react_stack=(entry,))
        result = handle_react_action(state, pass_action(), library)

        # counter_spell NEGATE resolves — minion health unchanged
        minion = result.get_minion(0)
        assert minion is not None
        assert minion.current_health == 5  # unchanged

        # Turn should have advanced
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 1
        assert result.turn_number == 2

    def test_mana_regenerates_for_new_active_player(self, react_state_empty_stack, library):
        """After react resolves, the new active player regenerates mana.

        Audit-followup: regen is suppressed on turn 2 (P2's first action) so
        both players start their first action with STARTING_MANA
        (Phase 11 decision). To exercise regen, advance the fixture to a
        later turn first.
        """
        # Bump turn_number so the post-flip turn is > 2 and regen applies.
        state = replace(react_state_empty_stack, turn_number=3)
        result = handle_react_action(state, pass_action(), library)

        # P2 is now active (idx=1)
        new_active = result.players[result.active_player_idx]
        assert new_active.current_mana == 6  # 5 + 1 regen


# ---------------------------------------------------------------------------
# Playing react cards
# ---------------------------------------------------------------------------


class TestPlayReactCard:
    def test_react_card_pushes_to_stack(self, react_state_empty_stack, library):
        """Playing a react card pushes ReactEntry and switches react_player_idx."""
        shield_block_id = library.get_numeric_id("prohibition")

        # P2 (react_player_idx=1) plays shield_block (card_index=0) targeting (1,2)
        action = play_react_action(card_index=0, target_pos=(1, 2))
        result = handle_react_action(react_state_empty_stack, action, library)

        # Stack should have one entry
        assert len(result.react_stack) == 1
        assert result.react_stack[0].player_idx == 1
        assert result.react_stack[0].card_numeric_id == shield_block_id
        assert result.react_stack[0].target_pos == (1, 2)

        # react_player_idx flips to P1 (counter-react opportunity)
        assert result.react_player_idx == 0

        # Card removed from P2's hand, mana spent
        p2 = result.players[1]
        assert shield_block_id not in p2.hand
        # Prohibition costs 4 mana: 5 - 4 = 1
        assert p2.current_mana == 1

        # Phase remains REACT
        assert result.phase == TurnPhase.REACT

    def test_multi_purpose_card_as_react(self, react_state_empty_stack, library):
        """Multi-purpose card (surgefed_sparkbot) can be played as react using react_mana_cost."""
        sparkbot_id = library.get_numeric_id("surgefed_sparkbot")

        # Change pending_action to sacrifice so sparkbot's OPPONENT_SACRIFICES triggers
        from grid_tactics.actions import Action
        sac_action = Action(action_type=ActionType.SACRIFICE, card_index=0, position=(4, 0))
        state = replace(react_state_empty_stack, pending_action=sac_action)

        # P2 plays sparkbot (card_index=1) as react, target_pos is deploy position
        action = play_react_action(card_index=1, target_pos=(3, 0))
        result = handle_react_action(state, action, library)

        # Stack should have one entry
        assert len(result.react_stack) == 1
        assert result.react_stack[0].card_numeric_id == sparkbot_id

        p2 = result.players[1]
        assert sparkbot_id not in p2.hand

    def test_insufficient_mana_raises(self, react_state_empty_stack, library):
        """Playing a react card with insufficient mana raises ValueError."""
        # Set P2 mana to 0
        p2_broke = replace(react_state_empty_stack.players[1], current_mana=0)
        state = replace(
            react_state_empty_stack,
            players=(react_state_empty_stack.players[0], p2_broke),
        )

        action = play_react_action(card_index=0, target_pos=(1, 2))
        with pytest.raises(ValueError, match="[Ii]nsufficient mana"):
            handle_react_action(state, action, library)

    def test_non_react_card_during_react_raises(self, react_state_empty_stack, library):
        """Playing a non-react, non-multi-purpose card during react raises ValueError."""
        # fire_imp (index 2 in P2's hand) is a regular minion, not react-eligible
        action = play_react_action(card_index=2)
        with pytest.raises(ValueError):
            handle_react_action(react_state_empty_stack, action, library)

    def test_stack_depth_cap_enforced(self, react_state_empty_stack, library):
        """Cannot exceed MAX_REACT_STACK_DEPTH entries on the stack."""
        shield_block_id = library.get_numeric_id("prohibition")

        # Fill stack to MAX_REACT_STACK_DEPTH
        entries = tuple(
            ReactEntry(player_idx=i % 2, card_index=0, card_numeric_id=shield_block_id)
            for i in range(MAX_REACT_STACK_DEPTH)
        )
        state = replace(react_state_empty_stack, react_stack=entries)

        action = play_react_action(card_index=0, target_pos=(1, 2))
        with pytest.raises(ValueError, match="[Ss]tack.*depth|[Mm]ax"):
            handle_react_action(state, action, library)

    def test_invalid_action_type_during_react_raises(self, react_state_empty_stack, library):
        """Non-PASS, non-PLAY_REACT action during react raises ValueError."""
        from grid_tactics.actions import draw_action
        with pytest.raises(ValueError):
            handle_react_action(react_state_empty_stack, draw_action(), library)


# ---------------------------------------------------------------------------
# Full react chaining
# ---------------------------------------------------------------------------


class TestReactChaining:
    def test_full_chain_lifo_resolution(self, react_state_empty_stack, library):
        """P2 reacts -> P1 counter-reacts -> P2 passes -> LIFO resolution.

        P2 plays shield_block (buff_health +2 on P1's minion at (1,2)).
        P1 counter-reacts with counter_spell (damage 3 on some target).
        P2 passes -> stack resolves LIFO:
          - counter_spell resolves first (LIFO): NEGATE cancels shield_block
          - shield_block is negated, does not resolve
        Minion stays at 5 HP (no buffs applied).
        """
        counter_spell_id = library.get_numeric_id("prohibition")
        shield_block_id = library.get_numeric_id("prohibition")

        state = react_state_empty_stack

        # Step 1: P2 plays shield_block targeting minion at (1,2)
        action1 = play_react_action(card_index=0, target_pos=(1, 2))
        state = handle_react_action(state, action1, library)
        assert len(state.react_stack) == 1
        assert state.react_player_idx == 0  # P1's turn to counter-react

        # Step 2: P1 counter-reacts with counter_spell (NEGATE, no target needed)
        action2 = play_react_action(card_index=0)
        state = handle_react_action(state, action2, library)
        assert len(state.react_stack) == 2
        assert state.react_player_idx == 1  # P2's turn to counter-counter

        # Step 3: P2 passes -> stack resolves LIFO
        state = handle_react_action(state, pass_action(), library)

        # LIFO resolution order:
        # 1. counter_spell resolves: NEGATE -> cancels next entry (shield_block)
        # 2. shield_block is negated -> skipped
        # Minion stays at full health
        minion = state.get_minion(0)
        assert minion is not None
        assert minion.current_health == 5  # unchanged (shield_block was negated)

        # Turn advanced
        assert state.phase == TurnPhase.ACTION
        assert state.active_player_idx == 1
        assert state.turn_number == 2


# ---------------------------------------------------------------------------
# Resolve react stack effects
# ---------------------------------------------------------------------------


class TestResolveReactStack:
    def test_resolve_empty_stack(self, react_state_empty_stack, library):
        """Resolving empty stack just advances turn."""
        result = resolve_react_stack(react_state_empty_stack, library)
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 1
        assert result.turn_number == 2
        assert result.react_stack == ()

    def test_resolve_counter_spell_negate(self, react_state_empty_stack, library):
        """Counter_spell NEGATE effect on the stack."""
        counter_spell_id = library.get_numeric_id("prohibition")
        entry = ReactEntry(
            player_idx=1,
            card_index=0,
            card_numeric_id=counter_spell_id,
        )
        state = replace(react_state_empty_stack, react_stack=(entry,))
        result = resolve_react_stack(state, library)

        # Counter_spell resolves (NEGATE) — minion unaffected, turn advances
        minion = result.get_minion(0)
        assert minion is not None
        assert minion.current_health == 5  # unchanged
        assert result.phase == TurnPhase.ACTION
        assert result.turn_number == 2

    def test_resolve_multi_purpose_react_effect(self, react_state_empty_stack, library):
        """Multi-purpose card's DEPLOY_SELF react_effect deploys the minion during stack resolution."""
        sparkbot_id = library.get_numeric_id("surgefed_sparkbot")
        entry = ReactEntry(
            player_idx=1,
            card_index=1,
            card_numeric_id=sparkbot_id,
            target_pos=(3, 0),  # empty P2 row position
        )
        # Change pending to sacrifice so sparkbot condition matches
        from grid_tactics.actions import Action
        sac_action = Action(action_type=ActionType.SACRIFICE, card_index=0, position=(4, 0))
        state = replace(react_state_empty_stack, react_stack=(entry,), pending_action=sac_action)
        result = resolve_react_stack(state, library)

        # DEPLOY_SELF: sparkbot deployed as a minion at (3,0)
        deployed = [m for m in result.minions if m.card_numeric_id == sparkbot_id]
        assert len(deployed) == 1
        assert deployed[0].position == (3, 0)
        assert deployed[0].owner == PlayerSide.PLAYER_2


# ---------------------------------------------------------------------------
# Action resolver integration: REACT phase delegation
# ---------------------------------------------------------------------------


class TestActionResolverReactDelegation:
    def test_resolve_action_delegates_to_react_handler(self, react_state_empty_stack, library):
        """resolve_action() delegates to handle_react_action when phase is REACT."""
        from grid_tactics.action_resolver import resolve_action

        result = resolve_action(react_state_empty_stack, pass_action(), library)
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 1
        assert result.turn_number == 2

    def test_resolve_action_react_play(self, react_state_empty_stack, library):
        """resolve_action() handles PLAY_REACT during REACT phase."""
        from grid_tactics.action_resolver import resolve_action

        action = play_react_action(card_index=0, target_pos=(1, 2))
        result = resolve_action(react_state_empty_stack, action, library)
        assert len(result.react_stack) == 1
        assert result.phase == TurnPhase.REACT


# ---------------------------------------------------------------------------
# Phase 14.7-02: 3-phase turn model + react_return_phase dispatch
# ---------------------------------------------------------------------------


class TestTurnPhaseNewValues:
    """TurnPhase has START_OF_TURN=2 / END_OF_TURN=3 appended in 14.7-02."""

    def test_new_values_pin(self):
        assert TurnPhase.START_OF_TURN == 2
        assert TurnPhase.END_OF_TURN == 3

    def test_round_trip_int(self):
        assert TurnPhase(2) is TurnPhase.START_OF_TURN
        assert TurnPhase(3) is TurnPhase.END_OF_TURN


class TestReactReturnPhaseDispatch:
    """resolve_react_stack uses state.react_return_phase to decide where to go after PASS-PASS."""

    def test_react_window_returns_to_action_by_default(
        self, react_state_empty_stack, library,
    ):
        """Legacy path: react_return_phase=None (unset) defaults to ACTION → advance turn.

        Backward-compat — pre-14.7-02 code never set react_return_phase
        so the default path MUST behave like the old turn-advance tail.
        """
        state = react_state_empty_stack
        # Baseline sanity: fixture does not set react_return_phase.
        assert state.react_return_phase is None

        result = resolve_react_stack(state, library)

        # Same as the old behavior: turn flip + phase=ACTION + inc turn number.
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 1
        assert result.turn_number == 2
        assert result.react_return_phase is None
        assert result.react_context is None

    def test_react_window_returns_to_start(self, react_state_empty_stack, library):
        """react_return_phase=START_OF_TURN → transition to ACTION without turn flip.

        The start-of-turn react window closes by entering ACTION for the
        SAME player (no turn advancement). Mana, turn_number and
        active_player_idx stay put.
        """
        from grid_tactics.enums import ReactContext

        state = replace(
            react_state_empty_stack,
            react_context=ReactContext.AFTER_START_TRIGGER,
            react_return_phase=TurnPhase.START_OF_TURN,
        )
        original_active = state.active_player_idx
        original_turn = state.turn_number

        result = resolve_react_stack(state, library)

        assert result.phase == TurnPhase.ACTION
        # NO turn flip, NO turn_number increment
        assert result.active_player_idx == original_active
        assert result.turn_number == original_turn
        # React bookkeeping cleared
        assert result.react_stack == ()
        assert result.react_player_idx is None
        assert result.react_context is None
        assert result.react_return_phase is None

    def test_react_window_returns_to_end(self, react_state_empty_stack, library):
        """react_return_phase=END_OF_TURN → advance turn (same as legacy ACTION path)."""
        from grid_tactics.enums import ReactContext

        state = replace(
            react_state_empty_stack,
            react_context=ReactContext.BEFORE_END_OF_TURN,
            react_return_phase=TurnPhase.END_OF_TURN,
        )

        result = resolve_react_stack(state, library)

        # Turn flip + increment + phase=ACTION (enter new active player's
        # START_OF_TURN which immediately passes through to ACTION in 14.7-02).
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 1
        assert result.turn_number == 2
        assert result.react_stack == ()
        assert result.react_player_idx is None
        assert result.react_context is None
        assert result.react_return_phase is None


class TestPhaseTransitionHelpers:
    """The 4 new phase-transition helpers exist and behave as placeholders."""

    def test_enter_start_of_turn_passthrough(self, library):
        """enter_start_of_turn() currently immediately transitions to ACTION.

        14.7-03 will insert trigger firing + react window — for 14.7-02
        it's a byte-simple phase flip.
        """
        from grid_tactics.react_stack import enter_start_of_turn

        state = GameState(
            board=Board.empty(),
            players=(
                Player(side=PlayerSide.PLAYER_1, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
                Player(side=PlayerSide.PLAYER_2, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
            ),
            active_player_idx=0,
            phase=TurnPhase.START_OF_TURN,
            turn_number=1,
            seed=42,
        )

        result = enter_start_of_turn(state, library)

        assert result.phase == TurnPhase.ACTION
        # No other state mutated
        assert result.active_player_idx == 0
        assert result.turn_number == 1

    def test_enter_end_of_turn_runs_tail_and_enters_next_start(self, library):
        """enter_end_of_turn() runs the end-of-turn tail then enter_start_of_turn."""
        from grid_tactics.react_stack import enter_end_of_turn

        state = GameState(
            board=Board.empty(),
            players=(
                Player(side=PlayerSide.PLAYER_1, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
                Player(side=PlayerSide.PLAYER_2, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
            ),
            active_player_idx=0,
            phase=TurnPhase.END_OF_TURN,
            turn_number=1,
            seed=42,
        )

        result = enter_end_of_turn(state, library)

        # Turn advanced: P2 now active, turn 2, phase = ACTION (because
        # START_OF_TURN placeholder immediately passes through).
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 1
        assert result.turn_number == 2

    def test_close_start_react_and_enter_action_clears_react(self, library):
        """close_start_react_and_enter_action clears react state, phase=ACTION, no turn flip."""
        from grid_tactics.enums import ReactContext
        from grid_tactics.react_stack import close_start_react_and_enter_action

        state = GameState(
            board=Board.empty(),
            players=(
                Player(side=PlayerSide.PLAYER_1, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
                Player(side=PlayerSide.PLAYER_2, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
            ),
            active_player_idx=0,
            phase=TurnPhase.REACT,
            turn_number=1,
            seed=42,
            react_player_idx=1,
            react_context=ReactContext.AFTER_START_TRIGGER,
            react_return_phase=TurnPhase.START_OF_TURN,
        )

        result = close_start_react_and_enter_action(state, library)

        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 0  # no turn flip
        assert result.turn_number == 1
        assert result.react_stack == ()
        assert result.react_player_idx is None
        assert result.react_context is None
        assert result.react_return_phase is None

    def test_close_end_react_and_advance_turn_flips(self, library):
        """close_end_react_and_advance_turn clears react, flips active, enters new START."""
        from grid_tactics.enums import ReactContext
        from grid_tactics.react_stack import close_end_react_and_advance_turn

        state = GameState(
            board=Board.empty(),
            players=(
                Player(side=PlayerSide.PLAYER_1, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
                Player(side=PlayerSide.PLAYER_2, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
            ),
            active_player_idx=0,
            phase=TurnPhase.REACT,
            turn_number=1,
            seed=42,
            react_player_idx=1,
            react_context=ReactContext.BEFORE_END_OF_TURN,
            react_return_phase=TurnPhase.END_OF_TURN,
        )

        result = close_end_react_and_advance_turn(state, library)

        # After tail + enter_start_of_turn placeholder passthrough.
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 1
        assert result.turn_number == 2
        assert result.react_stack == ()
        assert result.react_player_idx is None
        assert result.react_context is None
        assert result.react_return_phase is None


class TestActionResolverSetsReactContext:
    """Every ``phase=TurnPhase.REACT`` site in action_resolver sets react_context/return_phase."""

    def test_magic_cast_originator_sets_context(self, library):
        """_cast_magic originator path tags AFTER_ACTION / return ACTION.

        Uses Acidic Rain (cost 5, on_play burn to all metal/robot minions)
        — a magic card whose cast path routes through _cast_magic's
        originator pipeline and should emerge in REACT phase tagged
        AFTER_ACTION / return ACTION.
        """
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import play_card_action
        from grid_tactics.enums import ReactContext

        acidic_rain_id = library.get_numeric_id("acidic_rain")

        p1 = Player(
            side=PlayerSide.PLAYER_1,
            hp=STARTING_HP,
            current_mana=5, max_mana=5,
            hand=(acidic_rain_id,), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2,
            hp=STARTING_HP,
            current_mana=5, max_mana=5,
            hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=Board.empty(),
            players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.ACTION,
            turn_number=1,
            seed=42,
        )

        action = play_card_action(card_index=0)
        result = resolve_action(state, action, library)

        assert result.phase == TurnPhase.REACT
        assert result.react_context == ReactContext.AFTER_ACTION
        assert result.react_return_phase == TurnPhase.ACTION


class TestLegalActionsStartEndPhases:
    """Phase 14.7-02: legal_actions returns () during START_OF_TURN / END_OF_TURN."""

    def test_legal_actions_empty_in_start_of_turn(self, library):
        """START_OF_TURN is a placeholder; legal_actions is empty so server auto-advances."""
        from grid_tactics.legal_actions import legal_actions

        state = GameState(
            board=Board.empty(),
            players=(
                Player(side=PlayerSide.PLAYER_1, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
                Player(side=PlayerSide.PLAYER_2, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
            ),
            active_player_idx=0,
            phase=TurnPhase.START_OF_TURN,
            turn_number=1,
            seed=42,
        )

        assert legal_actions(state, library) == ()

    def test_legal_actions_empty_in_end_of_turn(self, library):
        """END_OF_TURN is a placeholder; legal_actions is empty so server auto-advances."""
        from grid_tactics.legal_actions import legal_actions

        state = GameState(
            board=Board.empty(),
            players=(
                Player(side=PlayerSide.PLAYER_1, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
                Player(side=PlayerSide.PLAYER_2, hp=20, current_mana=3, max_mana=3, hand=(), deck=(), grave=()),
            ),
            active_player_idx=0,
            phase=TurnPhase.END_OF_TURN,
            turn_number=1,
            seed=42,
        )

        assert legal_actions(state, library) == ()


# ---------------------------------------------------------------------------
# Phase 14.7-03: Start/End trigger firing + react-window opening
# ---------------------------------------------------------------------------


class TestStartOfTurnTriggers:
    """ON_START_OF_TURN triggers fire inside enter_start_of_turn + open react window."""

    def test_fallen_paladin_heals_at_start_of_owners_turn(self, library):
        """Fallen Paladin's PASSIVE_HEAL (retagged on_start_of_turn) heals self."""
        from grid_tactics.react_stack import enter_start_of_turn

        paladin_id = library.get_numeric_id("fallen_paladin")
        # Wounded Fallen Paladin (base 42 HP) — current 30.
        paladin = MinionInstance(
            instance_id=0,
            card_numeric_id=paladin_id,
            owner=PlayerSide.PLAYER_1,
            position=(2, 2),
            current_health=30,
        )
        board = Board.empty().place(2, 2, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.START_OF_TURN,
            turn_number=3,
            seed=42,
            minions=(paladin,),
            next_minion_id=1,
        )

        result = enter_start_of_turn(state, library)

        # Heal +2 applied — Fallen Paladin at 32 now.
        healed = result.get_minion(0)
        assert healed is not None
        assert healed.current_health == 32

    def test_start_of_turn_react_window_opens_for_triggers(self, library):
        """When Start: triggers fire, a REACT window opens with AFTER_START_TRIGGER context."""
        from grid_tactics.enums import ReactContext
        from grid_tactics.react_stack import enter_start_of_turn

        paladin_id = library.get_numeric_id("fallen_paladin")
        paladin = MinionInstance(
            instance_id=0,
            card_numeric_id=paladin_id,
            owner=PlayerSide.PLAYER_1,
            position=(2, 2),
            current_health=30,
        )
        board = Board.empty().place(2, 2, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.START_OF_TURN,
            turn_number=3,
            seed=42,
            minions=(paladin,),
            next_minion_id=1,
        )

        result = enter_start_of_turn(state, library)

        assert result.phase == TurnPhase.REACT
        assert result.react_context == ReactContext.AFTER_START_TRIGGER
        assert result.react_return_phase == TurnPhase.START_OF_TURN
        # Opponent reacts (P2 at idx=1)
        assert result.react_player_idx == 1

    def test_no_start_triggers_shortcuts_to_action(self, library):
        """enter_start_of_turn with no Start: triggers shortcuts to ACTION (snappy)."""
        from grid_tactics.react_stack import enter_start_of_turn

        # Plain Rat (no on_start_of_turn triggers) on the board.
        rat_id = library.get_numeric_id("rat")
        rat = MinionInstance(
            instance_id=0, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=5,
        )
        board = Board.empty().place(2, 2, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.START_OF_TURN,
            turn_number=3,
            seed=42,
            minions=(rat,),
            next_minion_id=1,
        )

        result = enter_start_of_turn(state, library)

        # No triggers → straight to ACTION, no react window.
        assert result.phase == TurnPhase.ACTION
        assert result.react_context is None
        assert result.react_return_phase is None


class TestEndOfTurnTriggers:
    """ON_END_OF_TURN triggers fire inside enter_end_of_turn + open react window."""

    def test_emberplague_applies_burn_to_adjacent_at_end_of_owners_turn(self, library):
        """Emberplague Rat's BURN (retagged on_end_of_turn) marks adjacent enemies burning."""
        from grid_tactics.react_stack import enter_end_of_turn

        ember_id = library.get_numeric_id("emberplague_rat")
        rat_id = library.get_numeric_id("rat")

        # P1 owns Emberplague at (2,2). P2 enemy Rat adjacent at (2,1).
        ember = MinionInstance(
            instance_id=0, card_numeric_id=ember_id,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=24,
        )
        enemy = MinionInstance(
            instance_id=1, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(2, 1), current_health=5,
        )
        board = Board.empty().place(2, 2, 0).place(2, 1, 1)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2),
            active_player_idx=0,  # P1 is active → P1's end of turn
            phase=TurnPhase.ACTION,
            turn_number=3,
            seed=42,
            minions=(ember, enemy),
            next_minion_id=2,
        )

        result = enter_end_of_turn(state, library)

        # Enemy at (2,1) has is_burning=True now
        enemy_after = result.get_minion(1)
        assert enemy_after is not None
        assert enemy_after.is_burning is True

    def test_dark_matter_battery_damages_opponent_at_end_of_turn(self, library):
        """Dark Matter Battery's damage-opp (retagged on_end_of_turn) hits opponent HP."""
        from dataclasses import replace as _replace
        from grid_tactics.react_stack import enter_end_of_turn

        battery_id = library.get_numeric_id("dark_matter_battery")
        # Battery on P1's side with 3 DM stacks — damage = 0 + 3 = 3.
        battery = MinionInstance(
            instance_id=0, card_numeric_id=battery_id,
            owner=PlayerSide.PLAYER_1, position=(0, 2), current_health=20,
            dark_matter_stacks=3,
        )
        board = Board.empty().place(0, 2, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.ACTION,
            turn_number=3,
            seed=42,
            minions=(battery,),
            next_minion_id=1,
        )

        result = enter_end_of_turn(state, library)

        # P2 HP dropped by 3 (scale_with dark_matter = 3)
        assert result.players[1].hp == STARTING_HP - 3

    def test_end_of_turn_react_window_opens_for_triggers(self, library):
        """When End: triggers fire, REACT opens with BEFORE_END_OF_TURN context."""
        from grid_tactics.enums import ReactContext
        from grid_tactics.react_stack import enter_end_of_turn

        battery_id = library.get_numeric_id("dark_matter_battery")
        battery = MinionInstance(
            instance_id=0, card_numeric_id=battery_id,
            owner=PlayerSide.PLAYER_1, position=(0, 2), current_health=20,
            dark_matter_stacks=1,
        )
        board = Board.empty().place(0, 2, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.ACTION,
            turn_number=3,
            seed=42,
            minions=(battery,),
            next_minion_id=1,
        )

        result = enter_end_of_turn(state, library)

        assert result.phase == TurnPhase.REACT
        assert result.react_context == ReactContext.BEFORE_END_OF_TURN
        assert result.react_return_phase == TurnPhase.END_OF_TURN
        assert result.react_player_idx == 1  # P2 reacts

    def test_no_end_triggers_shortcuts_to_turn_advance(self, library):
        """enter_end_of_turn with no End: triggers shortcuts to turn-advance."""
        from grid_tactics.react_stack import enter_end_of_turn

        rat_id = library.get_numeric_id("rat")
        rat = MinionInstance(
            instance_id=0, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=5,
        )
        board = Board.empty().place(2, 2, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.ACTION,
            turn_number=3,
            seed=42,
            minions=(rat,),
            next_minion_id=1,
        )

        result = enter_end_of_turn(state, library)

        # Shortcut: turn-advance → phase=ACTION, P2 active, turn=4
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 1
        assert result.turn_number == 4


class TestAdvanceToNextTurnHelper:
    """advance_to_next_turn drives PASS-PASS through an open react window to next turn."""

    def test_drives_through_start_of_turn_react_to_next_action(self, library):
        """Full loop: END_OF_TURN with End-trigger react → flip → START_OF_TURN with Start-trigger react → ACTION."""
        from grid_tactics.react_stack import advance_to_next_turn

        # Setup: P1 active with a Fallen Paladin (Start trigger) on their side.
        # Drive advance_to_next_turn from end of P1's turn; should end up in
        # P2's ACTION (turn advanced by 1).
        paladin_id = library.get_numeric_id("fallen_paladin")
        paladin = MinionInstance(
            instance_id=0, card_numeric_id=paladin_id,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=30,
        )
        board = Board.empty().place(2, 2, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.END_OF_TURN,
            turn_number=3,
            seed=42,
            minions=(paladin,),
            next_minion_id=1,
        )

        result = advance_to_next_turn(state, library)

        # Should end up in P2's ACTION phase (turn advanced to 4)
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 1
        assert result.turn_number == 4

    def test_returns_early_if_already_in_action(self, library):
        """Helper returns state unchanged if already in ACTION for next turn."""
        from grid_tactics.react_stack import advance_to_next_turn

        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=Board.empty(), players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.ACTION,
            turn_number=3,
            seed=42,
        )

        result = advance_to_next_turn(state, library)

        # Stays put
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 0
        assert result.turn_number == 3


class TestResolveReactStackAfterActionRoutesThroughEnterEnd:
    """After 14.7-03, resolve_react_stack AFTER_ACTION path routes via enter_end_of_turn."""

    def test_after_action_with_no_end_triggers_still_advances_turn(
        self, react_state_empty_stack, library,
    ):
        """Legacy behavior preserved: after-action PASS with no End triggers → turn advance."""
        state = react_state_empty_stack
        # Fixture has no End-trigger minions on the board.
        result = resolve_react_stack(state, library)

        # Same observable effect as pre-14.7-03: turn advanced.
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 1
        assert result.turn_number == 2

    def test_after_action_with_end_trigger_opens_end_react_window(self, library):
        """After-action PASS with an End trigger → enters END + opens react window."""
        from grid_tactics.enums import ReactContext
        from grid_tactics.react_stack import resolve_react_stack

        battery_id = library.get_numeric_id("dark_matter_battery")
        battery = MinionInstance(
            instance_id=0, card_numeric_id=battery_id,
            owner=PlayerSide.PLAYER_1, position=(0, 2), current_health=20,
            dark_matter_stacks=1,
        )
        board = Board.empty().place(0, 2, 0)
        p1 = Player(
            side=PlayerSide.PLAYER_1, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        p2 = Player(
            side=PlayerSide.PLAYER_2, hp=STARTING_HP,
            current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
        )
        state = GameState(
            board=board, players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.REACT,
            turn_number=3,
            seed=42,
            minions=(battery,),
            next_minion_id=1,
            react_stack=(),
            react_player_idx=1,
            react_context=ReactContext.AFTER_ACTION,
            react_return_phase=TurnPhase.ACTION,
        )

        result = resolve_react_stack(state, library)

        # Did NOT advance turn — still P1 active. Now in end-of-turn react window.
        assert result.phase == TurnPhase.REACT
        assert result.react_context == ReactContext.BEFORE_END_OF_TURN
        assert result.react_return_phase == TurnPhase.END_OF_TURN
        assert result.active_player_idx == 0
        assert result.turn_number == 3
        # And the End trigger damage fired: P2 HP dropped by 1
        assert result.players[1].hp == STARTING_HP - 1
