"""Phase contract enforcement for the Grid Tactics engine.

This module is the foundation of Phase 14.8's "comprehensive guarantee that
we're obeying the rules of the game" — every state-mutating engine call site
declares which contract authorized it, and the engine asserts at apply time
that the contract is legal in the current TurnPhase.

Contract sources are string-tagged for human readability in logs and debug
dumps. Format: "<category>:<name>" where category is one of:

- ``trigger``  — a TriggerType firing (on_play / on_death / on_summon / etc.)
- ``status``   — a status effect ticking (burn)
- ``action``   — a player-submitted ActionType being resolved
- ``system``   — engine-driven phase/turn/cleanup mutations
- ``sandbox``  — sandbox-only cheats (cheat_mana / set_active / undo / save / load)

The ``sandbox:`` category is the FIFTH category per orchestrator decision #5.
Any contract_source starting with ``sandbox:`` BYPASSES phase enforcement
entirely (the assertion function short-circuits on the prefix). Sandbox edits
will still flow through the event stream once plan 14.8-03 lands so the
client sees them, but they are NOT subject to the phase-legality check —
the user has god-mode by design.

Enforcement mode is controlled by env var ``CONTRACT_ENFORCEMENT_MODE``:

- ``off``    — assertions are no-ops (this plan's default; no behavior change)
- ``shadow`` — violations are logged at WARNING level but never raise
- ``strict`` — violations raise OutOfPhaseError (server catches in events.py
               and emits an ``error`` socket event without crashing the session)

OutOfPhaseError is SOFT-failure (orchestrator decision #2): the action is
rejected, state is unchanged, the session continues.

ON_DEATH allowed_phases enumerates exactly (ACTION, REACT, START_OF_TURN,
END_OF_TURN); ON_PLAY allowed_phases enumerates exactly (ACTION, REACT) per
orchestrator decision #9. NOT wildcard — every contract source enumerates
its phases explicitly.

Pending-state-bound actions (TUTOR_SELECT, DEATH_TARGET_PICK, REVIVE_PLACE,
TRIGGER_PICK, CONJURE_DEPLOY, decline variants, POST_MOVE_ATTACK decline)
declare allowed_phases as the permissive set AND a ``requires_pending``
field name in PENDING_REQUIREMENTS. The assertion checks pending FIRST
(orchestrator decision #8); if pending is satisfied, the phase check is
skipped (the modal interrupted some other phase legitimately).
"""

from __future__ import annotations

import logging
import os
import traceback
from typing import Optional

from .enums import ActionType, TriggerType, TurnPhase

# ---------------------------------------------------------------------------
# Logger for shadow-mode violation reporting
# ---------------------------------------------------------------------------

logger = logging.getLogger("grid_tactics.phase_contracts")


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class OutOfPhaseError(Exception):
    """Raised when a state mutation is attempted in a disallowed phase.

    Carries enough metadata for the server to emit a structured ``error``
    socket event to the client without crashing the session. Soft-failure
    semantics per orchestrator decision #2: the action is rejected, state
    is unchanged.

    Attributes:
        contract_source: The "<category>:<name>" string the caller declared.
        phase: The TurnPhase the engine was in when the violation was caught.
        allowed_phases: The frozenset the contract source declares as legal.
                        Empty frozenset() if the source was UNKNOWN (typo /
                        new code path that missed the table).
        pending_required: For pending-bound actions, the GameState field name
                          that must be set before the action becomes legal.
                          None for non-pending sources.
        unknown_source: Set to True when the source is not in PHASE_CONTRACTS
                        and not in PENDING_REQUIREMENTS — surfaces typos.
    """

    def __init__(
        self,
        contract_source: str,
        phase: TurnPhase,
        allowed_phases: frozenset,
        pending_required: Optional[str] = None,
    ) -> None:
        self.contract_source = contract_source
        self.phase = phase
        self.allowed_phases = allowed_phases
        self.pending_required = pending_required
        self.unknown_source = False
        if pending_required is not None:
            msg = (
                f"Phase contract violation: {contract_source!r} requires "
                f"pending field {pending_required!r} to be set "
                f"(phase={phase.name}, none of the allowed phases matched)"
            )
        else:
            allowed_names = sorted(p.name for p in allowed_phases) if allowed_phases else ["(none)"]
            msg = (
                f"Phase contract violation: {contract_source!r} fired in "
                f"phase {phase.name}, allowed phases: {allowed_names}"
            )
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Enforcement mode (env-var driven, cached at module load for perf)
# ---------------------------------------------------------------------------


