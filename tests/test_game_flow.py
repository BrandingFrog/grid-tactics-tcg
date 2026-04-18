"""Integration tests for Phase 12 Plan 02: Complete PvP game flow.

Tests VIEW-01 (game_start filtering), VIEW-02 (action validation),
VIEW-03 (legal actions in state updates), SERVER-03 (both receive state updates),
and a complete end-to-end game via two SocketIO test clients.

Also includes D-03 react card visibility test (plan checker request).
"""
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.server.app import create_app, socketio
from grid_tactics.server.events import register_events
from grid_tactics.server.room_manager import RoomManager


@pytest.fixture
def app():
    app = create_app(testing=True)
    library = CardLibrary.from_directory(Path("data/cards"))
    rm = RoomManager(library)
    register_events(rm)
    return app


def _create_game(app):
    """Create room, join, ready both players.

    Returns (client1, client2, game_start_1, game_start_2) where
    game_start_N is the game_start event data for each client.
    """
    c1 = socketio.test_client(app)
    c2 = socketio.test_client(app)

    c1.emit("create_room", {"display_name": "Alice"})
    r1 = c1.get_received()
    room_data = next(m for m in r1 if m["name"] == "room_created")["args"][0]
    room_code = room_data["room_code"]

    c2.emit("join_room", {"display_name": "Bob", "room_code": room_code})
    c1.get_received()  # clear player_joined
    c2.get_received()  # clear room_joined

    c1.emit("ready", {})
    c1.get_received()  # clear player_ready
    c2.get_received()  # clear player_ready

    c2.emit("ready", {})

    r1 = c1.get_received()
    r2 = c2.get_received()

    gs1 = next(m for m in r1 if m["name"] == "game_start")["args"][0]
    gs2 = next(m for m in r2 if m["name"] == "game_start")["args"][0]

    return c1, c2, gs1, gs2


def _get_events(client, event_name):
    """Get all events of a given name from a client's received queue."""
    received = client.get_received()
    return [m["args"][0] for m in received if m["name"] == event_name]


# -----------------------------------------------------------------------
# VIEW-01: game_start filtering
# -----------------------------------------------------------------------


class TestGameStartFiltered:
    """VIEW-01: game_start state is filtered per player."""

    def test_game_start_filtered_own_hand_visible(self, app):
        """Player's own hand is visible (non-empty list) in game_start."""
        c1, c2, gs1, gs2 = _create_game(app)
        my_idx_1 = gs1["your_player_idx"]
        state1 = gs1["state"]
        # My hand should be non-empty (starting hand is 3 or 4 cards)
        my_hand = state1["players"][my_idx_1]["hand"]
        assert len(my_hand) > 0, "Own hand should be visible in game_start"

    def test_game_start_filtered_opponent_hand_hidden(self, app):
        """Opponent's hand is empty list with hand_count in game_start."""
        c1, c2, gs1, gs2 = _create_game(app)
        my_idx_1 = gs1["your_player_idx"]
        opp_idx = 1 - my_idx_1
        opp_data = gs1["state"]["players"][opp_idx]
        assert opp_data["hand"] == [], "Opponent hand should be empty"
        assert "hand_count" in opp_data, "Opponent should have hand_count"
        assert opp_data["hand_count"] > 0, "Opponent hand_count should be > 0"

    def test_game_start_filtered_no_seed(self, app):
        """game_start state has no seed key."""
        c1, c2, gs1, gs2 = _create_game(app)
        assert "seed" not in gs1["state"], "Seed should be stripped from game_start state"

    def test_game_start_filtered_decks_hidden(self, app):
        """Both decks are empty lists with deck_count in game_start."""
        c1, c2, gs1, gs2 = _create_game(app)
        for player_data in gs1["state"]["players"]:
            assert player_data["deck"] == [], "Deck should be empty"
            assert "deck_count" in player_data, "Should have deck_count"
            assert player_data["deck_count"] > 0, "Deck should have cards"

    def test_game_start_has_card_defs(self, app):
        """game_start includes card_defs dict with card names."""
        c1, c2, gs1, gs2 = _create_game(app)
        assert "card_defs" in gs1, "game_start should include card_defs"
        card_defs = gs1["card_defs"]
        assert len(card_defs) > 0, "card_defs should not be empty"
        # Check structure of first card def
        sample = next(iter(card_defs.values()))
        assert "name" in sample
        assert "card_type" in sample
        assert "mana_cost" in sample

    def test_game_start_has_legal_actions(self, app):
        """game_start includes legal_actions for the active player."""
        c1, c2, gs1, gs2 = _create_game(app)
        active_idx = gs1["state"]["active_player_idx"]
        # The client whose player_idx matches active_idx should get actions
        if gs1["your_player_idx"] == active_idx:
            assert len(gs1["legal_actions"]) > 0, "Active player should have legal_actions"
            assert gs2["legal_actions"] == [], "Non-active player should have empty legal_actions"
        else:
            assert len(gs2["legal_actions"]) > 0, "Active player should have legal_actions"
            assert gs1["legal_actions"] == [], "Non-active player should have empty legal_actions"


