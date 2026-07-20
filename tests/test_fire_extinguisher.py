"""Fire Extinguisher: zero-mana, burn-only friendly Cleanse magic."""

from pathlib import Path

import pytest

from grid_tactics.action_resolver import resolve_action
from grid_tactics.actions import pass_action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.card_loader import CardLoader
from grid_tactics.effect_resolver import resolve_effect
from grid_tactics.enums import (
    ActionType,
    EffectType,
    PlayerSide,
    TargetType,
    TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.types import STARTING_HP


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _state(library, *, hand=(), minions=()):
    board = Board.empty()
    for minion in minions:
        board = board.place(*minion.position, minion.instance_id)
    p1 = Player(
        side=PlayerSide.PLAYER_1,
        hp=STARTING_HP,
        current_mana=0,
        max_mana=10,
        hand=tuple(hand),
        deck=(),
        grave=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2,
        hp=STARTING_HP,
        current_mana=0,
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
        seed=58,
        minions=tuple(minions),
        next_minion_id=max((m.instance_id for m in minions), default=-1) + 1,
    )


def test_definition(library):
    card = library.get_by_card_id("fire_extinguisher")
    assert card.mana_cost == 0
    assert card.element.name == "WATER"
    assert len(card.effects) == 1
    effect = card.effects[0]
    assert effect.effect_type == EffectType.CLEANSE
    assert effect.burn_only is True
    assert "EXTINGUISH" not in EffectType.__members__
    assert effect.target == TargetType.SINGLE_TARGET
    assert effect.target_side == "friendly"


def test_burn_only_is_a_cleanse_modifier_not_a_new_keyword():
    with pytest.raises(ValueError, match="valid only for a CLEANSE effect"):
        CardLoader._parse_single_effect(
            {
                "type": "damage",
                "trigger": "on_play",
                "target": "single_target",
                "amount": 1,
                "burn_only": True,
            },
            "bad_burn_only",
            "effects[0]",
        )


def test_client_receives_modifier_and_keeps_cleanse_wording(library):
    from grid_tactics.server.events import _build_card_defs

    numeric_id = library.get_numeric_id("fire_extinguisher")
    effect = _build_card_defs(library)[numeric_id]["effects"][0]
    assert effect["type"] == EffectType.CLEANSE.value
    assert effect["burn_only"] is True

    js_root = Path("src/grid_tactics/server/static/js")
    renderer = (js_root / "11-hud-board-hand.js").read_text(encoding="utf-8")
    glossary = (js_root / "03-deck-builder.js").read_text(encoding="utf-8")
    assert "Cleanse Burning from a friendly minion" in renderer
    assert "Cleanse all debuffs" in renderer
    assert "eff.type === 20 && !eff.burn_only" in glossary


def test_only_burning_friendly_minions_are_legal_targets(library):
    extinguisher_id = library.get_numeric_id("fire_extinguisher")
    rat_id = library.get_numeric_id("rat")
    friendly = MinionInstance(
        0, rat_id, PlayerSide.PLAYER_1, (1, 2), 10, is_burning=True,
    )
    enemy = MinionInstance(
        1, rat_id, PlayerSide.PLAYER_2, (3, 2), 10, is_burning=True,
    )
    clean_but_debuffed = MinionInstance(
        2, rat_id, PlayerSide.PLAYER_1, (1, 3), 10,
        attack_bonus=-3, max_health_bonus=-2,
    )
    state = _state(
        library,
        hand=(extinguisher_id,),
        minions=(friendly, enemy, clean_but_debuffed),
    )
    casts = [
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD and action.card_index == 0
    ]
    assert {action.target_pos for action in casts} == {(1, 2)}


def test_unplayable_without_a_burning_friendly_target(library):
    extinguisher_id = library.get_numeric_id("fire_extinguisher")
    rat_id = library.get_numeric_id("rat")
    clean_but_debuffed = MinionInstance(
        0, rat_id, PlayerSide.PLAYER_1, (1, 2), 10,
        attack_bonus=-3, max_health_bonus=-2,
    )
    state = _state(
        library, hand=(extinguisher_id,), minions=(clean_but_debuffed,),
    )

    casts = [
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD and action.card_index == 0
    ]
    assert casts == []


def test_cleanse_resolves_after_the_spell_stage(library):
    extinguisher_id = library.get_numeric_id("fire_extinguisher")
    rat_id = library.get_numeric_id("rat")
    friendly = MinionInstance(
        0,
        rat_id,
        PlayerSide.PLAYER_1,
        (1, 2),
        10,
        attack_bonus=-3,
        max_health_bonus=-2,
        is_burning=True,
    )
    state = _state(library, hand=(extinguisher_id,), minions=(friendly,))
    cast = next(
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD
    )

    staged = resolve_action(state, cast, library)
    assert staged.phase == TurnPhase.REACT
    assert staged.react_stack[0].target_pos == (1, 2)
    assert staged.get_minion(0).is_burning is True
    assert staged.players[0].current_mana == 0

    resolved = resolve_action(staged, pass_action(), library)
    cleaned = resolved.get_minion(0)
    assert cleaned.is_burning is False
    assert cleaned.attack_bonus == -3
    assert cleaned.max_health_bonus == -2
    assert cleaned.current_health == 10


def test_resolution_side_filter_cannot_cleanse_an_enemy(library):
    rat_id = library.get_numeric_id("rat")
    enemy = MinionInstance(
        0, rat_id, PlayerSide.PLAYER_2, (3, 2), 10, is_burning=True,
    )
    state = _state(library, minions=(enemy,))
    effect = library.get_by_card_id("fire_extinguisher").effects[0]
    result = resolve_effect(
        state,
        effect,
        caster_pos=(0, 0),
        caster_owner=PlayerSide.PLAYER_1,
        library=library,
        target_pos=(3, 2),
    )
    assert result is state
    assert result.get_minion(0).is_burning is True


def test_tensor_engine_targets_burning_friendlies_and_preserves_stats(library):
    torch = pytest.importorskip("torch")
    from grid_tactics.tensor_engine.card_table import CardTable
    from grid_tactics.tensor_engine.constants import PLAY_CARD_BASE
    from grid_tactics.tensor_engine.effects import apply_effects_batch
    from grid_tactics.tensor_engine.legal_actions import compute_legal_mask_batch
    from grid_tactics.tensor_engine.state import create_initial_state

    device = torch.device("cpu")
    table = CardTable.from_library(library, device)
    state = create_initial_state(1, device)
    extinguisher_id = library.get_numeric_id("fire_extinguisher")

    state.active_player[0] = 0
    state.phase[0] = 0
    state.hands[0, 0, 0] = extinguisher_id
    state.hand_sizes[0, 0] = 1
    for slot, owner, row, col, burning in (
        (0, 0, 1, 2, True),
        (1, 1, 3, 2, True),
        (2, 0, 1, 3, False),
    ):
        state.minion_alive[0, slot] = True
        state.minion_owner[0, slot] = owner
        state.minion_row[0, slot] = row
        state.minion_col[0, slot] = col
        state.board[0, row, col] = slot
        state.is_burning[0, slot] = burning
        state.minion_atk_bonus[0, slot] = -2

    mask = compute_legal_mask_batch(state, table)
    friendly_flat = 1 * 5 + 2
    enemy_flat = 3 * 5 + 2
    clean_friendly_flat = 1 * 5 + 3
    assert mask[0, PLAY_CARD_BASE + friendly_flat]
    assert not mask[0, PLAY_CARD_BASE + enemy_flat]
    assert not mask[0, PLAY_CARD_BASE + clean_friendly_flat]

    apply_effects_batch(
        state,
        card_ids=torch.tensor([extinguisher_id], dtype=torch.int32),
        trigger=0,
        caster_owners=torch.tensor([0], dtype=torch.int32),
        caster_slots=torch.tensor([-1], dtype=torch.int32),
        target_flat_pos=torch.tensor([friendly_flat], dtype=torch.int32),
        card_table=table,
        mask=torch.tensor([True]),
    )
    assert not state.is_burning[0, 0]
    assert state.minion_atk_bonus[0, 0] == -2
    assert state.is_burning[0, 1]
