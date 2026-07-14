"""Focused strategy and safety tests for the server preview AI."""

from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.action_resolver import resolve_action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, CardType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.server.preview_ai import pick_preview_action


@pytest.fixture(scope="module")
def library() -> CardLibrary:
    return CardLibrary.from_directory(Path("data/cards"))


@pytest.fixture(autouse=True)
def manual_draw_rules(monkeypatch):
    monkeypatch.setenv("GT_MANUAL_DRAW", "1")


def _minion(
    library: CardLibrary,
    instance_id: int,
    card_id: str,
    owner: PlayerSide,
    position: tuple[int, int],
    *,
    health: int | None = None,
) -> MinionInstance:
    card_def = library.get_by_card_id(card_id)
    return MinionInstance(
        instance_id=instance_id,
        card_numeric_id=library.get_numeric_id(card_id),
        owner=owner,
        position=position,
        current_health=card_def.health if health is None else health,
    )


def _state(
    library: CardLibrary,
    *,
    hand: tuple[str, ...] = (),
    deck: tuple[str, ...] = (),
    opponent_hand: tuple[str, ...] = (),
    mana: int = 10,
    opponent_mana: int = 10,
    dark_matter: int = 0,
    minions: tuple[MinionInstance, ...] = (),
) -> GameState:
    p1 = replace(
        Player.new(
            PlayerSide.PLAYER_1,
            tuple(library.get_numeric_id(card_id) for card_id in deck),
        ),
        hand=tuple(library.get_numeric_id(card_id) for card_id in hand),
        hp=100,
        current_mana=mana,
        max_mana=10,
        dark_matter=dark_matter,
    )
    p2 = replace(
        Player.new(PlayerSide.PLAYER_2, ()),
        hand=tuple(library.get_numeric_id(card_id) for card_id in opponent_hand),
        hp=100,
        current_mana=opponent_mana,
        max_mana=10,
    )
    board = Board.empty()
    for minion in minions:
        board = board.place(*minion.position, minion.instance_id)
    return GameState(
        board=board,
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=0,
        minions=minions,
        next_minion_id=max((m.instance_id for m in minions), default=-1) + 1,
    )


def _pick(state: GameState, library: CardLibrary):
    legal = legal_actions(state, library)
    picked = pick_preview_action(state, library, legal)
    assert picked in legal
    return picked


def test_skips_noop_ratchanter_activation_and_moves(library):
    ratchanter = _minion(
        library,
        0,
        "ratchanter",
        PlayerSide.PLAYER_1,
        (0, 0),
    )
    state = _state(library, mana=2, minions=(ratchanter,))

    picked = _pick(state, library)

    assert picked.action_type == ActionType.MOVE


@pytest.mark.parametrize(
    ("hand", "deck", "mana"),
    [
        (("dark_matter_stash", "fallen_paladin"), (), 5),
        (("dark_matter_barrage", "dark_wyrm"), (), 7),
        (("to_the_ratmobile", "rat"), ("fallen_paladin",), 3),
    ],
)
def test_skips_zero_value_magic(library, hand, deck, mana):
    state = _state(library, hand=hand, deck=deck, mana=mana)

    picked = _pick(state, library)
    picked_def = library.get_by_id(state.players[0].hand[picked.card_index])

    assert picked.action_type == ActionType.PLAY_CARD
    assert picked_def.card_type == CardType.MINION


def test_never_sacrifices_zero_attack_minion(library):
    battery = _minion(
        library,
        0,
        "dark_matter_battery",
        PlayerSide.PLAYER_1,
        (4, 0),
    )
    state = _state(library, hand=("rat",), mana=1, minions=(battery,))

    picked = _pick(state, library)

    assert picked.action_type != ActionType.SACRIFICE


def test_ranged_minion_deploys_to_back_row(library):
    state = _state(library, hand=("pyre_archer",), mana=3)

    picked = _pick(state, library)

    assert picked.action_type == ActionType.PLAY_CARD
    assert picked.position == (0, 2)


def test_feed_the_shadow_prefers_guaranteed_kill(library):
    friendly_rat = _minion(library, 0, "rat", PlayerSide.PLAYER_1, (0, 0))
    enemy_rat = _minion(library, 1, "rat", PlayerSide.PLAYER_2, (1, 0))
    enemy_wyrm = _minion(library, 2, "dark_wyrm", PlayerSide.PLAYER_2, (1, 1))
    state = _state(
        library,
        hand=("feed_the_shadow",),
        mana=2,
        minions=(friendly_rat, enemy_rat, enemy_wyrm),
    )

    picked = _pick(state, library)

    assert picked.action_type == ActionType.PLAY_CARD
    assert picked.target_pos == enemy_rat.position


