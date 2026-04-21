---
status: resolved
trigger: "paladin-heal-fires-during-rat-react-window — v2: HP commit raced spell stage close"
created: 2026-04-20T00:00:00Z
updated: 2026-04-21T16:30:00Z
---

## Current Focus

hypothesis: CONFIRMED — prior fix only paced frame APPLICATION timing; each _applySandboxFrame still committed sandboxState + called renderSandbox synchronously. So F2 (paladin-heal frame) at t≈1500ms wrote HP=32 to the paladin tile while spell stage was still visible (mid resolve-pop / mid exit-fade).
test: VERIFIED via Playwright timeline (8s sample @ 50ms intervals): HP=30 throughout stage-visible window (t=58→3418ms), HP commits to 32 at the exact moment stage hides (t=3418ms), trigger pulse + glyph fires at t=3639ms over the now-correct paladin tile, turn-flip banner blooms at t=4637ms. No HP change while stage was up.
next_action: COMPLETE — fix landed in src/grid_tactics/server/static/game.js extending the post-stage deferral to cover the entire state commit (not just the blip).

## Symptoms

expected: 6 sequential beats over ~5s — rat react open (1s) → rat react close → end-of-turn open + paladin pulse → HP 30→32 tick → end-of-turn close → P2 banner.

actual: At +111ms after click: HP=32, active=P2, turn=2 in DOM. Spell-stage then animates rat react for 3.3s. Heal visibly happens DURING the rat react animation.

errors: None.

reproduction: Sandbox test "Fallen Paladin End: heal blip fires on turn end" (id end-of-turn-trigger-blip-paladin). Click rat → click bottom green tile.

started: After 9c414f9 introduced per-frame emit for sandbox auto-drain (per the original report — needs verification).

evidence_table:
| t (ms) | active | turn | paladinHp | spellStage |
| 0      | P1     | 1    | 30        | hidden     |
| +111   | P2     | 2    | 32        | VISIBLE    |
| +3400  | P2     | 2    | 32        | hidden     |

## Eliminated

(none yet)

## Evidence

- timestamp: 2026-04-20
  checked: src/grid_tactics/server/sandbox_session.py apply_action (lines 181-253)
  found: apply_action calls on_frame() after the user action AND after each drained PASS. Loop is bounded at 16 iterations. on_frame is the per-frame emit callback added in 9c414f9 (Issue A fix).
  implication: Server is correctly emitting one sandbox_state per intermediate state — frames exist on the wire.

- timestamp: 2026-04-20
  checked: src/grid_tactics/server/events.py handle_sandbox_apply_action (lines 855-894) and _emit_sandbox_state (lines 782-840)
  found: _emit_frame closure calls _emit_sandbox_state, which emits a 'sandbox_state' Socket.IO event. With async_mode="threading" (app.py:30), each emit flushes synchronously to the socket. Six emits land before the handler returns.
  implication: All 6 frames are physically transmitted. The race is on the receive side.

- timestamp: 2026-04-20
  checked: src/grid_tactics/server/static/game.js sandbox_state handler (lines 7697-7803)
  found: Handler synchronously: derives prev→next diffs (spell cast, react close, hp jobs, action job) → overwrites sandboxState/gameState immediately → calls renderSandbox() (which calls renderBoard, renderHand) → enqueues async animation jobs. There is NO gating of state application; each of the 6 frames overwrites the previous render synchronously. The browser only paints the last commit before yielding to layout.
  implication: HP=32 and turn=2 land in the DOM at +111ms (the last frame). The spell-stage queue then plays back the chain over 3.4s asynchronously, but the wire state has long since committed.

- timestamp: 2026-04-20
  checked: _spellStageQueue, _spellStageBusy, isSpellStageAnimating (game.js:3899-3914), _showTurnBannerOrDefer (3748-3761)
  found: There IS an existing pattern for deferring the turn banner behind the spell-stage queue (_pendingTurnBanner, flushed by _hideSpellStage at line 4206). But that pattern only covers the banner — board state, HP, active player are committed eagerly.
  implication: The "defer until spell stage idle" mechanism is the right shape. We need to extend it to (a) board minion state, (b) player HP, (c) active_player_idx, (d) turn_number, and probably (e) phase indicators. The simplest implementation: queue inbound sandbox_state payloads and only apply each one once the spell-stage chain is idle.

- timestamp: 2026-04-20
  checked: detectReactWindowClose (game.js:4158-4165), detectSpellCast (4216-4232)
  found: These functions diff prev vs next state to decide whether the spell stage opens or closes. They are the ONLY signal the client uses to drive the spell-stage timeline.
  implication: If we queue payloads and apply them only when the stage is idle, each payload's spellCast/spellClose effect on the stage will correctly drive the next pause, creating natural pacing.

