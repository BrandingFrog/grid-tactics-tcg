"""Regression coverage for synchronized 25-turn roguelike events."""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.engine_events import (
    EVT_CARD_BURNED,
    EVT_CARD_DRAWN,
    EVT_PENDING_MODAL_OPENED,
    EVT_PENDING_MODAL_RESOLVED,
    EVT_PLAYER_HP_CHANGE,
    EVT_REACT_WINDOW_OPENED,
    EventStream,
)
from grid_tactics.types import MAX_HAND_SIZE
from grid_tactics.enums import PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.react_stack import (
    _close_end_of_turn_and_flip,
    _resolve_handshake_payout,
    apply_new_turn_resources,
    enter_start_of_turn,
)
from grid_tactics.roguelike_events import (
    CLUMSY_GREED,
    COMPOUND_INTEREST,
    GRAVE_EXPECTATIONS,
    MARKED_CARDS,
    POCKET_CHANGE,
    ROGUELIKE_EVENT_CHOICES,
    SHARP_EYED_SCEPTIC,
    SKELETON_CREW,
    SPRING_CLEANING,
    UNCHARTED_FORTUNE,
    WITH_A_SLAP,
    apply_handshake_slap_damage,
    choose_roguelike_event_for_ai,
    open_roguelike_event,
    resolve_marked_cards_choice,
    resolve_roguelike_event_choice,
    score_roguelike_event_choices,
)
from grid_tactics.server.view_filter import (
    filter_engine_events_for_viewer,
    filter_state_for_player,
    filter_state_for_spectator,
)


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _player(side, *, hand=(), deck=(), mana=3, hp=30):
    return Player(
        side=side,
        hp=hp,
        current_mana=mana,
        max_mana=max(5, mana),
        hand=tuple(hand),
        deck=tuple(deck),
        grave=(),
    )