_VALID_MODES = ("off", "shadow", "strict")
_MODE_CACHE: Optional[str] = None


def get_enforcement_mode() -> str:
    """Return the current enforcement mode: 'off' | 'shadow' | 'strict'.

    Reads env var ``CONTRACT_ENFORCEMENT_MODE`` once and caches. Tests can
    flip via ``monkeypatch.setenv(...) + _reset_mode_cache()``.

    Phase 14.8-05: default is now 'shadow' (was 'off'). Production server
    logs violations without raising — observability without rejection risk.
    CI explicitly sets CONTRACT_ENFORCEMENT_MODE=strict via tests/conftest.py
    so test runs fail on any out-of-phase mutation. Set to 'off' explicitly
    to disable entirely (e.g. for legacy debugging tools).
    """
    global _MODE_CACHE
    if _MODE_CACHE is not None:
        return _MODE_CACHE
    raw = os.environ.get("CONTRACT_ENFORCEMENT_MODE", "shadow").strip().lower()
    if raw not in _VALID_MODES:
        logger.warning(
            "Invalid CONTRACT_ENFORCEMENT_MODE=%r — defaulting to 'shadow'", raw
        )
        raw = "shadow"
    _MODE_CACHE = raw
    return _MODE_CACHE


def _reset_mode_cache() -> None:
    """Clear the cached mode. Tests use this after monkeypatch.setenv()."""
    global _MODE_CACHE
    _MODE_CACHE = None


# ---------------------------------------------------------------------------
# Contract tables — populated from research-doc audit
# ---------------------------------------------------------------------------

# Convenience aliases (keep code below readable).
_ACTION = TurnPhase.ACTION
_REACT = TurnPhase.REACT
_START = TurnPhase.START_OF_TURN
_END = TurnPhase.END_OF_TURN
_ALL_PHASES = frozenset({_ACTION, _REACT, _START, _END})

