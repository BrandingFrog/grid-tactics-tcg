---
status: resolved
trigger: "Sandbox deploy silent-fail (rescue-captured from remote stuck session)"
created: 2026-04-11
updated: 2026-04-11
---

# Sandbox deploy silent-fail — React window hypothesis

**Captured:** 2026-04-11
**Source:** rescued from a stuck remote Claude Code session (mobile app) before termination —
its queued feedback would have been lost otherwise.

## Failure under investigation

Task name: "Make sandbox screen match play screen"

Repro that was being debugged:

- Card 1: **Common Rat** (`nid 22`, 1🟦 Wood, 10🗡️/10🤍, melee, no effects)
- **Expected:** deploy to P1 back row, no on-summon effect. Forward movement 1 tile/action.
  Melee attack adjacent enemy for 10🤍 damage, takes 10🤍 back.
- **Actual:** deploy failed silently. Mana stuck at 1. "Something is racy."

Stuck session's last note before termination: "Let me debug step-by-step" — it was mid-Playwright
when terminated (the MCP browser was the whole reason `browser_navigate` was failing in the
sibling session with "Browser is already in use").

## Hypothesis to test

> **friend says react is causing issues because you can't respond to it to pass**
> **maybe that's the issue**

Reading between the lines: when P1 plays `sandbox_apply_action(PLAY_CARD)` the engine opens a
react window for P2. In a real game P2 would auto-pass the react window (no legal reacts in hand,
or decline). In sandbox mode there is **no P2 client** — nothing is driving the react decline,
so the server may be sitting in `Phase.REACT_WINDOW` waiting for a react/skip action that never
comes.

That would match the symptom:

- Deploy "silently fails" → the action *was* accepted server-side but the follow-up state
  transition (resolving the play, deducting mana, placing the minion on the board) is gated
  behind `react_window_resolved`.
- Mana "stuck at 1" → because the play never resolves, `state.mana[0]` is never decremented.
  The client sees the pre-action snapshot on the next `sandbox_state` emit.
- "Something is racy" → not actually a race. It's a missing auto-pass in sandbox mode.

## What to check before writing a fix

1. `src/grid_tactics/server/sandbox_session.py` (or wherever `sandbox_apply_action` lives) —
   does it call `state.step(action)` once, or does it loop until the phase is back to `ACTION`?
   If single-step, after a PLAY that opens a react window the state sits in `REACT_WINDOW`
   waiting on the opponent.
2. Same file — is there any auto-pass / auto-skip-react logic for the non-active player in
   sandbox mode? If not, that's the gap.
3. `src/grid_tactics/engine/phase.py` (or wherever react window is handled) — confirm that
   `PASS` from the reacting player is legal during `REACT_WINDOW`, so the fix can just emit a
   synthetic `SKIP_REACT` action from the server after the play.
4. `phases/14.6-sandbox-mode/14.6-CONTEXT.md` — may already document the god-view / single-client
   assumption that makes this gap obvious in hindsight.

## Suggested fix shape (for the debug session that picks this up)

After every successful `state.step(action)` in the sandbox handler, check `state.phase`:

```python
# Sandbox has no opponent client. If the action opened a react window for
# the non-active player, resolve it immediately by auto-skipping — otherwise
# the turn hangs and looks like a silent failure client-side.
while state.phase == Phase.REACT_WINDOW:
    state.step(Action.skip_react())  # or the sandbox-specific equivalent
```

Then emit `sandbox_state` once at the end, so the client sees a single consistent snapshot.

Either that, or refactor the sandbox handler to always drive both players until phase is back
to `ACTION` — cleaner, but bigger change.

## Route for picking this up

This is a real bug, not just a note — it belongs in `/gsd:debug`, not a casual scratchpad.
When someone loops back here:

1. `/gsd:debug` — hypothesis above is the starting point
2. First check: does the sandbox session's `apply_action` handle react windows? (fastest path
   to confirm or kill the hypothesis)
3. If confirmed, fix is tiny; verification is Playwright walkthrough identical to the one the
   stuck session was running (deploy Common Rat → assert mana went 1→0 and board has rat).

## Current Focus

hypothesis: React hypothesis is CONFIRMED (mechanism different from original guess — the
  engine DOES spend mana and deploy the rat on the single resolve_action call; the issue is
  that the state then sits in REACT phase waiting for a PASS that the sandbox UI has no way
  to issue because isReactWindow() requires react_player_idx === myPlayerIdx and sandbox
  pins myPlayerIdx=active_view_idx=0 while react_player_idx=1).
test: Wrote a direct Python repro (no server) that constructs SandboxSession, adds Common
  Rat to P1 hand, calls apply_action(PLAY_CARD). Inspected state before/after.
