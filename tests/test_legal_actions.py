"""Tests for legal_actions.py -- complete legal action enumeration.

Covers:
  - Empty board, empty hand, empty deck: only PASS returned
  - Player with cards in hand but no mana: only non-card actions returned
  - Minion card in hand with enough mana: deploy positions enumerated correctly
  - Ranged minion: only back row deploy positions
  - Melee minion: all friendly row positions
  - Magic card with single_target: enemy minion positions enumerated
  - Magic card with all_enemies: single play action (no target needed)
  - Minion on board can move to adjacent empty cells
  - Minion on board cannot move to occupied cells
  - Melee minion adjacent to enemy: attack action present
  - Ranged minion at distance 2 orthogonal: attack action present
  - Ranged minion at distance 3: attack action NOT present
  - Melee minion at distance 2: attack action NOT present
  - Deck non-empty: DRAW present; deck empty: DRAW absent
  - PASS always present
  - React phase: only react cards + multi-purpose react + pass
  - React phase: non-react cards excluded
  - Stack depth at max: only PASS in react phase
  - Soundness: all returned actions resolve without ValueError
"""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.actions import (
    Action,
    ActionType,
    attack_action,
    draw_action,
    move_action,
    pass_action,
    play_card_action,
    play_react_action,
)
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import CardType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.react_stack import ReactEntry
from grid_tactics.types import (
    BACK_ROW_P1,
    BACK_ROW_P2,
    MAX_REACT_STACK_DEPTH,
    STARTING_HP,
)


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
    react_player_idx=None,
    react_stack=(),
    pending_action=None,
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
        phase=phase, turn_number=1, seed=42,
        minions=tuple(minions), next_minion_id=next_id,
        react_player_idx=react_player_idx,
        react_stack=react_stack,
        pending_action=pending_action,
    )


# ---------------------------------------------------------------------------
# Basic cases
# ---------------------------------------------------------------------------


class TestBasicLegalActions:
    def test_empty_everything_only_pass(self, library):
        """Empty board, hand, deck -> only PASS is legal."""
        state = _make_state()
        actions = legal_actions(state, library)
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.PASS

    def test_pass_always_present(self, library):
        """PASS is always in the list regardless of state."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        state = _make_state(p1_hand=(fire_imp_id,), p1_deck=(fire_imp_id,))
        actions = legal_actions(state, library)
        pass_actions = [a for a in actions if a.action_type == ActionType.PASS]
        assert len(pass_actions) == 1

    def test_draw_not_action(self, library):
        """DRAW is no longer a player action (auto-draw at turn start)."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        state = _make_state(p1_deck=(fire_imp_id,))
        actions = legal_actions(state, library)
        draw_actions = [a for a in actions if a.action_type == ActionType.DRAW]
        assert len(draw_actions) == 0

    def test_pass_always_available(self, library):
        """PASS is always available in ACTION phase."""
        state = _make_state()
        actions = legal_actions(state, library)
        pass_actions = [a for a in actions if a.action_type == ActionType.PASS]
        assert len(pass_actions) == 1


# ---------------------------------------------------------------------------
# PLAY_CARD: minion deployment
# ---------------------------------------------------------------------------


