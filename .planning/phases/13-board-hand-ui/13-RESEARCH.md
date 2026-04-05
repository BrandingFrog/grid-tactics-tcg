# Phase 13: Board & Hand UI - Research

**Researched:** 2026-04-05
**Domain:** Browser game UI rendering (HTML/CSS/JS), Flask serving, Socket.IO client integration, card visual design
**Confidence:** HIGH

## Summary

Phase 13 renders the game state visually in the browser -- 5x5 grid with minions, hand with card details, mana/HP displays, turn/phase indicators, a deck builder with localStorage save slots, and lobby deck selection. This is a read-only rendering phase; click interactions are Phase 14.

The existing codebase provides a strong foundation: the Vercel dashboard (`web-dashboard/index.html`) already has a Duel tab with placeholder CSS for board, hand, lobby, and most UI elements. The server already sends `card_defs` at `game_start` and filtered `state_update` events with `legal_actions`. However, the current `_build_card_defs()` is missing effects, tribe, react_condition, and card_id fields that UI-02 requires. The Duel tab currently renders static mock data -- it needs to be driven by real Socket.IO events.

The user's YGO Roblox project (`BrandingFrog/ygo`) provides a detailed card visual reference: 2:3 aspect ratio, type-colored backgrounds, attribute circles with inner ring highlights, LuckiestGuy font, ATK/HP at bottom, mana cost badge. This Luau layout translates directly to HTML/CSS with `aspect-ratio`, `border-radius: 50%`, CSS `text-stroke`, and Google Fonts.

**Primary recommendation:** Extend the existing dashboard HTML with real Socket.IO-driven rendering. Enhance `_build_card_defs()` to include all fields needed for rendering. Build a CSS card component that matches the YGO Roblox design. Add deck builder save slots to localStorage. Flask serves the game HTML file alongside the existing pvp_server.py.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Game UI is a new "Play" tab alongside the existing dashboard tabs (Overview/Training/Cards/Games/Models). Same page structure.
- **D-02:** Flask serves everything -- game UI, dashboard HTML, SocketIO. One server, one URL. Vercel analytics dashboard stays separate for now.
- **D-03:** Each player sees themselves at the bottom of the grid. P2's view is flipped (rows 4->0 instead of 0->4).
- **D-04:** Minions displayed as compact cards in cells -- YGO-style adapted for Grid Tactics.
- **D-05:** Full YGO-style card adaptation with 2:3 aspect ratio: type-colored backgrounds (Minion=gold rgb(180,140,60), Magic=teal rgb(30,140,120), React=magenta rgb(160,40,100)), art area placeholder, attribute circle top-right (Fire=red rgb(220,40,30), Dark=purple rgb(130,50,180), Light=yellow rgb(240,220,40), Earth=brown rgb(140,100,40), Neutral=gray), card name with text-stroke, ATK/HP at bottom, mana cost badge top-left, dark border, rounded corners 3% radius. Unaffordable cards dimmed.
- **D-06:** Reference implementation: `BrandingFrog/ygo` repo, `src/client/CardFrameBuilder.luau` -- translate Roblox Luau layout to HTML/CSS.
- **D-07:** Deck builder is a standalone screen accessible from Play tab. Browse all cards, add up to 3 copies each, max 30 cards.
- **D-08:** Save slots in localStorage -- 3-5 slots to save and name different decks.
- **D-09:** In lobby (after joining room, before readying), player selects which saved deck to use. Deck is sent to server on ready.
- **D-10:** Minions on grid use compact card style -- name (truncated), ATK/HP, attribute circle, owner color tint. Smaller than hand cards.
- **D-11:** Clear turn indicator: "Your Turn" / "Opponent's Turn" banner. Phase shows ACTION or REACT. Dark theme with cyan highlights.

