# Spectator Mode

Third-party clients can join a room as a spectator without affecting state. Shipped in [[../Phases/v1.1/Phase 14.4 Spectator Mode]].

## Modes
- **God mode** — both hands visible.
- **Non-god** — fixed P1 perspective via [[View Filter]] (perspective toggle deferred).

## Server
- `RoomManager.join_as_spectator`
- Spectator fanout for state updates and chat
- Action gating: spectators cannot submit gameplay actions

## Frontend
- Lobby Spectate button + god-mode checkbox
- Dual-hand render in god mode
- Spectator badge