expecting: If the hypothesis is right, after apply_action the state will be in phase=REACT
  and legal_actions will contain only PASS (because P2 has no react cards). User has no UI
  path to issue that PASS.
next_action: Write a failing pytest that asserts the post-apply_action state is back in
  ACTION phase (i.e. the sandbox should auto-resolve trivial react windows). Then implement
  the fix in SandboxSession.apply_action: while state.phase == REACT and only PASS is legal,
  auto-apply PASS. Then re-run the test.

## Evidence

- timestamp: 2026-04-11T01 (initial repro)
  checked: src/grid_tactics/server/sandbox_session.py SandboxSession.apply_action
  found: Calls legal_actions + resolve_action exactly ONCE. No loop on phase.
  implication: After a PLAY_CARD that transitions to REACT, the session is left sitting
    in REACT with no further progress.

- timestamp: 2026-04-11T01
  checked: src/grid_tactics/action_resolver.py _apply_play_card + main path
  found: resolve_action spends mana (line 301), deploys the minion (line 343 via
    _deploy_minion), THEN transitions to TurnPhase.REACT (lines 1263-1269). So the mana
    decrement and board placement happen BEFORE the phase flip.
  implication: The original symptom description "mana stuck at 1, rat not on board" is
    actually WRONG about the server state. After apply_action the state correctly shows
    mana=0 and rat on board. The real symptom is "state is stuck in REACT phase".

- timestamp: 2026-04-11T01
  checked: Live Python repro via `PYTHONPATH=src python -c` harness
  found:
    Before: phase=0 (ACTION), P1 mana=1, P1 hand=(22,), 0 minions
    After apply_action: phase=1 (REACT), active_player_idx=0, react_player_idx=1,
      P1 mana=0, P1 hand=(), 1 minion on board.
    new legal_actions types: ['PASS']  (only PASS, P2 has no react cards)
  implication: Server state IS correct after the single resolve_action call. The stuck
    piece is the REACT phase — specifically, P2 has no way to issue the required PASS.

- timestamp: 2026-04-11T01
  checked: Followed up the repro with session.apply_action(pass_action())
  found: State cleanly resolves back to phase=0 (ACTION), active_player_idx=1, P2 mana=1,
    P1 mana=0, 1 minion on board. NOT game over, turn_number advanced.
  implication: The PASS action from the REACT state is LEGAL in the sandbox harness — the
    fix is just to auto-apply it when it's the ONLY legal action. This matches the
    multiplayer play-screen behavior and doesn't require any new engine code.

- timestamp: 2026-04-11T01
  checked: src/grid_tactics/server/static/game.js renderActionBar around line 4509
  found: The REAL multiplayer play screen has an auto-skip block:
    ```
    if (gameState.phase === 1 && legalActions.length === 1
            && legalActions[0].action_type === 4) {
        submitAction({ action_type: 4 });
        return;
    }
    ```
    This is client-side auto-pass when the only legal react is PASS. It fires from
    renderActionBar which is called after every state_update.
  implication: In REAL multiplayer P2's client auto-passes empty react windows. Sandbox
    has NO equivalent path — renderSandbox does not call renderActionBar and the sandbox
    has no isReactWindow()-aware UI at all. So the fix is either:
      (A) Add equivalent auto-pass in the server-side SandboxSession.apply_action (drain
          trivial react windows as part of the "apply" step), OR
      (B) Add a client-side auto-pass block in the sandbox_state handler.
    (A) is preferred: it keeps the emit cycle at one sandbox_state per user action,
    matches the spirit of "one action = one state snapshot", and is testable at the unit
    level without a browser. (B) would emit N times and couple the fix to DOM timing.

- timestamp: 2026-04-11T01
  checked: view_filter.py — is the client seeing a filtered state that hides the
    post-play mana/minion?
  found: filter_state_for_player only hides opponent hand and both decks and seed; it
    does NOT hide mana/board/phase. Sandbox doesn't even call it (emits raw god-view
    via sandbox.state.to_dict).
  implication: Rules out the "view_filter is lying" hypothesis. The state emitted to
    the client genuinely has mana=0 and rat on board — the original symptom description
    was mistaken about the server state; what the user actually sees is that mana=0 but
    NO subsequent action is possible because the session is stuck in REACT phase with
    no UI path to issue PASS.

## Eliminated

- hypothesis: "apply_action doesn't actually spend mana or deploy the minion — something
    is blocking the write path."
  evidence: Direct Python repro shows mana=0 and 1 minion on board immediately after
    apply_action. The write path works; the state is just in REACT phase afterward.
  timestamp: 2026-04-11T01