### Claude's Discretion
- Exact CSS Grid dimensions and spacing for the 5x5 board
- Hand card fan layout (horizontal scroll vs fixed positions)
- Mana/HP display widget design (bars, numbers, or both)
- Lobby UI layout (room code input, player list, ready button, deck selector)
- How card_defs from game_start maps to card rendering
- Dashboard tab integration mechanics (how Play tab coexists with analytics tabs)
- Responsive behavior within reason (desktop-first)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UI-01 | User can see the 5x5 grid with minions showing name, ATK/HP, owner, and attribute | Board rendering with CSS Grid, compact card components on cells, perspective flip for P2 (D-03), attribute circle colors (D-05) |
| UI-02 | User can see their hand with card details (name, mana cost, ATK/HP, effects, attribute) and unplayable cards dimmed | Hand card rendering with YGO-style full cards (D-05), requires enhancing `_build_card_defs()` to include effects/tribe, dimming via opacity/filter when mana insufficient |
| UI-03 | User can see both players' current mana and HP | State data already in `state_update.state.players[idx].hp/current_mana/max_mana`, render as stat widgets in opponent/self info bars |
| UI-04 | User can see whose turn it is and the current phase (ACTION vs REACT) | State data: `state_update.legal_actions` (non-empty = your turn), `state_update.state.phase` (0=ACTION, 1=REACT). Turn banner + phase indicator |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask | 3.1.3 (installed) | Serve HTML + Socket.IO | Already in project, D-02 requires Flask serves everything |
| Flask-SocketIO | 5.6.1 (installed) | Real-time game events | Already in project, game_start/state_update events exist |
| socket.io-client | 4.x (CDN) | Browser Socket.IO client | Already used by dashboard pattern |
| Google Fonts (LuckiestGuy) | CDN | Card name/stats font | D-05/D-06 mandates LuckiestGuy per YGO reference |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| CSS custom properties | native | Theme system | Reuse existing `--bg`, `--card`, `--cyan`, etc. from dashboard |
| localStorage API | native | Deck save slots | D-08 requires persistent deck storage in browser |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Vanilla JS DOM | React/Vue | Framework adds build step, contradicts dashboard pattern of single HTML file |
| Separate HTML files | One big HTML | Separate is cleaner but D-01 says same page structure as dashboard tabs |
| Google Fonts CDN | Self-hosted font | CDN is simpler, self-hosted needed only for offline play (not a requirement) |

## Architecture Patterns

### Recommended File Structure
```
src/grid_tactics/server/
  app.py              # MODIFY: Add route to serve game HTML
  events.py           # MODIFY: Enhance _build_card_defs() with effects/tribe/card_id
  static/
    game.html         # NEW: Game UI (Play tab + deck builder + lobby + board)
    game.css          # NEW: Card styles, board grid, YGO-adapted card design
    game.js           # NEW: Socket.IO client, state rendering, deck builder logic
```

Note: The existing `web-dashboard/index.html` is the Vercel analytics dashboard and should NOT be modified. Per D-02, Flask serves a separate game HTML file. The Duel tab CSS from the dashboard provides design patterns to replicate (not copy directly) in the new game UI.

### Pattern 1: Flask Static File Serving
**What:** Flask serves the game HTML from a static directory.
**When to use:** D-02 requires Flask serves everything.
**Example:**
```python
# In app.py -- add route to serve game HTML
from flask import send_from_directory
import os

def create_app(testing=False):
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    app = Flask(__name__, static_folder=static_dir)
    app.config["SECRET_KEY"] = "dev-secret-key"
    app.config["TESTING"] = testing

    @app.route('/')
    def index():
        return send_from_directory(static_dir, 'game.html')

    socketio.init_app(app, async_mode="threading", cors_allowed_origins="*")
    return app
```

### Pattern 2: Socket.IO Client State Rendering Loop
**What:** Listen for server events, store state, re-render UI on every `state_update`.
**When to use:** All game rendering.
**Example:**
```javascript
// game.js
let cardDefs = {};       // numeric_id -> card info (from game_start)
let gameState = null;    // latest filtered state (from state_update)
let myPlayerIdx = null;  // 0 or 1 (from game_start)
let legalActions = [];   // current legal actions (empty = not your turn)

const socket = io();

socket.on('game_start', (data) => {
    cardDefs = data.card_defs;
    gameState = data.state;
    myPlayerIdx = data.your_player_idx;
    legalActions = data.legal_actions;
    renderGame();
});

socket.on('state_update', (data) => {
    gameState = data.state;
    legalActions = data.legal_actions;
    renderGame();
});
```

