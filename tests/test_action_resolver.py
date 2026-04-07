"""Tests for the action resolver -- validates and applies all 5 main-phase actions.

Covers PASS, DRAW, MOVE, PLAY_CARD (minion + magic), ATTACK, dead minion cleanup,
deployment zone validation, attack range validation, and state transitions to REACT.
"""

import pytest
from dataclasses import replace

from grid_tactics.enums import (
    ActionType,
    CardType,
    EffectType,
    PlayerSide,
    ReactCondition,
    TargetType,
    TriggerType,
    TurnPhase,
)
from grid_tactics.cards import CardDefinition, EffectDefinition
from grid_tactics.card_library import CardLibrary
from grid_tactics.actions import Action
from grid_tactics.minion import MinionInstance
from grid_tactics.board import Board
from grid_tactics.player import Player
from grid_tactics.game_state import GameState
from grid_tactics.types import STARTING_HP


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------


def _make_test_library() -> CardLibrary:
    """Create a CardLibrary with test cards.

    Alphabetical ordering gives numeric IDs:
      0 = "test_magic_damage" (magic, 2 mana, ON_PLAY DAMAGE SINGLE_TARGET 2)
      1 = "test_melee"        (minion, 2 mana, atk=2, hp=5, range=0)
      2 = "test_on_death"     (minion, 2 mana, atk=1, hp=3, range=0, ON_DEATH DAMAGE ALL_ENEMIES 1)
      3 = "test_on_play"      (minion, 2 mana, atk=2, hp=4, range=0, ON_PLAY BUFF_ATTACK SELF_OWNER 1)
      4 = "test_ranged"       (minion, 3 mana, atk=1, hp=3, range=2)
      5 = "test_react_card"   (react, 1 mana)
    """
    cards = {
        "test_melee": CardDefinition(
            card_id="test_melee", name="Test Melee", card_type=CardType.MINION,
            mana_cost=2, attack=2, health=5, attack_range=0,
        ),
        "test_ranged": CardDefinition(
            card_id="test_ranged", name="Test Ranged", card_type=CardType.MINION,
            mana_cost=3, attack=1, health=3, attack_range=2,
        ),
        "test_on_death": CardDefinition(
            card_id="test_on_death", name="On Death Minion", card_type=CardType.MINION,
            mana_cost=2, attack=1, health=3, attack_range=0,
            effects=(
                EffectDefinition(
                    effect_type=EffectType.DAMAGE, trigger=TriggerType.ON_DEATH,
                    target=TargetType.ALL_ENEMIES, amount=1,
                ),
            ),
        ),
        "test_on_play": CardDefinition(
            card_id="test_on_play", name="On Play Minion", card_type=CardType.MINION,
            mana_cost=2, attack=2, health=4, attack_range=0,
            effects=(
                EffectDefinition(
                    effect_type=EffectType.BUFF_ATTACK, trigger=TriggerType.ON_PLAY,
                    target=TargetType.SELF_OWNER, amount=1,
                ),
            ),
        ),
        "test_magic_damage": CardDefinition(
            card_id="test_magic_damage", name="Damage Spell", card_type=CardType.MAGIC,
            mana_cost=2,
            effects=(
                EffectDefinition(
                    effect_type=EffectType.DAMAGE, trigger=TriggerType.ON_PLAY,
                    target=TargetType.SINGLE_TARGET, amount=2,
                ),
            ),
        ),
        "test_react_card": CardDefinition(
            card_id="test_react_card", name="Test React", card_type=CardType.REACT,
            mana_cost=1, react_condition=ReactCondition.ANY_ACTION,
        ),
    }
    return CardLibrary(cards)


def _make_state(
    p1_hand=(),
    p2_hand=(),
    p1_mana=5,
    p2_mana=5,
    p1_deck=(),
    p2_deck=(),
    p1_graveyard=(),
    p2_graveyard=(),
    minions=(),
    active_player_idx=0,
    phase=TurnPhase.ACTION,
    board=None,
    next_minion_id=None,
    react_player_idx=None,
):
    """Create a GameState with custom parameters."""
    if board is None:
        board = Board.empty()
        for m in minions:
            board = board.place(m.position[0], m.position[1], m.instance_id)

    if next_minion_id is None:
        next_minion_id = max((m.instance_id for m in minions), default=-1) + 1

    p1 = Player(
        side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=p1_mana,
        max_mana=5, hand=p1_hand, deck=p1_deck, graveyard=p1_graveyard,
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=p2_mana,
        max_mana=5, hand=p2_hand, deck=p2_deck, graveyard=p2_graveyard,
    )
    return GameState(
        board=board,
        players=(p1, p2),
        active_player_idx=active_player_idx,
        phase=phase,
        turn_number=1,
        seed=42,
        minions=tuple(minions),
        next_minion_id=next_minion_id,
        react_player_idx=react_player_idx,
    )