PHASE_CONTRACTS: dict[str, frozenset[TurnPhase]] = {
    # ------------------------------------------------------------------
    # Trigger-bound contracts (per research §"Trigger-bound contracts")
    # 10 entries. PASSIVE was DELETED from TriggerType in plan 14.8-05 —
    # no contract entry exists for it; any re-introduction would fail at
    # card-JSON load time (CardLoader._parse_enum).
    # ------------------------------------------------------------------
    # ON_PLAY fires in ACTION (cast originator) AND in REACT (deferred
    # magic resolves during react-stack LIFO drain) — orchestrator
    # decision #9: explicit pair, not wildcard.
    "trigger:on_play": frozenset({_ACTION, _REACT}),
    # ON_SUMMON only fires inside Window B (AFTER_SUMMON_EFFECT) which
    # is always REACT.
    "trigger:on_summon": frozenset({_REACT}),
    # ON_DEATH allowed in all four phases (orchestrator decision #9 —
    # explicit, NOT wildcard). Death can occur from combat (ACTION),
    # from a react card destroying a minion (REACT), from burn tick
    # (START_OF_TURN), or from end-of-turn effects (END_OF_TURN).
    "trigger:on_death": frozenset({_ACTION, _REACT, _START, _END}),
    "trigger:on_attack": frozenset({_ACTION}),
    "trigger:on_damaged": frozenset({_ACTION}),
    "trigger:on_move": frozenset({_ACTION}),
    "trigger:on_discard": frozenset({_ACTION}),
    # ON_START_OF_TURN / ON_END_OF_TURN: primary firing happens in their
    # natural phase (START_OF_TURN / END_OF_TURN). Plan 14.8-02 widening:
    # REACT is also legal because when the simultaneous-trigger picker
    # modal opens (2+ start/end triggers from same player), the engine
    # transitions to REACT to surface the picker UI; the user-submitted
    # TRIGGER_PICK action then resumes _resolve_trigger_and_open_react_window
    # while phase=REACT. Without REACT in the allowed set, every
    # picker-resumed trigger drain warns. The assertion still gates against
    # ACTION (the trigger can never legitimately fire from main-phase
    # action handling).
    "trigger:on_start_of_turn": frozenset({_REACT, _START}),
    "trigger:on_end_of_turn": frozenset({_REACT, _END}),
    # AURA is read-time only — never mutates per orchestrator decision
    # #7. We include the entry so any defensive code that accidentally
    # tags `aura` doesn't trip the unknown-source path. Auras MUST NOT
    # call replace(state, ...); they are pure reads.
    "trigger:aura": _ALL_PHASES,
    # NOTE: "trigger:passive" was never in this table and the PASSIVE
    # TriggerType enum value itself was DELETED in plan 14.8-05. Any
    # caller that accidentally tags "trigger:passive" hits the
    # unknown_source branch of assert_phase_contract — loud failure in
    # strict mode, warning in shadow mode.
    # ------------------------------------------------------------------
    # Status-bound contracts
    # ------------------------------------------------------------------
    "status:burn": frozenset({_START}),
    # ------------------------------------------------------------------
    # Action-bound contracts (per research §"Action-bound contracts")
    # 20 entries (PASS is split into pass_action + pass_react)
    # ------------------------------------------------------------------
    "action:play_card": frozenset({_ACTION}),
    "action:move": frozenset({_ACTION}),
    "action:attack": frozenset({_ACTION}),
    # DRAW is reserved/legacy (auto-draw replaces it post-14.7-02) but
    # tagged for completeness.
    "action:draw": frozenset({_ACTION}),
    # PASS is split per research §"Action-bound contracts": fatigue
    # path vs. closing-the-react-window path are semantically distinct.
    "action:pass_action": frozenset({_ACTION}),
    "action:pass_react": frozenset({_REACT}),
    "action:play_react": frozenset({_REACT}),
    "action:sacrifice": frozenset({_ACTION}),
    "action:transform": frozenset({_ACTION}),
    "action:activate_ability": frozenset({_ACTION}),
    # Pending-bound actions: phase set is the permissive ALL_PHASES,
    # but the assertion gates on PENDING_REQUIREMENTS first. The phase
    # set exists only as a fallback for unsetting-pending-then-firing
    # edge cases that should never legitimately happen.
    "action:decline_post_move_attack": _ALL_PHASES,
    "action:tutor_select": _ALL_PHASES,
    "action:decline_tutor": _ALL_PHASES,
    "action:conjure_deploy": _ALL_PHASES,
    "action:decline_conjure": _ALL_PHASES,
    "action:death_target_pick": _ALL_PHASES,
    "action:revive_place": _ALL_PHASES,
    "action:decline_revive": _ALL_PHASES,
    "action:trigger_pick": _ALL_PHASES,
    "action:decline_trigger": _ALL_PHASES,
    # ------------------------------------------------------------------
    # System-bound contracts (per research §"System-bound contracts")
    # 10 entries
    # ------------------------------------------------------------------
    # Turn flip is the END→START boundary event — fires AT the
    # transition. Plan 14.8-02 widening: REACT is also legal because
    # close_end_react_and_advance_turn clears the react bookkeeping
    # (react_stack=(), react_player_idx=None, react_context=None) but
    # does NOT reset state.phase before calling _close_end_of_turn_and_flip,
    # so the flip helper sees state.phase=REACT on entry and immediately
    # transitions to ACTION (then enter_start_of_turn flips to START_OF_TURN).
    # Without REACT in the allowed set, every end-of-turn-via-react path
    # surfaces as a violation.
    "system:turn_flip": frozenset({_REACT, _END, _START}),
    # Called from turn flip (which has just set phase=ACTION as a transient)
    # OR from initial setup (which bootstraps in END_OF_TURN before the
    # first flip). Plan 14.8-02 widening: ACTION is added because
    # _close_end_of_turn_and_flip sets phase=ACTION as a transient before
    # enter_start_of_turn is called (line 885 of react_stack.py); without
    # ACTION the assertion fires on every turn flip.
    "system:enter_start_of_turn": frozenset({_ACTION, _START, _END}),
    # Called from ACTION when the active player ends their turn (no
    # legal actions / passes), or from END_OF_TURN when re-entering
    # after a react closes. Plan 14.8-02 widening: REACT is added
    # because resolve_react_stack tail dispatch (line 1706) calls
    # enter_end_of_turn AFTER clearing the react bookkeeping but
    # BEFORE the phase has been reset — at that moment state.phase
    # is still REACT. This is the documented smoking-gun #2 from
    # plan 14.8-01.
    "system:enter_end_of_turn": frozenset({_ACTION, _REACT, _END}),
    # Any phase can enter a react window (action triggers it, start /
    # end triggers open windows after their drain).
    "system:enter_react": _ALL_PHASES,
    # Closing a react window can only happen FROM react.
    "system:close_react_window": frozenset({_REACT}),
    # Cleanup runs after any HP-zero-touching mutation in any phase.
    "system:cleanup_dead_minions": _ALL_PHASES,
    # Game-over check runs after cleanup in any phase.
    "system:check_game_over": _ALL_PHASES,
    # Identity-preserving no-op — safe in any phase.
    "system:fizzle": _ALL_PHASES,
    # Trigger queue mgmt: enqueueing happens at start/end transitions
    # AND from action paths that defer triggers (on_death enqueues into
    # the priority queue from any phase that can host a death).
    "system:enqueue_triggers": frozenset({_ACTION, _START, _END}),
    "system:drain_triggers": _ALL_PHASES,
    # Plan 14.8-02: Summon compound-window resolvers (Window A → Window B
    # per spec §4.2). resolve_summon_declaration_originator and
    # resolve_summon_effect_originator are CALLED from inside
    # resolve_react_stack's LIFO drain — the originator was pushed during
    # the action:play_card resolution but its Window A / Window B
    # resolution happens at REACT phase. Tagged with system: because the
    # mutation is engine-driven (drain step) not action-driven; the
    # initiating action's contract has already been satisfied at push
    # time. This is documented smoking-gun #1 from plan 14.8-01.
    "system:resolve_summon_declaration": frozenset({_REACT}),
}

