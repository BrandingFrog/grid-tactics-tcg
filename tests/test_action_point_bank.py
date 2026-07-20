"""Active action-bank v5 and Fortune-ante regressions."""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.action_resolver import resolve_action
from grid_tactics.actions import draw_action, pass_action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
from grid_tactics.engine_events import EVT_ACTION_POINTS_CHANGE, EventStream
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.react_stack import apply_new_turn_resources
from grid_tactics.roguelike_events import (
    WITH_A_SLAP,
    resolve_roguelike_event_choice,
)
from grid_tactics.server.view_filter import filter_state_for_player
from grid_tactics.server.sandbox_session import SandboxSession


@pytest.fixture(autouse=True)
def action_bank_rules(monkeypatch):
    monkeypatch.setenv("GT_MANUAL_DRAW", "1")


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _game(library: CardLibrary) -> GameState:
    rat = library.get_numeric_id("rat")
    state, _ = GameState.new_game(91, (rat,) * 40, (rat,) * 40)
    return state


def _drain_to_action(state: GameState, library: CardLibrary) -> GameState:
    for _ in range(100):
        if state.phase == TurnPhase.ACTION:
            return state
        actions = legal_actions(state, library)
        if actions:
            action = next(
                (candidate for candidate in actions
                 if candidate.action_type == ActionType.PASS),
                actions[0],
            )
            state = resolve_action(state, action, library)
            continue
        if state.phase == TurnPhase.START_OF_TURN:
            from grid_tactics.react_stack import enter_start_of_turn
            state = enter_start_of_turn(state, library)
            continue
        if state.phase == TurnPhase.END_OF_TURN:
            from grid_tactics.react_stack import enter_end_of_turn
            state = enter_end_of_turn(state, library)
            continue
        raise AssertionError(f"Cannot drain phase {state.phase}")
    raise AssertionError("turn flow did not settle")


def test_opening_points_and_first_incoming_turn(library):
    state = _game(library)
    assert tuple(player.action_points for player in state.players) == (1, 0)

    state = resolve_action(state, draw_action(), library)
    state = _drain_to_action(state, library)
    assert state.turn_number == 2
    assert state.active_player_idx == 1
    assert tuple(player.action_points for player in state.players) == (1, 1)


def test_paid_action_spends_and_returns_to_same_player(library):
    state = _game(library)
    players = list(state.players)
    players[0] = replace(players[0], action_points=3, current_mana=10)
    state = replace(state, players=tuple(players))
    play = next(
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD
    )

    state = resolve_action(state, play, library)
    assert state.players[0].action_points == 2
    assert state.actions_spent_this_turn == 1
    state = _drain_to_action(state, library)

    assert state.turn_number == 1
    assert state.active_player_idx == 0
    assert state.players[0].action_points == 2
    action_types = {action.action_type for action in legal_actions(state, library)}
    assert ActionType.DRAW not in action_types
    assert ActionType.PASS in action_types


def test_magic_costs_one_action_point(library):
    state = _game(library)
    rain = library.get_numeric_id("acidic_rain")
    players = list(state.players)
    players[0] = replace(
        players[0], hand=(rain,), current_mana=10, action_points=2,
    )
    state = replace(state, players=tuple(players))
    play = next(
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD
    )

    state = resolve_action(state, play, library)
    assert state.players[0].action_points == 1
    assert not state.magic_free_action_pending
    assert not state.magic_cast_this_turn
    state = _drain_to_action(state, library)
    assert state.turn_number == 1
    assert state.active_player_idx == 0


def test_rest_banks_points_draws_one_and_ends(library):
    state = _game(library)
    rat = library.get_numeric_id("rat")
    players = list(state.players)
    players[0] = replace(
        players[0],
        action_points=3,
        current_mana=1,
        hand=(),
        deck=(rat,) * 8,
    )
    state = replace(
        state,
        players=tuple(players),
        # Fortune history no longer changes REST or turn income.
        roguelike_event_history=(("a", "b", "c"), ("d", "e", "f")),
    )
    assert state.fortune_ante == 1
    assert state.rest_draw_count == 1
    assert state.automatic_turn_draw_count == 0
    actions = legal_actions(state, library)
    assert draw_action() in actions and pass_action() not in actions

    state = resolve_action(state, draw_action(), library)
    assert state.players[0].action_points == 3
    assert state.players[0].current_mana == 2
    assert len(state.players[0].hand) == 1
    assert state.consecutive_passes == 1
    state = _drain_to_action(state, library)

    assert state.turn_number == 2
    assert state.players[0].action_points == 3


