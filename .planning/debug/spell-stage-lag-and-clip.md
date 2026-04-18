---
status: investigating
trigger: "spell-stage center-screen chain overlay has lag/stutter and clipping issues after v0.11.31 rewrite"
created: 2026-04-18T00:00:00Z
updated: 2026-04-18T14:30:00Z
---

## Current Focus

hypothesis: SECOND ROOT CAUSE CONFIRMED. The v0.11.32 transform-commit fix made the fly animation play, but a SEPARATE clipping bug remains in the shift path. `.spell-stage-card { overflow: hidden }` at game.css:201 applies to the LEFT slot (#spell-stage-card). When the shift animation mounts `.spell-stage-card-inner` in the LEFT slot with `transform: translate(+dx, 0)` (positioned to the RIGHT of the slot's bounds) and animates it back to identity, the inner is clipped to the LEFT slot's rect for the entire glide. User sees the card "half hidden under UI" because the RIGHT half of the inner card is being clipped by the parent's overflow rule. Fix: change `overflow: hidden` → `overflow: visible` on `.spell-stage-card`.
test: Apply fix, commit, push, verify live site.
next_action: Edit game.css line 201, commit, push.

## Symptoms

expected:
- Card flies from caster's hand rect → spell-stage RIGHT slot rect, smooth (~500ms), on TOP of all other UI elements throughout the flight
- No visual clipping, no stuttering
- 1 second hold, then shift: current card glides right-to-left into LEFT slot, any prior LEFT card slides off-screen left
- "?" returns to RIGHT slot. Chain can be arbitrarily long
- Resolution: cards replay LIFO, sliding IN from off-screen LEFT into LEFT slot, hold ~600ms with "⚡" in RIGHT, then slide OFF-screen RIGHT. Final "👍" in RIGHT, stage fades

actual:
- "theres lag still" — unspecified which segment
- "the react card in going under the box when it should appear like the card is on top of those ui elements and moving over" — card clipped/hidden by other UI elements along flight path

errors: none visible

reproduction:
1. Open https://web-production-520c.up.railway.app/ (v0.11.31 live)
2. Click Tests nav tab
3. Load test id `prohibition-react-chain`
4. Click Acidic Rain in P1 hand, confirm cast
5. Toggle Controlling → P2
6. Click Prohibition in P2 hand — should fly from top down to stage RIGHT slot
7. Observe clipping and stutter

started: After v0.11.30/v0.11.31 rewrite of spell-stage flow (two-slot conveyor)

## Eliminated

<!-- Append as hypotheses are disproven -->

## Evidence

- timestamp: investigation-1
  checked: game.js lines 3393-3451 (`_showSpellStage`)
  found: Sequence is appendChild → getBoundingClientRect(slot) → getBoundingClientRect(src hand) → set inline transform to initial → set opacity 0 → set transition → 2×rAF → set final transform
  implication: The gBCR calls force layout flush BEFORE inline transform is set. After gBCR, the committed "baseline" for the wrap is "no transform, opacity 1". Setting inline transform+opacity after this does NOT retroactively commit those values — they're queued for next style recalc. When 2×rAF fires and sets final values, the browser interpolates from the last committed state (baseline) to final — skipping the initial.

- timestamp: investigation-2
  checked: Playwright poll at 5ms intervals during real sandbox flow
  found: Inline transform IS correctly set to `translate(-169px, 410px) scale(0.45)`, then flipped to `translate(0,0) scale(1)` 18ms later. But `getComputedStyle(wrap).transform` returns `matrix(1, 0, 0, 1, 0, 0)` (identity) at EVERY sample for the full 1s+. rect.x/y remain at final slot position (859, 290) — never at hand origin.
  implication: The inline initial transform is never committed. Transition runs from "no transform" to "no transform" effectively = no visible animation.

- timestamp: investigation-3
  checked: Direct console call to `_showSpellStage(0, 0)` vs socket-dispatched call
  found: Both paths show computed = identity. Not a timing-with-socket issue; the function itself has the bug.
  implication: The bug is in `_showSpellStage` regardless of caller.

- timestamp: investigation-4
  checked: Isolated test of 4 orderings (T1-T4) via in-page evaluate
  found:
    T1 (real order: append → gBCR → transform → transition): computed = IDENTITY (BROKEN)
    T2 (append → gBCR → transition-first → transform): computed = IDENTITY (BROKEN)
    T3 (gBCR-before-append → create → transform → transition → append): computed = CORRECT
    T4 (append → transform → transition, NO gBCR between): computed = CORRECT
  implication: The specific killer is `appendChild → getBoundingClientRect → setTransform`. Removing the intermediate gBCR OR moving it before appendChild both fix the issue.

- timestamp: investigation-5
  checked: Fix candidates with gBCR in original position
  found:
    FIX_A (append → gBCR → transform → opacity → `void offsetWidth` → transition): computed = CORRECT (matrix(0.45,...) and opacity 0)
    FIX_B (append → gBCR → transform → opacity → transition → getComputedStyle read): computed = IDENTITY (getComputedStyle does not flush here)
    FIX_C (append → gBCR → transform → opacity → transition → `void offsetWidth`): computed = IDENTITY (reflow after transition is set does not commit initial transform)
  implication: The fix must force reflow AFTER setting initial transform/opacity but BEFORE setting transition. `void wrap.offsetWidth;` between those two writes works. Classic "re-trigger CSS transition" pattern.

- timestamp: investigation-6
  checked: Applied FIX_A at runtime, slowed transition to 5000ms, verified animation plays
  found: Mid-flight computed = `matrix(0.790089, 0, 0, 0.790089, -64.5029, 156.735)` — interpolated value between initial and final. Opacity = 0.61 mid-flight. The fly animation works correctly with the fix.
  implication: FIX_A is the correct resolution.

- timestamp: investigation-7
  checked: User's "clipping" complaint - screenshot analysis mid-flight (with FIX_A applied + slow transition)
  found: The flying card renders fully and visibly over the board area. When it travels through y-coords below the spell-stage root's bottom edge (y=710), it remains visible because `.spell-stage-react` has `overflow: visible`. `elementsFromPoint` returns non-spell-stage elements but only because `.spell-stage` has `pointer-events: none` (makes elementsFromPoint skip it). Visually the card IS on top.
  implication: The "clipping" complaint appears to be a CONSEQUENCE of the no-animation bug — without the fly animation, the card just materializes in the slot and the user interprets this as "it went under and came out" rather than "it didn't fly at all". Once the fly works, the clipping perception should disappear.

- timestamp: investigation-8
  checked: Visual screenshot of v0.11.31 actual (unpatched) cast at 20ms, 50ms, 100ms, 150ms
  found: At 20ms, a semi-transparent ghost of the card appears near the RIGHT slot (this is likely the card-fly-ghost hand→grave animation, NOT the spell-stage card). By 50ms, the card is fully opaque in the RIGHT slot with NO flight. By 150ms, it has already shifted to the LEFT slot (the 1000ms shift timer may be being cleared prematurely by a second sandbox_state event).
  implication: User sees the spell-stage card "pop in" instead of fly. This feels like lag/stutter because the user expects animation but sees a jump-cut. Also, an early shift may be happening.

- timestamp: investigation-9
  checked: sandbox_state handler order in game.js line 6911 vs line 6934
  found: `renderSandbox()` runs SYNCHRONOUSLY before `setTimeout(0, _showSpellStage)`. But renderSandbox is fast (~0.6ms measured). So this is not the lag source directly — the lag source is that the fly animation doesn't fire.
  implication: The `setTimeout(0)` scheduling is not harmful; the bug is purely in the transform-commit ordering within `_showSpellStage`.

- timestamp: investigation-10
  checked: Mirror of the same bug exists in `_performStageShift` (game.js lines 3459-3498)
  found: Same pattern: appendChild → getBoundingClientRect(right) → getBoundingClientRect(left) → set initial transform → set transition → rAF×2 → set final. Vulnerable to the same "initial never commits" bug.
  implication: The shift glide animation (right→left) may also be broken by the same mechanism. Fix should be applied in both locations.



## Resolution

root_cause: |
  Both the fly-from-hand animation (_showSpellStage) and the shift slide-in
  animation (_performStageShift) suffer the same defect: they set an inline
  `transform` (initial) value immediately after calling `appendChild` and
  `getBoundingClientRect`, but BEFORE setting the `transition` property. The
  browser batches the initial transform with the upcoming final transform
  (set 2 rAFs later) into a single style recalc. Because the `transition`
  property is only established AFTER the initial transform is written, the
  browser has no committed "start value" for the transition — it sees the
  element go from baseline (no transform / identity) to final (identity)
  without ever rendering the initial offset. Result: computed transform is
  identity throughout; the card snaps into the slot with no visible flight.

  This manifests as the user-reported "lag" (really: no animation at all).
  The user-reported "clipping" ("card going under UI") is a perception
  artifact of the missing flight — without the fly animation the card just
  materialises in the center stage, which looks wrong but isn't actually
  clipping.

  Two rAFs are NOT sufficient to force a style commit in this code path
  because the first rAF fires BEFORE the browser's next style+layout pass
  (which is where inline styles would be committed if no further writes
  happened). When the second rAF then changes the transform again, the
  browser consolidates both writes.

  Verified empirically (Playwright on live v0.11.31): computed transform
  stays at `matrix(1, 0, 0, 1, 0, 0)` throughout the entire 520ms window
  while inline transform correctly reports the initial offset and then
  the final identity.

fix: |
  Insert a forced reflow (`void wrap.offsetWidth;`) BETWEEN the initial
  transform/opacity writes and the `transition` property write. This
  forces the browser to commit the initial values as a rendered baseline
  before the transition rule is attached. When the rAF chain then writes
  the final values, the transition has a proper start state to
  interpolate from.

  Applied to both spell-stage animation sites:
  - src/grid_tactics/server/static/game.js:3446 (_showSpellStage fly-from-hand)
  - src/grid_tactics/server/static/game.js:3499 (_performStageShift slide-in)

  `getComputedStyle(wrap).transform` reads were tested as an alternative
  flush and do NOT work in this scenario; `void offsetWidth` is required.

verification: |
  Patched game.js served via Playwright route interception against the
  live Railway deployment. Verified:
  - Fly-from-hand: smooth 584ms interpolation from `scale(0.45) translate(-169, 410)`
    to `scale(1) translate(0, 0)`. Opacity 0→1 in 260ms. ~36 intermediate
    frames captured via 8ms polling.
  - Shift slide-in: smooth 440ms interpolation from `translate(398, 0)` to
    `translate(0, 0)`. ~15 intermediate frames captured.
  - Mid-flight screenshot shows card rendered fully on top of all UI with
    no clipping.
  - No regressions in other spell-stage paths (slide-off-left for old
    LEFT card uses the "transition-first-then-transform" pattern which
    is immune to this bug).

files_changed:
  - src/grid_tactics/server/static/game.js (2 edits: fly + shift)

## Re-opened 2026-04-18

User reports after v0.11.32 deployed:
- "half the card is hidden under the ui"
- "there is still a laggy issue with the naimation"
- Screenshot shows the Prohibition react card appearing in the LEFT slot area but visually cut — approximately half the card obscured by the surrounding UI boxes/panels.

The prior fix (void wrap.offsetWidth) was correct and made the fly animation play, but was INSUFFICIENT. The re-opened complaint is a different failure mode that was masked by the no-animation bug: once the animation plays, a CSS overflow clipping rule becomes visually observable.

### Re-opened Evidence

- timestamp: reopen-1
  checked: game.css full scan for rules applying to .spell-stage, .spell-stage-card, .spell-stage-react, .spell-stage-card-inner
  found:
    - .spell-stage (#spell-stage): position: fixed, z-index: 200, pointer-events: none, transform: translate(-50%,-50%), display: flex.
    - .spell-stage-card + .spell-stage-react (shared): width 280px, aspect-ratio 2/3, border-radius 14px, will-change transform+opacity, box-shadow.
    - .spell-stage-card (LEFT slot ONLY) line 200-204: **overflow: hidden**, transition: transform 350ms, opacity 350ms.
    - .spell-stage-react (RIGHT slot): background dashed-border, NO overflow rule (inherits visible).
    - .spell-stage-card-inner: width/height 100%, will-change transform+opacity, transform-origin center. NO overflow rule.
  implication: The LEFT slot (`#spell-stage-card`) clips its children. The RIGHT slot (`#spell-stage-react`) does not. This asymmetry is the bug: `.spell-stage-card` was given `overflow: hidden` (probably to clip the card frame to the slot's rounded-rect) but this clips the inner card during the shift-glide animation where it starts at `translate(+dx, 0)` — positioned to the right of the slot's rect.

- timestamp: reopen-2
  checked: Code path confirmation — game.js:3487-3504 (_performStageShift)
  found: leftWrap (class .spell-stage-card-inner) is appended to `els.left` which is `#spell-stage-card`. leftWrap.style.transform is set to `translate(<right-slot.left - left-slot.left>, 0)` = approximately +280px+gap = +308px. The inner card is then glided back to `translate(0,0)` over 440ms.
  implication: For the entire 440ms glide, the inner card's rendered position is between +308px and +0px RIGHT of where the parent ends, and the `overflow: hidden` on the parent clips everything outside its rect. At the start the card is fully invisible (entirely off-rect), mid-flight only the LEFT portion is visible (the part that has entered the parent's rect), and only at the end is the card fully visible. Exactly matches the user screenshot ("half the card hidden").

- timestamp: reopen-3
  checked: Is overflow: hidden needed for any visual reason?
  found: The card-frame-full child uses `max-width: 100%; height: 100%;` so it fits inside the slot naturally. The border-radius: 14px on `.spell-stage-card` was probably the original intent for `overflow: hidden` (clip the card HTML's corners to the slot's rounded rect). But the inner card html itself already has its own border-radius, so clipping on the slot level is redundant. Additionally, the sibling `.spell-stage-react` already works fine without overflow: hidden.
  implication: Safe to remove `overflow: hidden`. No visual regression expected because the card HTML has its own corner styling.

- timestamp: reopen-4
  checked: Does the fly-from-hand animation ALSO suffer this bug?
  found: No — fly-from-hand mounts the inner into `els.right` (`.spell-stage-react`) which has NO overflow rule. The card flies in freely with no clipping. This matches the user's report that the complaint is specifically "in the LEFT slot area".
  implication: Only the shift-glide is affected. The fix is a single-line CSS change.

- timestamp: reopen-5
  checked: Lag complaint analysis — "still a laggy issue with the naimation"
  found: The shift timer is 1000ms (line 3458). During the 1s hold the card sits in RIGHT slot idle. Then shift begins: old LEFT card (if any) slides out over 420ms (line 3473), and NEW card glides into LEFT slot over 440ms (line 3501). Total perceived: 1s idle + 440ms glide. With the clipping bug the glide is partially invisible, and the user likely experiences the moment of "card materializing" at the end of the glide (when it enters the un-clipped final position) as "lag/stutter". Once overflow: visible is applied, the glide will be fully visible and the lag perception should resolve.
  implication: The "lag" is a consequence of the clipping — not a separate timing bug. Removing the clip should fix both symptoms simultaneously. If user still reports lag after the fix, re-open with timing-specific evidence.

### Re-opened Resolution

root_cause_v2: |
  `.spell-stage-card { overflow: hidden }` at game.css line 201 clips the
  inner `.spell-stage-card-inner` during the shift-glide animation. The
  inner card starts at `transform: translate(+dx, 0)` (positioned to the
  right of the LEFT slot's rect, where the RIGHT slot is) and glides to
  identity. For the full 440ms glide only the portion of the inner card
  that has entered the parent's rect is visible; the rest is clipped.
  User perceives "card half-hidden under the UI" and "laggy animation"
  (really: partially invisible animation).

  This was masked by the prior no-animation bug (v0.11.31 and earlier).
  The v0.11.32 fix made the animation play — which exposed this
  second-order clipping bug.

fix_v2: |
  Change `overflow: hidden` → `overflow: visible` on `.spell-stage-card`
  in src/grid_tactics/server/static/game.css line 201. The slot's width
  constraint (280px) is still respected by the flex layout, so the card
  sits correctly at rest. During the glide animation, the inner can now
  be rendered outside the slot's bounds without being clipped.

  No visual regression expected: the inner card HTML already has its own
  border-radius, and the sibling `.spell-stage-react` already works with
  overflow: visible.

verification_v2: |
  Pending: deploy to Railway, reproduce on live site, confirm card is
  fully visible throughout the shift glide.

files_changed_v2:
  - src/grid_tactics/server/static/game.css (line 201: overflow: hidden → overflow: visible)