### Pattern 3: YGO-Style Card Component (HTML/CSS)
**What:** Card rendered as a styled div with 2:3 aspect ratio, attribute circle, stats.
**When to use:** Hand cards and board minions (compact variant).
**Example:**
```html
<!-- Hand card (full size) -->
<div class="card-frame card-type-minion" style="--card-bg: rgb(180,140,60)">
  <div class="card-art">
    <div class="attr-circle attr-fire"></div>
  </div>
  <div class="card-mana">3</div>
  <div class="card-name">Fire Imp</div>
  <div class="card-stats">
    <span class="card-atk">ATK/20</span>
    <span class="card-hp">HP/10</span>
  </div>
</div>
```
```css
.card-frame {
    aspect-ratio: 2/3;
    width: 120px;
    background: var(--card-bg);
    border: 2px solid rgb(30, 25, 20);
    border-radius: 3%;
    position: relative;
    font-family: 'Luckiest Guy', cursive;
}
.card-art {
    width: 96%;
    aspect-ratio: 1;
    margin: 2% auto 0;
    background: rgba(255,255,255,0.15);
    border-radius: 3%;
    border: 1px solid rgb(30, 25, 20);
    position: relative;
}
.attr-circle {
    position: absolute;
    top: 4%;
    right: 4%;
    width: 18%;
    aspect-ratio: 1;
    border-radius: 50%;
    border: 2px solid rgb(30, 25, 20);
}
.attr-circle::after {
    content: '';
    position: absolute;
    top: 9%;
    left: 9%;
    width: 82%;
    height: 82%;
    border-radius: 50%;
    border: 1px solid rgba(255,255,255,0.5);
}
.attr-fire { background: rgb(220, 40, 30); }
.attr-dark { background: rgb(130, 50, 180); }
.attr-light { background: rgb(240, 220, 40); }
.attr-earth { background: rgb(140, 100, 40); }
.attr-neutral { background: rgb(128, 128, 128); }
.card-mana {
    position: absolute;
    top: 3%;
    left: 3%;
    width: 16%;
    aspect-ratio: 1;
    border-radius: 50%;
    background: rgb(30, 100, 220);
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.9em;
    font-weight: 900;
    border: 2px solid rgb(30, 25, 20);
    z-index: 2;
}
.card-name {
    text-align: center;
    color: white;
    -webkit-text-stroke: 1px black;
    text-stroke: 1px black;
    paint-order: stroke fill;
    font-size: 0.7em;
    padding: 2% 4%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.card-stats {
    display: flex;
    justify-content: space-between;
    padding: 0 4%;
    color: white;
    -webkit-text-stroke: 1px black;
    font-size: 0.6em;
}
```

### Pattern 4: Board Perspective Flip (D-03)
**What:** P2 sees the board upside-down so they're at the bottom.
**When to use:** Always -- both players see their side at bottom.
**Example:**
```javascript
function renderBoard(state) {
    const rows = [0, 1, 2, 3, 4];
    // P2 sees rows reversed: their back row (4) appears at bottom
    const displayRows = myPlayerIdx === 0 ? rows : rows.slice().reverse();
    // P1: rows 0,1,2,3,4 top-to-bottom (P2 zone at top, P1 at bottom)
    // P2: rows 4,3,2,1,0 top-to-bottom (P1 zone at top, P2 at bottom)
    displayRows.forEach(row => {
        for (let col = 0; col < 5; col++) {
            renderCell(row, col);
        }
    });
}
```

### Pattern 5: Deck Builder with localStorage Save Slots
**What:** Browse cards, build deck (3 copies max, 30 total), save to named slots.
**When to use:** Deck builder screen (D-07, D-08).
**Example:**
```javascript
const MAX_DECK_SIZE = 30;
const MAX_COPIES = 3;
const MAX_SLOTS = 5;

function saveDeck(slotIndex, name, deckList) {
    const slots = JSON.parse(localStorage.getItem('gt_deck_slots') || '[]');
    slots[slotIndex] = { name, cards: deckList, saved_at: Date.now() };
    localStorage.setItem('gt_deck_slots', JSON.stringify(slots));
}

function loadDeckSlots() {
    return JSON.parse(localStorage.getItem('gt_deck_slots') || '[]');
}
```

