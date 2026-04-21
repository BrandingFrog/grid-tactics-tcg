"""Unit tests for the phase_contracts module (Phase 14.8 plan 01).

Covers:
  * Enum-coverage: every TriggerType (except deprecated PASSIVE) and every
    ActionType has at least one PHASE_CONTRACTS entry.
  * Explicit-phase guarantees for ON_DEATH and ON_PLAY (orchestrator
    decision #9 — never wildcard).
  * Pending-state-bound action coverage and precedence (orchestrator
    decision #8 — pending check runs FIRST).
  * Sandbox category bypass (orchestrator decision #5).
  * Mode toggling via env var: off / shadow / strict.
  * Unknown-source surfaces loudly in strict, logs in shadow.
"""

from __future__ import annotations

import logging

import pytest

from grid_tactics import phase_contracts
from grid_tactics.enums import ActionType, TriggerType, TurnPhase
from grid_tactics.phase_contracts import (
    PENDING_REQUIREMENTS,
    PHASE_CONTRACTS,
    OutOfPhaseError,
    assert_phase_contract,
    expected_action_sources,
    expected_trigger_sources,
    get_enforcement_mode,
)


# ---------------------------------------------------------------------------
# Lightweight stub state — avoids constructing a full GameState fixture for
# pure unit tests of the assertion function. Real integration coverage lives
# in the test_resolve_action_* tests at the bottom of the file (added in
# Task 2).
# ---------------------------------------------------------------------------


class _StubState:
    """Minimal duck-typed stand-in for GameState for assertion unit tests."""

    def __init__(
        self,
        phase: TurnPhase = TurnPhase.ACTION,
        **pending,
    ) -> None:
        self.phase = phase
        # Initialize all known pending fields to None; let kwargs override.
        for f in PENDING_REQUIREMENTS.values():
            setattr(self, f, None)
        for k, v in pending.items():
            setattr(self, k, v)


@pytest.fixture(autouse=True)
def _reset_mode_each_test():
    """Ensure cached mode is cleared before AND after every test.

    Prevents env-var bleed between tests in the same process.
    """
    phase_contracts._reset_mode_cache()
    yield
    phase_contracts._reset_mode_cache()


# ---------------------------------------------------------------------------
# Enum-coverage tests
# ---------------------------------------------------------------------------


def test_every_trigger_type_has_contract_source():
    """Every TriggerType (except PASSIVE) must have a "trigger:<name>" entry.

    PASSIVE is skipped because research §"Trigger-bound contracts" marks it
    for deletion in plan 14.8-05; seeding it here would make it load-bearing.
    """
    expected = expected_trigger_sources()
    missing = expected - set(PHASE_CONTRACTS.keys())
    assert not missing, (
        f"PHASE_CONTRACTS missing entries for triggers: {sorted(missing)}"
    )


def test_every_action_type_has_contract_source():
    """Every ActionType must map to at least one "action:<name>" entry.

    PASS maps to BOTH "action:pass_action" and "action:pass_react" (the
    fatigue path vs. closing-the-react-window path are semantically distinct).
    """
    expected = expected_action_sources()
    missing = expected - set(PHASE_CONTRACTS.keys())
    assert not missing, (
        f"PHASE_CONTRACTS missing entries for actions: {sorted(missing)}"
    )


def test_pass_split_into_action_and_react():
    """PASS specifically must have both 'pass_action' and 'pass_react' rows."""
    assert "action:pass_action" in PHASE_CONTRACTS
    assert "action:pass_react" in PHASE_CONTRACTS
    assert PHASE_CONTRACTS["action:pass_action"] == frozenset({TurnPhase.ACTION})
    assert PHASE_CONTRACTS["action:pass_react"] == frozenset({TurnPhase.REACT})


# ---------------------------------------------------------------------------
# Explicit-phase guarantees (orchestrator decision #9)
# ---------------------------------------------------------------------------


def test_on_death_explicit_phases():
    """ON_DEATH must enumerate ALL four phases explicitly — NOT a wildcard."""
    assert PHASE_CONTRACTS["trigger:on_death"] == frozenset(
        {
            TurnPhase.ACTION,
            TurnPhase.REACT,
            TurnPhase.START_OF_TURN,
            TurnPhase.END_OF_TURN,
        }
    )


def test_on_play_explicit_phases():
    """ON_PLAY must enumerate exactly (ACTION, REACT) — orchestrator #9."""
    assert PHASE_CONTRACTS["trigger:on_play"] == frozenset(
        {TurnPhase.ACTION, TurnPhase.REACT}
    )


def test_passive_intentionally_absent():
    """PASSIVE is slated for deletion — must NOT be in the table."""
    assert "trigger:passive" not in PHASE_CONTRACTS


# ---------------------------------------------------------------------------
# Pending-bound coverage
# ---------------------------------------------------------------------------