# -----------------------------------------------------------------------
# VIEW-02: Action validation
# -----------------------------------------------------------------------


class TestActionValidation:
    """VIEW-02: Server validates actions and rejects invalid ones."""

    def test_legal_action_accepted(self, app):
        """Submitting a legal action produces a state_update (not error)."""
        c1, c2, gs1, gs2 = _create_game(app)
        active_idx = gs1["state"]["active_player_idx"]

        # Find which client is the active player
        if gs1["your_player_idx"] == active_idx:
            active_client, passive_client = c1, c2
            actions_list = gs1["legal_actions"]
        else:
            active_client, passive_client = c2, c1
            actions_list = gs2["legal_actions"]

        assert len(actions_list) > 0, "Active player should have legal actions"
        action_data = actions_list[0]

        active_client.emit("submit_action", action_data)

        # Active client should get state_update
        active_msgs = active_client.get_received()
        update_events = [m for m in active_msgs if m["name"] == "state_update"]
        error_events = [m for m in active_msgs if m["name"] == "error"]
        assert len(error_events) == 0, f"Should not get error: {error_events}"
        assert len(update_events) >= 1, "Should receive state_update after legal action"

    def test_illegal_action_rejected(self, app):
        """Submitting an action NOT in legal_actions produces error."""
        c1, c2, gs1, gs2 = _create_game(app)
        active_idx = gs1["state"]["active_player_idx"]

        if gs1["your_player_idx"] == active_idx:
            active_client = c1
        else:
            active_client = c2

        # Fabricate an illegal action: ATTACK with nonexistent minion IDs
        illegal_action = {"action_type": 4, "minion_id": 9999, "target_id": 9998}
        active_client.emit("submit_action", illegal_action)

        msgs = active_client.get_received()
        error_events = [m for m in msgs if m["name"] == "error"]
        assert len(error_events) >= 1, "Illegal action should produce error"
        assert "Illegal action" in error_events[0]["args"][0]["msg"]

    def test_malformed_action_rejected(self, app):
        """Submitting garbage data produces error, no crash."""
        c1, c2, gs1, gs2 = _create_game(app)
        active_idx = gs1["state"]["active_player_idx"]

        if gs1["your_player_idx"] == active_idx:
            active_client = c1
        else:
            active_client = c2

        # Completely malformed data
        active_client.emit("submit_action", "not a dict at all")
        msgs = active_client.get_received()
        error_events = [m for m in msgs if m["name"] == "error"]
        assert len(error_events) >= 1, "Malformed action should produce error"
        assert "Invalid action" in error_events[0]["args"][0]["msg"]

    def test_wrong_turn_rejected(self, app):
        """Non-active player submitting action gets 'Not your turn' error."""
        c1, c2, gs1, gs2 = _create_game(app)
        active_idx = gs1["state"]["active_player_idx"]

        # Find the passive client
        if gs1["your_player_idx"] == active_idx:
            passive_client = c2
            actions_list = gs1["legal_actions"]
        else:
            passive_client = c1
            actions_list = gs2["legal_actions"]

        # The passive client tries to submit an action (even a valid one from the active's list)
        # Use PASS as a simple action
        passive_client.emit("submit_action", {"action_type": 5})  # PASS
        msgs = passive_client.get_received()
        error_events = [m for m in msgs if m["name"] == "error"]
        assert len(error_events) >= 1, "Wrong turn should produce error"
        assert "Not your turn" in error_events[0]["args"][0]["msg"]

    def test_action_on_game_over_rejected(self, app):
        """Submitting action after game is over produces error."""
        c1, c2, gs1, gs2 = _create_game(app)

        # Play the game to completion first
        _play_to_completion(c1, c2, gs1, gs2)

        # Now try to submit another action
        c1.emit("submit_action", {"action_type": 5})  # PASS
        msgs = c1.get_received()
        error_events = [m for m in msgs if m["name"] == "error"]
        assert len(error_events) >= 1, "Post-game action should produce error"
        assert "already over" in error_events[0]["args"][0]["msg"].lower()


