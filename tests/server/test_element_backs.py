"""Regression tests for the 2026-07 element-card-backs + public Dark Matter
view-filter changes (server lane).

Covers:
  1. ``filter_state_for_player`` leaks per-card ELEMENT ONLY for the
     opponent's hand (``hand_elements``, order-preserving) — never card
     id / name / cost. This is a DESIGNED information leak so the client
     can tint face-down card backs by element.
  2. The viewer's OWN hand is untouched (full card_numeric_ids, no
     hand_elements key).
  3. The face-down DECK pile stays element-neutral: deck contents hidden,
     count only, no per-card elements.
  4. Both players' ``dark_matter`` pools are PUBLIC in every filtered
     view (and legacy state dicts without the key default to 0).
  5. ``filter_engine_events_for_viewer``: an opponent ``card_drawn``
     event is redacted to element-only (identity keys nulled, ``element``
     added); the viewer's own draws pass through unredacted; overdraw
     BURNS stay fully public; god_mode bypasses everything.
  6. Spectator views inherit the same rules (non-god = P1 perspective
     with element backs on P2's hand; god = full info).
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.engine_events import EVT_CARD_DRAWN, EngineEvent
from grid_tactics.game_state import GameState
from grid_tactics.server.view_filter import (
    filter_engine_events_for_viewer,
    filter_state_for_player,
    filter_state_for_spectator,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def library() -> CardLibrary:
    return CardLibrary.from_directory(Path("data/cards"))


def _element_int(library: CardLibrary, card_id: str) -> int | None:
    card = library.get_by_card_id(card_id)
    return int(card.element) if card.element is not None else None


@pytest.fixture(scope="module")
def known_hand_ids(library: CardLibrary) -> tuple[int, int, int]:
    """Three cards with distinct, known elements (earth, fire, dark)."""
    return (
        library.get_numeric_id("rat"),          # earth
        library.get_numeric_id("flame_wyrm"),   # fire
        library.get_numeric_id("dark_matter_stash"),  # dark
    )


@pytest.fixture()
def state(library: CardLibrary, known_hand_ids) -> GameState:
    """Real GameState with a KNOWN P2 hand and nonzero DM pools."""
    rat = library.get_numeric_id("rat")
    deck = tuple([rat] * 12)
    st, _rng = GameState.new_game(seed=42, deck_p1=deck, deck_p2=deck)
    p1 = replace(st.players[0], dark_matter=3)
    p2 = replace(st.players[1], hand=known_hand_ids, dark_matter=5)
    return replace(st, players=(p1, p2))


def _drawn_event(payload: dict, seq: int = 1) -> EngineEvent:
    return EngineEvent(
        type=EVT_CARD_DRAWN,
        contract_source="system:turn_flip",
        seq=seq,
        payload=payload,
        animation_duration_ms=350,
    )


# ---------------------------------------------------------------------------
# 1+2+3: opponent hand -> element only; own hand full; deck neutral
# ---------------------------------------------------------------------------


class TestOpponentHandElementBacks:
    def test_opponent_hand_leaks_element_only_in_order(
        self, state, library, known_hand_ids
    ):
        filtered = filter_state_for_player(state.to_dict(), 0, library)
        opp = filtered["players"][1]

        # Identity fully hidden.
        assert opp["hand"] == []
        assert opp["hand_count"] == 3

        # Element leak: parallel list, same order as the hidden hand.
        expected = [
            _element_int(library, "rat"),           # earth = 2
            _element_int(library, "flame_wyrm"),    # fire = 1
            _element_int(library, "dark_matter_stash"),  # dark = 5
        ]
        assert opp["hand_elements"] == expected
        assert len(opp["hand_elements"]) == opp["hand_count"]

    def test_hand_elements_never_carry_identity(self, state, library):
        """Elements are bare Element wire ints — nothing id/name/cost-shaped."""
        filtered = filter_state_for_player(state.to_dict(), 0, library)
        opp = filtered["players"][1]
        for v in opp["hand_elements"]:
            assert v is None or (isinstance(v, int) and 0 <= v <= 6)
        # No parallel leak keys were invented.
        for forbidden in (
            "hand_ids", "hand_names", "hand_costs", "hand_cards",
        ):
            assert forbidden not in opp

    def test_own_hand_untouched_full_identity(self, state, library):
        raw = state.to_dict()
        filtered = filter_state_for_player(raw, 0, library)
        own = filtered["players"][0]
        assert own["hand"] == raw["players"][0]["hand"]
        # Own hand needs no element sidecar — full ids are present.
        assert "hand_elements" not in own

    def test_symmetric_for_viewer_1(self, state, library, known_hand_ids):
        """Viewer 1 sees own known hand fully; P1's hand as elements only."""
        raw = state.to_dict()
        filtered = filter_state_for_player(raw, 1, library)
        own = filtered["players"][1]
        assert own["hand"] == list(known_hand_ids)
        assert "hand_elements" not in own
        opp = filtered["players"][0]
        assert opp["hand"] == []
        assert len(opp["hand_elements"]) == opp["hand_count"]

    def test_deck_pile_stays_neutral(self, state, library):
        """Deck stays fully hidden — count only, NO per-card elements."""
        filtered = filter_state_for_player(state.to_dict(), 0, library)
        for player_dict in filtered["players"]:
            assert player_dict["deck"] == []
            assert player_dict["deck_count"] > 0
            assert "deck_elements" not in player_dict

    def test_no_library_emits_none_elements(self, state):
        """Legacy callers without a library still get a shape-stable list."""
        filtered = filter_state_for_player(state.to_dict(), 0)
        opp = filtered["players"][1]
        assert opp["hand_elements"] == [None, None, None]


