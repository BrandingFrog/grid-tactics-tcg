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
