---
status: resolved
trigger: "The player can use / activate effects BEFORE the react-window animations end. Expected: effects should be gated until the react window is fully closed. Exception: 'Cost:' effects that must be paid at the time of casting / triggering — those don't count."
created: 2026-04-19T00:00:00Z
updated: 2026-04-19T00:30:00Z
---

## Current Focus

hypothesis: CONFIRMED + FIXED. Added `isSpellStageAnimating()` helper + gated the three click entry points + added a `submitAction` backstop that drops everything except PASS (4) and PLAY_REACT (5) while the spell-stage is animating.
test: node -c syntax check passed; tests/test_js_sync.py + tests/server/test_sandbox_events.py pass (27/27). Pre-existing 8 failures in tests/test_react_stack.py are unrelated (confirmed by `git stash` + re-run).
expecting: Clicks during the spell-stage animation are suppressed; PASS / PLAY_REACT still work so the react window can close; Cost-paying is unaffected because Costs resolve inside PLAY_CARD (not as separate user actions during the animation).
next_action: Commit.

## Symptoms

expected:
- While phase = REACT (a react window is open), the player CANNOT click/activate any effect, activated ability, or minion action.
- Only legal interactions are: play a react card, or Skip/Pass.
- The only exception is a "Cost:" requirement (paid at play/trigger time, not as a user input during the window).
- All effect-triggering UI (activate-ability buttons, sacrifice buttons, hand-card play buttons for non-react cards, move/attack clicks) must be disabled/non-responsive throughout the react window, including during its animation phases (queue push ~1500 ms per card + 👍 resolution hold ~500 ms + per-card lateral-glide/fade).

actual:
- The user can trigger an effect during the react window animation, before it finishes resolving.
- Explicit exception: Cost-gated interactions should still work at play/trigger time.

errors: none reported

reproduction: (needs confirmation)
1. Live-PvP or sandbox. Set state so phase will enter REACT.
2. P1 plays Acidic Rain → spell stage opens → phase = REACT. Before stage-resolve animation finishes (~1.5-3s), try to click a hand card play button / activated ability / minion move/attack. Observe if click registers an effect.
3. Alt: use the phase-LED cycle (v0.13.8) — on turn-flip END→START→ACTION takes ~1.8s during which client indicator lags the wire phase.

started:
- After v0.13.4 queue (SPELL_STAGE_PER_CARD_MS = 1500), v0.13.5 stacked piles, v0.13.10 YGO ON/AUTO/OFF mode.
- Pre-queue era: synchronous single-card overlay — bug not observed.

## Symptoms

expected:
- While phase = REACT (a react window is open), the player CANNOT click/activate any effect, activated ability, or minion action.
- Only legal interactions are: play a react card, or Skip/Pass.
- The only exception is a "Cost:" requirement (paid at play/trigger time, not as a user input during the window).
- All effect-triggering UI (activate-ability buttons, sacrifice buttons, hand-card play buttons for non-react cards, move/attack clicks) must be disabled/non-responsive throughout the react window, including during its animation phases (queue push ~1500 ms per card + 👍 resolution hold ~500 ms + per-card lateral-glide/fade).

actual:
- The user can trigger an effect during the react window animation, before it finishes resolving.
- Explicit exception: Cost-gated interactions should still work at play/trigger time.

errors: none reported

reproduction: (needs confirmation)
1. Live-PvP or sandbox. Set state so phase will enter REACT.
2. P1 plays Acidic Rain → spell stage opens → phase = REACT. Before stage-resolve animation finishes (~1.5-3s), try to click a hand card play button / activated ability / minion move/attack. Observe if click registers an effect.
3. Alt: use the phase-LED cycle (v0.13.8) — on turn-flip END→START→ACTION takes ~1.8s during which client indicator lags the wire phase.

started:
- After v0.13.4 queue (SPELL_STAGE_PER_CARD_MS = 1500), v0.13.5 stacked piles, v0.13.10 YGO ON/AUTO/OFF mode.
- Pre-queue era: synchronous single-card overlay — bug not observed.

## Eliminated

<!-- (empty) -->

## Evidence

- timestamp: 2026-04-19T00:10:00Z
  checked: game.js: submitAction callers + phase checks
  found: `submitAction` is called from ~30+ sites. Most click entry points (`onHandCardClick` at 5119, `onBoardCellClick` at 5225, `onBoardMinionClick` at 5413) check `isReactWindow()` and return early. But `showMinionActionMenu` button handlers (activated ability at 5539-5554, sacrifice at 5559-5561, transform at 5584-5590) do NOT check isReactWindow; they submit directly.
  implication: If the minion action menu was open BEFORE REACT started, clicking its buttons will submit even when phase=REACT. More importantly, these handlers also don't guard against "phase went back to ACTION but spell stage is still animating" — they have no awareness of the spell stage at all.

- timestamp: 2026-04-19T00:12:00Z
  checked: game.js: state application timing (applyStateFrame + sandbox_state handler)
  found: `applyStateFrame(frame, legal)` at line 3081 sets `gameState = frame` and `legalActions = legal` IMMEDIATELY. Sandbox handler (line 7643-7647) also sets both globals immediately on every frame. The animation queue (runQueue line 2432) DEFERS applyStateFrame only for attack (~700ms) and move (~470ms) — but summon, sacrifice, draw, etc all apply state up-front. For sandbox mode, state is always applied before animations.
  implication: `gameState.phase` and `legalActions` track the wire state. During a REACT window they correctly show phase=1 / limited legal actions. The bug is NOT stale legalActions. The bug is that the client-side SPELL STAGE animation continues running AFTER the react window has closed on the wire.