class TestMinionDeployment:
    def test_melee_minion_all_friendly_rows(self, library):
        """Melee minion (range=0) can deploy to any empty cell in P1 rows (0, 1)."""
        fire_imp_id = library.get_numeric_id("fire_imp")  # range=0, cost=1
        state = _make_state(p1_hand=(fire_imp_id,), p1_mana=5)
        actions = legal_actions(state, library)

        play_actions = [a for a in actions if a.action_type == ActionType.PLAY_CARD]
        # P1 friendly rows: 0 and 1, 5 cols each = 10 positions
        assert len(play_actions) == 10
        for a in play_actions:
            assert a.position[0] in (0, 1)

    def test_ranged_minion_back_row_only(self, library):
        """Ranged minion (range>=1) can only deploy to back row."""
        wind_archer_id = library.get_numeric_id("wind_archer")  # range=2, cost=2
        state = _make_state(p1_hand=(wind_archer_id,), p1_mana=5)
        actions = legal_actions(state, library)

        play_actions = [a for a in actions if a.action_type == ActionType.PLAY_CARD]
        # P1 back row: row 0, 5 cols = 5 positions
        assert len(play_actions) == 5
        for a in play_actions:
            assert a.position[0] == BACK_ROW_P1

    def test_p2_melee_deploys_to_p2_rows(self, library):
        """P2's melee minion deploys to rows 3, 4."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        state = _make_state(p2_hand=(fire_imp_id,), active_player_idx=1)
        actions = legal_actions(state, library)

        play_actions = [a for a in actions if a.action_type == ActionType.PLAY_CARD]
        assert len(play_actions) == 10
        for a in play_actions:
            assert a.position[0] in (3, 4)

    def test_p2_ranged_deploys_to_back_row(self, library):
        """P2's ranged minion deploys to row 4 only."""
        wind_archer_id = library.get_numeric_id("wind_archer")
        state = _make_state(p2_hand=(wind_archer_id,), active_player_idx=1)
        actions = legal_actions(state, library)

        play_actions = [a for a in actions if a.action_type == ActionType.PLAY_CARD]
        assert len(play_actions) == 5
        for a in play_actions:
            assert a.position[0] == BACK_ROW_P2

    def test_insufficient_mana_no_play(self, library):
        """Cards with cost > current mana are not legal to play."""
        flame_wyrm_id = library.get_numeric_id("flame_wyrm")  # cost=5
        state = _make_state(p1_hand=(flame_wyrm_id,), p1_mana=4)
        actions = legal_actions(state, library)

        play_actions = [a for a in actions if a.action_type == ActionType.PLAY_CARD]
        assert len(play_actions) == 0

    def test_occupied_cells_excluded(self, library):
        """Occupied cells are not valid deploy targets."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        # Place a minion at (0, 0)
        minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(0, 0), current_health=2,
        )
        state = _make_state(p1_hand=(fire_imp_id,), minions=(minion,))
        actions = legal_actions(state, library)

        play_actions = [a for a in actions if a.action_type == ActionType.PLAY_CARD]
        # 10 friendly positions minus 1 occupied = 9
        assert len(play_actions) == 9
        positions = [a.position for a in play_actions]
        assert (0, 0) not in positions


# ---------------------------------------------------------------------------
# PLAY_CARD: magic cards
# ---------------------------------------------------------------------------


class TestMagicCardPlay:
    def test_single_target_magic_enumerates_enemy_targets(self, library):
        """Magic with single_target enumerates each enemy minion as target."""
        fireball_id = library.get_numeric_id("fireball")  # single_target damage, cost=2
        enemy_minion = MinionInstance(
            instance_id=0, card_numeric_id=library.get_numeric_id("fire_imp"),
            owner=PlayerSide.PLAYER_2, position=(3, 0), current_health=2,
        )
        state = _make_state(p1_hand=(fireball_id,), minions=(enemy_minion,))
        actions = legal_actions(state, library)

        play_actions = [a for a in actions if a.action_type == ActionType.PLAY_CARD]
        assert len(play_actions) == 1
        assert play_actions[0].target_pos == (3, 0)

    def test_all_enemies_magic_single_action(self, library):
        """Magic with all_enemies effect produces one action (no target needed)."""
        inferno_id = library.get_numeric_id("inferno")  # all_enemies damage, cost=4
        enemy_minion = MinionInstance(
            instance_id=0, card_numeric_id=library.get_numeric_id("fire_imp"),
            owner=PlayerSide.PLAYER_2, position=(3, 0), current_health=2,
        )
        state = _make_state(p1_hand=(inferno_id,), minions=(enemy_minion,))
        actions = legal_actions(state, library)

        play_actions = [a for a in actions if a.action_type == ActionType.PLAY_CARD]
        assert len(play_actions) == 1
        assert play_actions[0].target_pos is None

    def test_react_cards_excluded_in_action_phase(self, library):
        """React cards cannot be played during ACTION phase."""
        shield_block_id = library.get_numeric_id("shield_block")
        state = _make_state(p1_hand=(shield_block_id,))
        actions = legal_actions(state, library)

        play_actions = [a for a in actions if a.action_type == ActionType.PLAY_CARD]
        assert len(play_actions) == 0


# ---------------------------------------------------------------------------
# MOVE enumeration
# ---------------------------------------------------------------------------


class TestMoveEnumeration:
    def test_minion_can_move_forward_in_lane(self, library):
        """Minion can move forward one cell in its lane (same column)."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=2,
        )
        state = _make_state(minions=(minion,))
        actions = legal_actions(state, library)

        move_actions = [a for a in actions if a.action_type == ActionType.MOVE]
        # Forward only in lane: P1 at (2,2) can only move to (3,2)
        assert len(move_actions) == 1
        positions = {a.position for a in move_actions}
        assert positions == {(3, 2)}

    def test_minion_cannot_move_to_occupied(self, library):
        """Minion cannot move forward if the cell is occupied."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        m1 = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=2,
        )
        m2 = MinionInstance(
            instance_id=1, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=2,
        )
        state = _make_state(minions=(m1, m2))
        actions = legal_actions(state, library)

        move_m1 = [a for a in actions if a.action_type == ActionType.MOVE and a.minion_id == 0]
        # Forward cell (2,2) is occupied -> 0 moves for m1
        assert len(move_m1) == 0

    def test_corner_minion_one_forward_move(self, library):
        """Minion in corner can only move forward in its lane."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(0, 0), current_health=2,
        )
        state = _make_state(minions=(minion,))
        actions = legal_actions(state, library)

        move_actions = [a for a in actions if a.action_type == ActionType.MOVE]
        # P1 at (0,0) moves forward to (1,0)
        assert len(move_actions) == 1
        assert move_actions[0].position == (1, 0)

    def test_back_row_minion_no_moves(self, library):
        """P1 minion on P2's back row (row 4) cannot move further forward."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=2,
        )
        state = _make_state(minions=(minion,))
        actions = legal_actions(state, library)

        move_actions = [a for a in actions if a.action_type == ActionType.MOVE]
        # Row 4 is the last row, forward would be row 5 (out of bounds)
        assert len(move_actions) == 0


# ---------------------------------------------------------------------------
# ATTACK enumeration
# ---------------------------------------------------------------------------


class TestAttackEnumeration:
    def test_melee_adjacent_enemy_attack_present(self, library):
        """Melee minion adjacent to enemy has attack action."""
        fire_imp_id = library.get_numeric_id("fire_imp")  # range=0
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=2,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_2, position=(2, 2), current_health=2,
        )
        state = _make_state(minions=(attacker, defender))
        actions = legal_actions(state, library)

        attack_actions = [a for a in actions if a.action_type == ActionType.ATTACK]
        assert len(attack_actions) == 1
        assert attack_actions[0].minion_id == 0
        assert attack_actions[0].target_id == 1

    def test_melee_at_distance_2_no_attack(self, library):
        """Melee minion at manhattan distance 2 cannot attack."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(0, 2), current_health=2,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_2, position=(2, 2), current_health=2,
        )
        state = _make_state(minions=(attacker, defender))
        actions = legal_actions(state, library)

        attack_actions = [a for a in actions if a.action_type == ActionType.ATTACK]
        assert len(attack_actions) == 0

    def test_ranged_at_distance_2_attack_present(self, library):
        """Ranged minion at orthogonal distance 2 has attack action."""
        wind_archer_id = library.get_numeric_id("wind_archer")  # range=2
        fire_imp_id = library.get_numeric_id("fire_imp")
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=wind_archer_id,
            owner=PlayerSide.PLAYER_1, position=(0, 2), current_health=3,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_2, position=(2, 2), current_health=2,
        )
        state = _make_state(minions=(attacker, defender))
        actions = legal_actions(state, library)

        attack_actions = [a for a in actions if a.action_type == ActionType.ATTACK]
        assert len(attack_actions) == 1

    def test_ranged_at_distance_3_no_attack(self, library):
        """Ranged minion (range=2) at distance 3 cannot attack."""
        wind_archer_id = library.get_numeric_id("wind_archer")  # range=2
        fire_imp_id = library.get_numeric_id("fire_imp")
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=wind_archer_id,
            owner=PlayerSide.PLAYER_1, position=(0, 2), current_health=3,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_2, position=(3, 2), current_health=2,
        )
        state = _make_state(minions=(attacker, defender))
        actions = legal_actions(state, library)

        attack_actions = [a for a in actions if a.action_type == ActionType.ATTACK]
        assert len(attack_actions) == 0

    def test_cannot_attack_own_minion(self, library):
        """No attack actions targeting own minions."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        m1 = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=2,
        )
        m2 = MinionInstance(
            instance_id=1, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=2,
        )
        state = _make_state(minions=(m1, m2))
        actions = legal_actions(state, library)

        attack_actions = [a for a in actions if a.action_type == ActionType.ATTACK]
        assert len(attack_actions) == 0


# ---------------------------------------------------------------------------
# REACT phase
# ---------------------------------------------------------------------------


class TestReactPhase:
    def test_react_phase_only_react_and_pass(self, library):
        """During REACT phase, only react cards whose condition matches + PASS are legal."""
        shield_block_id = library.get_numeric_id("shield_block")  # condition: opponent_attacks
        fire_imp_id = library.get_numeric_id("fire_imp")
        dark_sentinel_id = library.get_numeric_id("dark_sentinel")  # condition: opponent_plays_magic

        # P2 has shield_block (react), dark_sentinel (multi-purpose), fire_imp (not react)
        enemy_minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=2,
        )
        # pending_action is an ATTACK so shield_block's condition (opponent_attacks) is met
        state = _make_state(
            p2_hand=(shield_block_id, dark_sentinel_id, fire_imp_id),
            minions=(enemy_minion,),
            phase=TurnPhase.REACT,
            react_player_idx=1,
            pending_action=attack_action(minion_id=0, target_id=0),
        )
        actions = legal_actions(state, library)

        action_types = {a.action_type for a in actions}
        assert ActionType.PASS in action_types
        assert ActionType.PLAY_REACT in action_types
        assert ActionType.PLAY_CARD not in action_types
        assert ActionType.MOVE not in action_types
        assert ActionType.ATTACK not in action_types
        assert ActionType.DRAW not in action_types

    def test_react_phase_non_react_excluded(self, library):
        """Non-react, non-multi-purpose cards are excluded during react."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        state = _make_state(
            p2_hand=(fire_imp_id,),
            phase=TurnPhase.REACT,
            react_player_idx=1,
        )
        actions = legal_actions(state, library)

        # Only PASS
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.PASS

    def test_react_phase_stack_at_max_only_pass(self, library):
        """When stack is at MAX_REACT_STACK_DEPTH, only PASS is legal."""
        shield_block_id = library.get_numeric_id("shield_block")
        entries = tuple(
            ReactEntry(player_idx=i % 2, card_index=0, card_numeric_id=shield_block_id)
            for i in range(MAX_REACT_STACK_DEPTH)
        )
        state = _make_state(
            p2_hand=(shield_block_id,),
            phase=TurnPhase.REACT,
            react_player_idx=1,
            react_stack=entries,
        )
        actions = legal_actions(state, library)
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.PASS

    def test_react_phase_insufficient_mana_excluded(self, library):
        """React cards needing more mana than available are excluded."""
        counter_spell_id = library.get_numeric_id("counter_spell")  # cost=2
        state = _make_state(
            p2_hand=(counter_spell_id,), p2_mana=1,
            phase=TurnPhase.REACT,
            react_player_idx=1,
        )
        actions = legal_actions(state, library)
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.PASS


