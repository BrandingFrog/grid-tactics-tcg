"""Mandatory tutoring (user-decided 2026-07-03).

When a tutor/pick modal opens WITH matches, the player MUST pick:

  1. legal_actions: DECLINE_TUTOR is NOT enumerated while
     ``pending_tutor_matches`` is non-empty — only TUTOR_SELECT slots.
  2. action_resolver: DECLINE_TUTOR raises ValueError while matches
     remain (runtime backstop mirroring the legal-actions mask).
  3. Zero matches (defensive state — ``_enter_pending_tutor`` never
     enters pending with zero matches, it auto-resolves): DECLINE_TUTOR
     is the ONLY legal action and still resolves cleanly.
  4. A full hand does NOT exempt the pick: the tutored card
     overdraw-burns to the Exhaust Pile revealed (existing overdraw
     rule; EVT_CARD_BURNED with source="tutor").

Scope: the pending_tutor flow only (Diodebots, Tree Wyrm react, To The
Ratmobile). Conjure / revive / death-pick decline semantics are
unchanged by design — Ratchanter's conjure enters the SAME pending_tutor
state with ``pending_tutor_is_conjure=True`` and its DECLINE_TUTOR
deck-pick decline stays legal (regression-tested below).
"""

from pathlib import Path

import pytest

from grid_tactics.actions import (
    Action,
    decline_tutor_action,
    pass_action,
    play_card_action,
    tutor_select_action,
)
from grid_tactics.action_resolver import resolve_action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.engine_events import EVT_CARD_BURNED, EventStream
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.player import Player
from grid_tactics.types import MAX_HAND_SIZE, STARTING_HP


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _player(side, hand=(), deck=(), mana=10):
    return Player(
        side=side,
        hp=STARTING_HP,
        current_mana=mana,
        max_mana=10,
        hand=tuple(hand),
        deck=tuple(deck),
        grave=(),
    )