def test_feed_the_shadow_uses_cheapest_sufficient_fodder(library):
    friendly_rat = _minion(library, 0, "rat", PlayerSide.PLAYER_1, (0, 0))
    friendly_wyrm = _minion(library, 1, "dark_wyrm", PlayerSide.PLAYER_1, (0, 1))
    small_target = _minion(
        library,
        2,
        "pyre_archer",
        PlayerSide.PLAYER_2,
        (1, 0),
        health=5,
    )
    state = _state(
        library,
        hand=("feed_the_shadow",),
        mana=2,
        minions=(friendly_rat, friendly_wyrm, small_target),
    )

    picked = _pick(state, library)

    assert picked.action_type == ActionType.PLAY_CARD
    assert picked.destroyed_minion_id == friendly_rat.instance_id


def test_shady_trade_deal_discards_stash_for_on_discard_synergy(library):
    dark_mage = _minion(
        library,
        0,
        "shadow_blaster",
        PlayerSide.PLAYER_1,
        (0, 0),
    )
    state = _state(
        library,
        hand=("shady_trade_deal", "dark_matter_stash", "rat"),
        mana=1,
        minions=(dark_mage,),
    )

    picked = _pick(state, library)

    assert picked.action_type == ActionType.PLAY_CARD
    assert picked.card_index == 0
    assert picked.discard_card_indices == (1,)


def test_skips_tutor_that_would_overdraw_extra_cards(library):
    full_hand = ("to_the_ratmobile",) + ("prohibition",) * 9
    state = _state(
        library,
        hand=full_hand,
        deck=("rat", "rat"),
        mana=3,
    )

    picked = _pick(state, library)

    assert picked.action_type == ActionType.DRAW


def test_policy_is_deterministic_legal_and_resolvable(library):
    state = _state(library, hand=("rat",), deck=("fallen_paladin",), mana=1)
    legal = legal_actions(state, library)
    before = random.getstate()

    first = pick_preview_action(state, library, legal)
    second = pick_preview_action(state, library, legal)

    assert first == second
    assert first in legal
    assert random.getstate() == before
    resolved = resolve_action(state, first, library)
    assert resolved != state


def test_standard_rules_still_cast_useful_magic(library, monkeypatch):
    monkeypatch.setenv("GT_MANUAL_DRAW", "0")
    enemy = _minion(
        library,
        0,
        "dark_wyrm",
        PlayerSide.PLAYER_2,
        (4, 0),
    )
    state = _state(
        library,
        hand=("matter_of_time",),
        mana=4,
        dark_matter=50,
        minions=(enemy,),
    )

    picked = _pick(state, library)

    assert picked.action_type == ActionType.PLAY_CARD


def test_prohibition_answers_lethal_scaled_magic(library):
    enemy = _minion(
        library,
        0,
        "dark_wyrm",
        PlayerSide.PLAYER_2,
        (4, 0),
    )
    state = _state(
        library,
        hand=("matter_of_time",),
        opponent_hand=("prohibition",),
        mana=4,
        opponent_mana=4,
        dark_matter=50,
        minions=(enemy,),
    )
    cast = next(
        action
        for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD
    )
    react_state = resolve_action(state, cast, library)

    picked = _pick(react_state, library)

    assert picked.action_type == ActionType.PLAY_REACT


def test_react_choice_does_not_inspect_opponent_deck_identity(library):
    def pick_against(hidden_deck: tuple[str, ...]):
        state = _state(
            library,
            hand=("to_the_ratmobile",),
            deck=hidden_deck,
            opponent_hand=("prohibition",),
            mana=3,
            opponent_mana=4,
        )
        cast = next(
            action
            for action in legal_actions(state, library)
            if action.action_type == ActionType.PLAY_CARD
        )
        react_state = resolve_action(state, cast, library)
        return _pick(react_state, library)

    rat_deck_pick = pick_against(("rat", "rat"))
    non_rat_deck_pick = pick_against(("fallen_paladin", "fallen_paladin"))

    assert rat_deck_pick == non_rat_deck_pick
