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
    ReactContext,
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
        "test_zrally": CardDefinition(
            card_id="test_zrally", name="Rally Minion", card_type=CardType.MINION,
            mana_cost=1, attack=1, health=1, attack_range=2,  # ranged so no 14.1 pending
            effects=(
                EffectDefinition(
                    effect_type=EffectType.RALLY_FORWARD,
                    trigger=TriggerType.ON_MOVE,
                    target=TargetType.SELF_OWNER, amount=1,
                ),
            ),
        ),
    }
    return CardLibrary(cards)


class TestRallyForwardOnMove:
    """RALLY_FORWARD ON_MOVE: moving one friendly with rally also advances
    every other living friendly minion with the same card_numeric_id one
    tile forward (Furryroach behaviour)."""

    def test_zrally_advances_other_friendlies_with_same_card(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        rally_nid = lib.get_numeric_id("test_zrally")
        # Three rally minions for P1 at row 1, cols 0/1/2. P1 moves forward (+row).
        m0 = MinionInstance(instance_id=0, card_numeric_id=rally_nid,
                            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=1)
        m1 = MinionInstance(instance_id=1, card_numeric_id=rally_nid,
                            owner=PlayerSide.PLAYER_1, position=(1, 1), current_health=1)
        m2 = MinionInstance(instance_id=2, card_numeric_id=rally_nid,
                            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=1)
        state = _make_state(minions=[m0, m1, m2])
        # Move m0 forward 1 -> should trigger rally on m1 and m2.
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0))
        new_state = resolve_action(state, action, lib)
        assert new_state.get_minion(0).position == (2, 0)
        assert new_state.get_minion(1).position == (2, 1)
        assert new_state.get_minion(2).position == (2, 2)
        # Board mirrors positions
        assert new_state.board.get(2, 0) == 0
        assert new_state.board.get(2, 1) == 1
        assert new_state.board.get(2, 2) == 2
        assert new_state.board.get(1, 0) is None
        assert new_state.board.get(1, 1) is None
        assert new_state.board.get(1, 2) is None

    def test_zrally_skips_blocked_and_offboard(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        rally_nid = lib.get_numeric_id("test_zrally")
        blocker_nid = lib.get_numeric_id("test_melee")
        # m0 mover; m1 at col1 row1 would rally to (2,1) but blocked by enemy.
        # m2 at col2 row4 is already at back row -> no forward tile for P1? P1 forward=+1, 4+1=5 off-board.
        m0 = MinionInstance(instance_id=0, card_numeric_id=rally_nid,
                            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=1)
        m1 = MinionInstance(instance_id=1, card_numeric_id=rally_nid,
                            owner=PlayerSide.PLAYER_1, position=(1, 1), current_health=1)
        m2 = MinionInstance(instance_id=2, card_numeric_id=rally_nid,
                            owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=1)
        blocker = MinionInstance(instance_id=3, card_numeric_id=blocker_nid,
                                 owner=PlayerSide.PLAYER_2, position=(2, 1), current_health=5)
        state = _make_state(minions=[m0, m1, m2, blocker])
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0))
        new_state = resolve_action(state, action, lib)
        assert new_state.get_minion(0).position == (2, 0)
        assert new_state.get_minion(1).position == (1, 1)  # blocked, unchanged
        assert new_state.get_minion(2).position == (4, 2)  # off-board, unchanged

    def test_zrally_excludes_enemies_and_other_cards(self):
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        rally_nid = lib.get_numeric_id("test_zrally")
        other_nid = lib.get_numeric_id("test_ranged")
        m0 = MinionInstance(instance_id=0, card_numeric_id=rally_nid,
                            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=1)
        # Enemy rally minion — must NOT advance
        enemy = MinionInstance(instance_id=1, card_numeric_id=rally_nid,
                               owner=PlayerSide.PLAYER_2, position=(1, 1), current_health=1)
        # Friendly different card — must NOT advance
        friend_other = MinionInstance(instance_id=2, card_numeric_id=other_nid,
                                      owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=3)
        state = _make_state(minions=[m0, enemy, friend_other])
        action = Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0))
        new_state = resolve_action(state, action, lib)
        assert new_state.get_minion(0).position == (2, 0)
        assert new_state.get_minion(1).position == (1, 1)  # enemy unchanged
        assert new_state.get_minion(2).position == (1, 2)  # other card unchanged