def _state(p1, p2, **kwargs):
    defaults = dict(
        board=Board.empty(),
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=3,
        seed=7,
        minions=(),
        next_minion_id=0,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


def _pending_tutor_state(library, hand=(), deck=None, matches=(0,),
                         is_conjure=False):
    """Fabricated pending_tutor state — same pattern as the pending-mask
    tests in test_legal_actions.py (legal_actions / the resolver gate only
    consult the pending fields, not how they were entered)."""
    rat_id = library.get_numeric_id("rat")
    if deck is None:
        deck = (rat_id,) * max(len(matches), 1)
    p1 = _player(PlayerSide.PLAYER_1, hand=hand, deck=deck)
    p2 = _player(PlayerSide.PLAYER_2)
    return _state(
        p1, p2,
        pending_tutor_player_idx=0,
        pending_tutor_matches=tuple(matches),
        pending_tutor_remaining=max(len(matches), 0) and 1,
        pending_tutor_is_conjure=is_conjure,
    )


# ---------------------------------------------------------------------------
# 1. legal_actions: decline masked out while matches remain
# ---------------------------------------------------------------------------


class TestMandatoryTutorLegalActions:
    def test_no_decline_while_matches_remain(self, library):
        state = _pending_tutor_state(library, matches=(0, 1))
        actions = legal_actions(state, library)
        kinds = {a.action_type for a in actions}
        assert kinds == {ActionType.TUTOR_SELECT}
        assert len(actions) == 2  # one per match, nothing else

    def test_decline_is_only_action_at_zero_matches(self, library):
        state = _pending_tutor_state(library, matches=())
        actions = legal_actions(state, library)
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.DECLINE_TUTOR

    def test_full_hand_does_not_make_decline_legal(self, library):
        rat_id = library.get_numeric_id("rat")
        state = _pending_tutor_state(
            library, hand=(rat_id,) * MAX_HAND_SIZE, matches=(0,),
        )
        actions = legal_actions(state, library)
        kinds = {a.action_type for a in actions}
        assert kinds == {ActionType.TUTOR_SELECT}, (
            "a full hand does not exempt the pick — the tutored card "
            "burns to the Exhaust Pile instead"
        )


# ---------------------------------------------------------------------------
# 2 + 3. Resolver: decline raises with matches, resolves at zero matches
# ---------------------------------------------------------------------------


class TestMandatoryTutorResolver:
    def test_decline_raises_while_matches_remain(self, library):
        state = _pending_tutor_state(library, matches=(0,))
        with pytest.raises(ValueError, match="mandatory tutoring"):
            resolve_action(state, decline_tutor_action(), library)

    def test_decline_resolves_at_zero_matches(self, library):
        state = _pending_tutor_state(library, matches=())
        result = resolve_action(state, decline_tutor_action(), library)
        assert result.pending_tutor_player_idx is None
        assert result.pending_tutor_matches == ()
        # The resume tail opens the after-action react window.
        assert result.phase == TurnPhase.REACT

    def test_decline_raises_in_real_diodebot_flow(self, library):
        """Full engine flow: summon Blue Diodebot (tutors Red on summon),
        PASS both react windows, then try to decline the open tutor."""
        blue = library.get_numeric_id("blue_diodebot")
        red = library.get_numeric_id("red_diodebot")
        p1 = _player(PlayerSide.PLAYER_1, hand=(blue,), deck=(red,))
        p2 = _player(PlayerSide.PLAYER_2)
        state = _state(p1, p2)
        state = resolve_action(
            state, play_card_action(card_index=0, position=(1, 0)), library,
        )
        state = resolve_action(state, pass_action(), library)  # Window A
        state = resolve_action(state, pass_action(), library)  # Window B
        assert state.pending_tutor_player_idx == 0
        assert len(state.pending_tutor_matches) == 1
        # Decline is illegal — the pick is mandatory.
        with pytest.raises(ValueError, match="mandatory tutoring"):
            resolve_action(state, decline_tutor_action(), library)
        # And DECLINE_TUTOR is absent from the legal set.
        kinds = {a.action_type for a in legal_actions(state, library)}
        assert ActionType.DECLINE_TUTOR not in kinds
        # The mandatory pick still resolves normally.
        state = resolve_action(state, tutor_select_action(0), library)
        assert state.pending_tutor_player_idx is None
        assert red in state.players[0].hand


# ---------------------------------------------------------------------------
# Conjure exemption: Ratchanter's conjure deck-pick keeps its decline
# (pending_tutor_is_conjure=True — mandatory tutoring is tutor-only)
# ---------------------------------------------------------------------------


class TestConjureDeclineUnchanged:
    def test_decline_stays_legal_with_matches_for_conjure(self, library):
        state = _pending_tutor_state(library, matches=(0, 1), is_conjure=True)
        actions = legal_actions(state, library)
        kinds = {a.action_type for a in actions}
        assert ActionType.DECLINE_TUTOR in kinds, (
            "conjure decline semantics must be unchanged — mandatory "
            "tutoring applies to tutors only"
        )
        assert ActionType.TUTOR_SELECT in kinds
        # One TUTOR_SELECT per match + exactly one DECLINE_TUTOR.
        assert len(actions) == 3

    def test_decline_resolves_with_matches_for_conjure(self, library):
        rat_id = library.get_numeric_id("rat")
        state = _pending_tutor_state(
            library, deck=(rat_id, rat_id), matches=(0, 1), is_conjure=True,
        )
        result = resolve_action(state, decline_tutor_action(), library)
        # Pending cleared, card left IN the deck (not picked, not burned).
        assert result.pending_tutor_player_idx is None
        assert result.pending_tutor_matches == ()
        assert result.pending_tutor_is_conjure is False
        assert result.players[0].deck == (rat_id, rat_id)
        assert result.players[0].exhaust == ()

    def test_non_conjure_decline_still_raises_with_matches(self, library):
        """Control: the same state WITHOUT the conjure flag stays mandatory."""
        state = _pending_tutor_state(library, matches=(0, 1), is_conjure=False)
        with pytest.raises(ValueError, match="mandatory tutoring"):
            resolve_action(state, decline_tutor_action(), library)


# ---------------------------------------------------------------------------
# 4. Full hand: the mandatory pick overdraw-burns to the Exhaust Pile
# ---------------------------------------------------------------------------


class TestFullHandTutorBurns:
    def test_full_hand_pick_burns_to_exhaust_revealed(self, library):
        rat_id = library.get_numeric_id("rat")
        giant_id = library.get_numeric_id("giant_rat")
        state = _pending_tutor_state(
            library,
            hand=(rat_id,) * MAX_HAND_SIZE,
            deck=(giant_id, rat_id),
            matches=(0,),
        )
        stream = EventStream(next_seq=0)
        result = resolve_action(
            state,
            Action(action_type=ActionType.TUTOR_SELECT, card_index=0),
            library,
            event_collector=stream,
        )
        new_p1 = result.players[0]
        # Card left the deck but NOT into the (full) hand — burned instead.
        assert giant_id not in new_p1.deck
        assert len(new_p1.hand) == MAX_HAND_SIZE
        assert giant_id not in new_p1.hand
        assert new_p1.exhaust == (giant_id,)
        # Pending cleared — the pick was consumed even though it burned.
        assert result.pending_tutor_player_idx is None
        # The reveal event drives the client's existing overdraw-burn
        # animation (playOverdrawBurn via EVT_CARD_BURNED).
        burned = [e for e in stream.events if e.type == EVT_CARD_BURNED]
        assert len(burned) == 1
        assert burned[0].payload["source"] == "tutor"
        assert burned[0].payload["card_numeric_id"] == giant_id
        assert burned[0].payload["player_idx"] == 0