- hypothesis: "view_filter hides the post-play state so client sees pre-play snapshot."
  evidence: Sandbox emit uses raw `sandbox.state.to_dict()` with NO view_filter call;
    view_filter only hides opponent hand / decks / seed anyway.
  timestamp: 2026-04-11T01

- hypothesis: "There's a race condition between apply_action and the emit."
  evidence: Both run synchronously under `sandbox.lock` in the same handler thread.
    No async boundary.
  timestamp: 2026-04-11T01

## Resolution

root_cause: |
  SandboxSession.apply_action called resolve_action exactly once per user
  submission. When the action opened a react window (PLAY_CARD, ATTACK,
  SACRIFICE), the state correctly advanced (mana spent, minion placed,
  damage applied) and transitioned to TurnPhase.REACT with
  react_player_idx = 1 - active_player_idx.

  In real multiplayer this is fine because the inactive player's CLIENT
  auto-submits PASS via the auto-skip-empty-react block in renderActionBar
  (game.js around `gameState.phase === 1 && legalActions.length === 1`).
  The P2 client sees its own legal_actions=[PASS] and auto-submits.

  Sandbox has no second client. The single human driver has
  active_view_idx pinned to 0, so isReactWindow() returns false (it checks
  react_player_idx === myPlayerIdx). renderSandbox also doesn't call
  renderActionBar, so even the client-side auto-pass wouldn't fire. Net
  result: the session silently hung in REACT phase waiting for a PASS that
  no UI path could generate. From the user's POV, the deploy "partially
  worked" (mana did decrement and rat was on board, in the raw state) but
  the turn never ended and subsequent actions couldn't be taken.

  The original symptom description "mana stuck at 1, rat not on board" was
  slightly off — the state WAS updated, but the UX looked broken because
  the session was frozen mid-turn.

fix: |
  SandboxSession.apply_action now auto-drains trivial react windows
  immediately after the initial resolve_action. While the state is in
  REACT phase AND the only legal action is PASS, keep submitting PASS
  through the existing resolve_action path until we're either back in
  ACTION phase or there's a real decision to make (react cards available).
  Bounded to 16 iterations as a belt-and-braces guard against pathological
  engine states.

  This mirrors the multiplayer client's auto-skip-empty-react logic,
  preserves the invariant that sandbox uses the same rule engine as real
  games (no new engine code, no "god mode react bypass"), and leaves
  genuine react decisions intact for users who put react cards in P2's
  hand to test those flows.

  No new classes, no changes to action_resolver or react_stack, no engine
  duplication. 14-line edit in sandbox_session.py plus a 2-line import
  expansion.

verification: |
  1. Two new pytest unit tests in tests/server/test_sandbox_session.py:
     - test_apply_action_drains_trivial_react_window — confirms mana=0,
       rat on board, phase=ACTION, active_player_idx=1, react_player_idx
       is None after deploying a rat with 1 mana.
     - test_apply_action_preserves_react_window_when_opponent_has_reacts —
       confirms the drain does NOT fire when P2 has a Dark Mirror (react
       that counters OPPONENT_PLAYS_MINION) in hand, so the user can
       still exercise react flows.
  2. Updated tests/e2e/test_sandbox_smoke.py::test_03_click_to_deploy_reuses_live_game_handlers
     with regression guard assertions: sandboxState.phase === 0,
     react_player_idx === null, active_player_idx === 1 after deploy.
     The existing test already clicked hand + tile and asserted mana/rat
     visibility — those passed under the bug because the engine DID
     update state before entering REACT. The new phase/active-player
     assertions are what actually catch the stuck-in-REACT case.
  3. Verified regression coverage: stashed sandbox_session.py, re-ran
     the e2e test, confirmed it FAILS with the exact message
     "sandbox stuck in REACT phase (phase=1) after deploy". Popped
     the stash, re-ran, confirmed GREEN.
  4. Full sandbox test suite: 64 unit + 5 e2e = 69 tests, all pass.
  5. Core engine suite (action_resolver, legal_actions, react_stack,
     game_flow, game_loop, effect_resolver, status_effects,
     activated_abilities, win_detection, sacrifice, integration): all
     pass (332 tests).
  6. Three pre-existing failures on master (test_spectator_receives_state_update,
     test_member_count, test_build_valid_deck) also fail without the
     sandbox fix — confirmed unrelated.

files_changed:
  - src/grid_tactics/server/sandbox_session.py (import + apply_action drain loop)
  - tests/server/test_sandbox_session.py (2 new regression tests)
  - tests/e2e/test_sandbox_smoke.py (phase/react/active assertions in test 3)