def _make_state(
    p1_hand=(),
    p2_hand=(),
    p1_mana=5,
    p2_mana=5,
    p1_deck=(),
    p2_deck=(),
    p1_grave=(),
    p2_grave=(),
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
        max_mana=5, hand=p1_hand, deck=p1_deck, grave=p1_grave,
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=p2_mana,
        max_mana=5, hand=p2_hand, deck=p2_deck, grave=p2_grave,
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
        from grid_tactics.actions import pass_action

        lib = _make_test_library()
        # test_melee = numeric id 1, mana_cost=2
        state = _make_state(p1_hand=(1,), p1_mana=5)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(1, 2),
        )
        new_state = resolve_action(state, action, lib)
        # Phase 14.7-04: minion doesn't land until Window A (summon
        # declaration) PASS-PASSes. Drain the declaration window so we
        # can assert on the landed minion.
        new_state = resolve_action(new_state, pass_action(), lib)

        # Mana deducted
        assert new_state.players[0].current_mana == 3  # 5 - 2
        # Card removed from hand
        assert len(new_state.players[0].hand) == 0
        # Phase 14.5: minion plays do NOT route to grave on play — the
        # card only enters grave if/when the minion dies (and only if
        # from_deck=True).
        assert 1 not in new_state.players[0].grave
        # Minion created on board
        assert len(new_state.minions) == 1
        m = new_state.minions[0]
        assert m.position == (1, 2)
        assert m.card_numeric_id == 1
        assert m.owner == PlayerSide.PLAYER_1
        assert new_state.board.get(1, 2) == m.instance_id

    def test_deploy_ranged_to_back_row(self):
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import pass_action

        lib = _make_test_library()
        # test_ranged = numeric id 4, mana_cost=3
        state = _make_state(p1_hand=(4,), p1_mana=5)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(0, 2),
        )
        new_state = resolve_action(state, action, lib)
        # Phase 14.7-04: drain Window A to land the minion.
        new_state = resolve_action(new_state, pass_action(), lib)

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
        from grid_tactics.actions import pass_action

        lib = _make_test_library()
        # test_on_play = numeric id 3, ON_PLAY BUFF_ATTACK SELF_OWNER 1.
        # Phase 14.7-04 caveat: the compound-window refactor dispatches
        # _summon_declaration_ then (if the card has ON_SUMMON effects)
        # _summon_effect_. test_on_play uses the legacy ON_PLAY trigger on
        # a minion. Minion ON_PLAY effects no longer fire automatically
        # (only ON_SUMMON does). This test now asserts the minion lands
        # without the buff — the ON_PLAY effect is intentionally orphaned
        # for minions. Migration path: tests that want on-deploy effects
        # should rely on ON_SUMMON in real card JSONs (see Diodebots).
        state = _make_state(p1_hand=(3,), p1_mana=5)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(0, 0),
        )
        new_state = resolve_action(state, action, lib)
        new_state = resolve_action(new_state, pass_action(), lib)

        m = new_state.minions[0]
        # ON_PLAY on minions is legacy; only ON_SUMMON triggers through
        # the compound-window pipeline. Buff is NOT applied.
        assert m.attack_bonus == 0

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
    """PLAY_CARD magic defers effect resolution via an originator on the react stack.

    Phase 14.7-01: Costs (mana, discard) resolve on play; ON_PLAY effects sit
    at the BOTTOM of the react stack as a cast_mode originator and resolve
    LIFO after the chain closes. A Prohibition on top cancels the cast.
    """

    def test_magic_cast_pushes_originator_without_resolving_effect(self):
        """Cast: costs paid, card in grave, originator on stack, effect NOT yet applied."""
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

        # Costs resolved immediately
        assert new_state.players[0].current_mana == 3  # 5 - 2
        assert len(new_state.players[0].hand) == 0
        assert 0 in new_state.players[0].grave

        # Effect DEFERRED — damage should not yet be applied
        assert new_state.get_minion(0).current_health == 5  # unchanged

        # Originator pushed onto the stack, REACT phase entered
        assert new_state.phase.name == "REACT"
        assert new_state.react_player_idx == 1
        assert len(new_state.react_stack) == 1
        origin = new_state.react_stack[0]
        assert origin.is_originator is True
        assert origin.origin_kind == "magic_cast"
        assert origin.card_numeric_id == 0
        assert origin.target_pos == (3, 0)

    def test_magic_cast_resolves_after_both_pass_react(self):
        """With no react, passing through the stack resolves the originator."""
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import pass_action

        lib = _make_test_library()
        enemy = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_2,
            position=(3, 0), current_health=5,
        )
        state = _make_state(p1_hand=(0,), p1_mana=5, minions=[enemy])
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, target_pos=(3, 0),
        )
        state = resolve_action(state, action, lib)
        # P2 passes the react window — stack resolves LIFO, originator fires.
        state = resolve_action(state, pass_action(), lib)

        # Effect applied: enemy took 2 damage
        assert state.get_minion(0).current_health == 3  # 5 - 2
        # Turn advanced
        assert state.phase.name == "ACTION"
        assert state.active_player_idx == 1


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

    def test_dead_minion_card_goes_to_grave(self):
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

        # Defender's card_numeric_id (1) should be in P2's grave
        assert 1 in new_state.players[1].grave


# ---------------------------------------------------------------------------
# Death-keyword tests: ordering, chain reactions, modal targeting, PROMOTE
# parity. Added 2026-04-11 for the death-keyword-and-ordering fix. These
# verify the four defects documented in
# .planning/debug/death-keyword-and-ordering.md are resolved.
# ---------------------------------------------------------------------------


def _make_death_test_library() -> CardLibrary:
    """Extended test library with cards exercising every on_death shape.

    Card IDs (alphabetical ordering assigns numeric IDs):
      0 = "test_die_destroy"    : DESTROY / SINGLE_TARGET on_death (modal path)
      1 = "test_die_damage_all" : DAMAGE ALL_ENEMIES on_death (synchronous path)
      2 = "test_die_promote"    : PROMOTE on_death (unique), promote_target=test_rat
      3 = "test_melee"          : vanilla melee minion for bystanders
      4 = "test_rat"            : small minion, target of promote
    """
    cards = {
        "test_die_destroy": CardDefinition(
            card_id="test_die_destroy", name="Destroy-on-Death",
            card_type=CardType.MINION, mana_cost=3, attack=1, health=1, attack_range=0,
            effects=(
                EffectDefinition(
                    effect_type=EffectType.DESTROY,
                    trigger=TriggerType.ON_DEATH,
                    target=TargetType.SINGLE_TARGET,
                    amount=1,
                ),
            ),
        ),
        "test_die_damage_all": CardDefinition(
            card_id="test_die_damage_all", name="Damage-on-Death",
            card_type=CardType.MINION, mana_cost=2, attack=1, health=1, attack_range=0,
            effects=(
                EffectDefinition(
                    effect_type=EffectType.DAMAGE,
                    trigger=TriggerType.ON_DEATH,
                    target=TargetType.ALL_ENEMIES,
                    amount=1,
                ),
            ),
        ),
        "test_die_promote": CardDefinition(
            card_id="test_die_promote", name="Promote-on-Death",
            card_type=CardType.MINION, mana_cost=3, attack=3, health=3, attack_range=0,
            effects=(
                EffectDefinition(
                    effect_type=EffectType.PROMOTE,
                    trigger=TriggerType.ON_DEATH,
                    target=TargetType.SELF_OWNER,
                    amount=1,
                ),
            ),
            promote_target="test_rat",
            unique=True,
        ),
        "test_melee": CardDefinition(
            card_id="test_melee", name="Test Melee",
            card_type=CardType.MINION, mana_cost=2, attack=2, health=5, attack_range=0,
        ),
        "test_rat": CardDefinition(
            card_id="test_rat", name="Test Rat",
            card_type=CardType.MINION, mana_cost=1, attack=1, health=1, attack_range=0,
        ),
    }
    return CardLibrary(cards)