# ---------------------------------------------------------------------------
# PASS action tests
# ---------------------------------------------------------------------------


class TestPassAction:
    """PASS action transitions to REACT phase."""

    def test_pass_transitions_to_react(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        state = _make_state()
        action = Action(action_type=ActionType.PASS)
        new_state = resolve_action(state, action, lib)

        assert new_state.phase == TurnPhase.REACT
        assert new_state.react_player_idx == 1  # opponent of active player 0
        assert new_state.pending_action == action


# ---------------------------------------------------------------------------
# DRAW action tests
# ---------------------------------------------------------------------------


class TestDrawAction:
    """DRAW action moves card from deck to hand."""

    def test_draw_moves_card_from_deck_to_hand(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # P1 has card 1 (test_melee) in deck
        state = _make_state(p1_deck=(1,))
        action = Action(action_type=ActionType.DRAW)
        new_state = resolve_action(state, action, lib)

        assert 1 in new_state.players[0].hand
        assert len(new_state.players[0].deck) == 0

    def test_draw_from_empty_deck_raises(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        state = _make_state(p1_deck=())
        action = Action(action_type=ActionType.DRAW)
        with pytest.raises(ValueError, match="[Dd]eck|[Ee]mpty|[Dd]raw"):
            resolve_action(state, action, lib)


# ---------------------------------------------------------------------------
# MOVE action tests
# ---------------------------------------------------------------------------


class TestMoveAction:
    """MOVE action moves minion to adjacent empty cell."""

    def test_move_to_adjacent_empty_cell(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        minion = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        state = _make_state(minions=[minion])
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0))
        new_state = resolve_action(state, action, lib)

        moved = new_state.get_minion(0)
        assert moved.position == (2, 0)
        assert new_state.board.get(1, 0) is None  # old cell empty
        assert new_state.board.get(2, 0) == 0     # new cell has minion

    def test_move_to_occupied_cell_raises(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        m1 = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        m2 = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(2, 0), current_health=5,
        )
        state = _make_state(minions=[m1, m2])
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0))
        with pytest.raises(ValueError, match="[Oo]ccupied|[Ee]mpty|[Bb]locked"):
            resolve_action(state, action, lib)

    def test_move_to_non_adjacent_cell_raises(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        minion = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        state = _make_state(minions=[minion])
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(3, 0))
        with pytest.raises(ValueError, match="[Ff]orward|[Aa]djacent|[Nn]ot.*valid|LEAP"):
            resolve_action(state, action, lib)

    def test_move_opponent_minion_raises(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        minion = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(3, 0), current_health=5,
        )
        state = _make_state(minions=[minion])
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(4, 0))
        with pytest.raises(ValueError, match="[Oo]wn|[Cc]ontrol|[Bb]elong"):
            resolve_action(state, action, lib)

    def test_move_lateral_raises(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        minion = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        state = _make_state(minions=[minion])
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(1, 1))
        with pytest.raises(ValueError, match="[Ll]ane"):
            resolve_action(state, action, lib)

    def test_move_backward_raises(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        minion = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(2, 0), current_health=5,
        )
        state = _make_state(minions=[minion])
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(1, 0))
        with pytest.raises(ValueError, match="[Ff]orward"):
            resolve_action(state, action, lib)


# ---------------------------------------------------------------------------
# PLAY_CARD action tests
# ---------------------------------------------------------------------------


