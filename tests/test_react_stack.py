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

from grid_tactics.actions import pass_action, play_react_action
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

    P1 just acted (active_player_idx=0), react window open for P2 (react_player_idx=1).
    P2 has a shield_block (react card) and dark_sentinel (multi-purpose) in hand.
    """
    shield_block_id = library.get_numeric_id("shield_block")
    dark_sentinel_id = library.get_numeric_id("dark_sentinel")
    counter_spell_id = library.get_numeric_id("counter_spell")
    fire_imp_id = library.get_numeric_id("fire_imp")

    p1 = Player(
        side=PlayerSide.PLAYER_1,
        hp=STARTING_HP,
        current_mana=5,
        max_mana=5,
        hand=(counter_spell_id, fire_imp_id),  # P1 has counter_spell + fire_imp
        deck=(),
        graveyard=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2,
        hp=STARTING_HP,
        current_mana=5,
        max_mana=5,
        hand=(shield_block_id, dark_sentinel_id, fire_imp_id),  # P2 has shield_block + dark_sentinel + fire_imp
        deck=(),
        graveyard=(),
    )

    # Place a P1 minion on the board for targeting
    minion = MinionInstance(
        instance_id=0,
        card_numeric_id=library.get_numeric_id("iron_guardian"),
        owner=PlayerSide.PLAYER_1,
        position=(1, 2),
        current_health=5,
    )
    board = Board.empty().place(1, 2, 0)

    pending = pass_action()  # The action that triggered react window

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
        shield_block_id = library.get_numeric_id("shield_block")

        # Manually push a react entry onto the stack
        entry = ReactEntry(
            player_idx=1,
            card_index=0,
            card_numeric_id=shield_block_id,
            target_pos=(1, 2),  # target the P1 minion at (1,2)
        )
        state = replace(react_state_empty_stack, react_stack=(entry,))
        result = handle_react_action(state, pass_action(), library)

        # Audit-followup: shield_block now BUFF_HEALTH +20 (scaled).
        minion = result.get_minion(0)
        assert minion is not None
        assert minion.current_health == 25  # 5 + 20

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
        shield_block_id = library.get_numeric_id("shield_block")

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
        # shield_block costs 1 mana: 5 - 1 = 4
        assert p2.current_mana == 4

        # Phase remains REACT
        assert result.phase == TurnPhase.REACT

    def test_multi_purpose_card_as_react(self, react_state_empty_stack, library):
        """Multi-purpose card (dark_sentinel) can be played as react using react_mana_cost."""
        dark_sentinel_id = library.get_numeric_id("dark_sentinel")

        # P2 plays dark_sentinel (card_index=1) as react, target_pos is deploy position
        action = play_react_action(card_index=1, target_pos=(3, 0))
        result = handle_react_action(react_state_empty_stack, action, library)

        # Stack should have one entry
        assert len(result.react_stack) == 1
        assert result.react_stack[0].card_numeric_id == dark_sentinel_id

        # Audit-followup: dark_sentinel react_mana_cost is now 2: 5 - 2 = 3
        p2 = result.players[1]
        assert p2.current_mana == 3
        assert dark_sentinel_id not in p2.hand

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
        shield_block_id = library.get_numeric_id("shield_block")

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
        counter_spell_id = library.get_numeric_id("counter_spell")
        shield_block_id = library.get_numeric_id("shield_block")

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

    def test_resolve_shield_block_effect(self, react_state_empty_stack, library):
        """Shield block buff_health actually applies to the target minion."""
        shield_block_id = library.get_numeric_id("shield_block")
        entry = ReactEntry(
            player_idx=1,
            card_index=0,
            card_numeric_id=shield_block_id,
            target_pos=(1, 2),
        )
        state = replace(react_state_empty_stack, react_stack=(entry,))
        result = resolve_react_stack(state, library)

        minion = result.get_minion(0)
        assert minion is not None
        # Audit-followup: shield_block now buffs +20 hp (scaled). Fixture
        # minion starts at current_health=5, so 5 + 20 = 25.
        assert minion.current_health == 25

    def test_resolve_dark_mirror_damage_and_heal(self, react_state_empty_stack, library):
        """Dark mirror does damage to target and heals the owning player."""
        dark_mirror_id = library.get_numeric_id("dark_mirror")
        entry = ReactEntry(
            player_idx=1,
            card_index=0,
            card_numeric_id=dark_mirror_id,
            target_pos=(1, 2),
        )
        state = replace(react_state_empty_stack, react_stack=(entry,))
        result = resolve_react_stack(state, library)

        # Audit-followup: dark_mirror DAMAGE is now 10 (scaled). Fixture
        # minion has current_health=5, so this is lethal — the minion is
        # cleaned up and get_minion(0) returns None.
        minion = result.get_minion(0)
        assert minion is None

        # Heal 10 to player 1 (self_owner = player who played react = P2),
        # already at STARTING_HP so capped.
        assert result.players[1].hp == STARTING_HP

    def test_resolve_multi_purpose_react_effect(self, react_state_empty_stack, library):
        """Multi-purpose card's DEPLOY_SELF react_effect deploys the minion during stack resolution."""
        dark_sentinel_id = library.get_numeric_id("dark_sentinel")
        entry = ReactEntry(
            player_idx=1,
            card_index=1,
            card_numeric_id=dark_sentinel_id,
            target_pos=(3, 0),  # empty P2 row position
        )
        state = replace(react_state_empty_stack, react_stack=(entry,))
        result = resolve_react_stack(state, library)

        # dark_sentinel DEPLOY_SELF: should be deployed as a minion at (3,0)
        # Find the newly deployed minion (instance_id > 0 since minion 0 already exists)
        deployed = [m for m in result.minions if m.card_numeric_id == dark_sentinel_id]
        assert len(deployed) == 1
        assert deployed[0].position == (3, 0)
        # Audit-followup: dark_sentinel base health is now 30 (scaled).
        assert deployed[0].current_health == 30
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