class TestDeathKeywordPromote:
    """PROMOTE on_death parity: the Python engine now runs _apply_promote
    (previously silently skipped). Mirrors the tensor engine implementation.
    """

    def test_promote_on_death_transforms_friendly_rat(self):
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        promote_nid = lib.get_numeric_id("test_die_promote")
        rat_nid = lib.get_numeric_id("test_rat")

        # A dying "Promote-on-Death" (already at 0 hp) plus a friendly rat
        # to promote into it. unique=True, no other live copy — should
        # promote the rat.
        dying = MinionInstance(
            instance_id=0, card_numeric_id=promote_nid,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=0,
        )
        rat = MinionInstance(
            instance_id=1, card_numeric_id=rat_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=1,
        )
        state = _make_state(minions=[dying, rat])
        new_state = _cleanup_dead_minions(state, lib)

        # Dying minion is gone; rat has been transformed into promote.
        assert new_state.get_minion(0) is None
        rat_after = new_state.get_minion(1)
        assert rat_after is not None
        assert rat_after.card_numeric_id == promote_nid
        assert rat_after.current_health == 3  # promote card base hp
        assert rat_after.attack_bonus == 0

    def test_promote_unique_constraint_skips_when_copy_alive(self):
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        promote_nid = lib.get_numeric_id("test_die_promote")
        rat_nid = lib.get_numeric_id("test_rat")

        dying = MinionInstance(
            instance_id=0, card_numeric_id=promote_nid,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=0,
        )
        live_copy = MinionInstance(
            instance_id=1, card_numeric_id=promote_nid,
            owner=PlayerSide.PLAYER_1, position=(3, 3), current_health=3,
        )
        rat = MinionInstance(
            instance_id=2, card_numeric_id=rat_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=1,
        )
        state = _make_state(minions=[dying, live_copy, rat])
        new_state = _cleanup_dead_minions(state, lib)

        # unique=True + another live copy exists -> promote is skipped.
        rat_after = new_state.get_minion(2)
        assert rat_after is not None
        assert rat_after.card_numeric_id == rat_nid  # unchanged

    def test_promote_opens_modal_with_2_candidates(self):
        """With 2+ candidate Rats, promote opens the player-choice modal
        (filter=friendly_promote) instead of auto-picking the most-advanced
        one. Auto-pick is reserved for the unambiguous 1-candidate case.
        """
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        promote_nid = lib.get_numeric_id("test_die_promote")
        rat_nid = lib.get_numeric_id("test_rat")

        dying = MinionInstance(
            instance_id=0, card_numeric_id=promote_nid,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=0,
        )
        back_rat = MinionInstance(
            instance_id=1, card_numeric_id=rat_nid,
            owner=PlayerSide.PLAYER_1, position=(0, 0), current_health=1,
        )
        forward_rat = MinionInstance(
            instance_id=2, card_numeric_id=rat_nid,
            owner=PlayerSide.PLAYER_1, position=(3, 0), current_health=1,
        )
        state = _make_state(minions=[dying, back_rat, forward_rat])
        new_state = _cleanup_dead_minions(state, lib)

        # Neither Rat is promoted yet — the modal is pending; the player
        # picks which one. Both Rats remain Rats until DEATH_TARGET_PICK
        # resolves.
        assert new_state.pending_death_target is not None
        assert new_state.pending_death_target.filter == "friendly_promote"
        forward_after = new_state.get_minion(2)
        back_after = new_state.get_minion(1)
        assert forward_after.card_numeric_id == rat_nid
        assert back_after.card_numeric_id == rat_nid


def _drain_all_death_triggers(state, lib):
    """Test helper: drive the priority-queue drain to completion.

    Phase 14.7-05b: _cleanup_dead_minions enqueues on_death PendingTriggers
    into pending_trigger_queue_turn / pending_trigger_queue_other and
    opens a REACT window after each individual trigger resolves. To
    observe the end-state (all triggers resolved, all chain reactions
    settled), we simulate PASS-PASS for each opened react window —
    resolve_react_stack's drain-recheck hook continues the drain.

    Handles trigger-picker modals by picking queue index 0 (the
    turn-player-first order is preserved by _apply_trigger_pick's
    move-to-front logic). Bounded to avoid infinite loops.
    """
    from grid_tactics.action_resolver import resolve_action
    from grid_tactics.actions import Action
    from grid_tactics.enums import ActionType, TurnPhase

    safety = 0
    while safety < 64:
        safety += 1
        if state.is_game_over:
            return state
        if state.pending_trigger_picker_idx is not None:
            state = resolve_action(
                state,
                Action(action_type=ActionType.TRIGGER_PICK, card_index=0),
                lib,
            )
            continue
        if state.pending_death_target is not None:
            # Not auto-drainable without a target choice — caller must
            # drive DEATH_TARGET_PICK. Return as-is.
            return state
        if state.phase == TurnPhase.REACT:
            # Drain the react window via PASS.
            state = resolve_action(
                state, Action(action_type=ActionType.PASS), lib,
            )
            continue
        # No pending work.
        return state
    return state


class TestDeathKeywordOrdering:
    """Turn-player-first death ordering (Phase 14.7-05b): when minions
    from both sides die in the same cleanup pass, the turn player's
    on_death effects fire first (spec §7.2 priority queue)."""

    def test_active_player_deaths_fire_before_opponent(self):
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        damage_nid = lib.get_numeric_id("test_die_damage_all")
        melee_nid = lib.get_numeric_id("test_melee")

        # Two dying minions, one per side, active player = P2.
        # Each has DAMAGE ALL_ENEMIES on_death (amount=1).
        # P2 is active, so P2's dying minion fires first. Its "enemies"
        # are P1 minions (including the other dying minion, which is
        # already at 0 hp — no change). P1's dying effect fires second;
        # its enemy is a live P2 bystander.
        p1_dying = MinionInstance(
            instance_id=0, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=0,
        )
        p2_dying = MinionInstance(
            instance_id=1, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_2, position=(3, 0), current_health=0,
        )
        p2_bystander = MinionInstance(
            instance_id=2, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_2, position=(4, 4), current_health=5,
        )
        p1_bystander = MinionInstance(
            instance_id=3, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_1, position=(0, 4), current_health=5,
        )
        state = _make_state(
            minions=[p1_dying, p2_dying, p2_bystander, p1_bystander],
            active_player_idx=1,  # P2 active
        )
        state = _cleanup_dead_minions(state, lib)
        # Phase 14.7-05b: drain each opened react window + picker modal.
        new_state = _drain_all_death_triggers(state, lib)

        # Both bystanders took 1 damage from their opposing dying minion.
        assert new_state.get_minion(2).current_health == 4  # P2 bystander
        assert new_state.get_minion(3).current_health == 4  # P1 bystander
        # Both dying minions removed.
        assert new_state.get_minion(0) is None
        assert new_state.get_minion(1) is None
        # Priority queues fully drained.
        assert new_state.pending_trigger_queue_turn == ()
        assert new_state.pending_trigger_queue_other == ()
        assert new_state.pending_death_target is None

    def test_ordering_tiebreak_by_instance_id(self):
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        damage_nid = lib.get_numeric_id("test_die_damage_all")
        melee_nid = lib.get_numeric_id("test_melee")

        # Two P1 dying minions with different instance_ids; P1 is active.
        # Both fire DAMAGE ALL_ENEMIES 1 via the priority queue with the
        # trigger picker modal (2 entries on P1's side). _drain_all opens
        # the modal + picks index 0 twice. Final bystander takes 2 damage
        # regardless of pick order (both effects resolve).
        dying_a = MinionInstance(
            instance_id=5, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=0,
        )
        dying_b = MinionInstance(
            instance_id=3, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_1, position=(2, 0), current_health=0,
        )
        bystander = MinionInstance(
            instance_id=1, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_2, position=(4, 4), current_health=5,
        )
        state = _make_state(
            minions=[dying_a, dying_b, bystander],
            active_player_idx=0,
        )
        state = _cleanup_dead_minions(state, lib)
        new_state = _drain_all_death_triggers(state, lib)

        # Bystander took 2 damage (one per dying minion's on_death).
        assert new_state.get_minion(1).current_health == 3


