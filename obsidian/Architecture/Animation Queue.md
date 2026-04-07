# Animation Queue

Client-side serialization of visual effects from server state frames. Shipped in [[../Phases/v1.1/Phase 14.3 Game Juice]].

## Architecture
- Server emits state frames including a `last_action` payload.
- Client wraps state apply in `applyStateFrame(frame)`:
  1. Diffs old vs new state.
  2. Enqueues animation steps (summon scale-in, move lift/translate/drop, attack rubber-band + flash, damage popup, [[../Mechanics/Burn|burn]] tick, floating popups).
  3. Drains the queue.
  4. Pending UIs (react / tutor / move-attack picker) only show **after** drain.

## Why
- Serializes visuals so multiple events from one server message don't overlap.
- Provides a structural gate for prompt UIs.

## Files
- `src/grid_tactics/server/static/game.js`
