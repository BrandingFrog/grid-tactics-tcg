---
status: resolved
trigger: "sandbox react thrash + phantom HP ping on Test 1 (3-deep react chain)"
created: 2026-04-20T00:00:00Z
updated: 2026-04-20T22:15:00Z
---

## Current Focus

hypothesis: ROOT CAUSE CONFIRMED — client auto-skip in `renderActionBar` (game.js line 6747) races with server-side drain. When the server emits an INTERMEDIATE frame with phase=REACT + legal=[PASS] before the drain completes, the client auto-submits a REACT PASS. By the time that PASS hits the server, the server has already drained and is in ACTION phase. ACTION-phase PASS invokes `_apply_pass` which deals FATIGUE_DAMAGE=5 to the active player AND ends the turn. This produces: (1) extra unintended turn flip, (2) phase LED double-cycle, (3) phantom -5 HP ping.
test: Connected via socketio-client, loaded 'spell-stage-closes-with-thumbs-up' scenario, fired PLAY_CARD + PASS back-to-back — reproduced the full chain: P1 casts → REACT → ACTION (P2) → bogus PASS lands → P2 takes 5 damage → REACT → ACTION (P1, turn 3).
expecting: CONFIRMED
next_action: design + ship minimal fix

## Symptoms

expected: 3-deep react chain walks controlled ~1-2s per beat; phase LED transitions last ~900ms; HP changes only on actual card effects.
actual: phase badge flips ACTION->END->START->ACTION within ~3s; board gets 170+ class mutations in single tick; card clicks stop landing; phantom -5 HP indicators.
errors: no JS console errors, no Python exceptions
reproduction: start pvp_server, open /, click TESTS nav, load Test 1/17, double-click Acidic Rain in P1 hand to cast; observe phase badge thrash
started: after commit 9c414f9 (per-frame sandbox auto-drain emit)

## Eliminated

(none yet)

## Evidence

- timestamp: 2026-04-20
  checked: scripts/debug_sandbox_react_thrash.py — Python simulation of SandboxSession.apply_action with on_frame recorder, Test 1 setup, walk through 3-deep chain.
  found: Step 3 (P1 plays Prohibition) emits TWO frames via apply_action on_frame callback:
    - frame#2: phase=REACT, stack_len=3, legal_actions=[PASS] only (only_pass=True)
    - frame#3: phase=ACTION, stack_len=0, active=P2, turn=2 (drain completed the LIFO resolution + turn flip in one resolve_action call)
  implication: Client receives an intermediate REACT frame where the ONLY legal action is PASS — directly satisfies the client-side auto-skip condition in renderActionBar (game.js L6747): `if (gameState.phase === 1 && legalActions.some(a => a.action_type === 4)) { ... if (mode === 'auto' && onlyPass) submitAction({action_type: 4}); }`.

- timestamp: 2026-04-20
  checked: scripts/debug_sandbox_thrash_socket.py — socketio-client repro against live pvp_server. Loaded 'spell-stage-closes-with-thumbs-up' scenario, fired PLAY_CARD then PASS with 50ms gap (simulating client auto-skip race).
  found: Frames received:
    - frame#0 +3ms: phase=1(REACT), stack=1, legal=[4] (PASS only)
    - frame#1 +4ms: phase=0(ACTION), stack=0, turn=2, active=P2, legal=[1,4] (MOVE+PASS)
    - frame#2 +55ms: phase=1(REACT), p1_hp=95 (!), react_p=P1, legal=[4]
    - frame#3 +56ms: phase=0(ACTION), turn=3, active=P1, p1_hp=95
  implication: BOGUS PASS ARRIVES AFTER SERVER IS IN ACTION PHASE. Server's `resolve_action` routes ACTION-phase PASS to `_apply_pass` (action_resolver.py L120) which deals FATIGUE_DAMAGE=5 to the active player. P2 takes 5 face damage (100→95). The PASS also ends the turn → state opens end/start react windows → drain flips back to P1 (turn 3). This reproduces ALL user-visible symptoms: rapid active-player flip, extra LED END/START cycle, phantom -5 HP popup.

- timestamp: 2026-04-20
  checked: git log of 9c414f9 vs parent. Pre-fix apply_action drained server-side AND emitted ONLY the final state.
  found: Before 9c414f9, the client never saw the intermediate [PASS-only REACT] frame — it was collapsed into the ACTION frame before leaving the server. So the auto-skip path was unreachable during a sandbox drain.
  implication: 9c414f9 exposed a pre-existing latent bug: the client's sandbox-mode auto-skip was designed under the assumption that the sandbox drain hides trivial REACT windows. Per-frame emit broke that assumption. Fix options: (a) skip client-side auto-skip in sandbox mode since the server already drains, (b) only auto-skip when the legal PASS belongs to sandboxActiveViewIdx's player, (c) revert to server-drained emits for the REACT-leg frames and keep per-frame for the other transient signals. Option (a) is the smallest change and matches the server's existing responsibility split.

## Resolution

root_cause: Client-side auto-skip in `renderActionBar` (game.js L6747-6753) fires a PASS whenever an incoming sandbox_state shows `phase==REACT && legal_actions==[PASS]`. Before commit 9c414f9, such a state was never emitted in sandbox mode because apply_action drained PASS-only REACT windows server-side before emitting. 9c414f9 changed apply_action to emit per-frame, including the intermediate PASS-only REACT frame, which now trips the client auto-skip. The resulting PASS lands on the server AFTER the drain has already moved state to ACTION phase, so it routes to `_apply_pass` → FATIGUE_DAMAGE=5 to the active player → extra turn flip → visible thrash.

Emit-site fix was considered (skip emitting `phase==REACT + only-PASS` frames during drain) but rejected because the client's spell-stage chain animation tracks each card landing by stack-length delta across separate `apply_action` calls. Skipping those intermediate emits would lose the slam-in animation for the user's react card in the 3-deep chain. The correct fix is to remove the client-side duplication of server-side drain responsibility, which is what this patch does.
fix: Gated the `renderActionBar` auto-skip block with `!sandboxMode` (game.js L6747). In sandbox mode, the server's own drain handles trivial PASS-only REACT windows via `SandboxSession.apply_action`; the client auto-skip is redundant AND actively broken (the race produces fatigue damage + turn thrash). Guarding it off for sandbox preserves the real-multiplayer behavior (non-sandbox paths still auto-skip as before) while eliminating the race. Bumped `VERSION.json` to 0.13.19 so browser caches pick up the fix.
verification: PASSED. scripts/verify_sandbox_thrash_fix.py (simple scenario): 1 emit (PLAY_CARD), 0 PASS emits, both HPs stay at 100, final turn=2. scripts/verify_sandbox_3deep_fix.py (Test 1 full 3-deep chain via Playwright): 3 emits (PLAY_CARD + 2x PLAY_REACT), 0 PASS emits, 6 incoming frames tracing stack 0->1->2->3->0 cleanly, both HPs stay at 100, final turn=2 (single flip, not the pre-fix turn=3). Pre-existing sandbox e2e test failures (tests/e2e/test_sandbox_smoke.py) verified to be unrelated — same failures reproduce with my fix stashed away.
files_changed:
  - src/grid_tactics/server/static/game.js (L6747 — added !sandboxMode gate + explanatory comment)
  - src/grid_tactics/server/static/VERSION.json (0.13.18 -> 0.13.19)