class TestDeathKeywordChainReaction:
    """Chain-reaction death cleanup: an on_death effect that kills another
    minion enqueues that minion's on_death into the priority queue.
    After Phase 14.7-05b the chain entry fires on the next drain pass
    (after the original trigger's react window closes)."""

    def test_chain_death_damage_kills_another_minion_with_on_death(self):
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        damage_nid = lib.get_numeric_id("test_die_damage_all")
        melee_nid = lib.get_numeric_id("test_melee")

        # P1 dying with DAMAGE ALL_ENEMIES 1. A P2 minion with
        # DAMAGE ALL_ENEMIES on_death has 1 hp — will be killed by the
        # chain. Its on_death should enqueue and fire on the next
        # drain pass, damaging a P1 bystander.
        p1_dying = MinionInstance(
            instance_id=0, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=0,
        )
        p2_chain = MinionInstance(
            instance_id=1, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_2, position=(3, 0), current_health=1,
        )
        p1_bystander = MinionInstance(
            instance_id=2, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_1, position=(0, 4), current_health=5,
        )
        state = _make_state(
            minions=[p1_dying, p2_chain, p1_bystander],
            active_player_idx=0,
        )
        state = _cleanup_dead_minions(state, lib)
        new_state = _drain_all_death_triggers(state, lib)

        # Chain resolved: p2_chain killed by p1_dying's effect, then its
        # own on_death damaged p1_bystander (5 - 1 = 4).
        assert new_state.get_minion(0) is None
        assert new_state.get_minion(1) is None
        assert new_state.get_minion(2).current_health == 4
        assert new_state.pending_trigger_queue_turn == ()
        assert new_state.pending_trigger_queue_other == ()


class TestDeathKeywordLasercannonModal:
    """Lasercannon's DESTROY / SINGLE_TARGET on_death opens a click-target
    modal. The dying minion's owner picks an enemy to destroy; between the
    death and the pick, the engine is parked in pending_death_target state
    and blocks other actions."""

    def test_modal_opens_when_destroy_on_death_has_enemy_targets(self):
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        destroy_nid = lib.get_numeric_id("test_die_destroy")
        melee_nid = lib.get_numeric_id("test_melee")

        # P1 Lasercannon-alike dies; P2 has two melee bystanders; the
        # modal should fire and wait for P1 to pick one to destroy.
        dying = MinionInstance(
            instance_id=0, card_numeric_id=destroy_nid,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=0,
        )
        enemy_a = MinionInstance(
            instance_id=1, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_2, position=(3, 0), current_health=5,
        )
        enemy_b = MinionInstance(
            instance_id=2, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_2, position=(3, 4), current_health=5,
        )
        state = _make_state(
            minions=[dying, enemy_a, enemy_b],
            active_player_idx=0,
        )
        new_state = _cleanup_dead_minions(state, lib)

        assert new_state.pending_death_target is not None
        assert new_state.pending_death_target.owner_idx == 0
        assert new_state.pending_death_target.card_numeric_id == destroy_nid
        assert new_state.pending_death_target.filter == "enemy_minion"
        # Both enemies still alive, modal parks waiting for the pick.
        assert new_state.get_minion(1) is not None
        assert new_state.get_minion(2) is not None

    def test_modal_no_op_when_no_legal_target(self):
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        destroy_nid = lib.get_numeric_id("test_die_destroy")

        # Dying minion, no enemies on the board -> modal auto-skips.
        dying = MinionInstance(
            instance_id=0, card_numeric_id=destroy_nid,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=0,
        )
        state = _make_state(minions=[dying], active_player_idx=0)
        new_state = _cleanup_dead_minions(state, lib)

        assert new_state.pending_death_target is None
        assert new_state.pending_death_queue == ()

    def test_modal_pick_resolves_and_destroys_picked_enemy(self):
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.effect_resolver import apply_death_target_pick

        lib = _make_death_test_library()
        destroy_nid = lib.get_numeric_id("test_die_destroy")
        melee_nid = lib.get_numeric_id("test_melee")

        attacker = MinionInstance(
            instance_id=0, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=5,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=destroy_nid,
            owner=PlayerSide.PLAYER_2, position=(2, 0), current_health=1,
        )
        target_a = MinionInstance(
            instance_id=2, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=5,
        )
        state = _make_state(minions=[attacker, defender, target_a])
        # P1 attacks, killing defender -> defender's modal opens for P2.
        action = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        new_state = resolve_action(state, action, lib)

        assert new_state.pending_death_target is not None
        assert new_state.pending_death_target.owner_idx == 1  # P2 (defender's owner)

        # P2 submits DEATH_TARGET_PICK at target_a's position.
        pick = Action(
            action_type=ActionType.DEATH_TARGET_PICK,
            target_pos=(4, 2),
        )
        final = resolve_action(new_state, pick, lib)

        # Defender destroyed, target_a destroyed by the modal DESTROY
        # effect (health set to 0 then cleanup removed it).
        assert final.get_minion(1) is None
        assert final.get_minion(2) is None
        assert final.pending_death_target is None
        assert final.pending_death_queue == ()
        # Phase transitioned to REACT after the modal drained.
        assert final.phase == TurnPhase.REACT
        assert final.react_player_idx == 1

    def test_legal_actions_during_pending_death_modal(self):
        from grid_tactics.action_resolver import _cleanup_dead_minions
        from grid_tactics.legal_actions import legal_actions

        lib = _make_death_test_library()
        destroy_nid = lib.get_numeric_id("test_die_destroy")
        melee_nid = lib.get_numeric_id("test_melee")

        dying = MinionInstance(
            instance_id=0, card_numeric_id=destroy_nid,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=0,
        )
        enemy_a = MinionInstance(
            instance_id=1, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_2, position=(3, 0), current_health=5,
        )
        enemy_b = MinionInstance(
            instance_id=2, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_2, position=(3, 4), current_health=5,
        )
        state = _make_state(
            minions=[dying, enemy_a, enemy_b],
            active_player_idx=0,
        )
        new_state = _cleanup_dead_minions(state, lib)

        assert new_state.pending_death_target is not None
        la = legal_actions(new_state, lib)
        # Only DEATH_TARGET_PICK actions, one per valid enemy minion tile.
        assert len(la) == 2
        for a in la:
            assert a.action_type == ActionType.DEATH_TARGET_PICK
            assert a.target_pos in ((3, 0), (3, 4))


