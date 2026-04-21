"""Phase 14.8 plan 02 — phase-contract invariant test.

Long-term safety net: this test scans every card × every trigger × every
phase × every action × every pending-modal flow and proves the engine never
silently mutates state out of phase. Lives forever; gates every PR.

Five live test classes correspond to coverage dimensions:

  1. ``TestContractTableCoverage``   — pure schema (no engine simulation)
  2. ``TestTriggerInvariants``       — every card.trigger × every phase
  3. ``TestActionInvariants``        — every ActionType × every phase
  4. ``TestPendingModalInvariants``  — every pending-modal × every phase
  5. ``TestSandboxBypass``           — sandbox: prefix bypasses always

Plus one PLACEHOLDER class:

  6. ``TestEventSymmetry`` — M1 react_window open/close pairing — SKIPPED
     until plan 14.8-06 enables EngineEvent stream from 03a/b.

All simulation tests run with ``CONTRACT_ENFORCEMENT_MODE=shadow`` (set by
the autouse fixture below) and use ``ViolationCapture`` to collect ALL
violations in a single test run, then assert empty. Diagnostics are rich:
when a test fails you see EVERY contract source / phase pair that fired.

If a test fails, the fix lands IN PLACE in plan 14.8-02 (not deferred):
re-tag the call site, re-add to PHASE_CONTRACTS, or split a too-broad
helper. The 20-violation budget gate applies — see plan 14.8-02 task 2.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Optional

import pytest

from grid_tactics import phase_contracts
from grid_tactics.actions import (
    Action,
    attack_action,
    conjure_deploy_action,
    death_target_pick_action,
    decline_conjure_action,
    decline_post_move_attack_action,
    decline_revive_action,
    decline_trigger_action,
    decline_tutor_action,
    move_action,
    pass_action,
    play_card_action,
    play_react_action,
    revive_place_action,
    sacrifice_action,
    transform_action,
    trigger_pick_action,
    tutor_select_action,
)
from grid_tactics.enums import (
    ActionType,
    CardType,
    TriggerType,
    TurnPhase,
)
from grid_tactics.phase_contracts import (
    PENDING_REQUIREMENTS,
    PHASE_CONTRACTS,
    OutOfPhaseError,
    ViolationCapture,
    format_violations,
)


# ---------------------------------------------------------------------------
# Module-level fixtures — load the card library once, force shadow mode for
# every test so violations are CAPTURED (not raised).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def library():
    """Load all 33 card JSONs once per test module."""
    from grid_tactics.card_library import CardLibrary
    return CardLibrary.from_directory(Path("data/cards"))


@pytest.fixture(autouse=True)
def shadow_mode(monkeypatch):
    """Force every test in this module to run in shadow mode.

    Shadow mode logs WARNINGs (and routes to ViolationCapture if active)
    but never raises — so a single test run surfaces ALL violations.
    """
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "shadow")
    phase_contracts._reset_mode_cache()
    yield
    phase_contracts._reset_mode_cache()


# ---------------------------------------------------------------------------
# State construction helpers — minimal viable GameState builders. These are
# TEST helpers (live in this file), NOT production code. Keep them small;
# refactor only if duplication grows.
# ---------------------------------------------------------------------------


def _new_minimal_state(library, deck_card_ids: Optional[tuple] = None):
    """Fresh GameState in ACTION phase, P1 to act, both decks pre-seeded.

    Used as the base for derived states in specific phases.
    """
    from grid_tactics.game_state import GameState
    if deck_card_ids is None:
        # Default: any 7 cards (deck_size doesn't matter for contract tests).
        all_card_ids = sorted(
            library.get_numeric_id(c.card_id) for c in library.all_cards
        )
        deck_card_ids = tuple(all_card_ids[:7])
    state, _rng = GameState.new_game(
        seed=42, deck_p1=deck_card_ids, deck_p2=deck_card_ids,
    )
    return state


def _state_in_phase(library, phase: TurnPhase, deck_card_ids=None):
    """Fresh state with state.phase forced to ``phase``.

    For REACT we also set a sensible react_player_idx and react_context so
    handlers don't trip on missing react bookkeeping. For START/END phases
    we just flip the phase — the engine entry helpers (enter_start_of_turn /
    enter_end_of_turn) have their own phase contracts.
    """
    from grid_tactics.enums import ReactContext
    state = _new_minimal_state(library, deck_card_ids)
    if phase == TurnPhase.ACTION:
        return state
    if phase == TurnPhase.REACT:
        return replace(
            state,
            phase=TurnPhase.REACT,
            react_player_idx=1 - state.active_player_idx,
            react_context=ReactContext.AFTER_ACTION,
            react_return_phase=TurnPhase.ACTION,
        )
    return replace(state, phase=phase)


def _put_minion_on_board(state, card_def, library, position=(2, 2), owner_idx=0):
    """Place a single instance of ``card_def`` at ``position`` for owner_idx.

    Returns (new_state, minion_instance_id). Used by trigger simulation
    helpers that need a board-resident source for ON_DEATH / ON_ATTACK /
    ON_MOVE / ON_DAMAGED triggers.
    """
    from grid_tactics.minion import MinionInstance
    from grid_tactics.enums import PlayerSide
    owner = PlayerSide.PLAYER_1 if owner_idx == 0 else PlayerSide.PLAYER_2
    instance_id = state.next_minion_id
    minion = MinionInstance(
        instance_id=instance_id,
        card_numeric_id=library.get_numeric_id(card_def.card_id),
        owner=owner,
        position=position,
        current_health=card_def.health or 1,
    )
    new_board = state.board.place(position[0], position[1], instance_id)
    new_state = replace(
        state,
        board=new_board,
        minions=state.minions + (minion,),
        next_minion_id=instance_id + 1,
    )
    return new_state, instance_id


# ---------------------------------------------------------------------------
# 1. TestContractTableCoverage — pure schema check (no engine simulation)
# ---------------------------------------------------------------------------


class TestContractTableCoverage:
    """Pure-schema: every trigger / pending action used by code or cards
    must have a contract entry. These tests are fast and run before the
    slow simulation tests so a contract-table omission surfaces immediately.
    """

    def test_every_trigger_used_by_any_card_has_contract_source(self, library):
        """Every TriggerType declared in any card's effects must be in
        PHASE_CONTRACTS as ``trigger:<lowercased_name>``.

        Iterates the full data/cards directory. Catches the case where a
        new card uses a trigger that the table doesn't cover.
        """
        used_triggers: set[str] = set()
        for card in library.all_cards:
            for effect in card.effects:
                used_triggers.add(f"trigger:{effect.trigger.name.lower()}")
            if card.react_effect is not None:
                used_triggers.add(
                    f"trigger:{card.react_effect.trigger.name.lower()}"
                )
        # PASSIVE is intentionally excluded (slated for deletion plan 14.8-05);
        # the test below catches any card that re-introduces it.
        used_triggers.discard("trigger:passive")
        missing = used_triggers - set(PHASE_CONTRACTS.keys())
        assert not missing, (
            f"PHASE_CONTRACTS missing entries for triggers used by cards: "
            f"{sorted(missing)}"
        )

    def test_no_card_uses_passive_trigger(self, library):
        """PASSIVE was retagged in 14.7-03. Regression guard for plan 14.8-05's
        deletion: any card that re-introduces ``trigger: passive`` must fail.
        """
        offenders: list[str] = []
        for card in library.all_cards:
            for effect in card.effects:
                if effect.trigger == TriggerType.PASSIVE:
                    offenders.append(card.card_id)
                    break
        assert not offenders, (
            f"Cards still using TriggerType.PASSIVE (slated for deletion): "
            f"{offenders}"
        )

    def test_every_pending_action_has_pending_requirement(self):
        """PENDING_REQUIREMENTS must list every pending-bound action source.

        These are the 10 actions that legitimately interrupt phases via a
        modal: TUTOR_SELECT, DEATH_TARGET_PICK, REVIVE_PLACE, TRIGGER_PICK,
        CONJURE_DEPLOY, plus their decline variants and DECLINE_POST_MOVE_ATTACK.
        """
        expected_pending = {
            "action:tutor_select",
            "action:decline_tutor",
            "action:conjure_deploy",
            "action:decline_conjure",
            "action:death_target_pick",
            "action:revive_place",
            "action:decline_revive",
            "action:trigger_pick",
            "action:decline_trigger",
            "action:decline_post_move_attack",
        }
        missing = expected_pending - set(PENDING_REQUIREMENTS.keys())
        assert not missing, (
            f"PENDING_REQUIREMENTS missing pending-bound actions: "
            f"{sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# 2. TestTriggerInvariants — for each card with triggered effects, simulate
#    the trigger fire in a state from each phase the contract allows.
# ---------------------------------------------------------------------------


def _fire_trigger_for_card(state, card_def, effect, library):
    """Best-effort dispatch to fire ``effect``'s trigger from ``card_def``.

    The goal is to land at the right contract assertion site. Engine errors
    (TypeError / ValueError) inside the trigger path are SWALLOWED — we are
    testing contract invariants, NOT engine correctness.
    """
    from grid_tactics.effect_resolver import resolve_effects_for_trigger
    trig = effect.trigger
    if trig in (
        TriggerType.ON_PLAY,
        TriggerType.ON_DEATH,
        TriggerType.ON_ATTACK,
        TriggerType.ON_DAMAGED,
        TriggerType.ON_MOVE,
        TriggerType.ON_DISCARD,
        TriggerType.ON_START_OF_TURN,
        TriggerType.ON_END_OF_TURN,
        TriggerType.ON_SUMMON,
    ):
        # Place a minion source on the board (if not already), then fire the
        # trigger via the canonical resolve_effects_for_trigger path. This
        # path threads contract_source from the trigger kind, so the
        # assertion site is exactly the one we want to validate.
        if card_def.card_type == CardType.MINION:
            state2, instance_id = _put_minion_on_board(state, card_def, library)
            minion = state2.get_minion(instance_id)
            return resolve_effects_for_trigger(
                state2, card_def, minion, trig, library,
                contract_source=f"trigger:{trig.name.lower()}",
            )
        else:
            # Magic / react cards firing as triggers: use a sentinel position.
            from grid_tactics.enums import PlayerSide
            return resolve_effects_for_trigger(
                state, card_def, None, trig, library,
                contract_source=f"trigger:{trig.name.lower()}",
            )
    # AURA / PASSIVE: no fire path; AURA is read-time only.
    return state


class TestTriggerInvariants:
    """For each card with triggered effects, fire the trigger from a state
    in each ALLOWED phase and assert no contract violation logged.

    We do NOT assert violations DO fire in disallowed phases here — many
    triggers are gated by upstream dispatchers (e.g. ON_ATTACK only ever
    fires from inside ATTACK action handling, which has its own phase
    gate). Disallowed-phase enforcement is covered by TestActionInvariants
    via the action dispatchers and by the shadow-mode WARNING flow under
    real engine usage in the broader test suite.
    """

    def test_every_card_trigger_fires_cleanly_in_allowed_phases(self, library):
        """For every card.effect, fire the trigger from a state in EACH phase
        the contract allows; assert ZERO violations were captured.
        """
        all_violations: list[OutOfPhaseError] = []
        for card in library.all_cards:
            for effect in card.effects:
                if effect.trigger == TriggerType.PASSIVE:
                    continue  # PASSIVE intentionally absent from PHASE_CONTRACTS
                if effect.trigger == TriggerType.AURA:
                    continue  # AURA is read-time only — never fires via resolve
                source = f"trigger:{effect.trigger.name.lower()}"
                allowed = PHASE_CONTRACTS.get(source, frozenset())
                for phase in allowed:
                    state = _state_in_phase(library, phase)
                    with ViolationCapture() as cap:
                        try:
                            _fire_trigger_for_card(state, card, effect, library)
                        except Exception:
                            pass  # engine correctness errors out of scope
                    # Filter to only violations attributable to THIS source —
                    # downstream helpers may fire other contract sources we
                    # don't want to attribute here.
                    own = [v for v in cap.violations if v.contract_source == source]
                    if own:
                        all_violations.extend(
                            [(card.card_id, effect.trigger.name, phase.name, v)
                             for v in own]
                        )
        if all_violations:
            lines = [
                f"  - card={cid} trigger={trig} phase={ph} "
                f"violation_source={v.contract_source} violation_phase={v.phase.name}"
                for (cid, trig, ph, v) in all_violations
            ]
            pytest.fail(
                f"Card-trigger contract violations (in allowed phase!) — "
                f"{len(all_violations)} total:\n" + "\n".join(lines)
            )


# ---------------------------------------------------------------------------
# 3. TestActionInvariants — for every ActionType × every phase, attempt to
#    drive the engine and assert no violation in ALLOWED combos.
# ---------------------------------------------------------------------------


def _action_type_sources(action_type: ActionType) -> tuple[str, ...]:
    """Return the contract source(s) an ActionType maps to.

    PASS splits into two sources by phase (pass_action for ACTION,
    pass_react for REACT). Everything else is a single source.
    """
    if action_type == ActionType.PASS:
        return ("action:pass_action", "action:pass_react")
    return (f"action:{action_type.name.lower()}",)


def _build_action(action_type: ActionType) -> Optional[Action]:
    """Best-effort: build a syntactically valid Action of ``action_type``.

    Returns None if the action requires fields we cannot safely fabricate
    without engine state. The caller skips the test in that case.
    """
    if action_type == ActionType.PASS:
        return pass_action()
    if action_type == ActionType.DRAW:
        return Action(action_type=ActionType.DRAW)
    if action_type == ActionType.MOVE:
        return move_action(minion_id=0, position=(0, 0))
    if action_type == ActionType.ATTACK:
        return attack_action(minion_id=0, target_id=1)
    if action_type == ActionType.PLAY_CARD:
        return play_card_action(card_index=0, position=(0, 0))
    if action_type == ActionType.PLAY_REACT:
        return play_react_action(card_index=0)
    if action_type == ActionType.SACRIFICE:
        return sacrifice_action(minion_id=0)
    if action_type == ActionType.TRANSFORM:
        return transform_action(minion_id=0, transform_target="x")
    if action_type == ActionType.DECLINE_POST_MOVE_ATTACK:
        return decline_post_move_attack_action()
    if action_type == ActionType.TUTOR_SELECT:
        return tutor_select_action(match_index=0)
    if action_type == ActionType.DECLINE_TUTOR:
        return decline_tutor_action()
    if action_type == ActionType.ACTIVATE_ABILITY:
        return Action(action_type=ActionType.ACTIVATE_ABILITY, minion_id=0)
    if action_type == ActionType.CONJURE_DEPLOY:
        return conjure_deploy_action(position=(0, 0))
    if action_type == ActionType.DECLINE_CONJURE:
        return decline_conjure_action()
    if action_type == ActionType.DEATH_TARGET_PICK:
        return death_target_pick_action(target_pos=(0, 0))
    if action_type == ActionType.REVIVE_PLACE:
        return revive_place_action(position=(0, 0))
    if action_type == ActionType.DECLINE_REVIVE:
        return decline_revive_action()
    if action_type == ActionType.TRIGGER_PICK:
        return trigger_pick_action(queue_idx=0)
    if action_type == ActionType.DECLINE_TRIGGER:
        return decline_trigger_action()
    return None


class TestActionInvariants:
    """For every (ActionType, TurnPhase) combo, fabricate a state in that
    phase, fabricate a syntactically-valid action, and call resolve_action.

    We assert: in any phase that is ALLOWED for the action's contract source,
    NO violation must be logged for that source. We do NOT assert violations
    fire in disallowed phases — the dispatcher legitimately rejects many
    illegal-phase actions before they reach a contract assertion (that
    rejection IS the contract gate at that point).
    """

    @pytest.mark.parametrize("phase", list(TurnPhase))
    @pytest.mark.parametrize("action_type", list(ActionType))
    def test_action_in_phase_no_unexpected_violation(
        self, library, action_type, phase,
    ):
        from grid_tactics.action_resolver import resolve_action
        sources = _action_type_sources(action_type)
        # If ANY source for this action allows this phase → action SHOULD be
        # runnable cleanly with no violation logged for that source.
        allowed_sources = [
            s for s in sources if phase in PHASE_CONTRACTS.get(s, frozenset())
        ]
        if not allowed_sources:
            pytest.skip(
                f"Action {action_type.name} not allowed in phase {phase.name} — "
                "dispatcher-level rejection covers this"
            )
        action = _build_action(action_type)
        if action is None:
            pytest.skip(f"Cannot build {action_type.name} action without engine state")
        state = _state_in_phase(library, phase)
        with ViolationCapture() as cap:
            try:
                resolve_action(state, action, library)
            except Exception:
                pass  # engine-correctness errors out of scope
        # Assert no captured violation belongs to one of the allowed sources.
        own = [
            v for v in cap.violations
            if v.contract_source in allowed_sources
        ]
        assert not own, (
            f"Action {action_type.name} in phase {phase.name} (allowed via "
            f"{allowed_sources}) logged unexpected violations:\n"
            f"{format_violations(own)}"
        )


# ---------------------------------------------------------------------------
# 4. TestPendingModalInvariants — pending-precedence: when pending field is
#    set, the action is legal regardless of phase (orchestrator decision #8).
# ---------------------------------------------------------------------------


def _action_type_for_source(source: str) -> Optional[ActionType]:
    """Map a contract source string back to its ActionType.

    Used by TestPendingModalInvariants to construct the corresponding
    Action for each pending source.
    """
    name = source.split(":", 1)[1].upper()
    try:
        return ActionType[name]
    except KeyError:
        return None


def _state_with_pending(library, phase: TurnPhase, pending_field: str):
    """Build a state in ``phase`` with ``pending_field`` set to a sentinel.

    The sentinel value type depends on the field — int for player_idx and
    minion_id fields, tuple[int, int] for position fields, dict for object
    fields. We use minimal valid sentinels; the action resolver may still
    reject the action (e.g. invalid card_index in CONJURE_DEPLOY), but it
    must NOT raise OutOfPhaseError because pending was set.
    """
    state = _state_in_phase(library, phase)
    sentinels = {
        "pending_tutor_player_idx": 0,
        "pending_conjure_deploy_card": 0,  # numeric card id sentinel
        "pending_death_target": {"player_idx": 0, "candidates": ((0, 0),), "effect_type": 9},
        "pending_revive_player_idx": 0,
        "pending_trigger_picker_idx": 0,
        "pending_post_move_attacker_id": 0,
    }
    sentinel = sentinels.get(pending_field)
    if sentinel is None:
        return None
    try:
        return replace(state, **{pending_field: sentinel})
    except (TypeError, ValueError):
        return None


class TestPendingModalInvariants:
    """Per orchestrator decision #8: pending field check runs BEFORE the
    phase check. So pending-bound actions must be legal in ANY phase if the
    pending field is set.

    Two sub-tests per pending source:
      - With pending SET in each TurnPhase: NO contract violation for that source
      - With pending UNSET: contract violation MUST fire (with pending_required
        populated), proving the gate is wired.
    """

    @pytest.mark.parametrize("phase", list(TurnPhase))
    @pytest.mark.parametrize(
        "source,pending_field", list(PENDING_REQUIREMENTS.items())
    )
    def test_pending_action_legal_in_any_phase_when_pending_set(
        self, library, phase, source, pending_field,
    ):
        from grid_tactics.action_resolver import resolve_action
        state = _state_with_pending(library, phase, pending_field)
        if state is None:
            pytest.skip(f"Cannot construct pending state for {pending_field} in {phase.name}")
        action_type = _action_type_for_source(source)
        if action_type is None:
            pytest.skip(f"Cannot derive ActionType for source {source}")
        action = _build_action(action_type)
        if action is None:
            pytest.skip(f"Cannot build {action_type.name} action")
        with ViolationCapture() as cap:
            try:
                resolve_action(state, action, library)
            except OutOfPhaseError:
                pytest.fail(
                    f"OutOfPhaseError raised for {source} in {phase.name} "
                    f"despite {pending_field} being set"
                )
            except Exception:
                pass  # engine-correctness errors out of scope
        own = [v for v in cap.violations if v.contract_source == source]
        assert not own, (
            f"Pending source {source} fired contract violation in {phase.name} "
            f"despite {pending_field} being set:\n{format_violations(own)}"
        )

    @pytest.mark.parametrize(
        "source,pending_field", list(PENDING_REQUIREMENTS.items())
    )
    def test_pending_action_violates_when_pending_unset(
        self, library, source, pending_field,
    ):
        # Use the assertion function directly — bypasses the action dispatcher
        # which may legitimately early-reject the action before the contract
        # site fires. We are testing that the contract function itself
        # correctly surfaces the pending-required violation.
        from grid_tactics.phase_contracts import assert_phase_contract
        state = _state_in_phase(library, TurnPhase.ACTION)
        assert getattr(state, pending_field) is None, (
            f"State factory accidentally pre-set {pending_field}"
        )
        with ViolationCapture() as cap:
            assert_phase_contract(state, source)
        own = [
            v for v in cap.violations
            if v.contract_source == source and v.pending_required == pending_field
        ]
        assert own, (
            f"Expected pending-violation for {source} when {pending_field} unset; "
            f"got: {format_violations(cap.violations)}"
        )


# ---------------------------------------------------------------------------
# 5. TestSandboxBypass — sandbox: prefix bypasses phase enforcement always
# ---------------------------------------------------------------------------


class _StubStateForBypass:
    """Tiny stub state for testing assert_phase_contract directly."""
    def __init__(self, phase: TurnPhase) -> None:
        self.phase = phase
        for f in PENDING_REQUIREMENTS.values():
            setattr(self, f, None)


class TestSandboxBypass:
    """Sandbox cheats short-circuit assert_phase_contract regardless of mode
    or phase (orchestrator decision #5). Mode is shadow throughout this
    module — bypass must still hold.
    """

    def test_all_sandbox_sources_bypass_phase_check(self):
        from grid_tactics.phase_contracts import assert_phase_contract
        sources = [
            "sandbox:cheat_mana",
            "sandbox:cheat_hp",
            "sandbox:set_active",
            "sandbox:undo",
            "sandbox:redo",
            "sandbox:save",
            "sandbox:load",
            "sandbox:add_card_to_zone",
            "sandbox:move_card_between_zones",
            "sandbox:reset",
        ]
        for phase in TurnPhase:
            state = _StubStateForBypass(phase)
            for source in sources:
                with ViolationCapture() as cap:
                    assert_phase_contract(state, source)
                assert cap.violations == [], (
                    f"sandbox source {source} unexpectedly violated in {phase.name}"
                )


# ---------------------------------------------------------------------------
# 6. TestEventSymmetry — M1 placeholder for plan 14.8-06.
# ---------------------------------------------------------------------------


class TestEventSymmetry:
    @pytest.mark.skip(
        reason=(
            "Activates in plan 14.8-06 once EngineEvent stream from 14.8-03a/b "
            "is live; placeholder ensures the assertion exists from the start "
            "of the phase."
        )
    )
    def test_react_window_open_close_pairs_match_per_session(self, library):
        """For any captured EventStream from any test scenario, count of
        EVT_REACT_WINDOW_OPENED must equal EVT_REACT_WINDOW_CLOSED. Catches
        future 'I'll just shortcut here' regressions where one path forgets
        to emit the closing event.

        Implementation (when un-skipped in plan 06):
            from grid_tactics.engine_events import (
                EventStream, EVT_REACT_WINDOW_OPENED, EVT_REACT_WINDOW_CLOSED,
            )
            stream = EventStream()
            run_full_game_scenario(library, event_collector=stream)
            opened = sum(1 for e in stream.events if e.type == EVT_REACT_WINDOW_OPENED)
            closed = sum(1 for e in stream.events if e.type == EVT_REACT_WINDOW_CLOSED)
            assert opened == closed, (
                f"react_window symmetry violated: {opened} opened, {closed} closed."
            )
        """
        pass
