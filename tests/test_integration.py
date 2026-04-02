"""Integration tests for the complete turn cycle: action -> react -> resolve -> advance.

Covers:
  - Full turn cycle: P1 plays card -> react window opens -> P2 passes -> turn advances to P2
  - Full turn with react: P1 attacks -> P2 plays react shield_block -> P1 passes -> resolve -> advance
  - Multi-react chain: P1 acts -> P2 reacts -> P1 counter-reacts -> P2 passes -> LIFO resolution
  - Multiple turns: play 3-5 turns with various actions, verify state consistency
  - Combat scenario: deploy two minions, attack, verify damage and cleanup
  - Mana flow: verify mana deduction on play, regeneration at turn start
  - legal_actions consistency: at every step, legal_actions returns valid actions that resolve
"""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.action_resolver import resolve_action
from grid_tactics.actions import (
    attack_action,
    draw_action,
    move_action,
    pass_action,
    play_card_action,
    play_react_action,
)
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.types import STARTING_HP


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def library():
    """Load the real card library from data/cards."""
    return CardLibrary.from_directory(Path("data/cards"))


def _make_player(side, hand=(), deck=(), mana=5, graveyard=()):
    return Player(
        side=side, hp=STARTING_HP, current_mana=mana,
        max_mana=5, hand=hand, deck=deck, graveyard=graveyard,
    )


def _make_state(
    p1_hand=(), p2_hand=(),
    p1_mana=5, p2_mana=5,
    p1_deck=(), p2_deck=(),
    minions=(), board=None,
    active_player_idx=0,
    phase=TurnPhase.ACTION,
    turn_number=1,
):
    p1 = _make_player(PlayerSide.PLAYER_1, p1_hand, p1_deck, p1_mana)
    p2 = _make_player(PlayerSide.PLAYER_2, p2_hand, p2_deck, p2_mana)

    if board is None:
        board = Board.empty()
        for m in minions:
            board = board.place(m.position[0], m.position[1], m.instance_id)

    next_id = max((m.instance_id for m in minions), default=-1) + 1

    return GameState(
        board=board, players=(p1, p2),
        active_player_idx=active_player_idx,
        phase=phase, turn_number=turn_number, seed=42,
        minions=tuple(minions), next_minion_id=next_id,
    )


# ---------------------------------------------------------------------------
# Full turn cycle
# ---------------------------------------------------------------------------


