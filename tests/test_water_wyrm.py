"""Water Wyrm (user 2026-07-11): Rally Cleanse + magic-untargetable.

- CLEANSE (EffectType 20): fires in the owner's Rally Phase on itself —
  Burning cleared, negative attack / max-HP marks reset to 0. NOT a heal.
- magic_untargetable: never a legal SINGLE_TARGET for a MAGIC card;
  board-wide magic still hits it (untargetable, not immune — user MCQ).
"""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, EffectType, PlayerSide, TriggerType
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.server.preset_deck import get_preset_deck


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _base_state(library):
    deck = get_preset_deck(library)
    state, _ = GameState.new_game(seed=13, deck_p1=deck, deck_p2=deck)
    return state


def test_definition(library):
    w = library.get_by_card_id("water_wyrm")
    assert w.mana_cost == 5
    assert w.attack == 33 and w.health == 33
    assert w.magic_untargetable is True
    assert any(
        e.effect_type == EffectType.CLEANSE
        and e.trigger == TriggerType.ON_START_OF_TURN
        for e in w.effects
    )


def test_cleanse_clears_debuffs_not_damage(library):
    from grid_tactics.effect_resolver import _apply_effect_to_minion_dispatch

    wyrm_nid = library.get_numeric_id("water_wyrm")
    minion = MinionInstance(
        instance_id=1, card_numeric_id=wyrm_nid,
        owner=PlayerSide.PLAYER_1, position=(0, 0),
        current_health=20,           # chip damage stays
        attack_bonus=-5,             # debuff -> 0
        max_health_bonus=-3,         # debuff -> 0
        is_burning=True,             # cleared
    )
    state = _base_state(library)
    state = replace(
        state,
        minions=(minion,),
        board=state.board.place(0, 0, 1),
        next_minion_id=2,
    )
    w = library.get_by_card_id("water_wyrm")
    cleanse = next(e for e in w.effects if e.effect_type == EffectType.CLEANSE)
    new_state = _apply_effect_to_minion_dispatch(state, cleanse, minion, library)
    m = new_state.get_minion(1)
    assert m.is_burning is False
    assert m.attack_bonus == 0
    assert m.max_health_bonus == 0
    assert m.current_health == 20, "Cleanse is not a heal"


def test_cleanse_keeps_positive_buffs(library):
    from grid_tactics.effect_resolver import _apply_effect_to_minion_dispatch

    wyrm_nid = library.get_numeric_id("water_wyrm")
    minion = MinionInstance(
        instance_id=1, card_numeric_id=wyrm_nid,
        owner=PlayerSide.PLAYER_1, position=(0, 0),
        current_health=33, attack_bonus=4, max_health_bonus=2,
    )
    state = _base_state(library)
    state = replace(
        state, minions=(minion,), board=state.board.place(0, 0, 1),
        next_minion_id=2,
    )
    w = library.get_by_card_id("water_wyrm")
    cleanse = next(e for e in w.effects if e.effect_type == EffectType.CLEANSE)
    new_state = _apply_effect_to_minion_dispatch(state, cleanse, minion, library)
    m = new_state.get_minion(1)
    assert m.attack_bonus == 4 and m.max_health_bonus == 2


def test_magic_cannot_target_it(library):
    """A single-target magic (Dark Matter Barrage's targeted mode /
    matter_possessed 'Deal to target') must not enumerate the Water Wyrm's
    tile; another enemy stays targetable."""
    state = _base_state(library)
    wyrm_nid = library.get_numeric_id("water_wyrm")
    rat_nid = library.get_numeric_id("rat")
    # Find any magic with an ON_PLAY SINGLE_TARGET effect.
    from grid_tactics.enums import CardType, TargetType
    magic = next(
        c for c in library.all_cards
        if c.card_type == CardType.MAGIC
        and not c.destroy_ally_cost
        and any(e.trigger == TriggerType.ON_PLAY
                and e.target == TargetType.SINGLE_TARGET for e in c.effects)
    )
    magic_nid = library.get_numeric_id(magic.card_id)
    wyrm = MinionInstance(
        instance_id=1, card_numeric_id=wyrm_nid,
        owner=PlayerSide.PLAYER_2, position=(4, 0), current_health=33,
    )
    rat = MinionInstance(
        instance_id=2, card_numeric_id=rat_nid,
        owner=PlayerSide.PLAYER_2, position=(4, 4), current_health=10,
    )
    board = state.board.place(4, 0, 1).place(4, 4, 2)
    p = replace(state.players[0], hand=(magic_nid,), current_mana=10)
    state = replace(
        state, players=(p, state.players[1]), minions=(wyrm, rat),
        board=board, next_minion_id=3,
    )
    targets = {
        tuple(a.target_pos)
        for a in legal_actions(state, library)
        if a.action_type == ActionType.PLAY_CARD and a.target_pos is not None
    }
    assert (4, 4) in targets, "the rat must remain targetable"
    assert (4, 0) not in targets, "Water Wyrm must not be a magic target"