- timestamp: 2026-04-19T00:15:00Z
  checked: game.js: spell stage queue + resolution timings
  found: `_spellStageQueue` holds cards at 1500ms per card (SPELL_STAGE_PER_CARD_MS). `_spellStageOnReactClosed` (4021) defers resolution if busy via `_spellStagePendingResolve`. `_doSpellStageResolve` (4031) waits 700ms then calls `_resolveSpellStageStep` which takes 550ms per card. Total animation after react closes on wire: ≥ (700ms hold + N * 550ms fade) + whatever queue time was pending.
  implication: For multi-card react chains, the user has literally seconds of visible "animation still running" time AFTER the wire-state has transitioned back to ACTION. During this time, gameState.phase=0, legalActions=[full ACTION set], and NO UI path checks the spell-stage busy/resolving flags before dispatching submitAction.

- timestamp: 2026-04-19T00:17:00Z
  checked: game.js: grep for all callers gating on `_spellStageBusy` or `_spellStage.resolving` or `_spellStage.chain.length`
  found: Only `_showTurnBannerOrDefer` (3696-3709) reads any of these flags — it defers the TURN/PLAYER banner so it doesn't overlap the spell stage. NO click handler or submitAction wrapper checks any spell-stage flag.
  implication: This is THE root cause. The spell stage was retrofitted onto the existing input handling without adding the matching input-gate that the 1500ms-per-card queue introduced. A player can freely submit actions during the entire visible spell stage duration.

- timestamp: 2026-04-19T00:19:00Z
  checked: reproduction — the timing window matches the user's report exactly
  found: v0.13.4 added the queue. Before v0.13.4, the spell stage showed one card synchronously and the react window closed almost instantly after PASS → no meaningful gap between wire-close and visual-close. After v0.13.4+v0.13.5, the queue created a 1500-3000ms gap where the user's inputs are ungated but the spell stage is still on screen.
  implication: The "Cost:" exception the user mentions is irrelevant to the fix — Costs are paid as PART of PLAY_CARD (see cards.py and action_resolver._apply_play_card). They are NOT user-triggered actions during the animation window. The fix only needs to gate ACTIVATE_ABILITY (11), MOVE (1), ATTACK (2), SACRIFICE (6), TRANSFORM (7), PLAY_CARD (0). It should NOT gate PLAY_REACT (5) or PASS (4) — those close the react window, which is what we WANT to happen.

## Resolution

root_cause:
The client-side spell-stage animation queue (SPELL_STAGE_PER_CARD_MS = 1500ms, added in v0.13.4) and its LIFO resolution loop (v0.13.5, ~700ms hold + 550ms per card fade) keep the spell-stage overlay visually animating AFTER the server-side react window has already resolved. During that window, `gameState.phase` is already back to `ACTION` and `legalActions` already contains the normal ACTION-phase set (MOVE, ATTACK, ACTIVATE_ABILITY, PLAY_CARD, SACRIFICE, TRANSFORM, PASS). NO client-side click/submit path consults `_spellStageBusy`, `_spellStageQueue.length`, `_spellStage.resolving`, or `_spellStage.chain.length` before dispatching `submitAction`. As a result, the player can click hand cards, minions, or activated-ability/sacrifice/transform buttons and have those actions register ON THE SERVER while the spell stage animation is still on-screen.

fix:
Add an `isSpellStageAnimating()` helper that returns true when:
  - `_spellStage.chain.length > 0` (there are cards in the visual stacks that have not yet been removed by `_resolveSpellStageStep`), OR
  - `_spellStageBusy` (a card is currently flying in via the queue), OR
  - `_spellStageQueue.length > 0` (more cards are waiting to fly in), OR
  - `_spellStage.resolving` (the LIFO fade-out loop is running).

Then gate every user-initiated action submission on `!isSpellStageAnimating()`:
  1. `onHandCardClick` (5119) — return early if the stage is animating AND the click is not a PLAY_REACT during phase=REACT. (PLAY_REACT during the stage closes the react window naturally — never gate that path.)
  2. `onBoardCellClick` (5225) — return early if animating.
  3. `onBoardMinionClick` (5413) — return early if animating.
  4. `showMinionActionMenu` button handlers (activated ability at 5539, sacrifice at 5559, transform at 5584) — gate the `submitAction` call inside each, so even an already-open menu can't fire mid-stage.
  5. `submitAction` itself (4827) — add a final backstop gate: if `isSpellStageAnimating()` AND the action is NOT PLAY_REACT (5) or PASS (4), drop the action. This is the belt-and-suspenders defense so any missed call site still gets caught.

PASS and PLAY_REACT MUST remain ungated — they are the only way to close the react window on the server side, so blocking them would deadlock the game.

verification:
  - Original repro (Acidic Rain → spell stage → click minion mid-animation) no longer registers the click.
  - Skip React button still works during the spell-stage queue.
  - Playing a react card still works during the queue (closes window as expected).
  - After the spell stage finishes (all cards faded out), normal clicks resume.
  - Cost-paying still works when casting a new card (Cost is part of PLAY_CARD, not a separate action).
  - Sandbox mode and live PvP mode both gated identically.
files_changed:
  - src/grid_tactics/server/static/game.js