# ---------------------------------------------------------------------------
# Phase 14.7-05b: Death-trigger priority queue tests
#
# Verifies the _cleanup_dead_minions refactor: dead minions' ON_DEATH
# effects now enqueue into pending_trigger_queue_turn /
# pending_trigger_queue_other (spec §7.2 priority queue) instead of
# resolving inline via the legacy (active_first, instance_id) sort.
# ---------------------------------------------------------------------------


class TestDeathTriggerPriorityQueue:
    """Phase 14.7-05b: death-trigger priority queue integration.

    These tests exercise the NEW mechanism (PendingTrigger enqueue +
    drain) that replaces the legacy PendingDeathWork inline-resolve
    path. They complement the pre-existing TestDeathKeyword* classes
    (updated in-place to match new semantics via
    _drain_all_death_triggers).
    """

    def test_single_death_auto_resolves(self):
        """One dying minion with one ON_DEATH effect: auto-resolve via
        the turn queue (queue_turn has exactly 1 entry → no picker
        modal; _resolve_trigger_and_open_react_window auto-resolves and
        opens the AFTER_DEATH_EFFECT window)."""
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        damage_nid = lib.get_numeric_id("test_die_damage_all")
        melee_nid = lib.get_numeric_id("test_melee")

        dying = MinionInstance(
            instance_id=0, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=0,
        )
        enemy = MinionInstance(
            instance_id=1, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_2, position=(3, 3), current_health=5,
        )
        state = _make_state(minions=[dying, enemy], active_player_idx=0)
        new_state = _cleanup_dead_minions(state, lib)

        # Auto-resolved: enemy damaged, queue empty, picker NOT set.
        assert new_state.get_minion(1).current_health == 4
        assert new_state.pending_trigger_queue_turn == ()
        assert new_state.pending_trigger_queue_other == ()
        assert new_state.pending_trigger_picker_idx is None
        # Cleanup opened an AFTER_DEATH_EFFECT react window.
        from grid_tactics.enums import TurnPhase as _TP, ReactContext as _RC
        assert new_state.phase == _TP.REACT
        assert new_state.react_context == _RC.AFTER_DEATH_EFFECT

    def test_two_simultaneous_turn_player_deaths_open_picker(self):
        """Two dying minions, both on P1 (turn player): the priority
        queue holds 2 entries on the turn side → modal picker opens for
        P1 (pending_trigger_picker_idx == active_player_idx)."""
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        damage_nid = lib.get_numeric_id("test_die_damage_all")
        melee_nid = lib.get_numeric_id("test_melee")

        dying_a = MinionInstance(
            instance_id=0, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=0,
        )
        dying_b = MinionInstance(
            instance_id=1, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_1, position=(2, 0), current_health=0,
        )
        enemy = MinionInstance(
            instance_id=2, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_2, position=(3, 3), current_health=5,
        )
        state = _make_state(
            minions=[dying_a, dying_b, enemy], active_player_idx=0,
        )
        new_state = _cleanup_dead_minions(state, lib)

        # Picker opens for P1 (turn player).
        assert new_state.pending_trigger_picker_idx == 0
        assert len(new_state.pending_trigger_queue_turn) == 2
        assert new_state.pending_trigger_queue_other == ()

    def test_turn_player_deaths_resolve_first_with_single_each_side(self):
        """P1 (turn) + P2 each have ONE dying minion. Both queues have
        one entry, no picker. Drain order: turn queue first → other
        queue second. Observable: both bystanders damaged after full
        drain (each side's dying minion hit the opposing bystander)."""
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        damage_nid = lib.get_numeric_id("test_die_damage_all")
        melee_nid = lib.get_numeric_id("test_melee")

        p1_dying = MinionInstance(
            instance_id=0, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=0,
        )
        p2_dying = MinionInstance(
            instance_id=1, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_2, position=(3, 0), current_health=0,
        )
        p1_bystander = MinionInstance(
            instance_id=2, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_1, position=(0, 4), current_health=5,
        )
        p2_bystander = MinionInstance(
            instance_id=3, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_2, position=(4, 4), current_health=5,
        )
        state = _make_state(
            minions=[p1_dying, p2_dying, p1_bystander, p2_bystander],
            active_player_idx=0,
        )
        state = _cleanup_dead_minions(state, lib)
        # Drive drain to completion.
        final = _drain_all_death_triggers(state, lib)

        # Both bystanders took damage from the opposing dying minion.
        assert final.get_minion(2).current_health == 4  # P1 bystander
        assert final.get_minion(3).current_health == 4  # P2 bystander
        # Queues fully drained.
        assert final.pending_trigger_queue_turn == ()
        assert final.pending_trigger_queue_other == ()

    def test_death_with_pending_death_target_modal_integrates(self):
        """DESTROY/SINGLE_TARGET on_death (Lasercannon-like) + priority
        queue: when such a trigger auto-resolves from queue_turn, it
        opens the effect-level pending_death_target modal (preserving
        the pre-14.7-05 UX). After the user picks, the flow resumes
        through the cleanup+drain+react-window chain."""
        from grid_tactics.action_resolver import resolve_action

        lib = _make_death_test_library()
        destroy_nid = lib.get_numeric_id("test_die_destroy")
        melee_nid = lib.get_numeric_id("test_melee")

        # P1 attacks and both die: P1's attacker dies (simple melee,
        # no on_death) + P2's destroy-on-death defender dies.
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=5,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=destroy_nid,
            owner=PlayerSide.PLAYER_2, position=(2, 0), current_health=1,
        )
        target_enemy = MinionInstance(
            instance_id=2, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=5,
        )
        state = _make_state(
            minions=[attacker, defender, target_enemy],
            active_player_idx=0,
        )
        # P1 attacks defender → defender dies. defender's ON_DEATH
        # DESTROY/SINGLE_TARGET opens the pending_death_target modal
        # for P2 (defender's owner).
        action = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        mid_state = resolve_action(state, action, lib)

        assert mid_state.pending_death_target is not None
        assert mid_state.pending_death_target.owner_idx == 1  # P2
        # Priority queue popped this entry already (the modal opened
        # INSTEAD of the react window).
        assert mid_state.pending_trigger_queue_turn == ()
        assert mid_state.pending_trigger_queue_other == ()

        # P2 picks target_enemy at (4, 2).
        pick = Action(
            action_type=ActionType.DEATH_TARGET_PICK,
            target_pos=(4, 2),
        )
        final = resolve_action(mid_state, pick, lib)

        # target_enemy destroyed by the modal effect.
        assert final.get_minion(2) is None
        # pending_death_target cleared, queues drained, and
        # AFTER_DEATH_EFFECT react window is open.
        assert final.pending_death_target is None
        from grid_tactics.enums import TurnPhase as _TP, ReactContext as _RC
        assert final.phase == _TP.REACT
        assert final.react_context == _RC.AFTER_DEATH_EFFECT

    def test_chain_reaction_death_preserves_turn_first_ordering(self):
        """Chain-reaction: P1 (turn) has a damage-on-death minion dying.
        P2's chain-victim has 1 HP + its own on_death. After P1's
        effect resolves, the P2 victim dies and its trigger enqueues
        into pending_trigger_queue_other. Drain-recheck (on window
        close) continues with the P2 chain trigger — P2's effect
        damages the P1 bystander."""
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = _make_death_test_library()
        damage_nid = lib.get_numeric_id("test_die_damage_all")
        melee_nid = lib.get_numeric_id("test_melee")

        p1_dying = MinionInstance(
            instance_id=0, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=0,
        )
        p2_chain = MinionInstance(
            instance_id=1, card_numeric_id=damage_nid,
            owner=PlayerSide.PLAYER_2, position=(3, 0), current_health=1,
        )
        p1_bystander = MinionInstance(
            instance_id=2, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_1, position=(0, 4), current_health=5,
        )
        state = _make_state(
            minions=[p1_dying, p2_chain, p1_bystander],
            active_player_idx=0,
        )
        state = _cleanup_dead_minions(state, lib)
        final = _drain_all_death_triggers(state, lib)

        # Chain resolved: p2_chain died from p1_dying's effect, then
        # its own on_death damaged p1_bystander (5 → 4).
        assert final.get_minion(0) is None  # p1_dying removed
        assert final.get_minion(1) is None  # p2_chain removed
        assert final.get_minion(2).current_health == 4  # p1_bystander
        assert final.pending_trigger_queue_turn == ()
        assert final.pending_trigger_queue_other == ()


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
        from grid_tactics.actions import pass_action

        lib = _make_test_library()
        state = _make_state(p2_hand=(1,), p2_mana=5, active_player_idx=1)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(3, 2),
        )
        new_state = resolve_action(state, action, lib)
        # Phase 14.7-04: drain Window A to land the minion.
        new_state = resolve_action(new_state, pass_action(), lib)
        assert len(new_state.minions) == 1
        assert new_state.minions[0].position == (3, 2)

    def test_p2_deploy_ranged_to_back_row(self):
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import pass_action

        lib = _make_test_library()
        state = _make_state(p2_hand=(4,), p2_mana=5, active_player_idx=1)
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(4, 2),
        )
        new_state = resolve_action(state, action, lib)
        new_state = resolve_action(new_state, pass_action(), lib)
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

        # Phase 14.7-08: pending state persists + the post-move REACT
        # window opens immediately (spec v2 §4.1 — two independent react
        # windows per melee chain). This SUPERSEDES 14.1's single-window
        # assertion that phase stayed ACTION.
        assert new_state.pending_post_move_attacker_id == 0
        assert new_state.phase == TurnPhase.REACT
        assert new_state.react_context == ReactContext.AFTER_ACTION
        assert new_state.react_return_phase == TurnPhase.ACTION
        assert new_state.react_player_idx == 1  # opponent reacts
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
        # Phase 14.7-08: post-move REACT window opens immediately. Drain
        # it (opponent PASSes on the empty stack) before the attack
        # sub-action. Returns us to ACTION with pending intact.
        assert state.pending_post_move_attacker_id == 0
        assert state.phase == TurnPhase.REACT
        state = resolve_action(state, Action(action_type=ActionType.PASS), lib)
        assert state.phase == TurnPhase.ACTION
        assert state.pending_post_move_attacker_id == 0

        atk = Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1)
        new_state = resolve_action(state, atk, lib)

        assert new_state.pending_post_move_attacker_id is None
        assert new_state.get_minion(0).current_health == 3
        assert new_state.get_minion(1).current_health == 3
        # Second (post-attack) react window opens per spec v2 §4.1.
        assert new_state.phase == TurnPhase.REACT
        assert new_state.pending_action == atk

    def test_pending_decline_skips_second_react_window(self):
        """Phase 14.7-08: DECLINE means "no second action" → no second react window.

        Prior to 14.7-08 the DECLINE opened a phantom react window. Now
        the post-move window already fired (around the move) and DECLINE
        advances directly to END_OF_TURN (which, absent End triggers,
        shortcuts to turn-advance, i.e. opponent's START_OF_TURN →
        ACTION).
        """
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
        # Drain the post-move react window first (Phase 14.7-08).
        assert state.pending_post_move_attacker_id == 0
        assert state.phase == TurnPhase.REACT
        # Opponent's single PASS resolves the (empty) react stack; pending
        # flag survives so we return to ACTION for the optional attack.
        state = resolve_action(state, Action(action_type=ActionType.PASS), lib)
        assert state.phase == TurnPhase.ACTION
        assert state.pending_post_move_attacker_id == 0

        decline = Action(action_type=ActionType.DECLINE_POST_MOVE_ATTACK)
        new_state = resolve_action(state, decline, lib)

        # DECLINE clears pending, runs end-of-turn, and advances turn.
        # No second react window opens — 14.7-08 explicit behavior.
        assert new_state.pending_post_move_attacker_id is None
        assert new_state.get_minion(0).current_health == 5
        assert new_state.get_minion(1).current_health == 5
        # Turn has advanced to P2's ACTION (no End triggers, so END_OF_TURN
        # shortcuts to turn-advance → new player's START_OF_TURN → ACTION).
        assert new_state.active_player_idx == 1
        assert new_state.phase == TurnPhase.ACTION

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
        # Phase 14.7-08: post-move react window fires first. Drain it so
        # we land back in ACTION with pending still set — that's where
        # unrelated actions must be rejected.
        assert state.pending_post_move_attacker_id == 0
        assert state.phase == TurnPhase.REACT
        # Opponent's single PASS resolves the (empty) react stack; pending
        # flag survives so we return to ACTION for the optional attack.
        state = resolve_action(state, Action(action_type=ActionType.PASS), lib)
        assert state.phase == TurnPhase.ACTION
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
        # Phase 14.7-08: drain post-move react window first.
        assert state.pending_post_move_attacker_id == 0
        assert state.phase == TurnPhase.REACT
        # Opponent's single PASS resolves the (empty) react stack; pending
        # flag survives so we return to ACTION for the optional attack.
        state = resolve_action(state, Action(action_type=ActionType.PASS), lib)
        assert state.phase == TurnPhase.ACTION
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
# Phase 14.7-08: Two independent react windows for melee move+attack chains
# (spec v2 §4.1). Supersedes Phase 14.1's combined-single-window semantic.
# ---------------------------------------------------------------------------