def test_pending_requirements_cover_all_pending_actions():
    """Every key in PENDING_REQUIREMENTS must be present in PHASE_CONTRACTS."""
    missing = set(PENDING_REQUIREMENTS.keys()) - set(PHASE_CONTRACTS.keys())
    assert not missing, (
        f"PENDING_REQUIREMENTS keys not in PHASE_CONTRACTS: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Mode toggle tests
# ---------------------------------------------------------------------------


def test_off_mode_no_op(monkeypatch):
    """Default mode is off — assertions are no-ops even for bogus sources."""
    monkeypatch.delenv("CONTRACT_ENFORCEMENT_MODE", raising=False)
    phase_contracts._reset_mode_cache()
    assert get_enforcement_mode() == "off"
    state = _StubState(phase=TurnPhase.START_OF_TURN)
    # action:attack would be a violation in START_OF_TURN under strict.
    assert_phase_contract(state, "action:attack")  # no raise, no log


def test_shadow_mode_logs_no_raise(monkeypatch, caplog):
    """Shadow mode logs WARNING but does not raise."""
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "shadow")
    phase_contracts._reset_mode_cache()
    assert get_enforcement_mode() == "shadow"

    state = _StubState(phase=TurnPhase.START_OF_TURN)
    with caplog.at_level(logging.WARNING, logger="grid_tactics.phase_contracts"):
        assert_phase_contract(state, "action:attack")  # violation: ACTION-only

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        "action:attack" in r.getMessage() for r in warnings
    ), "expected a warning mentioning action:attack"


def test_unknown_source_raises_in_strict(monkeypatch):
    """Unknown source is surfaced loudly in strict mode."""
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "strict")
    phase_contracts._reset_mode_cache()

    state = _StubState(phase=TurnPhase.ACTION)
    with pytest.raises(OutOfPhaseError) as excinfo:
        assert_phase_contract(state, "action:bogus_made_up_source")
    assert excinfo.value.unknown_source is True


def test_strict_mode_phase_violation_raises(monkeypatch):
    """Standard phase violation raises OutOfPhaseError in strict mode."""
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "strict")
    phase_contracts._reset_mode_cache()

    state = _StubState(phase=TurnPhase.START_OF_TURN)
    with pytest.raises(OutOfPhaseError) as excinfo:
        assert_phase_contract(state, "action:attack")
    err = excinfo.value
    assert err.contract_source == "action:attack"
    assert err.phase == TurnPhase.START_OF_TURN
    assert TurnPhase.ACTION in err.allowed_phases
    assert err.pending_required is None


# ---------------------------------------------------------------------------
# Sandbox bypass
# ---------------------------------------------------------------------------


def test_sandbox_bypass(monkeypatch):
    """Sandbox category MUST bypass phase enforcement even in strict mode."""
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "strict")
    phase_contracts._reset_mode_cache()

    state = _StubState(phase=TurnPhase.START_OF_TURN)
    # No raise — sandbox: prefix is exempt.
    assert_phase_contract(state, "sandbox:cheat_mana")
    assert_phase_contract(state, "sandbox:set_active")
    assert_phase_contract(state, "sandbox:undo")
    assert_phase_contract(state, "sandbox:redo")
    assert_phase_contract(state, "sandbox:save")
    assert_phase_contract(state, "sandbox:load")
    assert_phase_contract(state, "sandbox:reset")


# ---------------------------------------------------------------------------
# Pending-precedence tests (orchestrator decision #8)
# ---------------------------------------------------------------------------


def test_pending_check_takes_precedence(monkeypatch):
    """Pending field set → action legal; unset → OutOfPhaseError with
    pending_required populated.

    Validates orchestrator decision #8: the pending field is checked
    BEFORE the phase set, because pending modals legitimately interrupt
    every phase.
    """
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "strict")
    phase_contracts._reset_mode_cache()

    # Case 1: pending is set → no raise even in a "wrong" phase context.
    state_with_pending = _StubState(
        phase=TurnPhase.REACT,  # tutor was opened mid-react
        pending_tutor_player_idx=0,
    )
    assert_phase_contract(state_with_pending, "action:tutor_select")  # no raise

    # Case 2: pending NOT set → OutOfPhaseError with pending_required set.
    state_without_pending = _StubState(phase=TurnPhase.ACTION)
    with pytest.raises(OutOfPhaseError) as excinfo:
        assert_phase_contract(state_without_pending, "action:tutor_select")
    assert excinfo.value.pending_required == "pending_tutor_player_idx"


def test_pending_precedence_for_decline_post_move_attack(monkeypatch):
    """DECLINE_POST_MOVE_ATTACK is gated by pending_post_move_attacker_id."""
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "strict")
    phase_contracts._reset_mode_cache()

    state_with = _StubState(
        phase=TurnPhase.ACTION,
        pending_post_move_attacker_id=42,
    )
    assert_phase_contract(state_with, "action:decline_post_move_attack")

    state_without = _StubState(phase=TurnPhase.ACTION)
    with pytest.raises(OutOfPhaseError) as excinfo:
        assert_phase_contract(state_without, "action:decline_post_move_attack")
    assert excinfo.value.pending_required == "pending_post_move_attacker_id"


