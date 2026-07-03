"""Server-lane tests for the 2026-07 turn-structure redesign event plumbing.

Covers view_filter.filter_engine_events_for_viewer behavior for the new
turn-structure events:

- Overdraw BURN draws are PUBLIC: a card_drawn event whose payload marks
  the card as sent to the Exhaust Pile keeps its card identity for BOTH
  viewers (burned cards are revealed by rule).
- Normal draws are still redacted for the opponent (regression guard).
- New event types (handshake, fatigue, overdraw/card-burned variants)
  pass through the filter unredacted for both viewers — they are public
  events by design and must never be swallowed or stripped.

These tests construct EngineEvent instances directly (not via
EventStream.collect) so they stay valid regardless of which EVT_*
constants the engine has registered — the filter must be payload-driven,
not constant-driven, for forward compatibility.
"""
from grid_tactics.engine_events import EVT_CARD_DRAWN, EngineEvent
from grid_tactics.server.view_filter import filter_engine_events_for_viewer


def _draw_event(payload: dict) -> EngineEvent:
    return EngineEvent(
        type=EVT_CARD_DRAWN,
        contract_source="system:turn_start_draw",
        seq=0,
        payload=payload,
        animation_duration_ms=350,
    )


# ---------------------------------------------------------------------------
# Overdraw burn: card identity is public
# ---------------------------------------------------------------------------


class TestOverdrawBurnIsPublic:
    def test_burned_flag_keeps_identity_for_opponent(self):
        ev = _draw_event({
            "player_idx": 0,
            "card_numeric_id": 42,
            "burned": True,
        })
        opp = filter_engine_events_for_viewer([ev], viewer_idx=1)[0]
        assert opp.payload["card_numeric_id"] == 42

    def test_destination_exhaust_keeps_identity_for_opponent(self):
        ev = _draw_event({
            "player_idx": 0,
            "card_numeric_id": 7,
            "destination": "exhaust",
        })
        opp = filter_engine_events_for_viewer([ev], viewer_idx=1)[0]
        assert opp.payload["card_numeric_id"] == 7

    def test_to_exhaust_flag_keeps_identity_for_opponent(self):
        ev = _draw_event({
            "player_idx": 1,
            "card_numeric_id": 13,
            "to_exhaust": True,
        })
        opp = filter_engine_events_for_viewer([ev], viewer_idx=0)[0]
        assert opp.payload["card_numeric_id"] == 13

    def test_overdraw_flag_keeps_identity_for_both_viewers(self):
        ev = _draw_event({
            "player_idx": 0,
            "card_numeric_id": 21,
            "overdraw": True,
        })
        for viewer in (0, 1):
            got = filter_engine_events_for_viewer([ev], viewer_idx=viewer)[0]
            assert got.payload["card_numeric_id"] == 21, (
                f"burned card identity hidden from viewer {viewer}"
            )

    def test_zone_exhaust_keeps_identity_for_opponent(self):
        ev = _draw_event({
            "player_idx": 0,
            "card_numeric_id": 5,
            "zone": "exhaust",
        })
        opp = filter_engine_events_for_viewer([ev], viewer_idx=1)[0]
        assert opp.payload["card_numeric_id"] == 5


# ---------------------------------------------------------------------------
# Normal draws: still redacted for the opponent (regression)
# ---------------------------------------------------------------------------


class TestNormalDrawStillRedacted:
    def test_plain_draw_redacted_for_opponent(self):
        ev = _draw_event({"player_idx": 0, "card_numeric_id": 42})
        opp = filter_engine_events_for_viewer([ev], viewer_idx=1)[0]
        assert opp.payload["card_numeric_id"] is None

    def test_falsy_burn_flags_do_not_disable_redaction(self):
        ev = _draw_event({
            "player_idx": 0,
            "card_numeric_id": 42,
            "burned": False,
            "to_exhaust": False,
            "destination": "hand",
        })
        opp = filter_engine_events_for_viewer([ev], viewer_idx=1)[0]
        assert opp.payload["card_numeric_id"] is None

    def test_own_draw_never_redacted(self):
        ev = _draw_event({"player_idx": 0, "card_numeric_id": 42})
        own = filter_engine_events_for_viewer([ev], viewer_idx=0)[0]
        assert own.payload["card_numeric_id"] == 42


# ---------------------------------------------------------------------------
# New turn-structure event types: public pass-through
# ---------------------------------------------------------------------------


class TestNewEventTypesPassThrough:
    def _roundtrip(self, ev_type: str, payload: dict) -> None:
        ev = EngineEvent(
            type=ev_type,
            contract_source="system:end_of_turn",
            seq=3,
            payload=payload,
        )
        for viewer in (0, 1):
            out = filter_engine_events_for_viewer([ev], viewer_idx=viewer)
            assert len(out) == 1, f"{ev_type} swallowed for viewer {viewer}"
            assert out[0].payload == payload, (
                f"{ev_type} payload mutated for viewer {viewer}"
            )

    def test_handshake_public_for_both_viewers(self):
        # Handshake: both players +1 mana; full-mana player draws instead.
        self._roundtrip("handshake", {
            "mana_gained": [1, 0],
            "cards_drawn": [None, 55],
        })

    def test_fatigue_public_for_both_viewers(self):
        self._roundtrip("fatigue", {
            "player_idx": 0,
            "damage": 20,
            "fatigue_count": 2,
        })

    def test_card_burned_public_for_both_viewers(self):
        # If the engine emits a dedicated burn event instead of tagging
        # card_drawn, its identity must also survive for both viewers.
        self._roundtrip("card_burned", {
            "player_idx": 1,
            "card_numeric_id": 9,
        })