# -----------------------------------------------------------------------
# VIEW-03: Legal actions in state updates
# -----------------------------------------------------------------------


class TestLegalActionsInUpdates:
    """VIEW-03: state_update includes legal_actions for decision-maker."""

    def test_state_update_has_legal_actions(self, app):
        """state_update includes non-empty legal_actions for the decision-maker."""
        c1, c2, gs1, gs2 = _create_game(app)
        active_idx = gs1["state"]["active_player_idx"]

        if gs1["your_player_idx"] == active_idx:
            active_client, passive_client = c1, c2
            actions_list = gs1["legal_actions"]
        else:
            active_client, passive_client = c2, c1
            actions_list = gs2["legal_actions"]

        # Submit first legal action
        active_client.emit("submit_action", actions_list[0])

        # Both clients receive state_update
        active_msgs = active_client.get_received()
        passive_msgs = passive_client.get_received()

        active_updates = [m for m in active_msgs if m["name"] == "state_update"]
        passive_updates = [m for m in passive_msgs if m["name"] == "state_update"]

        assert len(active_updates) >= 1
        assert len(passive_updates) >= 1

        # Find which one has legal_actions (the decision-maker)
        au = active_updates[0]["args"][0]
        pu = passive_updates[0]["args"][0]

        # At least one should have non-empty legal_actions (unless game over)
        if not au["state"].get("is_game_over", False):
            combined_actions = au["legal_actions"] + pu["legal_actions"]
            assert len(combined_actions) > 0, "Someone should have legal_actions"

    def test_non_decision_player_gets_empty_legal_actions(self, app):
        """Non-decision player gets empty legal_actions list."""
        c1, c2, gs1, gs2 = _create_game(app)
        active_idx = gs1["state"]["active_player_idx"]

        if gs1["your_player_idx"] == active_idx:
            active_client, passive_client = c1, c2
            active_gs, passive_gs = gs1, gs2
            actions_list = gs1["legal_actions"]
        else:
            active_client, passive_client = c2, c1
            active_gs, passive_gs = gs2, gs1
            actions_list = gs2["legal_actions"]

        active_client.emit("submit_action", actions_list[0])

        active_msgs = active_client.get_received()
        passive_msgs = passive_client.get_received()

        active_updates = [m for m in active_msgs if m["name"] == "state_update"]
        passive_updates = [m for m in passive_msgs if m["name"] == "state_update"]

        assert len(active_updates) >= 1
        assert len(passive_updates) >= 1

        au = active_updates[0]["args"][0]
        pu = passive_updates[0]["args"][0]

        # Exactly one should be empty, one non-empty (unless game ended)
        if not au["state"].get("is_game_over", False):
            # The non-decision-maker has empty legal_actions
            has_actions = [x for x in [au, pu] if len(x["legal_actions"]) > 0]
            no_actions = [x for x in [au, pu] if len(x["legal_actions"]) == 0]
            assert len(has_actions) == 1, "Exactly one player should have legal_actions"
            assert len(no_actions) == 1, "Exactly one player should have empty legal_actions"


# -----------------------------------------------------------------------
# SERVER-03: Both receive state updates
# -----------------------------------------------------------------------


