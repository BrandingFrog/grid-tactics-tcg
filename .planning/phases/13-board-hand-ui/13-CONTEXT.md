# Phase 13: Board & Hand UI - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Full game rendered in browser — 5x5 grid with minions, hand with card details, mana/HP, turn/phase indicator. Plus deck builder with save slots and lobby deck selection. Flask serves the game UI (not Vercel). Read-only rendering — no click interactions yet (Phase 14).

</domain>

<decisions>
## Implementation Decisions

### Page Structure
- **D-01:** Game UI is a new "Play" tab alongside the existing dashboard tabs (Overview/Training/Cards/Games/Models). Same page structure.
- **D-02:** Flask serves everything — game UI, dashboard HTML, SocketIO. One server, one URL. Vercel analytics dashboard stays separate for now. Simplest for PvP testing with a friend.

### Board Layout
- **D-03:** Each player sees themselves at the bottom of the grid. P2's view is flipped (rows 4→0 instead of 0→4). Standard card game perspective.
- **D-04:** Minions displayed as compact cards in cells — YGO-style adapted for Grid Tactics (see Card Style below).

### Card Style (adapted from user's YGO Roblox project)
- **D-05:** Full YGO-style card adaptation with 2:3 aspect ratio:
  - Background color by card type: Minion=gold (`rgb(180,140,60)`), Magic=teal (`rgb(30,140,120)`), React=magenta (`rgb(160,40,100)`)
  - Art area at top: colored placeholder (no card art per out-of-scope), attribute-tinted
  - Attribute circle (top-right): Fire=red (`rgb(220,40,30)`), Dark=purple (`rgb(130,50,180)`), Light=yellow (`rgb(240,220,40)`), Earth=brown (`rgb(140,100,40)`), Neutral=gray
  - Card name below art (bold font, white with black text-stroke)
  - ATK/HP at bottom (left: ATK, right: HP) — replaces YGO's ATK/DEF
  - Mana cost badge (top-left, blue circle)
  - Dark border, rounded corners (3% radius)
  - Unaffordable cards dimmed (opacity or grayscale filter)
- **D-06:** Reference implementation: `BrandingFrog/ygo` repo, `src/client/CardFrameBuilder.luau` — translate the Roblox Luau layout to HTML/CSS.

### Deck Builder
- **D-07:** Deck builder is a standalone screen (accessible from the Play tab). Users browse all cards, add up to 3 copies of each, max 30 cards total.
- **D-08:** Save slots in localStorage — a few slots (3-5) to save and name different decks.
- **D-09:** In the lobby (after joining room, before readying), player selects which saved deck to use. Deck is sent to server on ready.

### Board Minion Display
- **D-10:** Minions on the grid use a compact version of the card style — name (truncated), ATK/HP, attribute circle, owner color tint on background. Smaller than hand cards but same visual language.

### Turn/Phase Indicator
- **D-11:** Clear turn indicator: "Your Turn" / "Opponent's Turn" banner. Phase indicator shows ACTION or REACT. Matches dashboard's dark theme with cyan highlights.

### Claude's Discretion
- Exact CSS Grid dimensions and spacing for the 5x5 board
- Hand card fan layout (horizontal scroll vs fixed positions)
- Mana/HP display widget design (bars, numbers, or both)
- Lobby UI layout (room code input, player list, ready button, deck selector)
- How card_defs from game_start maps to card rendering
- Dashboard tab integration mechanics (how Play tab coexists with analytics tabs)
- Responsive behavior within reason (desktop-first per out-of-scope)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Card Style Reference (CRITICAL)
- `BrandingFrog/ygo` (private GitHub repo) — `src/client/CardFrameBuilder.luau`: 333-line Roblox card renderer. Translate layout to HTML/CSS. Key patterns: 2:3 aspect ratio, attribute circle top-right with inner ring, LuckiestGuy font, ATK/DEF at bottom, type-based background colors.
- `BrandingFrog/ygo` — `src/shared/Constants.luau`: `ATTRIBUTE_COLOR` table (Earth=brown, Fire=red, Light=yellow, Dark=purple), `TYPE_COLORS` (Monster=gold, Spell=teal, Trap=magenta), `getCardColor()` logic.

### Existing Dashboard (styling reference)
- `web-dashboard/index.html` — Dark gaming theme with CSS variables (`--bg:#0b0b16`, `--card:#141428`, `--cyan:#00d4ff`, etc.). Tab navigation pattern. Chart.js integration.

### Server (Phase 11-12 output)
- `src/grid_tactics/server/events.py` — Socket.IO events: `game_start` (sends card_defs + filtered state), `state_update`, `game_over`, `error`
- `src/grid_tactics/server/view_filter.py` — `filter_state_for_player()` used before every emit
- `src/grid_tactics/server/app.py` — Flask app factory, serves static files
- `pvp_server.py` — Entry point

### Game Data
- `data/cards/*.json` — 21 card definitions (loaded by server, sent as card_defs at game_start)
- `src/grid_tactics/enums.py` — CardType, ActionType, TurnPhase, PlayerSide enums (serialize as ints)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Dashboard CSS variables and dark theme — reuse for game UI consistency
- Tab navigation pattern (`nav-btn` class) — add "Play" tab alongside existing tabs
- `card_defs` sent at `game_start` — dict mapping numeric_id to card definition (name, type, mana_cost, attack, health, effects, attribute)
- `state_update` event payload — filtered state + legal_actions list, ready to drive UI rendering

### Established Patterns
- Vanilla HTML/JS + CSS (no framework, no build step) — consistent with dashboard
- Socket.IO client from CDN (`socket.io-client@4`)
- Chart.js for data visualization (dashboard only, not needed for game)

### Integration Points
- Flask serves `index.html` (game + dashboard combined, or separate HTML files)
- SocketIO connects to same server for both real-time game events and any dashboard needs
- `card_defs` from server at game_start provides all data needed to render cards without separate API calls

</code_context>

<specifics>
## Specific Ideas

- Card style MUST follow the YGO Roblox design — 2:3 aspect, type-colored backgrounds, attribute circles with inner ring highlight, ATK/HP at bottom, mana cost badge
- Font: LuckiestGuy (from Google Fonts) for card names and stats, matching the YGO implementation
- Deck builder saves to localStorage with named slots — player picks a saved deck in lobby before readying
- Board perspective flips for P2 so both players see their side at bottom

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 13-board-hand-ui*
*Context gathered: 2026-04-05*
