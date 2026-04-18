---
status: resolved
trigger: "sacrifice-svg-animation-missing — user reports the jumper SVG animation does not play when a minion performs SACRIFICE"
created: 2026-04-18T00:00:00Z
updated: 2026-04-18T00:00:00Z
---

## Current Focus

hypothesis: FIXED — two-layer gap: (1) sandbox server didn't enrich last_action; (2) sandbox_state client handler never dispatched deriveAnimationJob.
test: Playwright against local server confirms: SACRIFICE last_action rides the WS payload; .sacrifice-jumper SVG element appears at t+50ms, fades/translates toward enemy HP over 880ms, removed by t+900ms; hp-damage-popup fires after. Screenshot (sacrifice_fix_early.png) shows the pixel-art purple/white-glow jumper silhouette mid-jump toward P2.
expecting: User opens live site after deploy, runs the test, sees the jumper + damage blip sequence.
next_action: None — fix complete, tests pass, ready for commit + deploy.

## Symptoms

expected: Rat on row 4 (P2's back row; visually top of board since P1 perspective locks P1 at bottom) is selected, Sacrifice button clicked, the sprite morphs into a pixel-style purple+white-glowing jumping silhouette, it jumps a short distance forward toward the opponent HP display, then fades/transcends out. A damage blip pops on P2's face and P2's HP drops.
actual: User reports no SVG animation playing on sacrifice. Mechanics likely work (HP drop) but the visual morph/jump/fade is missing or wrong.
errors: None reported.
reproduction:
  1. Visit https://web-production-520c.up.railway.app/
  2. Click Tests tab
  3. Load `sacrifice-transcend-animation` test (first in list)
  4. Click Rat at top of board
  5. Click Sacrifice action button
  6. Observe — no jumper silhouette appears
started: Unknown; unclear if the animation ever worked in production or regressed

## Eliminated

<!-- Will be populated as hypotheses are disproved -->

## Evidence

- timestamp: 2026-04-18T00:00:00Z
  checked: data/tests/tests.json lines 12-24
  found: Test setup places rat at row=4 col=2 for player_idx=0. Matches BACK_ROW_P2=4 in types.py, so sacrifice IS legal for P1 minion on row 4. Scenario is valid.
  implication: The sacrifice action should be legal and clickable.

- timestamp: 2026-04-18T00:00:00Z
  checked: src/grid_tactics/server/static/game.js lines 3060-3159
  found: `SACRIFICE_JUMPER_SVG` constant defined (complex SVG with purple/white glow filter, jumper body). `playSacrificeTranscendAnimation(job, done)` function implemented — hides original sprite, creates `.sacrifice-jumper` fixed div on body, animates transform+opacity to enemy HP, removes after 880ms.
  implication: Animation code EXISTS in the codebase.

- timestamp: 2026-04-18T00:00:00Z
  checked: src/grid_tactics/server/static/game.js lines 3548-3553, 2170-2172
  found: Dispatcher has `case 'sacrifice_transcend'` routing to `playSacrificeTranscendAnimation`. `deriveAnimationJob` detects `la.type === 'SACRIFICE'` and returns `{type: 'sacrifice_transcend', payload: {pos: la.attacker_pos}}`.
  implication: Dispatch wiring is present — the animation should fire when a SACRIFICE last_action arrives with attacker_pos populated.

- timestamp: 2026-04-18T00:00:00Z
  checked: src/grid_tactics/server/view_filter.py `enrich_last_action` (lines 94-179)
  found: Function sets `attacker_pos` from `prev_state.get_minion(action.minion_id)` whenever action.minion_id is not None. SACRIFICE actions carry minion_id. For non-ATTACK/MOVE/PLAY_CARD types (including SACRIFICE) target_pos/damage/killed stay None but `type="SACRIFICE"` and `attacker_pos=[r,c]` should be emitted.
  implication: Server should correctly emit `last_action: {type: "SACRIFICE", attacker_pos: [4, 2], ...}` for P1's rat sacrifice.

- timestamp: 2026-04-18T00:00:00Z
  checked: Playwright live site — sandbox_state WS frame after sacrifice
  found: Payload keys present: active_player_idx, board, fatigue_counts, is_game_over, minions, next_minion_id, pending_action, pending_attack_*, pending_conjure_*, pending_death_*, pending_post_move_attacker_id, pending_revive_*, pending_tutor_*, phase, players, react_player_idx, react_stack, seed, turn_number, winner. **MISSING: last_action.** The server never enriches this field in sandbox mode.
  implication: Client's `deriveAnimationJob(prev, next)` sees `next.last_action === undefined`, skips the SACRIFICE branch, falls through to `next.pending_action`, which has `action_type=6` (SACRIFICE) — but the fallback block in `deriveAnimationJob` only handles PLAY_CARD (0), MOVE (1), ATTACK (2) and returns `{type:'noop'}` for anything else. So the sacrifice transcend animation is never dispatched.

- timestamp: 2026-04-18T00:00:00Z
  checked: src/grid_tactics/server/events.py lines 137-149 (real game emit) vs 711-744 (sandbox emit)
  found: Real multiplayer emit calls `enrich_last_action(state_dict, prev_state, state, resolved_action)`. Sandbox emit does NOT — it has `enrich_pending_*` calls but no `enrich_last_action`.
  implication: Root cause localised. Fix = propagate (prev_state, last_action) from SandboxSession.apply_action into _emit_sandbox_state and call enrich_last_action there.

- timestamp: 2026-04-18T00:00:00Z
  checked: Playwright mid-animation DOM sampling
  found: Sacrifice mechanically works — HP damage popup fires at T+50 (`<div class="damage-popup hp-damage-popup">-10</div>`), P2 HP drops from 100 to 90, Rat disappears from board. But **0** `.sacrifice-jumper` elements ever appear in the DOM (polled at T+50, 150, 300, 500, 800 ms).
  implication: Confirms the SVG jumper is not being injected — consistent with the root cause above.

- timestamp: 2026-04-18T00:00:00Z
  checked: src/grid_tactics/server/static/game.js sandbox_state handler (line 6501) vs multiplayer onStateUpdate (line 2934)
  found: SECOND root cause. After the server-side fix, last_action rides the payload (verified in WS frame), but the sandbox_state handler never calls `deriveAnimationJob(prev, next)`. Multiplayer calls it and enqueues the returned job. Sandbox derives only card-fly / spell-cast / hp-delta animations and then calls renderSandbox() immediately. Result: even with a SACRIFICE last_action, the sacrifice_transcend job was never queued, and the jumper never appeared.
  implication: Sandbox handler must mirror multiplayer's deriveAnimationJob dispatch to play action-keyed animations.

- timestamp: 2026-04-18T00:00:00Z
  checked: Playwright against local server after both fixes
  found: jumper element appears at t+50ms (opacity ~1.0, small translate); at t+150ms opacity 0.92 translate (28,-41); at t+400ms opacity 0.41 translate (45,-66) — jumping UP toward P2's face at screen-top; at t+900ms jumper removed, hp-damage-popup '-10' visible on P2. MutationObserver captured both elements in sequence. Screenshot (sacrifice_fix_early.png) shows the pixel-art purple/white-glow jumper silhouette perfectly matching the expected description.
  implication: Fix verified end-to-end. Also unlocks engine-action animations for other SACRIFICE/TRANSFORM/ACTIVATE_ABILITY cases (which the legacy pending_action fallback didn't cover) and gives attack/move/play_card animations their `last_action` data source in sandbox for free.

## Resolution

root_cause: Two coordinated gaps, both specific to sandbox mode:
  1. Server: `_emit_sandbox_state` in src/grid_tactics/server/events.py (line 711) omitted the `enrich_last_action` call that real multiplayer emit `_emit_state_to_players` performs (line 149). Sandbox payloads therefore lacked the `last_action` field entirely.
  2. Client: The `sandbox_state` socket handler in game.js (line 6501) never invoked `deriveAnimationJob(prev, next)`. It derived only card-fly / spell-cast / hp-delta jobs and then called `renderSandbox()` immediately, silently dropping any action-keyed animation job.
Taken together, the sacrifice-transcend SVG jumper code path (SACRIFICE_JUMPER_SVG + playSacrificeTranscendAnimation) was fully implemented but unreachable from sandbox/Tests mode. The HP-damage popup still fired because it's driven by a pure HP-delta diff, not by last_action — which is why the mechanic visibly worked while the animation was missing. Real multiplayer was never broken: it always went through `enrich_last_action` on the server and `deriveAnimationJob` on the client.
fix: Three changes —
  a) src/grid_tactics/server/sandbox_session.py — add `_last_prev_state` and `_last_action` attributes on SandboxSession; populate them in `apply_action` immediately before `resolve_action`; clear them in `_push_undo`, `undo`, `redo`, and `load_dict` so zone edits / cheat toggles / history navigation never replay stale animations. Expose via read-only `last_prev_state` / `last_action` properties.
  b) src/grid_tactics/server/events.py — inside `_emit_sandbox_state`, call `enrich_last_action(state_dict, sandbox.last_prev_state, state, sandbox.last_action)` alongside the existing `enrich_pending_*` calls. Mirrors real multiplayer's emit.
  c) src/grid_tactics/server/static/game.js — in the `sandbox_state` handler, derive `actionJob = deriveAnimationJob(prevForFly, payload.state)` BEFORE overwriting sandboxState. After renderSandbox() applies state, enqueue the action job FIRST (so it plays before subsidiary fly/hp jobs) with `stateApplied=true` (state was already applied by renderSandbox — skip the queue's post-anim applyStateFrame which doesn't exist for sandbox anyway). Non-noop jobs only — noop falls through just like multiplayer.
verification: Playwright harness (_debug_sacrifice_local.py) against local server confirms end-to-end: WS frame carries `"last_action":{"type":"SACRIFICE","attacker_pos":[4,2],...}`; `.sacrifice-jumper` SVG div is injected and animates (opacity 1.0 → 0.41 over 400ms while translate grows toward P2); hp-damage-popup `-10` fires after; P2 HP drops to 90. Screenshot `sacrifice_fix_early.png` shows the pixel-art jumper silhouette mid-jump, matching the user's described visual. Regression: 187 server/action/legal_actions tests pass, 64 sandbox tests pass. The only pre-existing failure (`test_spectator_receives_state_update`) also fails on master (unrelated).
files_changed:
  - src/grid_tactics/server/sandbox_session.py
  - src/grid_tactics/server/events.py
  - src/grid_tactics/server/static/game.js