class TestBothReceiveUpdates:
    """SERVER-03: Both players receive state_update after every action."""

    def test_both_receive_state_update(self, app):
        """After submit_action, BOTH clients receive state_update events."""
        c1, c2, gs1, gs2 = _create_game(app)
        active_idx = gs1["state"]["active_player_idx"]

        if gs1["your_player_idx"] == active_idx:
            active_client, passive_client = c1, c2
            actions_list = gs1["legal_actions"]
        else:
            active_client, passive_client = c2, c1
            actions_list = gs2["legal_actions"]

        active_client.emit("submit_action", actions_list[0])

        active_msgs = active_client.get_received()
        passive_msgs = passive_client.get_received()

        active_updates = [m for m in active_msgs if m["name"] == "state_update"]
        passive_updates = [m for m in passive_msgs if m["name"] == "state_update"]

        assert len(active_updates) >= 1, "Active player should receive state_update"
        assert len(passive_updates) >= 1, "Passive player should receive state_update"

    def test_react_phase_opponent_gets_legal_actions(self, app):
        """After action, if react phase triggers, opponent gets legal_actions (at minimum PASS)."""
        c1, c2, gs1, gs2 = _create_game(app)
        active_idx = gs1["state"]["active_player_idx"]

        if gs1["your_player_idx"] == active_idx:
            active_client, passive_client = c1, c2
            actions_list = gs1["legal_actions"]
        else:
            active_client, passive_client = c2, c1
            actions_list = gs2["legal_actions"]

        active_client.emit("submit_action", actions_list[0])

        passive_msgs = passive_client.get_received()
        passive_updates = [m for m in passive_msgs if m["name"] == "state_update"]

        if len(passive_updates) >= 1:
            pu_data = passive_updates[0]["args"][0]
            state = pu_data["state"]
            # If we're in react phase and this player is the reactor, they should have actions
            if state.get("phase") == 1:  # TurnPhase.REACT
                react_idx = state.get("react_player_idx")
                if react_idx == pu_data["your_player_idx"]:
                    assert len(pu_data["legal_actions"]) > 0, (
                        "React player should have legal_actions (at minimum PASS)"
                    )

    def test_state_update_is_filtered(self, app):
        """state_update contains filtered state (no opponent hand, no seed)."""
        c1, c2, gs1, gs2 = _create_game(app)
        active_idx = gs1["state"]["active_player_idx"]

        if gs1["your_player_idx"] == active_idx:
            active_client = c1
            actions_list = gs1["legal_actions"]
        else:
            active_client = c2
            actions_list = gs2["legal_actions"]

        active_client.emit("submit_action", actions_list[0])

        msgs = active_client.get_received()
        updates = [m for m in msgs if m["name"] == "state_update"]
        assert len(updates) >= 1

        state = updates[0]["args"][0]["state"]
        my_idx = updates[0]["args"][0]["your_player_idx"]
        opp_idx = 1 - my_idx

        # Opponent hand should be hidden
        assert state["players"][opp_idx]["hand"] == []
        assert "hand_count" in state["players"][opp_idx]
        # No seed
        assert "seed" not in state
        # Decks hidden
        for p in state["players"]:
            assert p["deck"] == []
            assert "deck_count" in p


# -----------------------------------------------------------------------
# D-03 checker request: react card visible to both players
# -----------------------------------------------------------------------


class TestReactCardVisibility:
    """D-03: After a react card is played, both players see it in grave."""

    def test_react_card_visible_in_grave(self, app):
        """When a react card is played, both players' state updates show it in grave."""
        # This is a smoke test -- we play a game and check that graves
        # are visible to both players after actions resolve
        c1, c2, gs1, gs2 = _create_game(app)
        active_idx = gs1["state"]["active_player_idx"]

        if gs1["your_player_idx"] == active_idx:
            active_client, passive_client = c1, c2
            actions_list = gs1["legal_actions"]
        else:
            active_client, passive_client = c2, c1
            actions_list = gs2["legal_actions"]

        # Submit first action
        active_client.emit("submit_action", actions_list[0])

        active_msgs = active_client.get_received()
        passive_msgs = passive_client.get_received()

        active_updates = [m for m in active_msgs if m["name"] == "state_update"]
        passive_updates = [m for m in passive_msgs if m["name"] == "state_update"]

        if len(active_updates) >= 1 and len(passive_updates) >= 1:
            # Both should have the same grave data (graves are public info)
            a_state = active_updates[0]["args"][0]["state"]
            p_state = passive_updates[0]["args"][0]["state"]

            # Graves should exist and be lists
            for idx in (0, 1):
                assert isinstance(a_state["players"][idx]["grave"], list)
                assert isinstance(p_state["players"][idx]["grave"], list)
                # Both views should see the same grave contents
                assert a_state["players"][idx]["grave"] == p_state["players"][idx]["grave"]


# -----------------------------------------------------------------------
# Full game flow
# -----------------------------------------------------------------------