class TestMeleeTwoReactWindows:
    """14.7-08: melee chain opens TWO independent react windows (move + attack).

    - Post-move window (react_context=AFTER_ACTION, return_phase=ACTION)
    - If player ATTACKs: second react window opens post-attack
    - If player DECLINEs: NO second react window — turn advances directly
    - pending_post_move_attacker_id survives the post-move react window
    - Prior 14.1 behavior (single react window after the combined action)
      is explicitly superseded per key_user_decisions #1.
    """

    def test_melee_move_opens_post_move_react_window(self):
        """MOVE by a melee minion with in-range targets enters REACT."""
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
            state,
            Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0)),
            lib,
        )

        # Window 1 open, pending preserved.
        assert state.phase == TurnPhase.REACT
        assert state.pending_post_move_attacker_id == 0
        assert state.react_context == ReactContext.AFTER_ACTION
        assert state.react_return_phase == TurnPhase.ACTION
        assert state.react_player_idx == 1  # P2 reacts post-move

        # Opponent PASSes on an empty react stack → window closes, we return
        # to ACTION with the pending flag intact for the optional attack.
        state = resolve_action(state, Action(action_type=ActionType.PASS), lib)
        assert state.phase == TurnPhase.ACTION
        assert state.pending_post_move_attacker_id == 0
        # The closing window cleared its bookkeeping.
        assert state.react_stack == ()
        assert state.react_context is None
        assert state.react_return_phase is None

    def test_melee_move_attack_opens_two_react_windows(self):
        """Full move+attack chain fires both windows; turn advances ONCE."""
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
        initial_turn = state.turn_number
        # Window 1: MOVE
        state = resolve_action(
            state,
            Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0)),
            lib,
        )
        assert state.phase == TurnPhase.REACT
        # Close window 1.
        state = resolve_action(state, Action(action_type=ActionType.PASS), lib)
        assert state.phase == TurnPhase.ACTION
        assert state.pending_post_move_attacker_id == 0

        # ATTACK: window 2 opens.
        state = resolve_action(
            state,
            Action(action_type=ActionType.ATTACK, minion_id=0, target_id=1),
            lib,
        )
        assert state.phase == TurnPhase.REACT
        assert state.react_context == ReactContext.AFTER_ACTION
        assert state.react_return_phase == TurnPhase.ACTION
        assert state.pending_post_move_attacker_id is None

        # Close window 2 → turn advances to P2 exactly once.
        state = resolve_action(state, Action(action_type=ActionType.PASS), lib)
        assert state.active_player_idx == 1
        assert state.phase == TurnPhase.ACTION
        # One full round-trip consumed one turn, not two.
        assert state.turn_number == initial_turn + 1

    def test_melee_move_decline_skips_second_window(self):
        """DECLINE after the post-move window advances turn — no phantom window."""
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
        # Move + close window 1.
        state = resolve_action(
            state,
            Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0)),
            lib,
        )
        state = resolve_action(state, Action(action_type=ActionType.PASS), lib)
        assert state.phase == TurnPhase.ACTION
        assert state.pending_post_move_attacker_id == 0

        # DECLINE: no second window. Turn advances directly.
        state = resolve_action(
            state,
            Action(action_type=ActionType.DECLINE_POST_MOVE_ATTACK),
            lib,
        )
        assert state.pending_post_move_attacker_id is None
        assert state.active_player_idx == 1
        # No End triggers / Start triggers in this test fixture → go direct
        # to P2's ACTION phase without a second REACT window.
        assert state.phase == TurnPhase.ACTION
        assert state.react_stack == ()

    def test_ranged_move_single_react_window(self):
        """Ranged minions are unchanged — single react window, no pending flag."""
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
        state = resolve_action(
            state,
            Action(action_type=ActionType.MOVE, minion_id=0, position=(1, 0)),
            lib,
        )
        # Ranged move: REACT window opens, pending NOT set.
        assert state.phase == TurnPhase.REACT
        assert state.pending_post_move_attacker_id is None

        # One PASS closes the window and advances the turn (no chain).
        state = resolve_action(state, Action(action_type=ActionType.PASS), lib)
        assert state.active_player_idx == 1
        assert state.phase == TurnPhase.ACTION

    def test_melee_move_no_in_range_targets_single_window(self):
        """Melee move with no in-range targets opens one window (no chain)."""
        from grid_tactics.action_resolver import resolve_action

        lib = _make_test_library()
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=5,
        )
        state = _make_state(minions=[attacker])
        state = resolve_action(
            state,
            Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0)),
            lib,
        )
        # No in-range enemies → no pending flag, standard single-window path.
        assert state.pending_post_move_attacker_id is None
        assert state.phase == TurnPhase.REACT

        state = resolve_action(state, Action(action_type=ActionType.PASS), lib)
        assert state.active_player_idx == 1
        assert state.phase == TurnPhase.ACTION

    def test_legal_actions_during_post_move_window_are_react_only(self):
        """During the post-move REACT window, opponent's only legal actions are
        PASS (+ any react cards whose conditions match). PLAY_CARD/MOVE/ATTACK
        by the opponent are NOT legal here.
        """
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.legal_actions import legal_actions

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
            state,
            Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0)),
            lib,
        )
        # In the post-move REACT window, opponent has no react cards in this
        # fixture, so the only legal action is PASS.
        assert state.phase == TurnPhase.REACT
        acts = legal_actions(state, lib)
        assert len(acts) == 1
        assert acts[0].action_type == ActionType.PASS

    def test_legal_actions_between_windows_are_attack_or_decline(self):
        """After the post-move window closes (pending still set), only ATTACK
        to in-range targets + DECLINE_POST_MOVE_ATTACK are legal.
        """
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.legal_actions import legal_actions

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
            state,
            Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 0)),
            lib,
        )
        state = resolve_action(state, Action(action_type=ActionType.PASS), lib)
        # Between windows: phase=ACTION + pending set.
        assert state.phase == TurnPhase.ACTION
        assert state.pending_post_move_attacker_id == 0
        acts = legal_actions(state, lib)
        action_types = {a.action_type for a in acts}
        # Only ATTACK (to the in-range defender) + DECLINE. No PLAY_CARD,
        # no MOVE, no SACRIFICE, no regular PASS.
        assert ActionType.ATTACK in action_types
        assert ActionType.DECLINE_POST_MOVE_ATTACK in action_types
        assert ActionType.PLAY_CARD not in action_types
        assert ActionType.MOVE not in action_types
        assert ActionType.SACRIFICE not in action_types
        # ATTACK targets must all be the pending attacker hitting an in-range enemy.
        for a in acts:
            if a.action_type == ActionType.ATTACK:
                assert a.minion_id == 0
                assert a.target_id == 1


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
                max_mana=5, hand=(), deck=(), grave=())
    p2 = Player(side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=5,
                max_mana=5, hand=(), deck=(), grave=())
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