### Pattern 6: Lobby Deck Selection + Ready (D-09)
**What:** After joining room, player selects a saved deck from dropdown, then clicks ready.
**When to use:** Lobby screen between join and game start.
**Example:**
```javascript
socket.emit('ready', {
    deck: selectedDeck  // array of card_id strings or numeric_ids
});
```
**Server change needed:** The `handle_ready` handler in `events.py` currently ignores the `data` payload. It needs to extract `data.get('deck')` and store it on the PlayerSlot so `start_game()` uses the player's chosen deck instead of the preset.

### Anti-Patterns to Avoid
- **Building a SPA framework:** Use vanilla JS string-template rendering (consistent with dashboard). Do not introduce React, Vue, or a bundler.
- **Modifying web-dashboard/index.html for game UI:** The Vercel dashboard is separate from the Flask-served game UI. Do not merge them.
- **Hardcoded card data in JS:** Use `card_defs` from the server's `game_start` event, not a static JS object. The existing `CARD_DB` in the dashboard is a separate concern.
- **Polling for state:** Use Socket.IO events (push), not HTTP polling. The server already pushes `state_update` after every action.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Real-time communication | Custom WebSocket protocol | Socket.IO (already in use) | Handles reconnection, rooms, namespaces, fallback to long-polling |
| Font rendering | Canvas text rendering | Google Fonts CSS `@import` for LuckiestGuy | Font rendering is a browser native capability |
| Card aspect ratio | JS resize calculations | CSS `aspect-ratio: 2/3` | Native CSS property, zero JS needed |
| Text stroke effect | Canvas overlay | CSS `-webkit-text-stroke` + `paint-order: stroke fill` | Browser-native, works in all modern browsers |
| Deck persistence | Custom server-side storage | localStorage | Deck builder is client-side only (D-08), no server persistence needed |

**Key insight:** This phase is pure UI rendering. The server infrastructure (events, state filtering, room management) already exists from Phases 11-12. The work is translating server data into visual HTML.

## Common Pitfalls

### Pitfall 1: Missing Card Data in card_defs
**What goes wrong:** The current `_build_card_defs()` only sends name, card_type, mana_cost, attack, health, attack_range, and element. It does NOT send effects, tribe, react_condition, card_id, react_effect, or promote_target. UI-02 requires "full card details" including effects.
**Why it happens:** Phase 12 implemented minimal card_defs for basic rendering.
**How to avoid:** Enhance `_build_card_defs()` to serialize all CardDefinition fields needed for UI rendering. At minimum add: effects (as list of dicts), tribe, react_condition, card_id.
**Warning signs:** Cards show name and stats but no effect text or tribe.