# ---------------------------------------------------------------------------
# Soundness: all returned actions can be resolved without error
# ---------------------------------------------------------------------------


class TestSoundness:
    def test_all_actions_resolve_without_error(self, library):
        """Every action from legal_actions resolves without ValueError."""
        from grid_tactics.action_resolver import resolve_action

        fire_imp_id = library.get_numeric_id("fire_imp")
        wind_archer_id = library.get_numeric_id("wind_archer")
        fireball_id = library.get_numeric_id("fireball")

        # Set up a state with minions, cards in hand, and cards in deck
        attacker = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=2,
        )
        defender = MinionInstance(
            instance_id=1, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_2, position=(2, 2), current_health=2,
        )
        state = _make_state(
            p1_hand=(fire_imp_id, wind_archer_id, fireball_id),
            p1_deck=(fire_imp_id,),
            minions=(attacker, defender),
            p1_mana=5,
        )

        actions = legal_actions(state, library)
        assert len(actions) > 5  # Should have many legal actions

        for action in actions:
            # Each legal action should resolve without error
            try:
                resolve_action(state, action, library)
            except ValueError as e:
                pytest.fail(
                    f"legal_actions returned an action that raises ValueError: "
                    f"{action} -> {e}"
                )

    def test_soundness_no_enemies_on_board(self, library):
        """legal_actions with single-target minions but no enemies doesn't emit illegal actions."""
        from grid_tactics.action_resolver import resolve_action

        fire_imp_id = library.get_numeric_id("fire_imp")

        # State with fire_imp in hand but NO enemy minions on the board
        state = _make_state(
            p1_hand=(fire_imp_id,),
            p1_deck=(fire_imp_id,),
            minions=(),
            p1_mana=5,
        )

        actions = legal_actions(state, library)

        for action in actions:
            try:
                resolve_action(state, action, library)
            except ValueError as e:
                pytest.fail(
                    f"legal_actions returned an action that raises ValueError: "
                    f"{action} -> {e}"
                )

    def test_react_phase_soundness(self, library):
        """Every action from legal_actions during REACT resolves without error."""
        from grid_tactics.action_resolver import resolve_action

        shield_block_id = library.get_numeric_id("shield_block")
        dark_sentinel_id = library.get_numeric_id("dark_sentinel")
        fire_imp_id = library.get_numeric_id("fire_imp")

        enemy_minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=2,
        )
        state = _make_state(
            p2_hand=(shield_block_id, dark_sentinel_id),
            minions=(enemy_minion,),
            phase=TurnPhase.REACT,
            react_player_idx=1,
        )

        actions = legal_actions(state, library)
        for action in actions:
            try:
                resolve_action(state, action, library)
            except ValueError as e:
                pytest.fail(
                    f"legal_actions (react) returned action that raises ValueError: "
                    f"{action} -> {e}"
                )


