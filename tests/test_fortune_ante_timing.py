"""Focused Fortune-ante timing across Marked Cards follow-ups."""

from pathlib import Path

import pytest

from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.player import Player
from grid_tactics.roguelike_events import (
    MARKED_CARDS,
    WITH_A_SLAP,
    resolve_marked_cards_choice,
    resolve_roguelike_event_choice,
)


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _player(side: PlayerSide, deck: tuple[int, ...]) -> Player:
    return Player(
        side=side,
        hp=30,
        current_mana=3,
        max_mana=5,
        hand=(),
        deck=deck,
        grave=(),
    )


def _pending_fortune(
    library: CardLibrary,
    *,
    prior_rounds: int = 0,
    p0_has_cards: bool = True,
    p1_has_cards: bool = True,
) -> GameState:
    cards = tuple(
        library.get_numeric_id(card_id)
        for card_id in ("rat", "prohibition", "acidic_rain", "dark_matter_barrage")
    )
    history = tuple(f"prior-{idx}" for idx in range(prior_rounds))
    return GameState(
        board=Board.empty(),
        players=(
            _player(PlayerSide.PLAYER_1, cards if p0_has_cards else ()),
            _player(PlayerSide.PLAYER_2, cards if p1_has_cards else ()),
        ),
        active_player_idx=0,
        phase=TurnPhase.START_OF_TURN,
        turn_number=26 + 25 * prior_rounds,
        seed=71,
        pending_roguelike_event_turn=26 + 25 * prior_rounds,
        pending_roguelike_event_options=(MARKED_CARDS, WITH_A_SLAP),
        roguelike_event_history=(history, history),
    )


def _lock_both(
    state: GameState,
    player_0_choice: str,
    player_1_choice: str,
    library: CardLibrary,
) -> GameState:
    state = resolve_roguelike_event_choice(
        state, 0, player_0_choice, library,
    )
    return resolve_roguelike_event_choice(
        state, 1, player_1_choice, library,
    )


def test_single_marked_cards_holds_ante_until_its_choice_resolves(library):
    state = _lock_both(
        _pending_fortune(library), MARKED_CARDS, WITH_A_SLAP, library,
    )

    assert state.pending_marked_cards_player_idx == 0
    assert state.fortune_rounds_completed == 0
    assert state.fortune_ante == 1

    # Pending timing survives the same JSON round-trip used by saved games
    # and server state frames.
    state = GameState.from_dict(state.to_dict())
    assert state.fortune_ante == 1

    state = resolve_marked_cards_choice(state, 0, 0, (1, 2))
    assert state.pending_marked_cards_player_idx is None
    assert state.fortune_rounds_completed == 1
    assert state.fortune_ante == 2


def test_two_marked_cards_hold_ante_through_both_sequential_modals(library):
    state = _lock_both(
        _pending_fortune(library, prior_rounds=1),
        MARKED_CARDS,
        MARKED_CARDS,
        library,
    )

    # The previous completed Fortune still counts, but the new history row
    # does not raise the tier while either player's follow-up is pending.
    assert state.pending_marked_cards_player_idx == 0
    assert state.pending_marked_cards_queue == (1,)
    assert state.fortune_rounds_completed == 1
    assert state.fortune_ante == 2

    state = resolve_marked_cards_choice(state, 0, 0, (1, 2))
    assert state.pending_marked_cards_player_idx == 1
    assert state.pending_marked_cards_queue == ()
    assert state.fortune_rounds_completed == 1
    assert state.fortune_ante == 2

    state = resolve_marked_cards_choice(state, 1, 0, (1, 2))
    assert state.pending_marked_cards_player_idx is None
    assert state.fortune_rounds_completed == 2
    assert state.fortune_ante == 3


def test_marked_cards_with_no_available_followup_completes_immediately(library):
    state = _lock_both(
        _pending_fortune(library, p0_has_cards=False),
        MARKED_CARDS,
        WITH_A_SLAP,
        library,
    )

    assert state.pending_marked_cards_player_idx is None
    assert state.pending_marked_cards_queue == ()
    assert state.fortune_rounds_completed == 1
    assert state.fortune_ante == 2