class TestPlayCardMinion:
    """PLAY_CARD deploys minion, deducts mana, triggers ON_PLAY."""

    def test_deploy_melee_to_friendly_row(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_melee = numeric id 1, mana_cost=2
        state = _make_state(p1_hand=(1,), p1_mana=5)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(1, 2),
        )
        new_state = resolve_action(state, action, lib)

        # Mana deducted
        assert new_state.players[0].current_mana == 3  # 5 - 2
        # Card removed from hand
        assert len(new_state.players[0].hand) == 0
        # Card in graveyard
        assert 1 in new_state.players[0].graveyard
        # Minion created on board
        assert len(new_state.minions) == 1
        m = new_state.minions[0]
        assert m.position == (1, 2)
        assert m.card_numeric_id == 1
        assert m.owner == PlayerSide.PLAYER_1
        assert new_state.board.get(1, 2) == m.instance_id

    def test_deploy_ranged_to_back_row(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_ranged = numeric id 4, mana_cost=3
        state = _make_state(p1_hand=(4,), p1_mana=5)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(0, 2),
        )
        new_state = resolve_action(state, action, lib)

        assert len(new_state.minions) == 1
        assert new_state.minions[0].position == (0, 2)

    def test_deploy_ranged_to_front_row_raises(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_ranged = numeric id 4, ranged must deploy to back row
        state = _make_state(p1_hand=(4,), p1_mana=5)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(1, 2),
        )
        with pytest.raises(ValueError, match="[Bb]ack.*row|[Rr]anged|[Dd]eploy"):
            resolve_action(state, action, lib)

    def test_play_card_insufficient_mana_raises(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_melee costs 2, player has only 1 mana
        state = _make_state(p1_hand=(1,), p1_mana=1)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(0, 0),
        )
        with pytest.raises(ValueError, match="[Mm]ana"):
            resolve_action(state, action, lib)

    def test_on_play_effect_triggers_after_deploy(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_on_play = numeric id 3, ON_PLAY BUFF_ATTACK SELF_OWNER 1
        state = _make_state(p1_hand=(3,), p1_mana=5)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(0, 0),
        )
        new_state = resolve_action(state, action, lib)

        m = new_state.minions[0]
        assert m.attack_bonus == 1  # buffed by ON_PLAY effect

    def test_mana_deduction_correct(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_ranged costs 3
        state = _make_state(p1_hand=(4,), p1_mana=5)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(0, 2),
        )
        new_state = resolve_action(state, action, lib)
        assert new_state.players[0].current_mana == 2  # 5 - 3


class TestPlayCardMagic:
    """PLAY_CARD magic resolves effect and discards."""

    def test_magic_card_resolves_effect_and_discards(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_magic_damage = numeric id 0, ON_PLAY DAMAGE SINGLE_TARGET 2
        # Need a target minion
        enemy = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(3, 0), current_health=5,
        )
        state = _make_state(p1_hand=(0,), p1_mana=5, minions=[enemy])
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, target_pos=(3, 0),
        )
        new_state = resolve_action(state, action, lib)

        # Mana deducted
        assert new_state.players[0].current_mana == 3  # 5 - 2
        # Card removed from hand, added to graveyard
        assert len(new_state.players[0].hand) == 0
        assert 0 in new_state.players[0].graveyard
        # Effect applied: enemy took 2 damage
        assert new_state.get_minion(0).current_health == 3  # 5 - 2


class TestPlayReactInActionPhaseRaises:
    """React cards cannot be played during ACTION phase."""

    def test_play_react_card_in_action_phase_raises(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_react_card = numeric id 5
        state = _make_state(p1_hand=(5,), p1_mana=5)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(0, 0),
        )
        with pytest.raises(ValueError, match="[Rr]eact|[Cc]annot|ACTION"):
            resolve_action(state, action, lib)


# ---------------------------------------------------------------------------
# ATTACK action tests
# ---------------------------------------------------------------------------