def _state(*, p0=None, p1=None, turn=25, phase=TurnPhase.END_OF_TURN, **kwargs):
    defaults = dict(
        board=Board.empty(),
        players=(
            p0 or _player(PlayerSide.PLAYER_1),
            p1 or _player(PlayerSide.PLAYER_2),
        ),
        active_player_idx=0,
        phase=phase,
        turn_number=turn,
        seed=41,
        minions=(),
        next_minion_id=1,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


def test_turn_25_opens_event_before_incoming_resources(library):
    rat = library.get_numeric_id("rat")
    p1 = _player(PlayerSide.PLAYER_1, deck=(rat, rat), mana=2)
    stream = EventStream()

    parked = _close_end_of_turn_and_flip(
        _state(p1=p1), library, event_collector=stream,
    )

    assert parked.turn_number == 26
    assert parked.active_player_idx == 1
    assert parked.phase == TurnPhase.START_OF_TURN
    assert parked.pending_roguelike_event_turn == 26
    assert parked.players[1].current_mana == 2
    assert parked.players[1].deck == (rat, rat)
    assert legal_actions(parked, library) == ()
    assert [event.type for event in stream.events][-1] == EVT_PENDING_MODAL_OPENED
    assert enter_start_of_turn(parked, library) == parked


@pytest.mark.parametrize(
    ("completed_turn", "incoming_turn"),
    ((25, 26), (50, 51), (75, 76), (100, 101)),
)
def test_fortune_round_recurs_every_25_completed_turns(
    library, completed_turn, incoming_turn,
):
    parked = _close_end_of_turn_and_flip(
        _state(turn=completed_turn), library,
    )

    assert parked.turn_number == incoming_turn
    assert parked.pending_roguelike_event_turn == incoming_turn
    assert len(parked.pending_roguelike_event_options) == 3
    assert parked.phase == TurnPhase.START_OF_TURN


def test_non_boundary_turn_continues_normally(library):
    rat = library.get_numeric_id("rat")
    p1 = _player(PlayerSide.PLAYER_2, deck=(rat, rat), mana=2)
    advanced = _close_end_of_turn_and_flip(
        _state(p1=p1, turn=24), library,
    )
    assert advanced.turn_number == 25
    assert advanced.pending_roguelike_event_turn is None
    assert advanced.players[1].current_mana == 3
    assert len(advanced.players[1].deck) == 1


def test_effects_wait_for_both_choices_then_apply_as_atomic_batch(library):
    rat = library.get_numeric_id("rat")
    prohibition = library.get_numeric_id("prohibition")
    p0 = _player(
        PlayerSide.PLAYER_1,
        hand=(rat, rat),
        deck=(rat, rat, rat, rat),
    )
    p1 = _player(PlayerSide.PLAYER_2, hand=(), deck=(rat,), mana=3)
    pending = _state(
        p0=p0,
        p1=p1,
        turn=26,
        phase=TurnPhase.START_OF_TURN,
        pending_roguelike_event_turn=26,
        pending_roguelike_event_options=(
            CLUMSY_GREED, SHARP_EYED_SCEPTIC, WITH_A_SLAP,
        ),
    )
    stream = EventStream()

    one_locked = resolve_roguelike_event_choice(
        pending, 0, CLUMSY_GREED, library, event_collector=stream,
    )
    assert one_locked.players == pending.players
    assert one_locked.pending_roguelike_event_choices == (CLUMSY_GREED, None)
    assert stream.events == []

    resolved = resolve_roguelike_event_choice(
        one_locked, 1, SHARP_EYED_SCEPTIC, library, event_collector=stream,
    )
    assert resolved.pending_roguelike_event_turn is None
    assert len(resolved.players[0].hand) == 4
    assert len(resolved.players[0].deck) == 0
    assert len(resolved.players[0].exhaust) == 2
    assert len(resolved.players[0].grave) == 0
    assert prohibition in resolved.players[1].hand
    assert resolved.players[1].current_mana == 4
    assert resolved.roguelike_event_history == (
        (CLUMSY_GREED,),
        (SHARP_EYED_SCEPTIC,),
    )
    assert stream.events[0].type == EVT_PENDING_MODAL_RESOLVED
    reveal = stream.events[0].payload
    assert reveal["resolution"] == "simultaneous_no_react"
    assert [item["choice"] for item in reveal["choices"]] == [
        CLUMSY_GREED, SHARP_EYED_SCEPTIC,
    ]
    assert reveal["choices"][0]["option"]["name"] == "Clumsy Greed"
    assert reveal["choices"][1]["resolved_option"]["name"] == (
        "Sharp Eyed Sceptic"
    )
    assert resolved.react_stack == ()
    assert resolved.react_player_idx is None
    assert EVT_REACT_WINDOW_OPENED not in [event.type for event in stream.events]

    # Both locked choices are intentionally public only in the resolve event.
    for viewer_idx in (0, 1):
        filtered = filter_engine_events_for_viewer(
            stream.events, viewer_idx, library=library,
        )
        assert filtered[0].payload["choices"] == reveal["choices"]


def test_clumsy_greed_exhausts_two_random_hand_cards(library):
    rat = library.get_numeric_id("rat")
    prohibition = library.get_numeric_id("prohibition")
    player = _player(
        PlayerSide.PLAYER_1,
        hand=(rat, prohibition),
        deck=(rat, prohibition, rat, prohibition),
    )
    stream = EventStream()
    resolved = _resolve_fortunes(
        _state(
            p0=player,
            phase=TurnPhase.START_OF_TURN,
            turn=26,
        ),
        CLUMSY_GREED, WITH_A_SLAP, library,
        event_collector=stream,
    )
    assert len(resolved.players[0].hand) == 4
    assert len(resolved.players[0].deck) == 0
    assert len(resolved.players[0].exhaust) == 2
    assert resolved.players[0].grave == ()
    deck_draws = [
        event for event in stream.events
        if event.type == EVT_CARD_DRAWN
        and event.payload.get("source") == "roguelike_event"
        and event.payload.get("player_idx") == 0
    ]
    hand_exhausts = [
        event for event in stream.events
        if event.type == EVT_CARD_BURNED
        and event.payload.get("source") == "clumsy_greed"
        and event.payload.get("player_idx") == 0
    ]
    assert len(deck_draws) == 4
    assert all(event.payload.get("from_zone") == "deck"
               for event in deck_draws)
    assert len(hand_exhausts) == 2
    assert all(event.payload.get("from_zone") == "hand"
               for event in hand_exhausts)
    source_indexes = [event.payload.get("source_index") for event in hand_exhausts]
    assert all(isinstance(index, int) for index in source_indexes)
    assert source_indexes == sorted(source_indexes, reverse=True)
    assert not any(
        event.type == "card_discarded"
        and event.payload.get("player_idx") == 0
        for event in stream.events
    )


def test_clumsy_greed_last_card_overdraw_is_deck_sourced(library):
    rat = library.get_numeric_id("rat")
    stream = EventStream()

    resolved = _resolve_fortunes(
        _state(
            p0=_player(
                PlayerSide.PLAYER_1,
                hand=(rat,) * MAX_HAND_SIZE,
                deck=(rat,),
            ),
            phase=TurnPhase.START_OF_TURN,
            turn=26,
        ),
        CLUMSY_GREED, WITH_A_SLAP, library,
        event_collector=stream,
    )

    deck_burn = next(
        event for event in stream.events
        if event.type == EVT_CARD_BURNED
        and event.payload.get("source") == "roguelike_event"
        and event.payload.get("player_idx") == 0
    )
    hand_exhausts = [
        event for event in stream.events
        if event.type == EVT_CARD_BURNED
        and event.payload.get("source") == "clumsy_greed"
        and event.payload.get("player_idx") == 0
    ]
    assert resolved.players[0].deck == ()
    assert deck_burn.payload.get("from_zone") == "deck"
    assert len(hand_exhausts) == 2
    assert all(event.payload.get("from_zone") == "hand"
               for event in hand_exhausts)


def test_with_a_slap_stacks_and_deals_five_per_stack(library):
    state = _state(
        turn=26,
        phase=TurnPhase.START_OF_TURN,
        pending_roguelike_event_turn=26,
    )
    for event_turn in (26, 51):
        state = replace(
            state,
            pending_roguelike_event_turn=event_turn,
            pending_roguelike_event_choices=(None, None),
            pending_roguelike_event_options=(
                WITH_A_SLAP, SHARP_EYED_SCEPTIC, CLUMSY_GREED,
            ),
        )
        state = resolve_roguelike_event_choice(
            state, 0, WITH_A_SLAP, library,
        )
        state = resolve_roguelike_event_choice(
            state, 1, SHARP_EYED_SCEPTIC, library,
        )
    assert state.handshake_slap_stacks == (2, 0)

    stream = EventStream()
    damaged = apply_handshake_slap_damage(state, event_collector=stream)
    assert damaged.players[1].hp == state.players[1].hp - 10
    hp_event = next(ev for ev in stream.events if ev.type == EVT_PLAYER_HP_CHANGE)
    assert hp_event.payload["delta"] == -10
    assert hp_event.payload["stacks"] == 2
    assert hp_event.payload["cause"] == "handshake_slap"
    assert hp_event.payload["source_player_idx"] == 0
    assert hp_event.payload["player_idx"] == 1
    assert hp_event.payload["prev"] == state.players[1].hp
    assert hp_event.payload["new"] == damaged.players[1].hp
    assert hp_event.animation_duration_ms == 1150


def test_both_players_slap_during_same_handshake():
    state = _state(
        handshake_pending=True,
        handshake_slap_stacks=(2, 1),
        p0=_player(PlayerSide.PLAYER_1, hp=30),
        p1=_player(PlayerSide.PLAYER_2, hp=30),
    )
    stream = EventStream()
    paid = _resolve_handshake_payout(state, event_collector=stream)
    assert paid.players[0].hp == 25
    assert paid.players[1].hp == 20
    assert not paid.handshake_pending
    slap_events = [
        event for event in stream.events
        if event.type == EVT_PLAYER_HP_CHANGE
        and event.payload.get("cause") == "handshake_slap"
    ]
    assert [event.payload["source_player_idx"] for event in slap_events] == [0, 1]
    assert [event.payload["player_idx"] for event in slap_events] == [1, 0]
    assert [event.payload["delta"] for event in slap_events] == [-10, -5]
    assert [event.payload["stacks"] for event in slap_events] == [2, 1]
    assert all(event.animation_duration_ms == 1150 for event in slap_events)


def test_postponed_resources_resume_once(library):
    rat = library.get_numeric_id("rat")
    pending = _state(
        p1=_player(PlayerSide.PLAYER_2, deck=(rat, rat), mana=2),
        turn=26,
        phase=TurnPhase.START_OF_TURN,
        active_player_idx=1,
    )
    resumed = apply_new_turn_resources(pending)
    assert resumed.players[1].current_mana == 3
    assert len(resumed.players[1].hand) == 1
    assert len(resumed.players[1].deck) == 1


def test_save_round_trip_and_legacy_slap_upgrade():
    state = _state(
        phase=TurnPhase.START_OF_TURN,
        turn=26,
        pending_roguelike_event_turn=26,
        pending_roguelike_event_choices=(WITH_A_SLAP, None),
        pending_roguelike_event_options=(
            WITH_A_SLAP, SHARP_EYED_SCEPTIC, CLUMSY_GREED,
        ),
        handshake_slap_stacks=(3, 1),
        roguelike_event_history=(
            (WITH_A_SLAP, WITH_A_SLAP, WITH_A_SLAP),
            (SHARP_EYED_SCEPTIC,),
        ),
    )
    assert GameState.from_dict(state.to_dict()) == state

    legacy = state.to_dict()
    legacy.pop("handshake_slap_stacks")
    legacy.pop("roguelike_event_history")
    legacy["handshake_slap_enabled"] = [True, False]
    restored_legacy = GameState.from_dict(legacy)
    assert restored_legacy.handshake_slap_stacks == (1, 0)
    assert restored_legacy.roguelike_event_history == ((), ())


def test_private_choices_are_redacted_but_lock_status_is_public(library):
    state = _state(
        phase=TurnPhase.START_OF_TURN,
        turn=26,
        pending_roguelike_event_turn=26,
        pending_roguelike_event_choices=(WITH_A_SLAP, None),
        pending_roguelike_event_options=(
            WITH_A_SLAP, SHARP_EYED_SCEPTIC, CLUMSY_GREED,
        ),
    )
    p0 = filter_state_for_player(state.to_dict(), 0, library)
    p1 = filter_state_for_player(state.to_dict(), 1, library)
    spectator = filter_state_for_spectator(
        state.to_dict(), god_mode=True, library=library,
    )

    assert p0["pending_roguelike_event_your_choice"] == WITH_A_SLAP
    assert p1["pending_roguelike_event_your_choice"] is None
    assert spectator["pending_roguelike_event_your_choice"] is None
    assert p0["pending_roguelike_event_chosen"] == [True, False]
    assert p1["pending_roguelike_event_choices"] == [None, None]
    assert spectator["pending_roguelike_event_choices"] == [None, None]
    assert len(p0["roguelike_event_options"]) == 3


def test_ai_prefers_clumsy_greed_for_low_hand_card_advantage(library):
    rat = library.get_numeric_id("rat")
    state = _state(
        p0=_player(PlayerSide.PLAYER_1, hand=(), deck=(rat,) * 8, mana=5),
        p1=_player(PlayerSide.PLAYER_2, hp=100),
        phase=TurnPhase.START_OF_TURN,
        turn=26,
        pending_roguelike_event_turn=26,
    )
    assert choose_roguelike_event_for_ai(state, 0, library) == CLUMSY_GREED


def test_ai_prefers_sceptic_when_greed_has_no_draws(library):
    rat = library.get_numeric_id("rat")
    state = _state(
        p0=_player(PlayerSide.PLAYER_1, hand=(rat,) * 4, deck=(), mana=0),
        p1=_player(PlayerSide.PLAYER_2, hp=30),
        phase=TurnPhase.START_OF_TURN,
        turn=26,
        pending_roguelike_event_turn=26,
    )
    assert (
        choose_roguelike_event_for_ai(state, 0, library)
        == SHARP_EYED_SCEPTIC
    )


def test_ai_prioritizes_next_handshake_lethal(library):
    rat = library.get_numeric_id("rat")
    state = _state(
        p0=_player(PlayerSide.PLAYER_1, hand=(), deck=(rat,) * 8, mana=5),
        p1=_player(PlayerSide.PLAYER_2, hp=5),
        phase=TurnPhase.START_OF_TURN,
        turn=26,
        pending_roguelike_event_turn=26,
    )
    scores = score_roguelike_event_choices(state, 0, library)
    assert scores[WITH_A_SLAP] > scores[CLUMSY_GREED]
    assert choose_roguelike_event_for_ai(state, 0, library) == WITH_A_SLAP


def test_ai_policy_is_reproducible_and_ignores_opponent_hidden_zones(library):
    rat = library.get_numeric_id("rat")
    base = _state(
        p0=_player(PlayerSide.PLAYER_1, hand=(rat,), deck=(rat,) * 3, mana=2),
        p1=_player(PlayerSide.PLAYER_2, hand=(), deck=(), hp=30),
        phase=TurnPhase.START_OF_TURN,
        turn=51,
        pending_roguelike_event_turn=51,
    )
    hidden_changed = replace(
        base,
        players=(
            base.players[0],
            _player(
                PlayerSide.PLAYER_2,
                hand=(rat,) * 7,
                deck=(rat,) * 12,
                hp=30,
            ),
        ),
    )
    first = choose_roguelike_event_for_ai(base, 0, library)
    assert choose_roguelike_event_for_ai(base, 0, library) == first
    assert choose_roguelike_event_for_ai(hidden_changed, 0, library) == first


def _resolve_fortunes(
    state, player_zero, player_one, library, *, event_collector=None,
):
    state = replace(
        state,
        pending_roguelike_event_turn=state.turn_number,
        pending_roguelike_event_choices=(None, None),
        pending_roguelike_event_options=(
            player_zero, player_one,
            CLUMSY_GREED if CLUMSY_GREED not in (player_zero, player_one)
            else WITH_A_SLAP,
        ),
    )
    state = resolve_roguelike_event_choice(
        state, 0, player_zero, library, event_collector=event_collector,
    )
    return resolve_roguelike_event_choice(
        state, 1, player_one, library, event_collector=event_collector,
    )


def test_offer_is_seeded_mirrored_and_limited_to_three(library):
    opened = open_roguelike_event(_state(
        phase=TurnPhase.START_OF_TURN, turn=26,
    ))
    assert len(opened.pending_roguelike_event_options) == 3
    assert len(set(opened.pending_roguelike_event_options)) == 3
    p0 = filter_state_for_player(opened.to_dict(), 0, library)
    p1 = filter_state_for_player(opened.to_dict(), 1, library)
    assert p0["roguelike_event_options"] == p1["roguelike_event_options"]
    assert [item["id"] for item in p0["roguelike_event_options"]] == [
        choice for choice in ROGUELIKE_EVENT_CHOICES
        if choice in opened.pending_roguelike_event_options
    ]


def test_skeleton_crew_offer_exposes_normal_reward_card_metadata(library):
    pending = _state(
        phase=TurnPhase.START_OF_TURN,
        turn=26,
        pending_roguelike_event_turn=26,
        pending_roguelike_event_options=(
            SKELETON_CREW, CLUMSY_GREED, WITH_A_SLAP,
        ),
    )

    filtered = filter_state_for_player(pending.to_dict(), 0, library)
    skeleton = next(
        option for option in filtered["roguelike_event_options"]
        if option["id"] == SKELETON_CREW
    )

    assert skeleton["reward_cards"] == (
        {"card_id": "reanimated_bones", "count": 2},
    )


def test_sharp_eyed_offer_exposes_prohibition_card_metadata(library):
    pending = _state(
        phase=TurnPhase.START_OF_TURN,
        turn=26,
        pending_roguelike_event_turn=26,
        pending_roguelike_event_options=(
            SHARP_EYED_SCEPTIC, CLUMSY_GREED, WITH_A_SLAP,
        ),
    )

    filtered = filter_state_for_player(pending.to_dict(), 0, library)
    sceptic = next(
        option for option in filtered["roguelike_event_options"]
        if option["id"] == SHARP_EYED_SCEPTIC
    )

    assert sceptic["reward_cards"] == (
        {"card_id": "prohibition", "count": 1},
    )


def test_grave_expectations_returns_two_then_deals_ceiling_quarter_hp(library):
    rat = library.get_numeric_id("rat")
    prohibition = library.get_numeric_id("prohibition")
    p0 = replace(
        _player(PlayerSide.PLAYER_1, hp=21),
        grave=(rat, prohibition, rat),
    )
    resolved = _resolve_fortunes(
        _state(p0=p0, phase=TurnPhase.START_OF_TURN, turn=26),
        GRAVE_EXPECTATIONS, SHARP_EYED_SCEPTIC, library,
    )
    assert resolved.players[0].hp == 15
    assert len(resolved.players[0].hand) == 2
    assert len(resolved.players[0].grave) == 1


def test_generated_and_grave_overdraws_keep_their_non_deck_origins(library):
    rat = library.get_numeric_id("rat")
    prohibition = library.get_numeric_id("prohibition")
    full_hand = (rat,) * MAX_HAND_SIZE

    sharp_stream = EventStream()
    sharp = _resolve_fortunes(
        _state(
            p0=_player(PlayerSide.PLAYER_1, hand=full_hand, deck=(rat,)),
            phase=TurnPhase.START_OF_TURN,
            turn=26,
        ),
        SHARP_EYED_SCEPTIC, WITH_A_SLAP, library,
        event_collector=sharp_stream,
    )
    sharp_burn = next(
        event for event in sharp_stream.events
        if event.type == EVT_CARD_BURNED
        and event.payload.get("source") == "roguelike_event"
        and event.payload.get("player_idx") == 0
    )
    assert sharp.players[0].deck == (rat,)
    assert sharp_burn.payload.get("card_numeric_id") == prohibition
    assert sharp_burn.payload.get("from_zone") == "generated"

    grave_stream = EventStream()
    grave_player = replace(
        _player(PlayerSide.PLAYER_1, hand=full_hand, deck=(rat,)),
        grave=(rat, prohibition),
    )
    grave = _resolve_fortunes(
        _state(
            p0=grave_player,
            phase=TurnPhase.START_OF_TURN,
            turn=26,
        ),
        GRAVE_EXPECTATIONS, WITH_A_SLAP, library,
        event_collector=grave_stream,
    )
    grave_burns = [
        event for event in grave_stream.events
        if event.type == EVT_CARD_BURNED
        and event.payload.get("source") == "grave_expectations"
        and event.payload.get("player_idx") == 0
    ]
    assert grave.players[0].deck == (rat,)
    assert grave.players[0].grave == ()
    assert len(grave_burns) == 2
    assert all(event.payload.get("from_zone") == "grave"
               for event in grave_burns)
    assert all(isinstance(event.payload.get("source_index"), int)
               for event in grave_burns)


def test_pocket_change_and_spring_cleaning(library):
    rat = library.get_numeric_id("rat")
    prohibition = library.get_numeric_id("prohibition")
    pocket = _resolve_fortunes(
        _state(
            p0=_player(PlayerSide.PLAYER_1, mana=2),
            p1=_player(PlayerSide.PLAYER_2, deck=(rat, prohibition)),
            phase=TurnPhase.START_OF_TURN,
            turn=26,
        ),
        POCKET_CHANGE, SHARP_EYED_SCEPTIC, library,
    )
    assert pocket.players[0].current_mana == 5
    assert len(pocket.players[1].hand) == 2  # own Sharp reward + opponent draw
    assert len(pocket.players[1].deck) == 1

    spring = _resolve_fortunes(
        _state(
            p0=_player(
                PlayerSide.PLAYER_1,
                hand=(rat, prohibition),
                deck=(rat, prohibition, rat, prohibition),
            ),
            phase=TurnPhase.START_OF_TURN,
            turn=26,
        ),
        SPRING_CLEANING, WITH_A_SLAP, library,
    )
    assert len(spring.players[0].hand) == 3
    assert len(spring.players[0].exhaust) == 2
    assert len(spring.players[0].grave) == 0
    assert len(spring.players[0].deck) == 1


def test_pocket_change_last_card_overdraw_is_deck_sourced(library):
    rat = library.get_numeric_id("rat")
    stream = EventStream()
    resolved = _resolve_fortunes(
        _state(
            p0=_player(PlayerSide.PLAYER_1, mana=2),
            p1=_player(
                PlayerSide.PLAYER_2,
                hand=(rat,) * MAX_HAND_SIZE,
                deck=(rat,),
            ),
            phase=TurnPhase.START_OF_TURN,
            turn=26,
        ),
        POCKET_CHANGE, WITH_A_SLAP, library,
        event_collector=stream,
    )
    pocket_burn = next(
        event for event in stream.events
        if event.type == EVT_CARD_BURNED
        and event.payload.get("source") == "pocket_change"
        and event.payload.get("player_idx") == 1
    )
    assert resolved.players[1].deck == ()
    assert pocket_burn.payload.get("from_zone") == "deck"


def test_spring_cleaning_exhausts_without_discard_effects_or_react(
    library,
):
    stash_id = library.get_numeric_id("dark_matter_stash")
    rat_id = library.get_numeric_id("rat")
    mage_id = library.get_numeric_id("shadow_blaster")
    mage_card = library.get_by_id(mage_id)
    mage = MinionInstance(
        instance_id=1,
        card_numeric_id=mage_id,
        owner=PlayerSide.PLAYER_1,
        position=(0, 0),
        current_health=mage_card.health,
    )
    stream = EventStream()
    resolved = _resolve_fortunes(
        _state(
            p0=_player(
                PlayerSide.PLAYER_1,
                hand=(stash_id,),
                deck=(rat_id, rat_id, rat_id),
            ),
            phase=TurnPhase.START_OF_TURN,
            turn=26,
            board=Board.empty().place(0, 0, mage.instance_id),
            minions=(mage,),
            next_minion_id=2,
        ),
        SPRING_CLEANING, WITH_A_SLAP, library,
        event_collector=stream,
    )
    assert resolved.players[0].dark_matter == 0
    assert resolved.players[0].grave == ()
    assert resolved.players[0].exhaust == (stash_id,)
    assert any(
        event.type == "card_burned"
        and event.payload.get("source") == "spring_cleaning"
        for event in stream.events
    )
    assert not any(event.type == "card_discarded" for event in stream.events)
    assert resolved.react_stack == ()
    assert resolved.react_player_idx is None
    assert EVT_REACT_WINDOW_OPENED not in [event.type for event in stream.events]


def test_spring_cleaning_batches_only_the_initial_hand_exhaust(library):
    """The client may batch hand cards, but never a later overdraw burn.

    Starting with a maximum-size hand makes Spring Cleaning draw one more
    card than can fit.  Both kinds of burn share the same source, so the
    explicit ``from_zone=hand`` marker is the required animation boundary.
    """
    rat_id = library.get_numeric_id("rat")
    prohibition_id = library.get_numeric_id("prohibition")
    original_hand = tuple(
        rat_id if index % 2 == 0 else prohibition_id
        for index in range(MAX_HAND_SIZE)
    )
    stream = EventStream()
    _resolve_fortunes(
        _state(
            p0=_player(
                PlayerSide.PLAYER_1,
                hand=original_hand,
                deck=(rat_id,) * (MAX_HAND_SIZE + 1),
            ),
            phase=TurnPhase.START_OF_TURN,
            turn=26,
        ),
        SPRING_CLEANING,
        WITH_A_SLAP,
        library,
        event_collector=stream,
    )
    spring_cards = [
        event for event in stream.events
        if event.payload.get("player_idx") == 0
        and event.payload.get("source") == "spring_cleaning"
        and event.type in (EVT_CARD_BURNED, EVT_CARD_DRAWN)
    ]
    hand_exhaust = spring_cards[0]
    replacement_draws = spring_cards[1:1 + MAX_HAND_SIZE]
    overdraw = spring_cards[-1]

    assert len(spring_cards) == MAX_HAND_SIZE + 2
    assert hand_exhaust.type == EVT_CARD_BURNED
    assert hand_exhaust.payload.get("card_numeric_ids") == list(original_hand)
    assert hand_exhaust.payload.get("card_count") == MAX_HAND_SIZE
    assert hand_exhaust.payload.get("from_zone") == "hand"
    assert hand_exhaust.payload.get("destination") == "exhaust"
    assert "card_numeric_id" not in hand_exhaust.payload
    assert all(event.type == EVT_CARD_DRAWN for event in replacement_draws)
    assert all(event.payload.get("from_zone") == "deck"
               for event in replacement_draws)
    assert overdraw.type == EVT_CARD_BURNED
    assert overdraw.payload.get("card_numeric_id") == rat_id
    assert "card_numeric_ids" not in overdraw.payload
    assert overdraw.payload.get("from_zone") == "deck"

    opponent_events = filter_engine_events_for_viewer(
        stream.events, 1, library=library,
    )
    opponent_batch = next(
        event for event in opponent_events
        if event.type == EVT_CARD_BURNED
        and event.payload.get("from_zone") == "hand"
        and event.payload.get("source") == "spring_cleaning"
    )
    assert opponent_batch.payload.get("card_numeric_ids") == list(original_hand)


@pytest.mark.parametrize("spring_idx", (0, 1))
def test_pocket_change_cross_draw_settles_after_spring_cleaning_snapshot(
    library, spring_idx,
):
    rat = library.get_numeric_id("rat")
    prohibition = library.get_numeric_id("prohibition")
    spring_player = _player(
        PlayerSide.PLAYER_1 if spring_idx == 0 else PlayerSide.PLAYER_2,
        hand=(rat, prohibition),
        deck=(rat, prohibition, rat, prohibition, rat),
    )
    pocket_player = _player(
        PlayerSide.PLAYER_2 if spring_idx == 0 else PlayerSide.PLAYER_1,
        mana=1,
    )
    players = (
        (spring_player, pocket_player)
        if spring_idx == 0 else (pocket_player, spring_player)
    )
    choices = (
        (SPRING_CLEANING, POCKET_CHANGE)
        if spring_idx == 0 else (POCKET_CHANGE, SPRING_CLEANING)
    )
    resolved = _resolve_fortunes(
        _state(
            p0=players[0], p1=players[1],
            phase=TurnPhase.START_OF_TURN, turn=26,
        ),
        choices[0], choices[1], library,
    )
    spring = resolved.players[spring_idx]
    pocket = resolved.players[1 - spring_idx]
    # Spring sees only its original two-card hand: discard 2, draw 3.
    # Pocket's opponent draw lands after both owner-local fortunes: draw 1.
    assert len(spring.exhaust) == 2
    assert len(spring.grave) == 0
    assert len(spring.hand) == 4
    assert len(spring.deck) == 1
    assert pocket.current_mana == 4


def test_skeleton_crew_summons_two_reward_only_bones(library):
    resolved = _resolve_fortunes(
        _state(phase=TurnPhase.START_OF_TURN, turn=26),
        SKELETON_CREW, WITH_A_SLAP, library,
    )
    bones_id = library.get_numeric_id("reanimated_bones")
    bones = [m for m in resolved.minions if m.card_numeric_id == bones_id]
    assert len(bones) == 2
    assert all(m.owner == PlayerSide.PLAYER_1 for m in bones)
    assert len({m.position for m in bones}) == 2
    assert library.get_by_id(bones_id).deckable is False
    assert any("not deckable" in error for error in library.validate_deck(
        (bones_id,) * 40
    ))


def test_compound_interest_pays_one_on_next_three_turn_starts(library):
    state = _resolve_fortunes(
        _state(
            p0=_player(PlayerSide.PLAYER_1, mana=0, deck=()),
            phase=TurnPhase.START_OF_TURN,
            turn=26,
        ),
        COMPOUND_INTEREST, WITH_A_SLAP, library,
    )
    assert state.compound_interest_turns == (3, 0)
    mana_values = []
    for _ in range(3):
        state = apply_new_turn_resources(state)
        mana_values.append(state.players[0].current_mana)
    # First resolved Fortune raises base turn income to 2; Compound Interest
    # remains an additional +1 for each of these three starts.
    assert mana_values == [3, 6, 9]
    assert state.compound_interest_turns == (0, 0)


def test_marked_cards_keeps_one_and_privately_orders_other_two(library):
    cards = tuple(library.get_numeric_id(card_id) for card_id in (
        "rat", "prohibition", "acidic_rain", "dark_matter_barrage",
    ))
    state = _resolve_fortunes(
        _state(
            p0=_player(PlayerSide.PLAYER_1, deck=cards),
            phase=TurnPhase.START_OF_TURN,
            turn=26,
        ),
        MARKED_CARDS, WITH_A_SLAP, library,
    )
    assert state.pending_marked_cards_player_idx == 0
    own = filter_state_for_player(state.to_dict(), 0, library)
    opponent = filter_state_for_player(state.to_dict(), 1, library)
    assert own["pending_marked_cards_cards"] == list(cards[:3])
    assert opponent["pending_marked_cards_cards"] == []
    assert opponent["pending_marked_cards_count"] == 3

    stream = EventStream()
    resolved = resolve_marked_cards_choice(
        state, 0, 1, (2, 0), event_collector=stream,
    )
    assert resolved.pending_marked_cards_player_idx is None
    assert resolved.players[0].hand == (cards[1],)
    assert resolved.players[0].deck == (cards[2], cards[0], cards[3])
    kept = next(
        event for event in stream.events
        if event.type == EVT_CARD_DRAWN
        and event.payload.get("source") == "marked_cards"
    )
    assert kept.payload.get("card_numeric_id") == cards[1]
    assert kept.payload.get("from_zone") == "deck"


def test_marked_cards_last_card_overdraw_is_deck_sourced(library):
    rat = library.get_numeric_id("rat")
    state = _resolve_fortunes(
        _state(
            p0=_player(
                PlayerSide.PLAYER_1,
                hand=(rat,) * MAX_HAND_SIZE,
                deck=(rat,),
            ),
            phase=TurnPhase.START_OF_TURN,
            turn=26,
        ),
        MARKED_CARDS, WITH_A_SLAP, library,
    )
    stream = EventStream()

    resolved = resolve_marked_cards_choice(
        state, 0, 0, (), event_collector=stream,
    )

    burn = next(
        event for event in stream.events
        if event.type == EVT_CARD_BURNED
        and event.payload.get("source") == "marked_cards"
    )
    assert resolved.players[0].deck == ()
    assert burn.payload.get("card_numeric_id") == rat
    assert burn.payload.get("from_zone") == "deck"


def test_uncharted_fortune_excludes_seen_and_current_offer(library):
    current = (UNCHARTED_FORTUNE, SHARP_EYED_SCEPTIC, WITH_A_SLAP)
    seen = tuple(choice for choice in ROGUELIKE_EVENT_CHOICES
                 if choice != SKELETON_CREW)
    state = _state(
        phase=TurnPhase.START_OF_TURN,
        turn=26,
        pending_roguelike_event_turn=26,
        pending_roguelike_event_options=current,
        pending_roguelike_event_choices=(None, None),
        roguelike_seen_fortunes=seen,
    )
    stream = EventStream()
    state = resolve_roguelike_event_choice(
        state, 0, UNCHARTED_FORTUNE, library, event_collector=stream,
    )
    state = resolve_roguelike_event_choice(
        state, 1, WITH_A_SLAP, library, event_collector=stream,
    )
    assert state.roguelike_event_history[0] == (
        f"{UNCHARTED_FORTUNE}:{SKELETON_CREW}",
    )
    assert SKELETON_CREW in state.roguelike_seen_fortunes
    assert len([m for m in state.minions
                if m.owner == PlayerSide.PLAYER_1]) == 2
    reveal = next(
        event for event in stream.events
        if event.type == EVT_PENDING_MODAL_RESOLVED
    )
    rolled = reveal.payload["choices"][0]
    assert rolled["choice"] == UNCHARTED_FORTUNE
    assert rolled["resolved_as"] == SKELETON_CREW
    assert rolled["resolved_option"]["name"] == "Skeleton Crew"
    assert rolled["resolved_option"]["reward_cards"] == (
        {"card_id": "reanimated_bones", "count": 2},
    )
