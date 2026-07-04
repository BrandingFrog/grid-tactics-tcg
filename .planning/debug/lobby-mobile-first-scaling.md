---
status: fixing
trigger: "lobby-mobile-first-scaling: desktop lobby renders small, doesn't scale up as the mobile composition"
created: 2026-07-04
updated: 2026-07-04
---

## Current Focus

hypothesis: CONFIRMED — the lobby scales each element independently via clamp()/vw with maxima, plus many fixed-px sizes, so the composition never scales as one piece.
test: read the full `#screen-lobby .lobby2-*` block and evaluate each size at 844x390 vs 1280x800 vs 1920x1080.
expecting: past the clamp maxima (title 76px, hero 250px) and fixed px (inputs 16px, buttons, labels) freeze while the 46%/54% columns keep widening → tiny UI floating in whitespace.
next_action: replace per-element clamp/px with one proportional scale unit --u and re-verify.

## Symptoms

expected: Desktop lobby = the 844x390 mobile lobby proportionally scaled up; hero card, title, nav, play panel all grow with the viewport; composition identical at every size.
actual: On desktop things stay small and stop scaling — hero clamped at 250px, fonts hit clamp() maxima, big empty areas; media queries also change composition.
errors: none — pure CSS scaling/layout.
reproduction: open http://localhost:5055/ at 1280x800 / 1920x1080 and compare to 844x390.
started: recent mobile-first lobby redesign; scaling done with per-element clamp()/vw.

## Evidence

- checked: `#screen-lobby .lobby2-*` block, game.css ~9576-9768.
  found: sizes are per-element and capped:
    - hero `width: clamp(140px,19vw,250px)` — caps at 250px (19vw exceeds 250 at ~1316px wide).
    - title `font-size: clamp(38px,7.5vw,76px)` — caps at 76px at ~1013px wide.
    - MANY fixed px that never scale: inputs 16px, play-button 18px, join 15px, ghost 14px, labels 12px, nav 15px, room rows 15px, foot 12px, all paddings/gaps/radii.
    - grid columns `46% 54%` (percentage) keep widening with the window.
  implication: past ~1013-1316px width the content is frozen while the columns keep growing → the exact "mobile UI floating in a big window" + ballooning whitespace reported.

- checked: how the in-game screen scales (game.css ~9107-9151, 9166-9174).
  found: it fits a mobile-landscape design box off vh and drops/re-adds columns per breakpoint. Different problem shape (grid/board), not directly reusable, but confirms the intended "one design, scaled" philosophy.

- checked: markup game.html 75-158.
  found: `.lobby2` (46/54 grid) holds brand+play; `#room-panel .lobby2-room` and `#lobby-status .lobby2-status` are SIBLINGS of `.lobby2` under `#screen-lobby`. So a scale var must live on `#screen-lobby` to reach them.

## Resolution

root_cause: The lobby was built to "scale up" by giving each element its own clamp()/vw rule with a maximum, and by leaving structural sizes as fixed px. There is no single scale factor for the composition, so above the clamp ceilings (~title 1013px / hero 1316px wide) and for every fixed-px element the design stops growing while the percentage columns keep widening — producing a small UI surrounded by whitespace on desktop instead of a proportionally scaled-up mobile view.

fix: Introduce ONE proportional scale unit on `#screen-lobby`:
  `--u: min(100vw / 844, 100vh / 390)` — a length equal to "1 baseline pixel of the 844x390 design", scaled to contain in the viewport. Every size in the lobby block becomes `calc(var(--u) * N)` where N is the value the old rules produced at exactly 844x390 (so mobile stays pixel-identical: --u = 1px there). Removed all clamp() ceilings and fixed px on sizing. Portrait/narrow (<=620px) overrides `--u` to a 390px-wide portrait baseline (`min(100vw/390, 1.7px)`) so the stacked layout stays legible. Hairline 1px borders left unscaled for crispness. Grid columns (46/54), max-height:34vh rooms list, and position:fixed toast anchor kept as-is. Hero carousel inner-card inline transform untouched.

verification:
  - static check: grep of lobby block (game.css 9576-9800) shows every sizing
    clamp()/vw and fixed px converted to calc(var(--u) * N); only intentional
    non-scaled values remain (min-height:100vh, max-width:90vw, max-height:34vh
    rooms list, 1px hairline borders, decorative box/drop-shadow offsets,
    toast bottom:18px, media-query guard).
  - served CSS at http://localhost:5055/static/game.css contains 55 var(--u)
    references (edits are live, no-cache).
  - PENDING orchestrator visual check (main session owns Playwright): open the
    lobby at 844x390, 1280x800, 1920x1080 and confirm the composition is the
    SAME at each size, just larger — see "Orchestrator verification" below.
files_changed:
  - src/grid_tactics/server/static/game.css (only)