# ---------------------------------------------------------------------------
# Pending-state requirements for action sources
# ---------------------------------------------------------------------------
#
# For these contract sources, the assertion checks the named GameState
# field FIRST (must be non-None). If the field is set, the action is
# legitimate regardless of phase — the modal interrupted some other
# phase. If the field is NOT set, the assertion raises with the
# pending_required attribute populated for the server to surface to
# the client.
#
# Per orchestrator decision #8: pending check takes precedence over
# the phase check. This is critical because pending modals legally
# interrupt every phase, so the phase check would otherwise reject
# legitimate actions (e.g. picking a death target during a react chain
# that opened the modal).

PENDING_REQUIREMENTS: dict[str, str] = {
    "action:tutor_select": "pending_tutor_player_idx",
    "action:decline_tutor": "pending_tutor_player_idx",
    "action:conjure_deploy": "pending_conjure_deploy_card",
    "action:decline_conjure": "pending_conjure_deploy_card",
    "action:death_target_pick": "pending_death_target",
    "action:revive_place": "pending_revive_player_idx",
    "action:decline_revive": "pending_revive_player_idx",
    "action:trigger_pick": "pending_trigger_picker_idx",
    "action:decline_trigger": "pending_trigger_picker_idx",
    "action:decline_post_move_attack": "pending_post_move_attacker_id",
}

