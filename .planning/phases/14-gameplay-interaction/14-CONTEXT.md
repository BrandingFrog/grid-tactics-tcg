# Phase 14: Gameplay Interaction - Context

**Gathered:** 2026-04-06
**Status:** Ready for planning
**Source:** Direct context (skipped discuss-phase — requirements clear, partial work already done)

<domain>
## Phase Boundary

Browser UI for taking actions in a live game: clicking cards/cells, react window prompts, game over screen. The server already enforces all rules and emits state updates with legal actions per turn.

**Already done in current session (committed e95c6e7, b94a208):**
- PLAY-01 click-to-play with valid target highlighting (green = valid deploy/move, red = attack target, cyan = selected)
- Hand card click → highlight valid cells → click cell to play
- Own minion click → highlight valid moves and attack targets
- Auto-draw when DRAW is the only legal action
- Pass Turn / Skip React button in action bar
- Lobby deck selector refresh + incomplete deck disabling

**Remaining work:**
- PLAY-02 React window UI (visual prompt + play react card / pass)
- PLAY-03 Game over screen (winner, reason, final HP)

</domain>

<decisions>
## Implementation Decisions

### Architecture
- **No new server-side work expected.** Server already emits state_update with phase=REACT, legal_actions filtered to react cards + pass for the reacting player.
- Keep current click-to-play implementation in `game.js` — extend it, do not refactor.
- Game tooltip and hand styling already match deck builder — keep using `card-frame-hand` and existing CSS classes.

### React Window UI (PLAY-02)
- **Visual indicator:** Phase badge already shows "REACT" — extend with a banner/highlight on the action that's pending.
- **Pending action display:** Show what the opponent is about to do (e.g. "Opponent attacking your Fire Imp", "Opponent playing Fireball at row 3 col 2"). The pending_action should be visible in the gameState (need to verify what server sends — check `gameState.pending_action` or `gameState.react_stack`).
- **React card highlighting:** During react phase, hand cards that are legal as react actions glow with the existing `.card-playable` class. Click → submit PLAY_REACT action.
- **Skip button:** Already exists as "Skip React" button — keep as-is.
- **Time pressure:** No timer in this phase (FUTURE-01 deferred).

### Game Over Screen (PLAY-03)
- **Trigger:** Server emits `game_over` event with `{winner_idx, final_state, reason}`. Client already listens via `onGameOver()` — currently just logs to console.
- **Display:** Modal overlay over the game screen with:
  - Big "VICTORY" or "DEFEAT" header (cyan/red)
  - Reason text ("HP depleted", "Sacrifice damage", or "Opponent forfeited")
  - Final HP for both players
  - "Leave Game" button (existing) + "Back to Lobby" button
  - **No rematch button** — that's POLISH-03 (Phase 15)
- **Style:** Match existing screen overlay style (dark backdrop, card-style centered modal with cyan border).

### Claude's Discretion
- Exact wording of pending action descriptions
- Modal animation (probably none — instant show is fine)
- Whether to disable hand/board click during react window (must allow react card click but block other actions — already handled by legal_actions filtering)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Implementation
- `src/grid_tactics/server/static/game.js` — Client app (~1900 lines). Look at: `onStateUpdate`, `renderGame`, `renderActionBar`, `onHandCardClick`, `onBoardCellClick`, `getLegalByType`, `submitAction`, `onGameOver`.
- `src/grid_tactics/server/static/game.css` — All styles. New CSS goes in here. See: `.card-playable`, `.cell-valid`, `.cell-attack`, `.action-bar`, `.btn-action`, `.phase-react`.
- `src/grid_tactics/server/static/game.html` — Game screen markup. Game-tooltip already exists in sidebar.

### Server (read-only — should not need changes)
- `src/grid_tactics/server/events.py` — `_emit_state_to_players`, `_emit_game_over`, `submit_action` handler
- `src/grid_tactics/server/view_filter.py` — What state is visible to each player (check if pending action / react stack is in filtered state)
- `src/grid_tactics/react_stack.py` — React mechanics (LIFO stack)
- `src/grid_tactics/enums.py` — `ActionType` (PLAY_REACT = 5), `TurnPhase` (ACTION = 0, REACT = 1)
- `src/grid_tactics/actions.py` — `play_react_action(card_index, target_pos)`

### Roadmap & Requirements
- `.planning/ROADMAP.md` — Phase 14 success criteria (lines 221-230)
- `.planning/REQUIREMENTS.md` — PLAY-01, PLAY-02, PLAY-03 (line 31-33)

</canonical_refs>

<specifics>
## Specific Ideas

### React Window UX flow
1. Player A submits an attack/play_card → server resolves, sets phase=REACT, sends state_update to Player B
2. Player B sees: phase badge says "REACT", banner appears showing "Opponent is attacking your Fire Imp", react cards in hand glow green
3. Player B clicks a react card → submit PLAY_REACT → server resolves react chain
4. OR Player B clicks "Skip React" → server resolves the original action

### Game over UX flow
1. Server emits `game_over` event with winner_idx and reason
2. Client renders overlay modal with VICTORY/DEFEAT
3. Modal blocks all other interaction
4. Click "Back to Lobby" → return to lobby screen, reset game state

### Existing patterns to reuse
- Modal overlay style: Look at how `.screen` works — could use a similar approach with a `.game-over-overlay` class
- Banner pattern: Look at `.turn-banner` for the pending-action banner styling
- Button styles: `.btn-action`, `.btn-pass` already exist, use them

</specifics>

<deferred>
## Deferred Ideas

- **POLISH-03 Rematch button** — Phase 15
- **POLISH-02 Game log** — Phase 15
- **POLISH-01 Reconnection** — Phase 15
- **FUTURE-01 Turn timer** — future milestone
- **FUTURE-02 Animations** — future milestone
- React window timer (auto-skip after N seconds) — future milestone

</deferred>

---

*Phase: 14-gameplay-interaction*
*Context gathered: 2026-04-06 (skipped discuss-phase — clear requirements + partial work done)*