def test_pass_is_free_no_effect_and_declines_handshake(library):
    state = _game(library)
    players = list(state.players)
    players[0] = replace(players[0], action_points=3)
    before = players[0]
    state = replace(
        state,
        players=tuple(players),
        consecutive_passes=1,
        actions_spent_this_turn=1,
    )

    state = resolve_action(state, pass_action(), library)
    assert state.players[0].action_points == 3
    assert state.players[0].current_mana == before.current_mana
    assert state.players[0].hand == before.hand
    assert state.consecutive_passes == 0
    assert not state.handshake_pending


def test_pass_after_action_banks_every_remaining_point(library):
    state = _game(library)
    players = list(state.players)
    players[0] = replace(players[0], action_points=3, current_mana=10)
    state = replace(state, players=tuple(players))
    play = next(
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD
    )

    state = resolve_action(state, play, library)
    state = _drain_to_action(state, library)
    assert state.turn_number == 1
    assert state.players[0].action_points == 2
    assert draw_action() not in legal_actions(state, library)
    assert pass_action() in legal_actions(state, library)

    state = resolve_action(state, pass_action(), library)
    state = _drain_to_action(state, library)
    assert state.turn_number == 2
    assert state.players[0].action_points == 2


def test_spending_final_point_auto_passes_after_action_chain(library):
    state = _game(library)
    players = list(state.players)
    players[0] = replace(players[0], action_points=1, current_mana=10)
    state = replace(state, players=tuple(players))
    play = next(
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD
    )

    state = resolve_action(state, play, library)
    assert state.players[0].action_points == 0
    state = _drain_to_action(state, library)

    # No empty-bank decision is exposed: once the action/react chain closes,
    # Decay runs and the opponent receives the next turn automatically.
    assert state.turn_number == 2
    assert state.active_player_idx == 1
    assert state.players[0].action_points == 0


def test_restored_empty_bank_can_only_pass_without_reward(library):
    state = _game(library)
    players = list(state.players)
    players[0] = replace(
        players[0], action_points=0, current_mana=2, hand=(),
    )
    state = replace(state, players=tuple(players))

    assert legal_actions(state, library) == (pass_action(),)
    state = resolve_action(state, pass_action(), library)
    assert state.players[0].action_points == 0
    assert state.players[0].current_mana == 2
    assert state.players[0].hand == ()


@pytest.mark.parametrize(
    "continuation_type",
    [ActionType.ATTACK, ActionType.DECLINE_POST_MOVE_ATTACK],
)
def test_final_point_move_continuation_is_free_then_auto_passes(
    library, continuation_type,
):
    state = _game(library)
    rat = library.get_numeric_id("rat")
    giant = library.get_numeric_id("giant_rat")
    mover = MinionInstance(
        instance_id=0,
        card_numeric_id=rat,
        owner=PlayerSide.PLAYER_1,
        position=(0, 0),
        current_health=library.get_by_id(rat).health,
    )
    target = MinionInstance(
        instance_id=1,
        card_numeric_id=giant,
        owner=PlayerSide.PLAYER_2,
        position=(2, 0),
        current_health=library.get_by_id(giant).health,
    )
    board = Board.empty().place(0, 0, 0).place(2, 0, 1)
    players = list(state.players)
    players[0] = replace(players[0], action_points=1)
    state = replace(
        state,
        board=board,
        minions=(mover, target),
        next_minion_id=2,
        players=tuple(players),
    )
    move = next(
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.MOVE and action.position == (1, 0)
    )

    state = resolve_action(state, move, library)
    assert state.players[0].action_points == 0
    state = _drain_to_action(state, library)
    assert state.turn_number == 1
    continuation = next(
        action for action in legal_actions(state, library)
        if action.action_type == continuation_type
    )
    state = resolve_action(state, continuation, library)
    state = _drain_to_action(state, library)

    assert state.turn_number == 2
    assert state.players[0].action_points == 0