# ---------------------------------------------------------------------------
# Phase 14.5: grave / exhaust / token exclusion
# ---------------------------------------------------------------------------


class TestPilesPhase145:
    """Phase 14.5 pile semantics: grave tracks from_deck cards that died
    or were played as one-shots; exhaust tracks discard-for-cost; tokens
    (from_deck=False) vanish on death."""

    def _ratchanter_library(self) -> CardLibrary:
        """Build a library containing a cheap minion with a
        discard_cost_tribe cost so the discard-for-cost path is
        exercisable without relying on JSON card data."""
        cards = {
            "test_melee": CardDefinition(
                card_id="test_melee", name="Test Melee", card_type=CardType.MINION,
                mana_cost=2, attack=2, health=5, attack_range=0,
            ),
            "test_rat": CardDefinition(
                card_id="test_rat", name="Test Rat", card_type=CardType.MINION,
                mana_cost=1, attack=1, health=1, attack_range=0, tribe="Rat",
            ),
            "test_rat_costs_rat": CardDefinition(
                card_id="test_rat_costs_rat", name="Pricey Rat", card_type=CardType.MINION,
                mana_cost=2, attack=3, health=3, attack_range=0,
                discard_cost_tribe="Rat",
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
        }
        return CardLibrary(cards)

    def test_minion_death_adds_to_grave(self):
        """A deck-origin minion killed by damage has its card_numeric_id
        appended to its owner's grave."""
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = self._ratchanter_library()
        melee_nid = lib.get_numeric_id("test_melee")
        dead = MinionInstance(
            instance_id=0, card_numeric_id=melee_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0),
            current_health=0,  # already dead
            from_deck=True,
        )
        state = _make_state(minions=[dead])
        new_state = _cleanup_dead_minions(state, lib)
        assert melee_nid in new_state.players[0].grave
        # Board cleared, minion removed
        assert new_state.board.get(1, 0) is None
        assert new_state.get_minion(0) is None

    def test_token_death_does_not_add_to_grave(self):
        """A from_deck=False token (e.g. summon_token spawn) vanishes on
        death — nothing is appended to the owner's grave."""
        from grid_tactics.action_resolver import _cleanup_dead_minions

        lib = self._ratchanter_library()
        rat_nid = lib.get_numeric_id("test_rat")
        token = MinionInstance(
            instance_id=0, card_numeric_id=rat_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0),
            current_health=0,  # dead
            from_deck=False,
        )
        state = _make_state(minions=[token])
        new_state = _cleanup_dead_minions(state, lib)
        assert new_state.players[0].grave == ()
        assert new_state.players[1].grave == ()
        # Board cleanup still happens
        assert new_state.board.get(1, 0) is None
        assert new_state.get_minion(0) is None

    def test_magic_play_goes_to_grave(self):
        """Casting a magic card routes its card_numeric_id to the caster's
        grave immediately (one-shot play)."""
        from grid_tactics.action_resolver import resolve_action

        lib = self._ratchanter_library()
        magic_nid = lib.get_numeric_id("test_magic_damage")
        # Put an enemy minion on the board as a target for SINGLE_TARGET.
        enemy = MinionInstance(
            instance_id=0, card_numeric_id=lib.get_numeric_id("test_melee"),
            owner=PlayerSide.PLAYER_2, position=(3, 0), current_health=5,
        )
        state = _make_state(p1_hand=(magic_nid,), p1_mana=5, minions=[enemy])
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, target_pos=(3, 0),
        )
        new_state = resolve_action(state, action, lib)
        assert magic_nid in new_state.players[0].grave
        assert len(new_state.players[0].hand) == 0

    def test_discard_for_cost_goes_to_exhaust(self):
        """discard_cost_tribe removes a hand card as a COST; it goes to
        the exhaust pile, NOT the grave."""
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import pass_action

        lib = self._ratchanter_library()
        pricey_nid = lib.get_numeric_id("test_rat_costs_rat")
        rat_nid = lib.get_numeric_id("test_rat")
        # P1 has the pricey rat + a plain Rat to discard as cost.
        state = _make_state(
            p1_hand=(pricey_nid, rat_nid), p1_mana=5,
        )
        action = Action(
            action_type=ActionType.PLAY_CARD, card_index=0, position=(1, 0),
            discard_card_index=1,
        )
        new_state = resolve_action(state, action, lib)
        # Phase 14.7-04: drain Window A (summon declaration) so the
        # minion lands — the discard cost was already consumed when
        # _apply_play_card ran (costs are PAID pre-declaration).
        new_state = resolve_action(new_state, pass_action(), lib)
        p1 = new_state.players[0]
        # Pricey rat deployed (minion NOT in grave), sacrificed rat in exhaust
        assert rat_nid in p1.exhaust, (
            f"expected {rat_nid} in exhaust, got {p1.exhaust}"
        )
        assert rat_nid not in p1.grave, (
            f"sacrificed card must not be in grave, got {p1.grave}"
        )
        assert pricey_nid not in p1.grave, (
            "deployed minion must not enter grave on play"
        )
        # Pricey rat is on the board
        assert len(new_state.minions) == 1
        assert new_state.minions[0].card_numeric_id == pricey_nid
        assert new_state.minions[0].from_deck is True

    def test_conjured_minion_has_from_deck_false(self):
        """The activated summon_token path constructs a MinionInstance with
        from_deck=False. Covered structurally by constructing one directly
        and asserting the field — there is no current card that exercises
        the summon_token branch, so this test pins the kwarg contract."""
        lib = self._ratchanter_library()
        rat_nid = lib.get_numeric_id("test_rat")
        token = MinionInstance(
            instance_id=0, card_numeric_id=rat_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 0),
            current_health=1,
            from_deck=False,
        )
        assert token.from_deck is False
        # And default is True (regression guard)
        normal = MinionInstance(
            instance_id=1, card_numeric_id=rat_nid,
            owner=PlayerSide.PLAYER_1, position=(1, 1),
            current_health=1,
        )
        assert normal.from_deck is True
