---
phase: 14-gameplay-interaction
plan: 02
status: complete
completed: 2026-04-06
---

# Plan 14-02 Summary: Game Over Modal

## What Shipped

PLAY-03 game over modal: when the server emits `game_over`, the player sees a centered modal overlay showing VICTORY or DEFEAT (or DRAW), the inferred reason, both players' final HP, and a working "Back to Lobby" button. The previously-dead "Leave Game" sidebar button is now wired to the same return-to-lobby flow.

## HTML Element Added (game.html)

Inside `#screen-game .game-layout`, after `.game-sidebar`:

```html
<div id="game-over-overlay" class="game-over-overlay" style="display:none;">
  <div class="game-over-modal">
    <div class="game-over-result" id="game-over-result">VICTORY</div>
    <div class="game-over-reason" id="game-over-reason">HP depleted</div>
    <div class="game-over-hp-rows">
      <div class="game-over-hp-row">
        <span class="game-over-hp-label" id="game-over-self-name">You</span>
        <span class="game-over-hp-value" id="game-over-self-hp">0</span>
      </div>
      <div class="game-over-hp-row">
        <span class="game-over-hp-label" id="game-over-opp-name">Opponent</span>
        <span class="game-over-hp-value" id="game-over-opp-hp">0</span>
      </div>
    </div>
    <button class="btn btn-primary full-width" id="btn-back-to-lobby">Back to Lobby</button>
  </div>
</div>
```

The overlay uses `position: fixed` so it floats above the game grid regardless of `.game-layout`'s grid behavior.

## Functions Added/Modified (game.js)

**Modified:**
- **`onGameOver(data)`** (was just `console.log`) — Now sets `gameState`, `legalActions=[]`, calls `renderGame()` to update the underlying board, then `showGameOver(data)`

**Added (after `onGameOver`):**
- **`deriveGameOverReason(finalState)`** — Server doesn't send reason; client infers:
  - `winner === null` → "Draw"
  - `final_state.players[loser].hp <= 0` → "HP depleted"
  - Otherwise → "Sacrifice damage"
- **`showGameOver(data)`** — Reads `data.winner` (NOT `winner_idx`), determines VICTORY/DEFEAT/DRAW, applies appropriate CSS class (`.victory` cyan / `.defeat` red / `.draw` yellow), populates HP rows from `final_state.players[myPlayerIdx]` and `final_state.players[1 - myPlayerIdx]`, sets `overlay.style.display = 'flex'`
- **`hideGameOver()`** — Sets overlay display to none
- **`resetGameClientState()`** — Clears `gameState`, `legalActions`, `myPlayerIdx`, `opponentName`, `roomCode`, `sessionToken`, selection state. Hides room panel, clears room code display, player list, lobby status. Removes leftover react banner / action bar. Re-enables ready button.
- **`returnToLobby()`** — `hideGameOver()` → `resetGameClientState()` → `showScreen('screen-lobby')`
- **`setupGameHandlers()`** — Wires `#btn-leave` and `#btn-back-to-lobby` to `returnToLobby`

**Wired into `DOMContentLoaded` block:** Added `setupGameHandlers();` after `setupActivityTabs();`

## CSS Classes Added (game.css)

Appended after the react window block:

- `.game-over-overlay` — `position: fixed`, `inset: 0`, dark backdrop with `backdrop-filter: blur(2px)`, flex center, `z-index: 1000`
- `.game-over-modal` — Card background, cyan 2px border, glowing shadow, padding, flex column with gap
- `.game-over-result` — 48px bold uppercase letter-spaced text, centered
- `.game-over-result.victory` — Cyan with cyan text-shadow glow
- `.game-over-result.defeat` — Red with red text-shadow glow
- `.game-over-result.draw` — Yellow with yellow text-shadow glow
- `.game-over-reason` — Muted small uppercase text
- `.game-over-hp-rows` — Flex column container for HP rows
- `.game-over-hp-row` — Flex row, label left, value right, card2 background, border
- `.game-over-hp-label` — 13px text
- `.game-over-hp-value` — 18px bold cyan tabular numerals
- Mobile @media (max-width: 600px) override: smaller modal padding, 36px result text

## How `deriveGameOverReason` Infers the Reason

The server sends `data.winner` (0, 1, or null) and `data.final_state` but NOT a reason field. The client checks:

1. If `winner == null` → "Draw"
2. Else look up loser's hp: `finalState.players[1 - winner].hp`
3. If `loserHp <= 0` → "HP depleted" (HP-depletion win condition)
4. Otherwise → "Sacrifice damage" (the only other current win condition is a minion crossing the back row and sacrificing for lethal direct damage)

This is a heuristic — it works because the engine has only two win conditions. If a third is added, this needs updating.

## Visual Verification

Tested via Playwright in two browser windows:
- **VICTORY:** Synthesized `onGameOver({winner: 0, ...})` on Alice's tab (winner). Modal showed:
  - "VICTORY" in cyan with glow
  - "HP DEPLETED" reason
  - "Alice: 25" (self) and "Bob: 0" (loser)
  - Cyan "Back to Lobby" button
  - Dark blurred backdrop covered the entire screen
- **DEFEAT:** Synthesized on Bob's tab with `winner: 0` and `your_player_idx: 1`. Modal showed:
  - "DEFEAT" in red with red glow
  - Same reason and HP layout
  - Bob saw his own 0 HP, Alice's 30 HP
- **Back to Lobby button:** Clicked → `activeScreen: "screen-lobby"`, overlay hidden, `gameState === null`, `legalActions.length === 0`, `roomCode === null`, room panel hidden — full state reset confirmed
- **No JS console errors** during game over or return-to-lobby

## Confirmation: Plan 14-01 Still Works

The react window UI from Plan 14-01 was retested in the same session before testing 14-02:
- Bob's auto-draw triggered Alice's react window → banner showed correctly
- Bob's deploy triggered Alice's react window → banner showed "Opponent is playing a card at row 5 col 1"
- Phase badge correctly showed REACT (yellow)
- No regression observed

## Phase 14 Status

PLAY-01 ✓ (already shipped earlier this session in commits e95c6e7, b94a208)
PLAY-02 ✓ (this plan 14-01)
PLAY-03 ✓ (this plan 14-02)

**Phase 14 (Gameplay Interaction) is COMPLETE.** Ready to mark requirements done in REQUIREMENTS.md and ROADMAP.md.

## Notes

- "Leave Game" sidebar button now works (was previously dead — no click handler attached)
- Server has no `leave_room` event, so leaving mid-game leaks server-side state until timeout. POLISH-01 (Phase 15) will handle proper room cleanup with reconnection.
- No rematch button — that's POLISH-03 (Phase 15)