# Intentionally NOT in PENDING_REQUIREMENTS:
#
# MAGIC_CAST_ORIGINATOR — This is an internal originator pushed onto the
#   react stack by _cast_magic. It is NOT a player-submittable action;
#   resolution happens inside the engine when the react stack drains LIFO
#   (resolve_react_stack pops it and calls resolve_effect with
#   contract_source="trigger:on_play"). There is no incoming external
#   action whose contract_source is "action:magic_cast_originator" to
#   gate. The system: tags ("system:enter_react", "trigger:on_play")
#   cover the actual mutation sites.
#
# POST_MOVE_ATTACK choose path — When pending_post_move_attacker_id is
#   set, the player has TWO options: submit ATTACK (covered by
#   "action:attack" — phase gate ACTION applies normally; pending field
#   is checked client-side as a hint but the server's ATTACK handler
#   doesn't require pending_post_move_attacker_id to be set; a regular
#   ATTACK from a freshly-summoned-this-turn minion is the same code
#   path) OR submit DECLINE_POST_MOVE_ATTACK (covered by
#   "action:decline_post_move_attack" which IS in PENDING_REQUIREMENTS).
#   So the "choose ATTACK" path is gated by phase=ACTION; only the
#   decline path needs the pending field gate.


# ---------------------------------------------------------------------------
# Assertion entry point
# ---------------------------------------------------------------------------


# Test-only capture target — when set, _log_violation appends to it AS WELL AS
# emitting the warning. Used by tests/test_phase_contract_invariants.py to
# inspect shadow-mode violations across full simulation runs.
_capture_target: Optional["ViolationCapture"] = None


class ViolationCapture:
    """Context manager that captures phase-contract violations during shadow mode.

    Usage:
        with ViolationCapture() as cap:
            resolve_action(state, some_action, library)
        if cap.violations:
            pytest.fail(format_violations(cap.violations))

    Re-entrancy: stacked captures replace each other (only the innermost
    captures violations); on exit, the previous target is restored. Tests
    should not nest captures across test boundaries — use one capture per
    scenario.
    """

    def __init__(self) -> None:
        self.violations: list[OutOfPhaseError] = []
        self._prev_target: Optional["ViolationCapture"] = None

    def __enter__(self) -> "ViolationCapture":
        global _capture_target
        self._prev_target = _capture_target
        _capture_target = self
        return self

    def __exit__(self, *_args) -> None:
        global _capture_target
        _capture_target = self._prev_target


def format_violations(violations: list[OutOfPhaseError]) -> str:
    """Group violations by (contract_source, phase) and produce a bullet list.

    Used in pytest assertion messages so the diff shows ALL distinct
    violations in one shot rather than just the first.
    """
    if not violations:
        return "(none)"
    groups: dict[tuple[str, str, Optional[str]], int] = {}
    for v in violations:
        key = (
            v.contract_source,
            v.phase.name if hasattr(v.phase, "name") else str(v.phase),
            v.pending_required,
        )
        groups[key] = groups.get(key, 0) + 1
    lines = [f"{len(violations)} total violation(s) across {len(groups)} unique pattern(s):"]
    for (src, phase, pend), count in sorted(groups.items()):
        suffix = f" (pending_required={pend})" if pend else ""
        lines.append(f"  - [{count}x] source={src} phase={phase}{suffix}")
    return "\n".join(lines)


def _log_violation(err: OutOfPhaseError) -> None:
    """Structured WARNING log for shadow-mode violations.

    Includes contract_source, phase, allowed_phases, pending_required, and
    a truncated stack trace skipping pytest internals so the engine call
    site is the visible bottom frame.

    If a ViolationCapture is active, ALSO appends the error to its violations
    list — tests can iterate the full set of violations from a simulation run.
    """
    # Truncate stack to the engine frames (skip pytest/internal frames if
    # we can identify them by file path heuristic).
    frames = traceback.extract_stack()
    relevant = [
        f
        for f in frames
        if "site-packages" not in (f.filename or "")
        and "pytest" not in (f.filename or "").lower()
        and "phase_contracts.py" not in (f.filename or "")
    ][-8:]  # last 8 engine frames is plenty
    stack_summary = " -> ".join(
        f"{f.name}@{f.filename.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}:{f.lineno}"
        for f in relevant
    )
    logger.warning(
        "Phase contract violation: source=%s phase=%s allowed=%s "
        "pending_required=%s unknown_source=%s stack=%s",
        err.contract_source,
        err.phase.name,
        sorted(p.name for p in err.allowed_phases) if err.allowed_phases else [],
        err.pending_required,
        err.unknown_source,
        stack_summary,
    )
    if _capture_target is not None:
        _capture_target.violations.append(err)