# ---------------------------------------------------------------------------
# 4: Dark Matter pools are public
# ---------------------------------------------------------------------------


class TestDarkMatterPoolsPublic:
    def test_both_pools_visible_to_both_viewers(self, state, library):
        raw = state.to_dict()
        for viewer in (0, 1):
            filtered = filter_state_for_player(raw, viewer, library)
            assert filtered["players"][0]["dark_matter"] == 3
            assert filtered["players"][1]["dark_matter"] == 5

    def test_legacy_state_dict_defaults_to_zero(self, state, library):
        """Pre-redesign dicts lack the key — filter backfills 0."""
        raw = state.to_dict()
        for p in raw["players"]:
            p.pop("dark_matter", None)
        filtered = filter_state_for_player(raw, 0, library)
        assert filtered["players"][0]["dark_matter"] == 0
        assert filtered["players"][1]["dark_matter"] == 0

    def test_avatar_panel_fields_present_for_both_players(self, state, library):
        """The client avatar panel needs hp / mana / DM / statuses for
        BOTH players in every filtered view."""
        filtered = filter_state_for_player(state.to_dict(), 0, library)
        for p in filtered["players"]:
            for key in (
                "hp", "current_mana", "max_mana", "dark_matter",
                "discarded_last_turn",
            ):
                assert key in p, f"avatar panel field missing: {key}"


# ---------------------------------------------------------------------------
# 5: engine-event filtering — opponent card_drawn carries element only
# ---------------------------------------------------------------------------


class TestCardDrawnEventElement:
    def test_opponent_draw_redacted_to_element_only(self, library):
        rat = library.get_numeric_id("rat")
        ev = _drawn_event({
            "player_idx": 1,
            "source": "turn_start",
            "card_numeric_id": rat,
        })
        [out] = filter_engine_events_for_viewer([ev], 0, library=library)
        assert out.payload["card_numeric_id"] is None
        assert out.payload["element"] == _element_int(library, "rat")
        # Nothing identity-shaped survives.
        for k in ("card_id", "stable_id", "name"):
            assert out.payload.get(k) is None

    def test_own_draw_passes_through_unredacted(self, library):
        rat = library.get_numeric_id("rat")
        ev = _drawn_event({
            "player_idx": 0,
            "source": "turn_start",
            "card_numeric_id": rat,
        })
        [out] = filter_engine_events_for_viewer([ev], 0, library=library)
        assert out is ev  # frozen dataclass shared by reference
        assert out.payload["card_numeric_id"] == rat
        assert "element" not in out.payload

    def test_overdraw_burn_stays_fully_public(self, library):
        """Burns are revealed by rule — identity must NOT be redacted."""
        wyrm = library.get_numeric_id("flame_wyrm")
        ev = _drawn_event({
            "player_idx": 1,
            "source": "turn_start",
            "card_numeric_id": wyrm,
            "burned": True,
        })
        [out] = filter_engine_events_for_viewer([ev], 0, library=library)
        assert out.payload["card_numeric_id"] == wyrm

    def test_draw_without_card_id_gets_none_element(self, library):
        """action:draw legacy payload has no card_numeric_id."""
        ev = _drawn_event({"player_idx": 1})
        [out] = filter_engine_events_for_viewer([ev], 0, library=library)
        assert out.payload["element"] is None

    def test_no_library_gets_none_element_but_still_redacts(self, library):
        rat = library.get_numeric_id("rat")
        ev = _drawn_event({"player_idx": 1, "card_numeric_id": rat})
        [out] = filter_engine_events_for_viewer([ev], 0)
        assert out.payload["card_numeric_id"] is None
        assert out.payload["element"] is None

    def test_dark_matter_change_event_public_both_viewers(self):
        """EVT_DARK_MATTER_CHANGE is public info — passes through
        unredacted to BOTH viewers (pool redesign 2026-07)."""
        from grid_tactics.engine_events import EVT_DARK_MATTER_CHANGE
        ev = EngineEvent(
            type=EVT_DARK_MATTER_CHANGE,
            contract_source="trigger:on_play",
            seq=7,
            payload={
                "player_idx": 1, "prev": 2, "new": 4, "delta": 2,
                "source": "dark_matter_stash",
            },
        )
        for viewer in (0, 1):
            [out] = filter_engine_events_for_viewer([ev], viewer)
            assert out is ev
            assert out.payload["delta"] == 2

    def test_god_mode_bypasses_all_redaction(self, library):
        rat = library.get_numeric_id("rat")
        ev = _drawn_event({"player_idx": 1, "card_numeric_id": rat})
        [out] = filter_engine_events_for_viewer(
            [ev], 0, god_mode=True, library=library
        )
        assert out is ev
        assert out.payload["card_numeric_id"] == rat


# ---------------------------------------------------------------------------
# 6: spectator parity
# ---------------------------------------------------------------------------


class TestSpectatorViews:
    def test_non_god_spectator_gets_p1_perspective_element_backs(
        self, state, library
    ):
        spec = filter_state_for_spectator(
            state.to_dict(), god_mode=False, perspective_idx=0,
            library=library,
        )
        opp = spec["players"][1]
        assert opp["hand"] == []
        assert len(opp["hand_elements"]) == 3
        assert spec["players"][0]["dark_matter"] == 3
        assert spec["players"][1]["dark_matter"] == 5

    def test_god_spectator_sees_full_hands(self, state, library, known_hand_ids):
        spec = filter_state_for_spectator(
            state.to_dict(), god_mode=True, library=library,
        )
        assert spec["players"][1]["hand"] == list(known_hand_ids)
        assert spec["players"][0]["dark_matter"] == 3
        assert spec["players"][1]["dark_matter"] == 5
