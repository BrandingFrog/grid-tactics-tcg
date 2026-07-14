---
phase: quick-260714-rge
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/grid_tactics/game_state.py
  - src/grid_tactics/legal_actions.py
  - src/grid_tactics/phase_contracts.py
  - src/grid_tactics/react_stack.py
  - src/grid_tactics/roguelike_events.py
  - src/grid_tactics/server/events.py
  - src/grid_tactics/server/view_filter.py
  - src/grid_tactics/server/static/js/06-event-queue.js
  - src/grid_tactics/server/static/js/09-duel-interaction.js
  - src/grid_tactics/server/static/js/10-modals.js
  - src/grid_tactics/server/static/css/zz-overrides.css
  - src/grid_tactics/server/static/js/11-hud-board-hand.js
  - data/cards/minion_reanimated_bones.json
  - tests/test_roguelike_events.py
  - tests/test_client_game_js.py
autonomous: true
requirements: []

must_haves:
  truths:
    - "After turns 25, 50, 75, ... the incoming turn is paused before its mana/draw/Rally work."
    - "Both players can privately choose one of the three event options without turn-order gating."
    - "Effects resolve only after both choices are locked, then the postponed turn resumes."
    - "Clumsy Greed draws up to four cards, then deterministically-randomly discards up to two hand cards."
    - "With a Slap permanently adds a stack; future Handshakes deal 5 opponent damage per stack for that chooser."
    - "Sharp Eyed Sceptic grants one Prohibition and one mana, respecting mana and hand caps."
    - "The modal reuses the Rock-Paper-Scissors vintage chrome, selection, Accept, and waiting treatment."
    - "AI-only seats score hand/deck economy, mana, Slap pressure, and opponent HP to choose strategically without hidden-information cheating."
    - "Resolved picks are public in each player's avatar/details tooltip, with repeated choices aggregated as ×N."
    - "Each round offers both players the same seeded-random three fortunes from the expanded pool."
    - "Marked Cards lets its owner keep one of the top three and explicitly order the other two on top."
    - "The random-unseen fortune cannot resolve to any fortune offered previously or in the current round."
    - "Reanimated Bones is undeckable; its fortune generates two token copies on random friendly empty tiles."
  artifacts:
    - path: "src/grid_tactics/roguelike_events.py"
      provides: "Event option definitions, synchronized choice recording, and effect resolution"
    - path: "src/grid_tactics/server/static/js/10-modals.js"
      provides: "RPS-themed mandatory event-choice modal"
    - path: "tests/test_roguelike_events.py"
      provides: "Cadence, postponement, effects, Handshake damage, and serialization coverage"
  key_links:
    - from: "src/grid_tactics/react_stack.py"
      to: "src/grid_tactics/roguelike_events.py"
      via: "turn-flip cadence opens the pending event before turn-start resources"
    - from: "src/grid_tactics/server/events.py"
      to: "src/grid_tactics/server/static/js/10-modals.js"
      via: "roguelike_event_pick socket message and engine_events final_state"
---

<objective>
Add a synchronized roguelike event every 25 completed turns. The next turn is
postponed while both players choose one of three options, using the same visual
language and interaction pattern as the existing Rock-Paper-Scissors modal.
</objective>

<execution>
1. Add serialized pending-event and Handshake-upgrade fields to GameState.
2. Open the event at the 25-turn boundary before incoming-turn resources.
3. Record choices independently; resolve both only after both are present.
4. Apply effects through the engine event stream and resume Rally safely.
5. Add the socket handler, AI auto-choice path, per-viewer choice redaction,
   RPS-themed client modal, and focused regression/visual tests.
</execution>

<verification>
- `python -m pytest tests/test_roguelike_events.py -q`
- `python -m pytest tests/test_client_game_js.py tests/server/test_events_fixes.py -q`
- `node --check` for modified client JavaScript
- Local browser screenshot at a forced turn-26 event state
</verification>