class TestAttackAction:
    """ATTACK action with simultaneous damage (D-01)."""

    def test_melee_adjacent_attack_simultaneous_damage(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_melee numeric_id=1: attack=2, health=5, range=0
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 0), current_health=5,
        )
        state = _make_state(minions=[attacker, defender])
        action = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        new_state = resolve_action(state, action, lib)

        # Both take simultaneous damage
        a = new_state.get_minion(0)
        d = new_state.get_minion(1)
        assert a.current_health == 3  # 5 - 2 (defender's attack)
        assert d.current_health == 3  # 5 - 2 (attacker's attack)

    def test_attack_kills_both_simultaneous(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # Both minions at 2 HP with attack=2 -> both die
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=2,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 0), current_health=2,
        )
        state = _make_state(minions=[attacker, defender])
        action = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        new_state = resolve_action(state, action, lib)

        # Both should be removed (dead)
        assert new_state.get_minion(0) is None
        assert new_state.get_minion(1) is None
        assert len(new_state.minions) == 0

    def test_ranged_attack_orthogonal_distance_2(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_ranged numeric_id=4: attack=1, health=3, range=2
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=4, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=3,
        )
        # test_melee numeric_id=1: attack=2, health=5
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 0), current_health=5,
        )
        state = _make_state(minions=[attacker, defender])
        action = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        new_state = resolve_action(state, action, lib)

        # Ranged at distance 2 orthogonal -- valid. Audit-followup: melee
        # defender (range=0) cannot retaliate at dist=2, so attacker takes
        # zero counter-damage (no longer the legacy simultaneous-strike).
        assert new_state.get_minion(0).current_health == 3  # untouched
        assert new_state.get_minion(1).current_health == 4  # 5 - 1

    def test_ranged_attack_diagonal_adjacent(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_ranged numeric_id=4: range=2, allows diagonal adjacent (chebyshev=1)
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=4, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=3,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 1), current_health=5,
        )
        state = _make_state(minions=[attacker, defender])
        action = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        new_state = resolve_action(state, action, lib)

        # Diagonal adjacent: chebyshev=1, should succeed. Audit-followup:
        # melee defender (range=0) uses manhattan<=1 retaliation check;
        # diagonal adjacency is manhattan=2, so no counter-damage.
        assert new_state.get_minion(0).current_health == 3  # untouched
        assert new_state.get_minion(1).current_health == 4  # 5 - 1

    def test_melee_attack_at_distance_2_fails(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=5,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 0), current_health=5,
        )
        state = _make_state(minions=[attacker, defender])
        action = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        with pytest.raises(ValueError, match="[Rr]ange|[Aa]ttack|[Rr]each"):
            resolve_action(state, action, lib)


# ---------------------------------------------------------------------------
# Dead minion cleanup tests
# ---------------------------------------------------------------------------


class TestDeadMinionCleanup:
    """Dead minions removed after action, on_death triggers in instance_id order."""

    def test_dead_minion_removed_from_board_and_minions(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # Attacker kills defender (defender has 2 hp, attacker has atk=2)
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 0), current_health=2,
        )
        state = _make_state(minions=[attacker, defender])
        action = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        new_state = resolve_action(state, action, lib)

        # Defender (hp 2 - 2 = 0) should be dead and removed
        assert new_state.get_minion(1) is None
        assert new_state.board.get(2, 0) is None
        # Attacker alive (hp 5 - 2 = 3)
        assert new_state.get_minion(0) is not None
        assert new_state.get_minion(0).current_health == 3

    def test_on_death_effects_trigger_in_instance_id_order(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        # test_on_death (id=2): ON_DEATH DAMAGE ALL_ENEMIES 1
        # Kill the on_death minion, its death effect should damage enemies
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,  # attack=2
        )
        death_minion = MinionInstance(
            instance_id=1, card_numeric_id=2, owner=PlayerSide.PLAYER_2,
            position=(2, 0), current_health=1,  # dies from 2 damage, attack=1
        )
        # Another P1 minion to verify on_death damage
        bystander = MinionInstance(
            instance_id=2, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=5,
        )
        state = _make_state(minions=[attacker, death_minion, bystander])
        action = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        new_state = resolve_action(state, action, lib)

        # death_minion dies -> ON_DEATH: DAMAGE ALL_ENEMIES 1
        # "enemies" from death_minion's perspective = PLAYER_1 minions
        # attacker took 1 combat damage + 1 on_death = 5 - 1 - 1 = 3
        assert new_state.get_minion(0).current_health == 3
        # bystander took 1 on_death damage = 5 - 1 = 4
        assert new_state.get_minion(2).current_health == 4
        # death_minion is removed
        assert new_state.get_minion(1) is None

    def test_dead_minion_card_goes_to_graveyard(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 0), current_health=2,
        )
        state = _make_state(minions=[attacker, defender])
        action = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        new_state = resolve_action(state, action, lib)

        # Defender's card_numeric_id (1) should be in P2's graveyard
        assert 1 in new_state.players[1].graveyard


# ---------------------------------------------------------------------------
# Phase transition tests
# ---------------------------------------------------------------------------


