---
phase: 14-gameplay-interaction
plan: 01
status: complete
completed: 2026-04-06
---

# Plan 14-01 Summary: React Window UI

## What Shipped

PLAY-02 react window UI: when the server enters the REACT phase, the reacting player sees a yellow banner describing the pending opponent action, react cards in hand glow yellow (distinct from the green ACTION-phase highlight), and clicking a yellow card submits a PLAY_REACT action.

## Functions Added (game.js)

After `getLegalByType()` (around line 1305):
- **`isReactWindow()`** — Returns true when `gameState.phase === 1`, `react_player_idx === myPlayerIdx`, and there are legal actions
- **`getLegalReactCardIndices()`** — Returns `{handIdx: true}` map of hand indices with legal PLAY_REACT actions
- **`describePendingAction(pa)`** — Returns human-readable string for pending opponent action. Coverage:
  - `action_type === 0` PLAY_CARD: "Opponent is playing a card at row X col Y" (or "casting a card" if no position)
  - `action_type === 1` MOVE: "Opponent is moving a minion"
  - `action_type === 2` ATTACK: "Opponent is attacking your {minion_name}" (looks up via `target_id`)
  - `action_type === 5` PLAY_REACT (chain): "Opponent is responding with {card_name}" (reads `react_stack`)
  - `action_type === 6` SACRIFICE: "Opponent is sacrificing their {minion_name} for damage"
  - Fallback: "Opponent action pending" — used for auto-draw (action_type 3)
- **`renderReactBanner()`** — Removes any existing banner, builds new one with REACT WINDOW label + description, inserts before action bar

## Functions Modified (game.js)

- **`renderGame()`** — Added `renderReactBanner()` call after `renderActionBar()`
- **`onHandCardClick(handIdx)`** — Added react-window early branch at top: filters legalActions for `action_type: 5` matching this card index, submits PLAY_REACT payload
- **`onBoardCellClick(row, col)`** — Added `if (isReactWindow()) return;` early-out
- **`onBoardMinionClick(minion)`** — Added `if (isReactWindow()) return;` early-out
- **`updateHandHighlights()`** — Branches on `isReactWindow()`: during react, only `.card-react-playable` (yellow) is set; otherwise standard `.card-playable` (green) / `.card-selected-hand` (cyan) logic

## CSS Classes Added (game.css)

Appended after the mobile responsive block:

- `.react-banner` — Flex container with yellow border, pulse animation
- `.react-banner-label` — "REACT WINDOW" pill, yellow uppercase
- `.react-banner-desc` — Pending action description text
- `@keyframes react-pulse` — 1.8s ease-in-out box-shadow pulse
- `.card-frame-hand.card-react-playable` — Yellow glow + border for legal react cards
- `.card-frame-hand.card-react-playable:hover` — Brighter glow + lift on hover
- Mobile @media (max-width: 600px) override for banner layout

## Visual Verification

Tested via Playwright in two browser windows:
- Game start with both players ready → server enters REACT phase for the non-active player (auto-draw window)
- Bob saw the yellow REACT WINDOW banner with "Opponent action pending" (auto-draw fallback)
- Bob clicked SKIP REACT → server resolved → moved to action phase
- Bob played Fire Imp → Alice entered react window with banner "Opponent is playing a card at row 5 col 1"
- Alice's hand cards correctly dimmed (no react cards in hand to highlight in this scenario)
- Phase badge correctly showed REACT (yellow) on the reacting player's tab
- Action button correctly relabeled to "Skip React"
- No JS console errors during react window transitions

## Notes

- The pending action description uses 1-indexed row/col for human readability
- Auto-draw (action_type=3) triggers a react window per the engine, but no react cards exist for it — the banner shows "Opponent action pending" as a graceful fallback
- Board click inertness during react was tested by inspection of the code path — `isReactWindow()` returns early before any selection logic