- timestamp: 2026-04-20
  checked: data/tests/tests.json end-of-turn-trigger-blip-paladin (line 39-49)
  found: Setup places Paladin at (1,2) with current_health=30, gives P1 1 mana + a rat in hand. Click rat → click any green tile to deploy. The deploy triggers: (1) PLAY_CARD, (2) opens after-action REACT for P2, (3) auto-PASS drains it, (4) phase becomes END_OF_TURN, (5) enter_end_of_turn fires Paladin's heal trigger AND opens trigger react window, (6) auto-PASS drains, (7) phase advances → start of P2 turn.
  implication: At least 4-6 distinct sandbox_state frames are emitted. The user's expected pacing (rat lands → react open → react close → heal triggers → heal HP tick → react close → P2 banner) requires each frame to be visible for >= 700ms each.

- timestamp: 2026-04-21 (v2 follow-up)
  checked: src/grid_tactics/server/static/game.js _applySandboxFrame (lines 3822-4042 in pre-fix v1)
  found: V1 fix paced the FRAME APPLICATION timing via _sandboxNextApplyAt, but each apply still committed sandboxState + called renderSandbox synchronously. So when F2 was popped at t≈1500ms, the new HP=32 painted to the paladin tile while the spell stage was still resolving (~1860ms remaining). The _pendingTriggerBlip mechanism only delayed the BLIP animation, not the underlying minion-HP commit.
  implication: Need to defer the entire state commit (sandboxState write + renderSandbox call), not just the blip. Flush from _hideSpellStage's exit-fade callback so HP=32 commits exactly when stage hides, BEFORE the blip pulse fires.

- timestamp: 2026-04-21 (v2 verification)
  checked: Live Playwright verification @ 50ms sample interval, 8s window
  found: |
    Timeline with v2 fix in place:
      t=58ms   stage VISIBLE,  HP=30 (rat react opens)
      t=1534ms stage VISIBLE,  HP=30, pendF=1 (F2 deferred — KEY: HP unchanged)
      t=3418ms stage HIDDEN,   HP=32 (commit happens at exact moment of close)
      t=3639ms stage HIDDEN,   HP=32, pulse+glyph (trigger blip fires)
      t=4253ms stage HIDDEN,   HP=32, glyph still showing
      t=4637ms stage HIDDEN,   HP=32, TURN 2 / Active P2 (F3 applied)
  implication: Fix verified. HP did NOT change while stage was visible. Sequence matches user's spec.

## Hypothesis decision

