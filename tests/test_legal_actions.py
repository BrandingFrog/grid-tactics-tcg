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

    def test_deck_nonempty_draw_present(self, library):
        """If deck is non-empty, DRAW is legal."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        state = _make_state(p1_deck=(fire_imp_id,))
        actions = legal_actions(state, library)
        draw_actions = [a for a in actions if a.action_type == ActionType.DRAW]
        assert len(draw_actions) == 1

    def test_deck_empty_no_draw(self, library):
        """If deck is empty, DRAW is not legal."""
        state = _make_state()
        actions = legal_actions(state, library)
        draw_actions = [a for a in actions if a.action_type == ActionType.DRAW]
        assert len(draw_actions) == 0


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
    def test_minion_can_move_to_adjacent_empty(self, library):
        """Minion can move to all orthogonally adjacent empty cells."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=2,
        )
        state = _make_state(minions=(minion,))
        actions = legal_actions(state, library)

        move_actions = [a for a in actions if a.action_type == ActionType.MOVE]
        # Center of board has 4 adjacent cells
        assert len(move_actions) == 4
        positions = {a.position for a in move_actions}
        assert positions == {(1, 2), (3, 2), (2, 1), (2, 3)}

    def test_minion_cannot_move_to_occupied(self, library):
        """Minion cannot move to an occupied adjacent cell."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        m1 = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=2,
        )
        m2 = MinionInstance(
            instance_id=1, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(1, 3), current_health=2,
        )
        state = _make_state(minions=(m1, m2))
        actions = legal_actions(state, library)

        move_m1 = [a for a in actions if a.action_type == ActionType.MOVE and a.minion_id == 0]
        # (1,2) has 4 adjacent: (0,2), (2,2), (1,1), (1,3). (1,3) is occupied -> 3 moves
        assert len(move_m1) == 3
        positions = {a.position for a in move_m1}
        assert (1, 3) not in positions

    def test_corner_minion_fewer_moves(self, library):
        """Minion in corner has only 2 adjacent positions."""
        fire_imp_id = library.get_numeric_id("fire_imp")
        minion = MinionInstance(
            instance_id=0, card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1, position=(0, 0), current_health=2,
        )
        state = _make_state(minions=(minion,))
        actions = legal_actions(state, library)

        move_actions = [a for a in actions if a.action_type == ActionType.MOVE]
        assert len(move_actions) == 2


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