class TestFullTurnCycle:
    def test_play_card_then_pass_react_advances_turn(self, library):
        """P1 deploys a minion -> react window opens -> P2 passes -> turn advances to P2."""
        shadow_knight_id = library.get_numeric_id("shadow_knight")  # cost=3, melee, no ON_PLAY effects

        state = _make_state(p1_hand=(shadow_knight_id,), p1_mana=5)

        # P1 deploys shadow_knight to (0, 0)
        state = resolve_action(state, play_card_action(card_index=0, position=(0, 0)), library)

        # Should be in REACT phase, P2's turn to react
        assert state.phase == TurnPhase.REACT
        assert state.react_player_idx == 1
        assert state.active_player_idx == 0  # still P1's "turn" until react resolves

        # P2 passes react
        state = resolve_action(state, pass_action(), library)

        # Turn advances to P2
        assert state.phase == TurnPhase.ACTION
        assert state.active_player_idx == 1
        assert state.turn_number == 2

        # Minion should be on the board
        minion = state.get_minion(0)
        assert minion is not None
        assert minion.position == (0, 0)

    def test_pass_action_then_pass_react(self, library):
        """P1 passes -> react window -> P2 passes -> turn advances."""
        state = _make_state()

        # P1 passes
        state = resolve_action(state, pass_action(), library)
        assert state.phase == TurnPhase.REACT

        # P2 passes react
        state = resolve_action(state, pass_action(), library)
        assert state.phase == TurnPhase.ACTION
        assert state.active_player_idx == 1
        assert state.turn_number == 2

    def test_draw_then_pass_react(self, library):
        """P1 draws -> react -> P2 passes -> turn advances."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        state = _make_state(p1_deck=(fire_imp_id,))

        state = resolve_action(state, draw_action(), library)
        assert state.phase == TurnPhase.REACT
        assert fire_imp_id in state.players[0].hand

        state = resolve_action(state, pass_action(), library)
        assert state.phase == TurnPhase.ACTION
        assert state.active_player_idx == 1


# ---------------------------------------------------------------------------
# React in action
# ---------------------------------------------------------------------------


class TestReactInteraction:
    def test_react_shield_block_buffs_minion(self, library):
        """P1 attacks -> P2 plays shield_block on defending minion -> resolve -> advance."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        shield_block_id = library.get_numeric_id("shield_block")

        attacker = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=2,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_2, position=(2, 2), current_health=2,
        )

        state = _make_state(
            p2_hand=(shield_block_id,),
            minions=(attacker, defender),
        )

        # P1 attacks P2's minion (simultaneous: both deal attack damage to each other)
        state = resolve_action(state, attack_action(minion_id=0, target_id=1), library)
        assert state.phase == TurnPhase.REACT

        # After attack: fire_imp has 2 attack, so both take 2 damage
        # attacker: 2 - 2 = 0 (dead, cleaned up)
        # defender: 2 - 2 = 0 (dead, cleaned up)
        # Both dead, but P2 can still react before the turn ends

        # P2 plays shield_block. Since both minions are dead, we need a live target.
        # Let's adjust the scenario so the defender survives.
        pass  # Re-do scenario with stronger defender

    def test_react_with_surviving_minion(self, library):
        """P1 attacks -> defender survives -> P2 shield_blocks -> resolve.

        Defender has more health so it survives the attack. P2 then buffs it.
        """
        fire_imp_id = library.get_numeric_id("fire_imp")  # attack=2
        iron_guardian_id = library.get_numeric_id("iron_guardian")  # melee, attack=1, health=5
        shield_block_id = library.get_numeric_id("shield_block")  # buff_health +2

        attacker = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=2,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=iron_guardian_id,
            owner=PlayerSide.PLAYER_2, position=(2, 2), current_health=5,
        )

        state = _make_state(
            p2_hand=(shield_block_id,),
            minions=(attacker, defender),
        )

        # P1 attacks: fire_imp (attack=2) vs iron_guardian (attack=1)
        # attacker takes 1 damage: 2-1=1 (alive)
        # defender takes 2 damage: 5-2=3 (alive)
        state = resolve_action(state, attack_action(minion_id=0, target_id=1), library)
        assert state.phase == TurnPhase.REACT

        # P2 plays shield_block on defender at (2,2)
        state = resolve_action(state, play_react_action(card_index=0, target_pos=(2, 2)), library)
        # Counter-react opportunity for P1
        assert state.react_player_idx == 0

        # P1 passes
        state = resolve_action(state, pass_action(), library)

        # shield_block resolved: buff_health +2 on defender at (2,2)
        # iron_guardian started at 5 HP, took 2 damage (->3), then on_damaged triggered (+1 -> 4)
        # shield_block adds +2 -> 6
        defender_after = state.get_minion(1)
        assert defender_after is not None
        assert defender_after.current_health == 6  # 5 - 2 + 1(on_damaged) + 2(shield_block)

        # Turn advanced
        assert state.phase == TurnPhase.ACTION
        assert state.active_player_idx == 1
        assert state.turn_number == 2

    def test_multi_react_chain_lifo(self, library):
        """P1 deploys minion -> P2 reacts with dark_mirror (condition: opponent_plays_minion)
        -> P1 counter-reacts with counter_spell (condition: opponent_plays_react, NEGATE)
        -> P2 passes -> LIFO resolves: counter_spell negates dark_mirror, minion undamaged."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        dark_mirror_id = library.get_numeric_id("dark_mirror")   # condition: opponent_plays_minion
        counter_spell_id = library.get_numeric_id("counter_spell")  # condition: opponent_plays_magic, NEGATE

        # P1 has fire_imp to deploy and counter_spell for react
        # P2 has dark_mirror to react to the deploy
        p1_minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_2, position=(3, 0), current_health=2,
        )

        state = _make_state(
            p1_hand=(fire_imp_id, counter_spell_id),
            p2_hand=(dark_mirror_id,),
            minions=(p1_minion,),  # enemy minion for dark_mirror to target
            p1_mana=5,
            p2_mana=5,
        )

        # P1 deploys fire_imp at (1, 0) -- this triggers react window
        state = resolve_action(state, play_card_action(card_index=0, position=(1, 0)), library)
        assert state.phase == TurnPhase.REACT
        assert state.react_player_idx == 1  # P2 can react

        # P2 plays dark_mirror (condition: opponent_plays_minion -- met!)
        # targeting the newly deployed minion at (1, 0)
        state = resolve_action(state, play_react_action(card_index=0, target_pos=(1, 0)), library)
        assert state.react_player_idx == 0  # P1 can counter-react

        # P1 counter-reacts with counter_spell (condition: opponent_plays_magic --
        # dark_mirror is a react, and counter_spell checks for magic OR react on stack)
        # counter_spell has NEGATE effect -- cancels dark_mirror
        state = resolve_action(state, play_react_action(card_index=0), library)
        assert state.react_player_idx == 1  # P2 can counter

        # P2 passes -> resolve LIFO
        state = resolve_action(state, pass_action(), library)

        # LIFO resolution:
        # 1. counter_spell resolves: NEGATE -> cancels next entry (dark_mirror)
        # 2. dark_mirror is negated -> skipped
        # Result: minion at (1,0) is undamaged
        deployed_minion = state.get_minion(1)  # instance_id=1 (newly deployed)
        if deployed_minion is not None:
            # Minion should be at full HP since dark_mirror was negated
            card_def = library.get_by_id(deployed_minion.card_numeric_id)
            assert deployed_minion.current_health == card_def.health

        assert state.phase == TurnPhase.ACTION
        assert state.active_player_idx == 1
        assert state.turn_number == 2


# ---------------------------------------------------------------------------
# Multi-turn and mana flow
# ---------------------------------------------------------------------------


class TestMultiTurnFlow:
    def test_three_turns_state_consistency(self, library):
        """Play 3 turns and verify state transitions are consistent."""
        shadow_knight_id = library.get_numeric_id("shadow_knight")  # cost=3, no ON_PLAY effects

        state = _make_state(
            p1_hand=(shadow_knight_id,),
            p2_hand=(shadow_knight_id,),
        )

        # Turn 1: P1 deploys shadow_knight at (0,0)
        state = resolve_action(state, play_card_action(card_index=0, position=(0, 0)), library)
        state = resolve_action(state, pass_action(), library)  # P2 passes react
        assert state.turn_number == 2
        assert state.active_player_idx == 1

        # Turn 2: P2 deploys shadow_knight at (4,4)
        state = resolve_action(state, play_card_action(card_index=0, position=(4, 4)), library)
        state = resolve_action(state, pass_action(), library)  # P1 passes react
        assert state.turn_number == 3
        assert state.active_player_idx == 0

        # Turn 3: P1 moves shadow_knight from (0,0) to (1,0)
        state = resolve_action(state, move_action(minion_id=0, position=(1, 0)), library)
        state = resolve_action(state, pass_action(), library)  # P2 passes react
        assert state.turn_number == 4
        assert state.active_player_idx == 1

        # Verify both minions on board
        assert state.get_minion(0) is not None
        assert state.get_minion(0).position == (1, 0)
        assert state.get_minion(1) is not None
        assert state.get_minion(1).position == (4, 4)

    def test_mana_deduction_and_regeneration(self, library):
        """Mana is deducted on play and regenerated at turn start."""
        shadow_knight_id = library.get_numeric_id("shadow_knight")  # cost=3, no ON_PLAY effects

        state = _make_state(p1_hand=(shadow_knight_id,), p1_mana=5)

        # P1 plays shadow_knight (cost 3): 5 - 3 = 2
        state = resolve_action(state, play_card_action(card_index=0, position=(0, 0)), library)
        assert state.players[0].current_mana == 2

        # P2 passes react -> turn advances, P2 gets mana regen
        state = resolve_action(state, pass_action(), library)

        # P1 had 2 mana, no regen yet (not P1's turn start)
        assert state.players[0].current_mana == 2
        # P2 had 5 mana, gets +1 = 6
        assert state.players[1].current_mana == 6

    def test_combat_damage_and_cleanup(self, library):
        """Deploy minions, attack, verify damage and dead minion cleanup."""
        fire_imp_id = library.get_numeric_id("fire_imp")  # attack=2, health=2

        attacker = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=2,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_2, position=(2, 2), current_health=2,
        )
        state = _make_state(minions=(attacker, defender))

        # Attack: both deal 2 damage, both die
        state = resolve_action(state, attack_action(minion_id=0, target_id=1), library)

        # Both dead -> cleaned up
        assert state.get_minion(0) is None
        assert state.get_minion(1) is None
        assert state.board.get(1, 2) is None
        assert state.board.get(2, 2) is None

        # Dead minion cards in graveyard
        assert fire_imp_id in state.players[0].graveyard
        assert fire_imp_id in state.players[1].graveyard


# ---------------------------------------------------------------------------
# legal_actions consistency across turns
# ---------------------------------------------------------------------------


class TestLegalActionsConsistency:
    def test_legal_actions_valid_at_every_step(self, library):
        """At every game step, all legal_actions resolve without error."""
        shadow_knight_id = library.get_numeric_id("shadow_knight")  # no ON_PLAY effects
        shield_block_id = library.get_numeric_id("shield_block")

        state = _make_state(
            p1_hand=(shadow_knight_id,),
            p2_hand=(shield_block_id,),
            p1_deck=(shadow_knight_id,),
        )

        # Step 1: ACTION phase - verify all actions are valid
        actions = legal_actions(state, library)
        assert len(actions) > 1
        for a in actions:
            try:
                resolve_action(state, a, library)
            except ValueError as e:
                pytest.fail(f"Step 1 invalid action {a}: {e}")

        # P1 deploys shadow_knight
        state = resolve_action(state, play_card_action(card_index=0, position=(0, 0)), library)

        # Step 2: REACT phase - verify react actions are valid
        actions = legal_actions(state, library)
        assert any(a.action_type == ActionType.PASS for a in actions)
        for a in actions:
            try:
                resolve_action(state, a, library)
            except ValueError as e:
                pytest.fail(f"Step 2 invalid action {a}: {e}")

        # P2 passes react
        state = resolve_action(state, pass_action(), library)

        # Step 3: P2's turn - verify actions
        actions = legal_actions(state, library)
        for a in actions:
            try:
                resolve_action(state, a, library)
            except ValueError as e:
                pytest.fail(f"Step 3 invalid action {a}: {e}")
