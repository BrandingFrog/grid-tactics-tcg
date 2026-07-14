"""Late-game automatic draw and empty-deck fatigue clock."""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.engine_events import (
    EVT_CARD_BURNED,
    EVT_CARD_DRAWN,
    EVT_PENDING_MODAL_RESOLVED,
    EVT_PLAYER_HP_CHANGE,
    EventStream,
)
from grid_tactics.enums import PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.react_stack import apply_new_turn_resources
from grid_tactics.roguelike_events import (
    WITH_A_SLAP,
    resolve_roguelike_event_choice,
)
from grid_tactics.types import MAX_HAND_SIZE


@pytest.fixture(autouse=True)
def active_rules(monkeypatch):
    monkeypatch.setenv("GT_MANUAL_DRAW", "1")


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _state(
    library: CardLibrary,
    *,
    completed_fortunes: int,
    deck: tuple[int, ...] = (),
    hand: tuple[int, ...] = (),
    exhaust: tuple[int, ...] = (),
    hp: int = 100,
) -> GameState:
    rat = library.get_numeric_id("rat")
    state, _ = GameState.new_game(75, (rat,) * 40, (rat,) * 40)
    players = list(state.players)
    players[0] = replace(
        players[0],
        hp=hp,
        hand=hand,
        deck=deck,
        exhaust=exhaust,
    )
    history = tuple(
        f"fortune-{idx}" for idx in range(completed_fortunes)
    )
    return replace(
        state,
        players=tuple(players),
        turn_number=76 if completed_fortunes >= 3 else 75,
        roguelike_event_history=(history, history),
    )


def test_clock_is_off_before_turn_75_fortune_resolves(library):
    state = _state(library, completed_fortunes=2, deck=(), hand=())

    resolved = apply_new_turn_resources(state)

    assert state.fortune_ante == 3
    assert state.automatic_turn_draw_count == 0
    assert resolved.players[0].hand == ()
    assert resolved.players[0].hp == 100
    assert resolved.fatigue_counts == (0, 0)


@pytest.mark.parametrize(
    ("completed_fortunes", "economy_rate", "automatic_draws"),
    (
        (0, 1, 0),
        (1, 2, 0),
        (2, 3, 0),
        (3, 3, 1),
        (4, 3, 1),
        (8, 3, 1),
    ),
)
def test_fortune_economy_caps_separately_from_deckout_clock(
    library, completed_fortunes, economy_rate, automatic_draws,
):
    state = _state(library, completed_fortunes=completed_fortunes)

    assert state.fortune_ante == economy_rate
    assert state.automatic_turn_draw_count == automatic_draws


def test_third_fortune_unlocks_one_automatic_turn_draw(library):
    rat = library.get_numeric_id("rat")
    state = _state(library, completed_fortunes=3, deck=(rat,), hand=())
    stream = EventStream()

    resolved = apply_new_turn_resources(state, event_collector=stream)

    assert state.fortune_ante == 3
    assert state.automatic_turn_draw_count == 1
    assert resolved.players[0].hand == (rat,)
    assert resolved.players[0].deck == ()
    draw = next(event for event in stream.events if event.type == EVT_CARD_DRAWN)
    assert draw.payload == {
        "player_idx": 0,
        "source": "turn_start",
        "card_numeric_id": rat,
    }


def test_late_turn_draw_overdraws_to_exhaust(library):
    rat = library.get_numeric_id("rat")
    full_hand = (rat,) * MAX_HAND_SIZE
    state = _state(
        library,
        completed_fortunes=3,
        deck=(rat,),
        hand=full_hand,
    )
    stream = EventStream()

    resolved = apply_new_turn_resources(state, event_collector=stream)

    assert resolved.players[0].hand == full_hand
    assert resolved.players[0].deck == ()
    assert resolved.players[0].exhaust == (rat,)
    assert any(event.type == EVT_CARD_BURNED for event in stream.events)


def test_empty_deck_fatigue_escalates_each_own_turn(library):
    state = _state(library, completed_fortunes=3, deck=(), hand=())
    first_stream = EventStream()

    first = apply_new_turn_resources(state, event_collector=first_stream)
    assert first.players[0].hp == 90
    assert first.fatigue_counts == (1, 0)
    assert next(
        event for event in first_stream.events
        if event.type == EVT_PLAYER_HP_CHANGE
    ).payload["delta"] == -10

    second_stream = EventStream()
    second = apply_new_turn_resources(
        replace(first, turn_number=78),
        event_collector=second_stream,
    )
    assert second.players[0].hp == 70
    assert second.fatigue_counts == (2, 0)
    assert next(
        event for event in second_stream.events
        if event.type == EVT_PLAYER_HP_CHANGE
    ).payload["delta"] == -20


def test_late_fatigue_can_end_the_game(library):
    state = _state(
        library,
        completed_fortunes=3,
        deck=(),
        hand=(),
        hp=5,
    )

    resolved = apply_new_turn_resources(state)

    assert resolved.is_game_over
    assert resolved.winner == PlayerSide.PLAYER_2
    assert resolved.players[0].hp == -5


def test_pending_third_fortune_does_not_start_clock_early(library):
    rat = library.get_numeric_id("rat")
    state = _state(library, completed_fortunes=3, deck=(rat,))
    pending = replace(
        state,
        pending_marked_cards_player_idx=0,
        pending_marked_cards_cards=(rat,),
    )

    assert pending.fortune_rounds_completed == 2
    assert pending.automatic_turn_draw_count == 0
    assert state.automatic_turn_draw_count == 1
    assert state.to_dict()["automatic_turn_draw_count"] == 1


def test_turn_75_fortune_resume_applies_first_forced_draw(library):
    rat = library.get_numeric_id("rat")
    state = _state(library, completed_fortunes=2, deck=(rat,), hand=())
    state = replace(
        state,
        phase=TurnPhase.START_OF_TURN,
        turn_number=76,
        pending_roguelike_event_turn=76,
        pending_roguelike_event_options=(WITH_A_SLAP,),
    )
    state = resolve_roguelike_event_choice(
        state, 0, WITH_A_SLAP, library,
    )
    reveal_stream = EventStream()
    state = resolve_roguelike_event_choice(
        state, 1, WITH_A_SLAP, library,
        event_collector=reveal_stream,
    )

    assert state.fortune_rounds_completed == 3
    assert state.fortune_ante == 3
    assert state.automatic_turn_draw_count == 1
    reveal = next(
        event for event in reveal_stream.events
        if event.type == EVT_PENDING_MODAL_RESOLVED
    )
    assert reveal.payload["fortune_ante"] == 3
    assert reveal.payload["turn_mana_gain"] == 3
    assert reveal.payload["rest_draw_count"] == 3
    assert reveal.payload["automatic_turn_draw_count"] == 1
    assert reveal.payload["ante_increased"] is False

    resumed = apply_new_turn_resources(state)
    assert resumed.players[0].hand == (rat,)
    assert resumed.players[0].deck == ()