def test_point_gain_banks_and_caps(library):
    state = _game(library)
    for points, expected in ((0, 1), (1, 2), (2, 3), (3, 3)):
        players = list(state.players)
        players[0] = replace(players[0], action_points=points)
        candidate = replace(state, players=tuple(players), turn_number=3)
        candidate = apply_new_turn_resources(candidate)
        assert candidate.players[0].action_points == expected


def test_point_spend_and_turn_gain_emit_live_hud_events(library):
    state = _game(library)
    players = list(state.players)
    players[0] = replace(players[0], action_points=2, current_mana=10)
    state = replace(state, players=tuple(players))
    play = next(
        action for action in legal_actions(state, library)
        if action.action_type == ActionType.PLAY_CARD
    )

    spend_stream = EventStream()
    state = resolve_action(
        state, play, library, event_collector=spend_stream,
    )
    spend_events = [
        event for event in spend_stream.events
        if event.type == EVT_ACTION_POINTS_CHANGE
    ]
    assert [event.payload for event in spend_events] == [{
        "player_idx": 0,
        "prev": 2,
        "new": 1,
        "delta": -1,
        "cause": "action_spent",
    }]

    players = list(state.players)
    players[0] = replace(players[0], action_points=1)
    state = replace(state, players=tuple(players), turn_number=3)
    gain_stream = EventStream()
    state = apply_new_turn_resources(state, event_collector=gain_stream)
    gain_events = [
        event for event in gain_stream.events
        if event.type == EVT_ACTION_POINTS_CHANGE
    ]
    assert [event.payload for event in gain_events] == [{
        "player_idx": 0,
        "prev": 1,
        "new": 2,
        "delta": 1,
        "cause": "turn_start",
    }]


def test_rest_and_pass_never_emit_point_spend(library):
    state = _game(library)
    rest_stream = EventStream()
    resolve_action(
        state, draw_action(), library, event_collector=rest_stream,
    )
    assert all(
        event.type != EVT_ACTION_POINTS_CHANGE
        for event in rest_stream.events
    )

    pass_stream = EventStream()
    pass_state = replace(state, actions_spent_this_turn=1)
    resolve_action(
        pass_state, pass_action(), library, event_collector=pass_stream,
    )
    assert all(
        event.type != EVT_ACTION_POINTS_CHANGE
        for event in pass_stream.events
    )


def test_legacy_opening_save_does_not_preload_inactive_player(library):
    opening = _game(library).to_dict()
    for player in opening["players"]:
        player.pop("action_points", None)
    restored = GameState.from_dict(opening)
    assert tuple(player.action_points for player in restored.players) == (1, 0)

    later = dict(opening)
    later["turn_number"] = 2
    later["active_player_idx"] = 1
    restored_later = GameState.from_dict(later)
    assert tuple(
        player.action_points for player in restored_later.players
    ) == (1, 1)


def test_sandbox_matches_opening_bank_and_resets_turn_local_flags(library):
    sandbox = SandboxSession(library, "action-bank-test")
    assert tuple(
        player.action_points for player in sandbox.state.players
    ) == (1, 0)

    sandbox._state = replace(
        sandbox.state,
        actions_spent_this_turn=2,
        turn_end_requested=True,
        magic_free_action_pending=True,
        magic_cast_this_turn=True,
    )
    sandbox.set_active_player(1)
    assert sandbox.state.active_player_idx == 1
    assert sandbox.state.active_player.action_points == 1
    assert sandbox.state.actions_spent_this_turn == 0
    assert not sandbox.state.turn_end_requested
    assert not sandbox.state.magic_free_action_pending
    assert not sandbox.state.magic_cast_this_turn

    events = sandbox.apply_sandbox_edit(
        "set_player_field",
        {"player_idx": 1, "field": "action_points", "value": 3},
    )
    assert len(events) == 1
    assert events[0].type == EVT_ACTION_POINTS_CHANGE
    assert events[0].payload["field"] == "action_points"
    assert events[0].payload["new"] == 3


