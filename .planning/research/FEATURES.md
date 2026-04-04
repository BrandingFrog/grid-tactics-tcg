# Feature Landscape: Online PvP Dueling

**Domain:** Real-time multiplayer turn-based card game (room-based PvP)
**Researched:** 2026-04-04
**Confidence:** HIGH

## Context

Grid Tactics TCG has a complete Python game engine (immutable dataclass-based, 5x5 grid, 19 cards, mana banking, react windows, sacrifice mechanic, legal action enumeration). This research focuses exclusively on what is needed to enable two human players to duel online through a web UI with the existing engine as the authoritative server.

---

## Table Stakes

Features users expect from online PvP in a card game. Missing any = product feels broken.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Server-authoritative game loop | Prevents cheating. Every online card game validates server-side. | Medium | Thin wrapper around existing `resolve_action()` + `legal_actions()`. Server holds GameState per room. |
| Room code system (create/join) | Standard for private casual games. No matchmaking needed at this scale. | Low | `secrets.token_urlsafe(6)` + Flask-SocketIO `join_room()`. In-memory dict of rooms. |
| Per-player views (hidden information) | Card games are imperfect-info games. Seeing opponent's hand = broken. | Medium | `to_client_dict(viewer_side)` strips opponent hand/deck contents. Send different payloads per socket. |
| Legal action filtering in UI | Players must know what moves are valid without trial-and-error. | Medium | Server sends `legal_actions()` result with each state update. Client highlights valid targets/cells. |
| 5x5 grid board visualization | The game IS a grid game. Without spatial rendering, no positional decisions. | High | CSS Grid layout. Each cell shows minion (name, ATK/HP, owner color). Player rows colored differently. |
| Hand display with card details | Players need to see their cards, costs, and which are playable. | Medium | Fan of cards at bottom. Name, mana cost, ATK/HP, effect text, attribute. Unplayable cards dimmed. |
| Mana / HP display | Core resource tracking. Both players' values must be visible. | Low | Already in GameState. Current mana / max mana + HP bar for both players. |
| Turn flow indicator | Must be clear whose turn it is and what phase (ACTION vs REACT). | Low | "Your Turn" / "Opponent's Turn" banner. Phase indicator with contextual prompts. |
| React window UI | Core differentiator. Opponent must see what happened and choose to counter or pass. | Medium | Show pending action description, highlight playable react cards, prominent pass button. |
| Win detection + game over screen | Game must end properly with clear feedback. | Low | Already in GameState. Victory/Defeat overlay with reason and final HP. |
| Real-time state sync | Both players see updates immediately after actions resolve. | Medium | Flask-SocketIO emit to room after each `resolve_action()`. |

## Differentiators

Features that elevate the experience. Not required for launch but high-value additions.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Turn timer | Prevents stalling/griefing. 45s action, 20s react. Auto-pass on expiry. | Medium | Server-authoritative countdown. Client shows visual timer. |
| Action animation / transition | Cards sliding onto grid, damage numbers, attack flash. Game feels alive. | Medium | CSS transitions on state diffs. Don't block gameplay. |
| Reconnection handling | Browser close / WiFi drop shouldn't end the game. | Medium | 60s window. Session token in cookie. Re-send full state on reconnect. |
| Game log / action history | Scrollable sidebar of what happened. Helps track game progression. | Low | Append action descriptions to a log array. Display in sidebar. |
| Card hover/inspect preview | See full card details on hover (stats, effects, attribute). | Low | Tooltip or modal. Card data already loaded from JSON definitions. |
| Rematch button | Quick restart after game ends. Both players stay in room. | Low | Server creates new GameState in same room. |
| Sound effects | Audio feedback for card play, attack, damage, victory. | Low | HTML5 Audio with short clips. Mute toggle. |
| Spectator mode | Third parties watch games. Valuable for community. | Medium | Read-only room role. Sees board but not hands (or full view for friends). |

## Anti-Features

Features to explicitly NOT build in v1.1.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Matchmaking / ELO ranking | Massive complexity, requires critical mass of players | Room codes. Share via Discord/text. |
| User accounts / authentication | Database schema, password handling, sessions -- zero value for friends playing | Anonymous sessions with display names |
| Deck builder | Only 19 cards. Not enough variety for meaningful deckbuilding. | Preset deck for both players. Deckbuilding at 30+ cards. |
| Chat / free text | Moderation burden, toxicity risk | Predefined emotes only (or none for v1.1) |
| AI opponent in PvP UI | Requires PyTorch model loading, GPU inference | Separate milestone |
| Game replay system | Action history persistence, replay viewer with timeline | Game log text covers 80% of value |
| Mobile-responsive layout | Adds CSS complexity | Desktop-first. Basic viewport meta tag. |
| Persistent game history | Database writes per game, storage schema | Games are ephemeral. In-memory only. |
| Card art / visual polish | Massive time sink. Core value is gameplay. | Colored borders by attribute, simple type icons |
| Peer-to-peer networking | Destroys server authority, enables cheating | Server-authoritative always |

## Feature Dependencies

```
Flask-SocketIO Server Setup
  -> Room Code System (create/join)
    -> Player Connection (WebSocket)
      -> State Serialization (GameState -> filtered JSON)
        -> Per-Player View Filtering (hidden information)
          -> Board Rendering (5x5 grid)
          -> Hand Rendering (playable cards)
          -> Status Display (mana, HP, turn phase)
            -> Legal Action Display (highlight valid moves)
              -> Action Submission (click -> emit -> server validates -> resolve)
                -> React Window Flow (REACT phase UI)
                  -> Win Detection Display (game over overlay)
```

**Critical path:** Server -> Rooms -> Connection -> Serialization -> Board UI -> Actions -> React -> Win

## MVP Recommendation

Prioritize by dependency chain:

1. **Flask-SocketIO server + room system** -- Foundation. Two clients can connect to a room.
2. **State serialization + per-player views** -- GameState converts to filtered JSON per player.
3. **Board + hand + status UI** -- Visual representation of game state in browser.
4. **Legal actions + action submission** -- Players make moves, server validates and applies.
5. **React window flow** -- React phase works correctly in the UI.
6. **Win detection + game over** -- Game ends properly, result displayed.

**Defer to post-launch:** Turn timer, animations, spectator mode, sound effects, reconnection resilience, game log.

---
*Feature landscape for: Grid Tactics TCG v1.1 Online PvP Dueling*
*Researched: 2026-04-04*
