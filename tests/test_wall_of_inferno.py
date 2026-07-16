"""Wall of Inferno row targeting and deferred spell-stage resolution."""

from pathlib import Path

import pytest

from grid_tactics.action_resolver import resolve_action
from grid_tactics.actions import pass_action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.effect_resolver import resolve_effect
from grid_tactics.enums import ActionType, PlayerSide, TargetType, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.rl.action_space import ActionEncoder
from grid_tactics.types import STARTING_HP


@pytest.fixture
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _state(library, *, hand=(), minions=()):
    board = Board.empty()
    for minion in minions:
        board = board.place(
            minion.position[0], minion.position[1], minion.instance_id,
        )
    p1 = Player(
        side=PlayerSide.PLAYER_1,
        hp=STARTING_HP,
        current_mana=10,
        max_mana=10,
        hand=tuple(hand),
        deck=(),
        grave=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2,
        hp=STARTING_HP,
        current_mana=10,
        max_mana=10,
        hand=(),
        deck=(),
        grave=(),
    )
    return GameState(
        board=board,
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=42,
        minions=tuple(minions),
        next_minion_id=max((m.instance_id for m in minions), default=-1) + 1,
    )


def test_wall_card_definition(library):
    wall = library.get_by_card_id("wall_of_inferno")
    assert wall.mana_cost == 2
    assert wall.element.name == "FIRE"
    assert len(wall.effects) == 1
    assert wall.effects[0].target == TargetType.ROW
    assert wall.effects[0].target_side == "enemy"


def test_wall_can_be_aimed_at_every_board_cell(library):
    wall_id = library.get_numeric_id("wall_of_inferno")
    state = _state(library, hand=(wall_id,))
    casts = [
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD
        and action.card_index == 0
    ]
    assert {action.target_pos for action in casts} == {
        (row, col) for row in range(5) for col in range(5)
    }


def test_row_target_survives_rl_action_encoding(library):
    wall_id = library.get_numeric_id("wall_of_inferno")
    state = _state(library, hand=(wall_id,))
    encoder = ActionEncoder()
    cast = next(
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD
        and action.target_pos == (4, 3)
    )
    encoded = encoder.encode(cast, state)
    decoded = encoder.decode(encoded, state, library)
    assert decoded.target_pos == (4, 3)


def test_wall_burns_only_enemy_minions_in_chosen_row(library):
    rat_id = library.get_numeric_id("rat")
    minions = (
        MinionInstance(0, rat_id, PlayerSide.PLAYER_2, (2, 0), 10),
        MinionInstance(1, rat_id, PlayerSide.PLAYER_2, (2, 4), 10),
        MinionInstance(2, rat_id, PlayerSide.PLAYER_2, (3, 2), 10),
        MinionInstance(3, rat_id, PlayerSide.PLAYER_1, (2, 2), 10),
    )
    state = _state(library, minions=minions)
    wall = library.get_by_card_id("wall_of_inferno")
    result = resolve_effect(
        state,
        wall.effects[0],
        caster_pos=(0, 0),
        caster_owner=PlayerSide.PLAYER_1,
        library=library,
        target_pos=(2, 3),
    )
    assert result.get_minion(0).is_burning is True
    assert result.get_minion(1).is_burning is True
    assert result.get_minion(2).is_burning is False
    assert result.get_minion(3).is_burning is False


def test_wall_target_is_captured_before_react_and_resolves_after_pass(library):
    wall_id = library.get_numeric_id("wall_of_inferno")
    rat_id = library.get_numeric_id("rat")
    enemy = MinionInstance(0, rat_id, PlayerSide.PLAYER_2, (3, 1), 10)
    state = _state(library, hand=(wall_id,), minions=(enemy,))
    cast = next(
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD
        and action.target_pos == (3, 4)
    )

    staged = resolve_action(state, cast, library)
    assert staged.phase == TurnPhase.REACT
    assert staged.react_stack[0].target_pos == (3, 4)
    assert staged.get_minion(0).is_burning is False

    resolved = resolve_action(staged, pass_action(), library)
    assert resolved.get_minion(0).is_burning is True


def test_tensor_engine_marks_all_row_selectors_and_burns_enemy_row(library):
    torch = pytest.importorskip("torch")
    from grid_tactics.tensor_engine.card_table import CardTable
    from grid_tactics.tensor_engine.constants import PLAY_CARD_BASE
    from grid_tactics.tensor_engine.effects import apply_effects_batch
    from grid_tactics.tensor_engine.legal_actions import compute_legal_mask_batch
    from grid_tactics.tensor_engine.state import create_initial_state

    device = torch.device("cpu")
    table = CardTable.from_library(library, device)
    state = create_initial_state(1, device)
    wall_id = library.get_numeric_id("wall_of_inferno")

    state.active_player[0] = 0
    state.phase[0] = 0
    state.player_mana[0, 0] = 10
    state.hands[0, 0, 0] = wall_id
    state.hand_sizes[0, 0] = 1
    mask = compute_legal_mask_batch(state, table)
    assert mask[0, PLAY_CARD_BASE:PLAY_CARD_BASE + 25].all()

    # Enemy and friendly occupy the selected row; only the enemy burns.
    for slot, owner, col in ((0, 1, 0), (1, 0, 4)):
        state.minion_alive[0, slot] = True
        state.minion_owner[0, slot] = owner
        state.minion_row[0, slot] = 2
        state.minion_col[0, slot] = col
        state.board[0, 2, col] = slot
    apply_effects_batch(
        state,
        card_ids=torch.tensor([wall_id], dtype=torch.int32),
        trigger=0,
        caster_owners=torch.tensor([0], dtype=torch.int32),
        caster_slots=torch.tensor([-1], dtype=torch.int32),
        target_flat_pos=torch.tensor([2 * 5 + 3], dtype=torch.int32),
        card_table=table,
        mask=torch.tensor([True]),
    )
    assert state.is_burning[0, 0]
    assert not state.is_burning[0, 1]