def test_turn_10_mana_increase_is_independent_from_fortune_choice(library):
    state = _game(library)
    players = list(state.players)
    players[0] = replace(players[0], current_mana=0, action_points=0)
    state = replace(
        state,
        players=tuple(players),
        phase=TurnPhase.START_OF_TURN,
        turn_number=11,
        pending_roguelike_event_turn=11,
        pending_roguelike_event_options=(WITH_A_SLAP,),
    )
    state = resolve_roguelike_event_choice(
        state, 0, WITH_A_SLAP, library,
    )
    assert state.fortune_ante == 1
    assert state.turn_mana_gain == 2
    state = resolve_roguelike_event_choice(
        state, 1, WITH_A_SLAP, library,
    )
    assert state.fortune_ante == 1
    assert state.turn_mana_gain == 2

    state = apply_new_turn_resources(state)
    assert state.players[0].current_mana == 2
    assert state.players[0].action_points == 1
    assert state.fortune_ante == 1
    assert state.turn_mana_gain == 2


def test_serialization_and_views_keep_public_bank_and_ante(library):
    state = _game(library)
    players = (
        replace(state.players[0], action_points=3),
        replace(state.players[1], action_points=2),
    )
    state = replace(
        state,
        players=players,
        actions_spent_this_turn=1,
        roguelike_event_history=(("a",), ("b",)),
    )
    restored = GameState.from_dict(state.to_dict())
    assert tuple(player.action_points for player in restored.players) == (3, 2)
    assert restored.actions_spent_this_turn == 1
    assert restored.fortune_ante == 1
    assert restored.rest_draw_count == 1
    assert restored.turn_mana_gain == 1

    filtered = filter_state_for_player(restored.to_dict(), 0, library)
    assert [player["action_points"] for player in filtered["players"]] == [3, 2]
    assert filtered["fortune_ante"] == 1
    assert filtered["rest_draw_count"] == 1
    assert filtered["turn_mana_gain"] == 1


def test_hud_has_three_coin_banks_and_profile_renderer():
    html = Path("src/grid_tactics/server/static/game.html").read_text(
        encoding="utf-8"
    )
    hud = Path(
        "src/grid_tactics/server/static/js/11-hud-board-hand.js"
    ).read_text(encoding="utf-8")
    action_bar = Path(
        "src/grid_tactics/server/static/js/10-modals.js"
    ).read_text(encoding="utf-8")
    render_game = Path(
        "src/grid_tactics/server/static/js/09-duel-interaction.js"
    ).read_text(encoding="utf-8")
    event_queue = Path(
        "src/grid_tactics/server/static/js/06-event-queue.js"
    ).read_text(encoding="utf-8")
    css = Path(
        "src/grid_tactics/server/static/css/zz-overrides.css"
    ).read_text(encoding="utf-8")
    socket_client = Path(
        "src/grid_tactics/server/static/vendor/socket.io-4.7.4.min.js"
    )

    for bank_id in (
        "self-action-bank", "opp-action-bank",
        "sandbox-p0-action-bank", "sandbox-p1-action-bank",
    ):
        assert f'id="{bank_id}"' in html
    assert html.count('class="action-coin"') >= 12
    assert "_actionBankMarkup" in hud
    assert "action-bank-tooltip" in hud
    assert ".tooltip-stats .ts-actions" in css
    assert ".ts-actions .action-bank-tooltip" in css
    assert ".ts-actions .action-coin" in css
    assert "display: inline-flex !important" in css
    assert "margin: 0 !important" in css
    assert "end your turn with no effect" in action_bar
    assert "showPlayerPreview(activePlayerPreviewIdx)" in render_game
    assert "payload.source === 'rest'" in event_queue
    assert 'case "action_points_change"' in event_queue
    assert "showPlayerPreview(activePlayerPreviewIdx)" in event_queue
    assert '/static/vendor/socket.io-4.7.4.min.js' in html
    assert "cdn.socket.io" not in html
    assert socket_client.read_text(encoding="utf-8").startswith("/*!\n * Socket.IO v4.7.4")