### Pitfall 2: Element Enum Integer Mapping
**What goes wrong:** Server sends `element` as an integer (Element IntEnum). Client needs to map these to attribute colors and names.
**Why it happens:** The Element enum is: WOOD=0, FIRE=1, EARTH=2, WATER=3, METAL=4, DARK=5, LIGHT=6. But D-05 only defines colors for Fire, Dark, Light, Earth, and Neutral. Wood, Water, Metal need colors too (from dashboard: wood=#66bb6a, water=#42a5f5, metal=#bdbdbd).
**How to avoid:** Define a complete ELEMENT_MAP in JS that covers all 7 elements plus a fallback for null/undefined.
**Warning signs:** Some cards show no attribute circle or wrong color.

### Pitfall 3: CardType Enum Mapping for Backgrounds
**What goes wrong:** Server sends `card_type` as integer. CardType: MINION=0, MAGIC=1, REACT=2. Must map to correct background colors.
**Why it happens:** Easy to mix up integer values.
**How to avoid:** Explicit mapping constant:
```javascript
const TYPE_COLORS = {
    0: 'rgb(180,140,60)',   // MINION = gold
    1: 'rgb(30,140,120)',   // MAGIC = teal
    2: 'rgb(160,40,100)',   // REACT = magenta
};
```

### Pitfall 4: Board Coordinate System vs Display
**What goes wrong:** Server board uses (row, col) where row 0 is P2's back row and row 4 is P1's back row. P2 needs the display flipped but the data coordinates stay the same.
**Why it happens:** Confusion between display order and data coordinates.
**How to avoid:** Only flip the display iteration order (rows 4->0 for P2). Never modify the actual coordinates in state data. When rendering cells, always use the original (row, col) from state.
**Warning signs:** Minions appear on wrong side of board for one player.

### Pitfall 5: Hand Card Index vs Card Numeric ID
**What goes wrong:** The hand in state is an array of `card_numeric_id` integers. Legal actions reference `card_index` (position in hand array, 0-based). Confusing these causes wrong card selections.
**Why it happens:** Two different indexing systems.
**How to avoid:** When rendering hand, store both: the card_numeric_id (for rendering via card_defs lookup) and the hand index (for action submission in Phase 14).
**Warning signs:** Clicking a card plays a different card.

### Pitfall 6: Minion Board State Structure
**What goes wrong:** Minions are NOT stored in board cells. The `state.board` array contains cell ownership info (or is flat). Minions are in `state.minions[]` with position `[row, col]`. Must iterate minions and place them at their position.
**Why it happens:** Assuming board is a 2D grid of units.
**How to avoid:** Build a position-to-minion lookup from `state.minions`: `const minionMap = {}; state.minions.forEach(m => minionMap[m.position.join(',')] = m);`
**Warning signs:** Board renders but no minions appear.

### Pitfall 7: Deck Submission Format
**What goes wrong:** Server's `get_preset_deck()` returns a tuple of card_numeric_ids. If the client sends card_id strings, the server won't understand them.
**Why it happens:** Mismatch between client's card knowledge (card_id strings from card_defs or deck builder) and server's numeric ID system.
**How to avoid:** Either (a) client sends numeric_ids directly, or (b) server converts card_id strings to numeric_ids on receipt. Option (a) is simpler since card_defs already include numeric_id as the key.
**Warning signs:** "Invalid deck" errors when readying up.

### Pitfall 8: Socket.IO Connection Before Flask Serves HTML
**What goes wrong:** If Flask doesn't serve the game HTML correctly, Socket.IO client can't connect.
**Why it happens:** Flask's static_folder or template configuration is wrong.
**How to avoid:** Test the route: `curl http://localhost:5000/` should return the game HTML. Set `static_folder` to the directory containing game assets.

## Code Examples

### Enhanced _build_card_defs (Server-Side)
```python
# Source: Existing events.py _build_card_defs, enhanced for UI-02
def _build_card_defs(library):
    """Build dict mapping numeric_id to card info for client rendering."""
    defs = {}
    for nid in range(library.card_count):
        try:
            card = library.get_by_id(nid)
            d = {
                "card_id": card.card_id,
                "name": card.name,
                "card_type": int(card.card_type),
                "mana_cost": card.mana_cost,
                "attack": card.attack,
                "health": card.health,
                "attack_range": card.attack_range,
                "element": int(card.element) if card.element is not None else None,
                "tribe": card.tribe,
            }
            # Serialize effects for display
            if card.effects:
                d["effects"] = [
                    {
                        "type": int(e.effect_type),
                        "trigger": int(e.trigger),
                        "target": int(e.target),
                        "amount": e.amount,
                    }
                    for e in card.effects
                ]
            # React condition
            if card.react_condition is not None:
                d["react_condition"] = int(card.react_condition)
            defs[nid] = d
        except (KeyError, IndexError):
            break
    return defs
```

### Card Frame HTML Generation (Client-Side)
```javascript
// Source: Translated from BrandingFrog/ygo CardFrameBuilder.luau
const ELEMENT_NAMES = ['Wood','Fire','Earth','Water','Metal','Dark','Light'];
const ELEMENT_CSS = ['attr-wood','attr-fire','attr-earth','attr-water','attr-metal','attr-dark','attr-light'];
const TYPE_BG = {
    0: 'rgb(180,140,60)',   // Minion = gold
    1: 'rgb(30,140,120)',   // Magic = teal
    2: 'rgb(160,40,100)',   // React = magenta
};
const TYPE_NAMES = ['Minion', 'Magic', 'React'];

function renderHandCard(numericId, handIndex, canAfford) {
    const c = cardDefs[numericId];
    if (!c) return '';
    const bg = TYPE_BG[c.card_type] || 'rgb(100,100,100)';
    const dimClass = canAfford ? '' : ' card-dimmed';
    let h = `<div class="card-frame${dimClass}" data-hand-idx="${handIndex}" style="--card-bg:${bg}">`;
    // Mana cost badge (top-left)
    h += `<div class="card-mana">${c.mana_cost}</div>`;
    // Art area with attribute circle
    h += '<div class="card-art">';
    if (c.element !== null && c.element !== undefined) {
        h += `<div class="attr-circle ${ELEMENT_CSS[c.element]}">`;
        h += '<div class="attr-inner-ring"></div></div>';
    }
    h += '</div>';
    // Name
    h += `<div class="card-name">${c.name}</div>`;
    // Stats (minion) or effect text (magic/react)
    if (c.card_type === 0 && c.attack != null) {
        h += '<div class="card-stats">';
        h += `<span class="card-atk">ATK/${c.attack}</span>`;
        h += `<span class="card-hp">HP/${c.health}</span>`;
        h += '</div>';
    }
    h += '</div>';
    return h;
}
```

### Compact Board Minion Rendering
```javascript
// Source: D-10 compact card style for grid cells
function renderBoardMinion(minion, cardDef) {
    const ownerClass = minion.owner === myPlayerIdx ? 'owner-self' : 'owner-opp';
    const elemClass = cardDef.element !== null ? ELEMENT_CSS[cardDef.element] : '';
    let h = `<div class="board-minion ${ownerClass}">`;
    if (elemClass) h += `<div class="board-attr ${elemClass}"></div>`;
    h += `<div class="board-minion-name">${cardDef.name}</div>`;
    h += '<div class="board-minion-stats">';
    const atk = (cardDef.attack || 0) + (minion.attack_bonus || 0);
    h += `<span class="bm-atk">${atk}</span>`;
    h += `<span class="bm-hp">${minion.current_health}</span>`;
    h += '</div></div>';
    return h;
}
```

### Perspective-Flipped Board Rendering
```javascript
// Source: D-03 board flip logic
function renderBoard() {
    const el = document.getElementById('game-board');
    let h = '';
    // Display order depends on player perspective
    const rowOrder = myPlayerIdx === 0
        ? [0, 1, 2, 3, 4]    // P1: opponent at top (rows 0-1), self at bottom (rows 3-4)
        : [4, 3, 2, 1, 0];   // P2: opponent at top (rows 3-4 displayed), self at bottom (rows 0-1 displayed)

    // Build minion position lookup
    const minionAt = {};
    (gameState.minions || []).forEach(m => {
        minionAt[m.position[0] + ',' + m.position[1]] = m;
    });

    rowOrder.forEach(row => {
        const zone = getZoneClass(row);
        for (let col = 0; col < 5; col++) {
            const m = minionAt[row + ',' + col];
            h += `<div class="board-cell ${zone}">`;
            if (m) {
                const cd = cardDefs[m.card_numeric_id];
                h += renderBoardMinion(m, cd || {});
            }
            h += '</div>';
        }
    });
    el.innerHTML = h;
}

function getZoneClass(row) {
    // From perspective of P1: rows 0-1 are P2 zone, 2 is neutral, 3-4 are P1 zone
    if (myPlayerIdx === 0) {
        if (row <= 1) return 'zone-opponent';
        if (row === 2) return 'zone-neutral';
        return 'zone-self';
    } else {
        if (row >= 3) return 'zone-opponent';
        if (row === 2) return 'zone-neutral';
        return 'zone-self';
    }
}
```

### Deck Builder localStorage Save/Load
```javascript
const DECK_STORAGE_KEY = 'gt_deck_slots';
const MAX_SLOTS = 5;

function getDeckSlots() {
    try {
        return JSON.parse(localStorage.getItem(DECK_STORAGE_KEY) || '[]');
    } catch { return []; }
}

function saveDeckSlot(index, name, cards) {
    const slots = getDeckSlots();
    while (slots.length <= index) slots.push(null);
    slots[index] = { name, cards, savedAt: Date.now() };
    localStorage.setItem(DECK_STORAGE_KEY, JSON.stringify(slots));
}

function deleteDeckSlot(index) {
    const slots = getDeckSlots();
    if (index < slots.length) slots[index] = null;
    localStorage.setItem(DECK_STORAGE_KEY, JSON.stringify(slots));
}
```

### Turn/Phase Indicator
```javascript
function renderTurnIndicator() {
    const isMyTurn = legalActions.length > 0;
    const phase = gameState.phase; // 0 = ACTION, 1 = REACT
    const phaseLabel = phase === 1 ? 'REACT' : 'ACTION';
    const turnLabel = isMyTurn ? 'YOUR TURN' : "OPPONENT'S TURN";
    const turnClass = isMyTurn ? 'turn-yours' : 'turn-theirs';

    return `<div class="turn-banner ${turnClass}">
        <span class="turn-label">${turnLabel}</span>
        <span class="phase-badge phase-${phaseLabel.toLowerCase()}">${phaseLabel}</span>
        <span class="turn-number">Turn ${gameState.turn_number}</span>
    </div>`;
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `aspect-ratio` polyfill | Native CSS `aspect-ratio` | 2021+ (all browsers) | Card 2:3 ratio is one CSS property, no padding hacks |
| `-webkit-text-stroke` only | `paint-order: stroke fill` + `-webkit-text-stroke` | 2022+ | Text stroke renders correctly (stroke behind fill, not overlapping) |
| Socket.IO v2 | Socket.IO v4 (CDN) | 2021 | Breaking changes in transport, already on v4 in project |

**Deprecated/outdated:**
- `aspect-ratio` padding hack: No longer needed. All modern browsers support `aspect-ratio` natively.
- Google Fonts v1 API: Use v2 (`fonts.googleapis.com/css2?family=Luckiest+Guy`).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | None (pytest auto-discovers tests/) |
| Quick run command | `.venv/Scripts/python -m pytest tests/test_pvp_server.py -x -q` |
| Full suite command | `.venv/Scripts/python -m pytest tests/ -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UI-01 | Board renders 5x5 grid with minions | manual | Visual inspection in browser | N/A |
| UI-02 | Hand shows card details, dimmed when unaffordable | manual | Visual inspection in browser | N/A |
| UI-03 | Mana/HP displayed for both players | manual | Visual inspection in browser | N/A |
| UI-04 | Turn/phase indicator correct | manual | Visual inspection in browser | N/A |
| -- | card_defs includes effects/tribe/card_id | unit | `.venv/Scripts/python -m pytest tests/test_pvp_server.py -x -q` | Needs new test |
| -- | Board perspective flip logic (P2 rows reversed) | unit | `.venv/Scripts/python -m pytest tests/test_board_ui.py -x -q` | Wave 0 |
| -- | Deck save/load localStorage | manual | Browser dev tools inspection | N/A |
| -- | Flask serves game.html at / | unit | `.venv/Scripts/python -m pytest tests/test_pvp_server.py -x -q` | Needs new test |

**Note:** This is primarily a UI phase. Most requirements (UI-01 through UI-04) are visual and require manual browser verification. Automated tests cover the server-side enhancements (card_defs completeness, Flask routing).

### Sampling Rate
- **Per task commit:** `.venv/Scripts/python -m pytest tests/test_pvp_server.py -x -q`
- **Per wave merge:** `.venv/Scripts/python -m pytest tests/ -q`
- **Phase gate:** Full suite green + visual browser verification (two windows, same room)

### Wave 0 Gaps
- [ ] `tests/test_pvp_server.py::test_card_defs_include_effects` -- verifies enhanced card_defs
- [ ] `tests/test_pvp_server.py::test_flask_serves_game_html` -- verifies Flask route returns HTML
- [ ] `tests/test_pvp_server.py::test_ready_with_deck` -- verifies deck submission on ready

## Open Questions

1. **Deck card_id vs numeric_id in deck builder**
   - What we know: Server uses numeric_ids internally. Card JSON uses string card_ids. `_build_card_defs` maps numeric_id -> card info.
   - What's unclear: Should the deck builder work with card_id strings (human-readable) or numeric_ids?
   - Recommendation: Use card_id strings in localStorage (human-readable, stable across library reloads). Convert to numeric_ids when sending to server. The card_defs already include card_id field (after enhancement).

2. **Deck builder card source**
   - What we know: The deck builder needs to show all available cards. In the dashboard, CARD_DB is hardcoded.
   - What's unclear: Should the Flask-served game UI fetch card list from the server or embed it?
   - Recommendation: Add a REST endpoint (`/api/cards`) that returns card_defs, OR embed card_defs in the game HTML via a Jinja template variable, OR request them via Socket.IO before showing the deck builder. The Socket.IO approach is simplest -- emit a `get_cards` event and receive `card_list` response.

3. **How to handle element colors for Wood/Water/Metal**
   - What we know: D-05 defines colors for Fire, Dark, Light, Earth, and Neutral. The game has 7 elements: Wood, Fire, Earth, Water, Metal, Dark, Light.
   - What's unclear: No D-05 color specified for Wood, Water, or Metal.
   - Recommendation: Use dashboard's existing element colors: Wood=green(102,187,106), Water=blue(66,165,245), Metal=gray(189,189,189). These are already in the dashboard CSS.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Flask server | Yes | 3.12.10 (.venv) | -- |
| Flask | HTTP serving | Yes | 3.1.3 | -- |
| Flask-SocketIO | Real-time events | Yes | 5.6.1 | -- |
| pytest | Testing | Yes | 9.0.2 | -- |
| Google Fonts CDN | LuckiestGuy font | Yes (internet) | -- | Self-host font file |
| socket.io-client CDN | Browser Socket.IO | Yes (internet) | 4.x | Bundle locally |
| Modern browser | CSS aspect-ratio, text-stroke | Yes (dev machine) | -- | -- |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

## Sources

### Primary (HIGH confidence)
- `BrandingFrog/ygo` repo `src/client/CardFrameBuilder.luau` -- 333-line Roblox card renderer (fetched via `gh api`). Layout pattern: 2:3 aspect, art at top (96% width, 1:1 aspect), attribute circle at top-right of art (18% size, with inner ring), name at 66% Y, ATK/DEF at 90% Y, LuckiestGuy font, UIStroke for text outline, UICorner 3% radius.
- `BrandingFrog/ygo` repo `src/shared/Constants.luau` -- Color tables: TYPE_COLORS (Monster=rgb(180,140,60), Spell=rgb(30,140,120), Trap=rgb(160,40,100)), ATTRIBUTE_COLOR (Earth=rgb(140,100,40), Fire=rgb(220,40,30), Light=rgb(240,220,40), Dark=rgb(130,50,180)).
- `src/grid_tactics/server/events.py` -- Existing `_build_card_defs()`, `game_start` emit, `state_update` emit.
- `src/grid_tactics/server/view_filter.py` -- Filtered state structure.
- `src/grid_tactics/game_state.py::to_dict()` -- Full state serialization format.
- `src/grid_tactics/enums.py` -- CardType (0=MINION,1=MAGIC,2=REACT), Element (0-6), TurnPhase (0=ACTION,1=REACT).
- `web-dashboard/index.html` -- Existing dashboard CSS variables, tab navigation, Duel tab placeholder CSS and mock rendering functions.
- `src/grid_tactics/server/room_manager.py` -- PlayerSlot.deck field already exists (defaults to None/preset).
- [Google Fonts - Luckiest Guy](https://fonts.google.com/specimen/Luckiest+Guy) -- Font availability confirmed.

### Secondary (MEDIUM confidence)
- CSS `aspect-ratio` browser support: universal in modern browsers (Chrome 88+, Firefox 89+, Safari 15+).
- CSS `paint-order` for text-stroke: supported in Chrome 35+, Firefox 60+, Safari 8+.

### Tertiary (LOW confidence)
- None -- all findings verified against primary sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- Flask, Socket.IO, and vanilla JS are already established in the project
- Architecture: HIGH -- Extending existing server patterns and dashboard CSS conventions
- Card design: HIGH -- Direct translation from YGO Luau source code (read from repo)
- Pitfalls: HIGH -- Identified from reading actual server code and data structures
- Deck builder: MEDIUM -- localStorage pattern is standard, but deck submission to server needs minor server changes

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (stable -- no fast-moving dependencies)