# ---------------------------------------------------------------------------
# Phase 14.1: Pending post-move attack mask
# ---------------------------------------------------------------------------


class TestPendingPostMoveAttackMask:
    """Mask must restrict to ATTACK-from-pending + DECLINE in pending state."""

    def _melee_state_with_pending(self, library, enemy_positions):
        """Build a state where a P1 melee minion at (1,2) has pending set,
        with enemy minions at the given positions."""
        fire_imp_id = library.get_numeric_id("fire_imp")  # melee, range=0
        attacker = MinionInstance(
            instance_id=10, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=2,
        )
        enemies = tuple(
            MinionInstance(
                instance_id=20 + i, card_numeric_id=fire_imp_id,
                owner=PlayerSide.PLAYER_2, position=pos, current_health=2,
            )
            for i, pos in enumerate(enemy_positions)
        )
        state = _make_state(
            p1_hand=(fire_imp_id,),  # would normally be playable
            p1_mana=5, p2_mana=5,
            minions=(attacker, *enemies),
        )
        return replace(state, pending_post_move_attacker_id=10)

    def test_pending_state_only_attack_and_decline(self, library):
        """In pending state: only ATTACK from the pending attacker on
        in-range enemies + DECLINE_POST_MOVE_ATTACK are legal."""
        # Two enemies adjacent to attacker at (1,2): (0,2) and (2,2)
        # One enemy not adjacent: (4,4)
        state = self._melee_state_with_pending(
            library, enemy_positions=[(0, 2), (2, 2), (4, 4)]
        )
        actions = legal_actions(state, library)

        # Every action is either ATTACK (from minion 10) or DECLINE
        for a in actions:
            assert a.action_type in (
                ActionType.ATTACK, ActionType.DECLINE_POST_MOVE_ATTACK,
            ), f"Unexpected action type in pending state: {a}"
            if a.action_type == ActionType.ATTACK:
                assert a.minion_id == 10, "Only pending attacker may attack"

        # Exactly one DECLINE
        decline = [a for a in actions if a.action_type == ActionType.DECLINE_POST_MOVE_ATTACK]
        assert len(decline) == 1

        # Two valid attack targets (the two adjacent enemies); the (4,4)
        # enemy is out of range and must NOT be a target.
        attacks = [a for a in actions if a.action_type == ActionType.ATTACK]
        target_ids = {a.target_id for a in attacks}
        assert target_ids == {20, 21}, f"Expected adjacent enemies only, got {target_ids}"

        # No PLAY_CARD / MOVE / SACRIFICE / DRAW / regular PASS / REACT
        forbidden = {
            ActionType.PLAY_CARD, ActionType.MOVE, ActionType.SACRIFICE,
            ActionType.DRAW, ActionType.PASS, ActionType.PLAY_REACT,
        }
        for a in actions:
            assert a.action_type not in forbidden, (
                f"Forbidden action type {a.action_type} in pending state"
            )

    def test_pending_state_no_targets_only_decline(self, library):
        """Defensive: pending with no in-range enemies -> only DECLINE.

        Wave 1 prevents this from happening at runtime, but the mask must
        not crash and must keep the player able to escape.
        """
        # Only enemy is far away, not adjacent to (1,2)
        state = self._melee_state_with_pending(
            library, enemy_positions=[(4, 4)]
        )
        actions = legal_actions(state, library)
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.DECLINE_POST_MOVE_ATTACK

    def test_normal_state_mask_unchanged_when_pending_none(self, library):
        """Non-pending state must enumerate the same actions as before."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        state = _make_state(p1_hand=(fire_imp_id,), p1_mana=5)
        # Sanity: pending is None by default
        assert state.pending_post_move_attacker_id is None
        actions = legal_actions(state, library)
        # Should match the existing TestMinionDeployment expectation:
        # 10 deploy positions for melee minion in P1 rows.
        play = [a for a in actions if a.action_type == ActionType.PLAY_CARD]
        assert len(play) == 10
        # No DECLINE in non-pending state
        decline = [a for a in actions if a.action_type == ActionType.DECLINE_POST_MOVE_ATTACK]
        assert len(decline) == 0

    def test_slot_1001_decodes_to_pass_normally_and_decline_in_pending(self, library):
        """Action encoder slot 1001 dual meaning: PASS without pending,
        DECLINE_POST_MOVE_ATTACK with pending set."""
        pytest.importorskip("stable_baselines3")  # rl pkg __init__ imports SB3
        from grid_tactics.rl.action_space import ActionEncoder, PASS_IDX

        encoder = ActionEncoder()

        # Non-pending state -> slot 1001 decodes to PASS
        normal_state = _make_state()
        assert normal_state.pending_post_move_attacker_id is None
        decoded_normal = encoder.decode(PASS_IDX, normal_state, library)
        assert decoded_normal.action_type == ActionType.PASS

        # Pending state -> slot 1001 decodes to DECLINE_POST_MOVE_ATTACK
        pending_state = self._melee_state_with_pending(
            library, enemy_positions=[(0, 2)]
        )
        decoded_pending = encoder.decode(PASS_IDX, pending_state, library)
        assert decoded_pending.action_type == ActionType.DECLINE_POST_MOVE_ATTACK

        # Encoder maps DECLINE -> slot 1001
        from grid_tactics.actions import decline_post_move_attack_action
        encoded = encoder.encode(decline_post_move_attack_action(), pending_state)
        assert encoded == PASS_IDX

    def test_build_action_mask_pending_state(self, library):
        """build_action_mask reflects the pending-state restriction."""
        pytest.importorskip("stable_baselines3")  # rl pkg __init__ imports SB3
        from grid_tactics.rl.action_space import (
            ATTACK_BASE, ActionEncoder, PASS_IDX, build_action_mask,
        )

        encoder = ActionEncoder()
        state = self._melee_state_with_pending(
            library, enemy_positions=[(0, 2), (2, 2), (4, 4)]
        )
        mask = build_action_mask(state, library, encoder)

        # Slot 1001 (DECLINE) is True
        assert mask[PASS_IDX]

        # Exactly 2 ATTACK slots are True (the two adjacent enemies)
        attack_slice = mask[ATTACK_BASE:ATTACK_BASE + 625]
        assert int(attack_slice.sum()) == 2

        # Total True == 3 (2 attacks + 1 decline)
        assert int(mask.sum()) == 3