def assert_phase_contract(state, source: str) -> None:
    """Assert that ``source`` is legal to fire in ``state.phase``.

    Behavior depends on enforcement mode:
      * off    — no-op (returns immediately)
      * shadow — log WARNING on violation, never raise
      * strict — raise OutOfPhaseError on violation

    Algorithm:
      1. If mode is off: return.
      2. If source starts with "sandbox:": return (5th-category bypass per
         orchestrator decision #5).
      3. If source is in PENDING_REQUIREMENTS: check the pending field
         FIRST (orchestrator decision #8). If set, return. If not set,
         raise/log with pending_required populated.
      4. Look up source in PHASE_CONTRACTS. If absent, raise/log with
         unknown_source=True (likely a typo or new code path that missed
         the table).
      5. Check state.phase ∈ allowed. If not, raise/log.
    """
    mode = get_enforcement_mode()
    if mode == "off":
        return

    # Sandbox category bypasses phase enforcement entirely.
    if source.startswith("sandbox:"):
        return

    # Pending-bound actions: pending field check takes precedence.
    if source in PENDING_REQUIREMENTS:
        field = PENDING_REQUIREMENTS[source]
        if getattr(state, field, None) is not None:
            return  # pending was set → action legitimate, skip phase check
        # Pending NOT set — the action was submitted out of context.
        # Fall back to phase check ONLY if the source is in PHASE_CONTRACTS
        # AND the phase matches (defense-in-depth: a malformed call could
        # pass a pending-bound source with the engine in a weird state).
        # In practice this branch raises because pending-bound actions all
        # have allowed_phases=ALL_PHASES, so the phase check never fails;
        # we want the pending_required attribute populated on the error.
        err = OutOfPhaseError(
            contract_source=source,
            phase=getattr(state, "phase", TurnPhase.ACTION),
            allowed_phases=PHASE_CONTRACTS.get(source, frozenset()),
            pending_required=field,
        )
        if mode == "shadow":
            _log_violation(err)
            return
        raise err

    # Standard phase check.
    allowed = PHASE_CONTRACTS.get(source)
    if allowed is None:
        # Unknown source — surface loudly.
        err = OutOfPhaseError(
            contract_source=source,
            phase=getattr(state, "phase", TurnPhase.ACTION),
            allowed_phases=frozenset(),
            pending_required=None,
        )
        err.unknown_source = True
        if mode == "shadow":
            _log_violation(err)
            return
        raise err

    if state.phase not in allowed:
        err = OutOfPhaseError(
            contract_source=source,
            phase=state.phase,
            allowed_phases=allowed,
            pending_required=None,
        )
        if mode == "shadow":
            _log_violation(err)
            return
        raise err


# ---------------------------------------------------------------------------
# Coverage helpers (used by tests + future invariant test in plan 14.8-02)
# ---------------------------------------------------------------------------


def expected_trigger_sources() -> set[str]:
    """Return the set of "trigger:<name>" sources the table SHOULD cover.

    Phase 14.8-05: PASSIVE was deleted from TriggerType so the legacy
    ``if t.name != "PASSIVE"`` filter is no longer needed. AURA is
    still included because we tag it for read-time documentation even
    though it never mutates.
    """
    return {
        f"trigger:{t.name.lower()}"
        for t in TriggerType
    }


def expected_action_sources() -> set[str]:
    """Return the set of "action:<name>" sources the table SHOULD cover.

    PASS is special — it maps to BOTH "action:pass_action" and
    "action:pass_react". All other action types map to a single source
    derived from their lowercased enum name.
    """
    sources: set[str] = set()
    for a in ActionType:
        if a.name == "PASS":
            sources.add("action:pass_action")
            sources.add("action:pass_react")
        else:
            sources.add(f"action:{a.name.lower()}")
    return sources


__all__ = [
    "OutOfPhaseError",
    "PHASE_CONTRACTS",
    "PENDING_REQUIREMENTS",
    "assert_phase_contract",
    "get_enforcement_mode",
    "_reset_mode_cache",
    "expected_trigger_sources",
    "expected_action_sources",
    "ViolationCapture",
    "format_violations",
]