class TestPhaseTransition:
    """Actions transition to REACT phase with react_player_idx set to opponent."""

    def test_action_transitions_to_react(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        state = _make_state(p1_deck=(1,))
        action = Action(action_type=ActionType.DRAW)
        new_state = resolve_action(state, action, lib)

        assert new_state.phase == TurnPhase.REACT
        assert new_state.react_player_idx == 1  # opponent

    def test_react_phase_delegates_to_react_handler(self):
        """resolve_action delegates to handle_react_action during REACT phase.

        Updated from test_wrong_phase_raises: after 03-03, REACT phase actions
        are handled by handle_react_action instead of raising ValueError.
        """
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        state = _make_state(phase=TurnPhase.REACT, react_player_idx=1)
        action = Action(action_type=ActionType.PASS)
        new_state = resolve_action(state, action, lib)

        # PASS during react resolves stack and advances turn
        assert new_state.phase == TurnPhase.ACTION
        assert new_state.active_player_idx == 1  # flipped from 0
        assert new_state.turn_number == 2

    def test_p2_action_transitions_react_to_p1(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        state = _make_state(active_player_idx=1, p2_deck=(1,))
        action = Action(action_type=ActionType.DRAW)
        new_state = resolve_action(state, action, lib)

        assert new_state.react_player_idx == 0  # opponent of P2


# ---------------------------------------------------------------------------
# Deploy zone validation for P2 (mirror test)
# ---------------------------------------------------------------------------


class TestDeployZoneP2:
    """P2 deployment mirrors P1: melee to rows 3-4, ranged to row 4 only."""

    def test_p2_deploy_melee_to_friendly_row(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        state = _make_state(p2_hand=(1,), p2_mana=5, active_player_idx=1)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(3, 2),
        )
        new_state = resolve_action(state, action, lib)
        assert len(new_state.minions) == 1
        assert new_state.minions[0].position == (3, 2)

    def test_p2_deploy_ranged_to_back_row(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        state = _make_state(p2_hand=(4,), p2_mana=5, active_player_idx=1)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(4, 2),
        )
        new_state = resolve_action(state, action, lib)
        assert new_state.minions[0].position == (4, 2)

    def test_p2_deploy_ranged_to_non_back_row_raises(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        state = _make_state(p2_hand=(4,), p2_mana=5, active_player_idx=1)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(3, 2),
        )
        with pytest.raises(ValueError, match="[Bb]ack.*row|[Rr]anged|[Dd]eploy"):
            resolve_action(state, action, lib)


# ---------------------------------------------------------------------------
# Phase 14.1: Pending post-move attack state tests
# ---------------------------------------------------------------------------


class TestPendingPostMoveAttack:
    """Melee minions enter pending-attack state after a productive forward move."""

    def test_melee_move_sets_pending_state_when_target_in_range(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 1), current_health=5,
        )
        state = _make_state(minions=[attacker, defender])
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0))
        new_state = resolve_action(state, action, lib)

        assert new_state.pending_post_move_attacker_id == 0
        assert new_state.phase == TurnPhase.ACTION
        assert new_state.get_minion(1).current_health == 5

    def test_melee_move_no_pending_when_no_targets(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        state = _make_state(minions=[attacker])
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0))
        new_state = resolve_action(state, action, lib)

        assert new_state.pending_post_move_attacker_id is None
        assert new_state.phase == TurnPhase.REACT

    def test_ranged_move_never_sets_pending(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=4, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=3,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 1), current_health=5,
        )
        state = _make_state(minions=[attacker, defender])
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(1, 0))
        new_state = resolve_action(state, action, lib)

        assert new_state.pending_post_move_attacker_id is None
        assert new_state.phase == TurnPhase.REACT

    def test_pending_attack_resolves_combat_and_clears_state(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 1), current_health=5,
        )
        state = _make_state(minions=[attacker, defender])
        move = Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0))
        state = resolve_action(state, move, lib)
        assert state.pending_post_move_attacker_id == 0

        atk = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        new_state = resolve_action(state, atk, lib)

        assert new_state.pending_post_move_attacker_id is None
        assert new_state.get_minion(0).current_health == 3
        assert new_state.get_minion(1).current_health == 3
        assert new_state.phase == TurnPhase.REACT
        assert new_state.pending_action == atk

    def test_pending_decline_clears_state_with_one_react(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 1), current_health=5,
        )
        state = _make_state(minions=[attacker, defender])
        state = resolve_action(
            state, Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0)), lib,
        )
        assert state.pending_post_move_attacker_id == 0

        decline = Action(action_type=ActionType.DECLINE_POST_MOVE_ATTACK)
        new_state = resolve_action(state, decline, lib)

        assert new_state.pending_post_move_attacker_id is None
        assert new_state.get_minion(0).current_health == 5
        assert new_state.get_minion(1).current_health == 5
        assert new_state.phase == TurnPhase.REACT
        assert new_state.pending_action == decline

    def test_pending_state_blocks_unrelated_actions(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 1), current_health=5,
        )
        state = _make_state(minions=[attacker, defender], p1_hand=(1,))
        state = resolve_action(
            state, Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0)), lib,
        )
        assert state.pending_post_move_attacker_id == 0

        with pytest.raises(ValueError, match="[Pp]ending"):
            resolve_action(state, Action(action_type=ActionType.PASS), lib)

        with pytest.raises(ValueError, match="[Pp]ending"):
            resolve_action(
                state,
                Action(action_type=ActionType.PLAY_CARD, card_index=0, position=(0, 1)),
                lib,
            )

        with pytest.raises(ValueError, match="[Pp]ending"):
            resolve_action(
                state,
                Action(action_type=ActionType.MOVE, minion_id=0, position=(3, 0)),
                lib,
            )

        with pytest.raises(ValueError, match="[Pp]ending"):
            resolve_action(
                state,
                Action(action_type=ActionType.SACRIFICE, minion_id=0),
                lib,
            )

    def test_pending_attack_only_with_pending_attacker(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        other = MinionInstance(
            instance_id=2, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 1), current_health=5,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(2, 1), current_health=5,
        )
        state = _make_state(minions=[attacker, other, defender])
        state = resolve_action(
            state, Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0)), lib,
        )
        assert state.pending_post_move_attacker_id == 0

        with pytest.raises(ValueError, match="[Pp]ending"):
            resolve_action(
                state,
                Action(action_type=ActionType.ATTACK, minion_id=2, target_id=1),
                lib,
            )

    def test_decline_outside_pending_state_raises(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        state = _make_state()
        with pytest.raises(ValueError, match="DECLINE|pending"):
            resolve_action(
                state,
                Action(action_type=ActionType.DECLINE_POST_MOVE_ATTACK),
                lib,
            )


# ---------------------------------------------------------------------------
# Zero-effective-attack ATTACK enumeration gate
# ---------------------------------------------------------------------------


def test_zero_effective_attack_minion_has_no_attack_actions():
    """A minion with effective_attack <= 0 must not be enumerated as an attacker."""
    from grid_tactics.legal_actions import legal_actions

    zero_atk_card = CardDefinition(
        card_id="zero_atk",
        name="Zero Atk",
        card_type=CardType.MINION,
        mana_cost=1,
        attack=0,
        health=10,
        attack_range=0,
    )
    target_card = CardDefinition(
        card_id="target",
        name="Target",
        card_type=CardType.MINION,
        mana_cost=1,
        attack=1,
        health=10,
        attack_range=0,
    )
    lib = CardLibrary({"zero_atk": zero_atk_card, "target": target_card})

    # Place P1 zero-attack adjacent to a P2 enemy
    attacker = MinionInstance(
        instance_id=0,
        card_numeric_id=lib.get_numeric_id("zero_atk"),
        owner=PlayerSide.PLAYER_1,
        position=(2, 2),
        current_health=10,
    )
    enemy = MinionInstance(
        instance_id=1,
        card_numeric_id=lib.get_numeric_id("target"),
        owner=PlayerSide.PLAYER_2,
        position=(2, 3),
        current_health=10,
    )
    board = Board.empty().place(2, 2, 0).place(2, 3, 1)
    p1 = Player(side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=5,
                max_mana=5, hand=(), deck=(), graveyard=())
    p2 = Player(side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=5,
                max_mana=5, hand=(), deck=(), graveyard=())
    state = GameState(
        board=board, players=(p1, p2), active_player_idx=0,
        phase=TurnPhase.ACTION, turn_number=3, seed=42,
        minions=(attacker, enemy), next_minion_id=2,
    )

    actions = legal_actions(state, lib)
    attack_actions = [a for a in actions if a.action_type == ActionType.ATTACK]
    assert attack_actions == [], (
        "Zero-effective-attack minion must not be enumerated as an attacker"
    )

    # Now buff to +1 attack: ATTACK should appear
    buffed = replace(attacker, attack_bonus=1)
    state2 = replace(state, minions=(buffed, enemy))
    actions2 = legal_actions(state2, lib)
    attack_actions2 = [a for a in actions2 if a.action_type == ActionType.ATTACK]
    assert len(attack_actions2) == 1
    assert attack_actions2[0].minion_id == 0
    assert attack_actions2[0].target_id == 1