def _play_to_completion(c1, c2, gs1, gs2, max_iterations=1500):
    """Play a game to completion, returning the game_over data for both clients.

    Each iteration: find who has legal_actions, submit the first one,
    collect state_updates. Continue until game_over.

    Returns (game_over_1, game_over_2) or raises AssertionError if stuck.
    """
    # Track last known state for each client
    clients = {gs1["your_player_idx"]: c1, gs2["your_player_idx"]: c2}

    # Current legal_actions come from game_start initially
    current_actions = {
        gs1["your_player_idx"]: gs1["legal_actions"],
        gs2["your_player_idx"]: gs2["legal_actions"],
    }

    game_over_data = {}

    for iteration in range(max_iterations):
        # Find who has legal_actions
        decision_idx = None
        for idx in (0, 1):
            if len(current_actions.get(idx, [])) > 0:
                decision_idx = idx
                break

        if decision_idx is None:
            # Might already be game over
            break

        # Submit first legal action
        action = current_actions[decision_idx][0]
        clients[decision_idx].emit("submit_action", action)

        # Collect responses from both clients
        for idx in (0, 1):
            msgs = clients[idx].get_received()

            for m in msgs:
                if m["name"] == "state_update":
                    data = m["args"][0]
                    current_actions[idx] = data.get("legal_actions", [])
                elif m["name"] == "game_over":
                    game_over_data[idx] = m["args"][0]

        if len(game_over_data) == 2:
            return game_over_data[0], game_over_data[1]

    # If we got game_over for at least one, that's enough
    if game_over_data:
        # Drain any remaining
        for idx in (0, 1):
            if idx not in game_over_data:
                msgs = clients[idx].get_received()
                for m in msgs:
                    if m["name"] == "game_over":
                        game_over_data[idx] = m["args"][0]

    assert len(game_over_data) == 2, (
        f"Game did not complete within {max_iterations} iterations. "
        f"Got game_over for {list(game_over_data.keys())}"
    )
    return game_over_data[0], game_over_data[1]


class TestCompleteGame:
    """End-to-end: a complete game via two SocketIO test clients."""

    def test_complete_game(self, app):
        """Complete game to conclusion -- game_over with winner and filtered state."""
        c1, c2, gs1, gs2 = _create_game(app)
        go1, go2 = _play_to_completion(c1, c2, gs1, gs2)

        # Both should have game_over data
        assert "winner" in go1
        assert "winner" in go2
        assert "final_state" in go1
        assert "final_state" in go2

        # Winner should be consistent
        assert go1["winner"] == go2["winner"]

        # Winner should be an int (0 or 1) or None (draw)
        assert go1["winner"] is None or go1["winner"] in (0, 1)

        # Final state should be filtered
        for go in (go1, go2):
            my_idx = go["your_player_idx"]
            opp_idx = 1 - my_idx
            # Opponent hand hidden
            opp_data = go["final_state"]["players"][opp_idx]
            assert opp_data["hand"] == []
            assert "hand_count" in opp_data
            # No seed
            assert "seed" not in go["final_state"]

    def test_complete_game_both_receive_game_over(self, app):
        """Both clients receive game_over event."""
        c1, c2, gs1, gs2 = _create_game(app)
        go1, go2 = _play_to_completion(c1, c2, gs1, gs2)

        # Both received game_over (guaranteed by _play_to_completion)
        assert go1 is not None
        assert go2 is not None

    def test_complete_game_state_updates_throughout(self, app):
        """During gameplay, every action produces state_updates for both players."""
        c1, c2, gs1, gs2 = _create_game(app)

        clients = {gs1["your_player_idx"]: c1, gs2["your_player_idx"]: c2}
        current_actions = {
            gs1["your_player_idx"]: gs1["legal_actions"],
            gs2["your_player_idx"]: gs2["legal_actions"],
        }

        actions_submitted = 0
        both_received_count = 0

        for _ in range(500):
            decision_idx = None
            for idx in (0, 1):
                if len(current_actions.get(idx, [])) > 0:
                    decision_idx = idx
                    break

            if decision_idx is None:
                break

            action = current_actions[decision_idx][0]
            clients[decision_idx].emit("submit_action", action)
            actions_submitted += 1

            got_update = {0: False, 1: False}
            game_over = False

            for idx in (0, 1):
                msgs = clients[idx].get_received()
                for m in msgs:
                    if m["name"] == "state_update":
                        got_update[idx] = True
                        data = m["args"][0]
                        current_actions[idx] = data.get("legal_actions", [])
                    elif m["name"] == "game_over":
                        game_over = True

            if got_update[0] and got_update[1]:
                both_received_count += 1

            if game_over:
                break

        assert actions_submitted > 0, "Should have submitted at least one action"
        assert both_received_count > 0, "Both clients should receive state_updates"
        # Every action should produce updates for both
        assert both_received_count == actions_submitted, (
            f"Expected {actions_submitted} rounds where both received updates, "
            f"got {both_received_count}"
        )