Fix: queue inbound sandbox_state payloads on the client. Only apply the head of the queue when the spell-stage is idle (not animating, no chain, no busy queue). Each payload application can re-open the stage (e.g. if it's a new cast/react), in which case the next payload waits until the stage is idle again. This naturally serializes the visible chain to the user's expected pacing.

The first frame — when the queue is empty AND the stage is not animating — applies immediately so simple actions (e.g. cheating mana, undo, set_active) are still snappy.

There IS one subtlety: the very first cast (the rat play) needs to fire the spell stage. The spell stage is detected by detectSpellCast(prev, next) where prev is the buffered state and next is the new payload. So the buffering must preserve the (prev, next) diff at apply time, not at receive time.

## Resolution

root_cause: |
  Sandbox apply_action emits one sandbox_state Socket.IO event per intermediate
  state during trivial-react auto-drain (rat-deploy → after-action react open →
  drained PASS → end_of_turn enters → paladin trigger fires + opens trigger
  react → drained PASS → turn flip). With async_mode="threading" all 3 emits
  flush back-to-back before the JS event loop yields. The sandbox_state handler
  applied each frame synchronously (overwrote sandboxState, called renderSandbox
  immediately), so the browser only painted the LAST frame (HP=32, P2 active,
  turn=2) and the spell-stage animation queue then replayed the rat react
  chain over 3.4s on top of the already-committed post-flip state.

  The existing _pendingTurnBanner mechanism deferred only the turn banner
  behind the spell stage; HP, active player, board minion state, and trigger
  blips all committed eagerly.

  V2 ROOT CAUSE (after V1 fix): The V1 frame queue paced FRAME APPLICATION
  timing via _sandboxNextApplyAt, but inside each apply call sandboxState
  was still written and renderSandbox was still called synchronously. When
  F2 was popped at t≈1500ms (still within the spell stage's ~3.4s
  resolve+fade window), the paladin tile painted with HP=32 immediately,
  visible behind the closing stage. User reported "HP changes mid-stage,
  not after" — exactly what the V1 fix failed to address.

fix: |
  V1 (commit e2bff54): added _sandboxFrameQueue with Date.now()-based
  pacing and _pendingTriggerBlip deferral. PARTIAL FIX — paced when frames
  applied, but each apply still committed state synchronously.

  V2 (this fix): extends V1 to defer the entire state commit (not just
  the blip) behind the spell stage. All in src/grid_tactics/server/static/game.js:

  (a) New _pendingPostStageFrame global (parallel to _pendingTriggerBlip)
      holds a parked frame's full payload + side-effect job lists.

  (b) _applySandboxFrame now checks isSpellStageAnimating() at the top of
      its body. If true AND the frame doesn't open a NEW cast on the same
      frame AND the frame either (i) closes the stage OR (ii) carries a
      trigger blip → defer. Triggers _spellStageOnReactClosed immediately
      (so the chain's resolve animation starts) but parks payload + jobs
      for _hideSpellStage to flush. Updates _sandboxNextApplyAt to budget
      close (1900ms) + blip (1000ms) + safety (200ms). Frames unrelated
      to the stage (e.g. hand cheats while stage is up) take the immediate
      path so they don't park forever.

  (c) New _flushPendingPostStageFrame() commits sandboxState + calls
      renderSandbox + replays the parked actionJob/flyJobs/hpJobs. Called
      from _hideSpellStage's exit-fade callback BEFORE the blip flush, so
      the visual sequence is: stage hides → state commits (paladin tile
      shows new HP=32) → 200ms breath → trigger pulse + ⏳ glyph fires
      over the now-correct paladin tile → drain queue → next frame's
      banner.

  (d) Banner detection moved from inline call inside _applySandboxFrame
      (which fired even on deferred frames) to an explicit `firedBanner`
      flag captured pre-defer. Immediate path fires the banner via
      _showTurnBannerOrDefer; deferred path passes firedBanner through
      to _flushPendingPostStageFrame's caller (_hideSpellStage), which
      runs _runTurnFlipVisuals after a 200ms or 1300ms (if blip pending)
      breath.

  (e) _hideSpellStage now sources both pendingBlip and deferredBanner
      from EITHER the parked frame OR the legacy _pendingTriggerBlip /
      _pendingTurnBanner globals — parked frame wins. This handles the
      common case (deferred frame carries blip) AND the legacy case
      (immediate frame deferred a banner via _showTurnBannerOrDefer).

  No engine changes. No new server emits. Sandbox-only.

verification: |
  Verified via Playwright timeline (.planning/debug/verify_paladin_heal_v2.py):
  load http://127.0.0.1:5000/ → TESTS → SKIP twice to "Fallen Paladin
  End: heal blip fires on turn end" → click rat → click any cell-valid
  board cell → sample DOM @ 50ms intervals for 8s.

  Observed timeline:
    t=58ms   stage VISIBLE,  HP=30 (rat react opens)
    t=1534ms stage VISIBLE,  HP=30, pendF=1 (F2 deferred — KEY: HP unchanged)
    t=3418ms stage HIDDEN,   HP=32 (commit at exact moment of close)
    t=3639ms stage HIDDEN,   HP=32, pulse+glyph (trigger blip fires)
    t=4253ms stage HIDDEN,   HP=32, glyph still showing
    t=4637ms stage HIDDEN,   HP=32, TURN 2 / Active P2 (F3 applied)

  Visual sequence matches user spec:
    1. Rat lands on board.
    2. Spell stage shows rat react ~3.4s, HP=30 throughout.
    3. Spell stage closes.
    4. Paladin tile pulses + ⏳ glyph (~900ms).
    5. HP visible at 32 throughout the pulse (committed at step 3 boundary).
    6. End-of-turn react auto-resolves (no separate visual — engine state).
    7. TURN 2 / PLAYER 2 banner blooms.

  HP did NOT change while stage was visible. ✓

  Pre-existing pytest failures (test_evaluate_vs_random, test_run_game_*,
  test_react_stack tests, test_tensor_engine_parity, etc.) are unrelated
  to this change. Sandbox + events test suites pass: 68 / 68.

  JS syntax check via `node -c` passes. All new symbols are declared
  exactly once.

files_changed:
  - src/grid_tactics/server/static/game.js (V1: sandbox frame queue +
    _pendingTriggerBlip + detectSpellStageClose helper. V2: extended to
    _pendingPostStageFrame deferral covering full state commit, with
    _flushPendingPostStageFrame called from _hideSpellStage exit fade.)
  - .planning/debug/verify_paladin_heal_v2.py (Playwright verification
    script — kept for future regression tests.)