def test_invalid_mode_falls_back_to_off(monkeypatch, caplog):
    """An invalid CONTRACT_ENFORCEMENT_MODE value falls back to off."""
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "garbage_value")
    phase_contracts._reset_mode_cache()
    with caplog.at_level(logging.WARNING, logger="grid_tactics.phase_contracts"):
        assert get_enforcement_mode() == "off"
    assert any("Invalid CONTRACT_ENFORCEMENT_MODE" in r.getMessage() for r in caplog.records)


def test_get_enforcement_mode_caches(monkeypatch):
    """Mode is cached after first read; setenv after read does NOT take effect
    until _reset_mode_cache() is called."""
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "shadow")
    phase_contracts._reset_mode_cache()
    assert get_enforcement_mode() == "shadow"

    # Change env var — without reset, cached value persists.
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "strict")
    assert get_enforcement_mode() == "shadow"

    # After reset, new value takes effect.
    phase_contracts._reset_mode_cache()
    assert get_enforcement_mode() == "strict"


# ---------------------------------------------------------------------------
# Integration tests (Task 2): tagging is benign at mode=off and structured
# logging in mode=shadow doesn't break engine behavior.
# ---------------------------------------------------------------------------


def test_module_default_mode_is_off_when_env_var_unset(monkeypatch):
    """Sanity: when the env var is fully UNSET, the module default is "off".

    Plan 14.8-02 changed conftest.py to default the env var to "shadow"
    for the test session — but the underlying module-level default (when
    no env var is set at all) must still be "off" to preserve back-compat
    for any consumer that imports the module without the test fixture.
    This test deletes the env var and verifies the off fallback still works.
    """
    monkeypatch.delenv("CONTRACT_ENFORCEMENT_MODE", raising=False)
    phase_contracts._reset_mode_cache()
    assert get_enforcement_mode() == "off"


def _build_minimal_game(library):
    """Helper: build a fresh GameState with two trivial decks for integration
    tests. Deck contents don't matter for the contract assertions; we just
    need a state in ACTION phase that resolve_action can process."""
    from grid_tactics.game_state import GameState
    # Use any 7 cards (deck_size doesn't matter for these tests).
    all_card_ids = sorted(
        library.get_numeric_id(c.card_id) for c in library.all_cards
    )
    deck = tuple(all_card_ids[:7])
    state, _rng = GameState.new_game(seed=42, deck_p1=deck, deck_p2=deck)
    return state


def test_resolve_action_does_not_fire_assertions_in_off_mode(monkeypatch, caplog):
    """A real action through resolve_action emits NO contract warnings
    at mode=off (the foundation plan's invariant)."""
    monkeypatch.delenv("CONTRACT_ENFORCEMENT_MODE", raising=False)
    phase_contracts._reset_mode_cache()
    from grid_tactics.action_resolver import resolve_action
    from grid_tactics.actions import pass_action
    from grid_tactics.card_library import CardLibrary
    from pathlib import Path
    library = CardLibrary.from_directory(Path("data/cards"))
    state = _build_minimal_game(library)

    with caplog.at_level(logging.WARNING, logger="grid_tactics.phase_contracts"):
        try:
            resolve_action(state, pass_action(), library)
        except ValueError:
            # Some action legality issues are unrelated to contracts.
            pass

    contract_warnings = [
        r for r in caplog.records
        if r.name == "grid_tactics.phase_contracts"
    ]
    assert not contract_warnings, (
        f"Expected no contract warnings at mode=off, got: "
        f"{[r.getMessage() for r in contract_warnings]}"
    )


def test_shadow_mode_logs_violations_but_does_not_break_resolve_action(
    monkeypatch, caplog,
):
    """Shadow mode logs WARNING for any violation but does NOT raise.

    Runs a few resolve_action calls under shadow mode. The engine's
    behavior must be IDENTICAL to mode=off (no exceptions, no state
    corruption). Any structured warnings emitted include the
    ``source=`` field so plan 14.8-02's invariant test can parse them.
    """
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "shadow")
    phase_contracts._reset_mode_cache()
    assert get_enforcement_mode() == "shadow"

    from grid_tactics.action_resolver import resolve_action
    from grid_tactics.actions import pass_action
    from grid_tactics.card_library import CardLibrary
    from pathlib import Path
    library = CardLibrary.from_directory(Path("data/cards"))
    state = _build_minimal_game(library)

    with caplog.at_level(logging.WARNING, logger="grid_tactics.phase_contracts"):
        try:
            new_state = resolve_action(state, pass_action(), library)
            assert new_state is not None
        except ValueError:
            # Domain-legality issue, not a contract assertion.
            pass

    contract_warnings = [
        r for r in caplog.records
        if r.name == "grid_tactics.phase_contracts"
    ]
    for warn in contract_warnings:
        msg = warn.getMessage()
        assert "source=" in msg, (
            f"Shadow-mode warning missing source= field: {msg}"
        )
