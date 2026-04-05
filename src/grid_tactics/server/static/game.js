/* Grid Tactics - Client-Side Game Logic
   Socket.IO integration, lobby, deck builder, and game rendering.
   Vanilla JS (no modules, no build step). */

// =============================================
// Section 1: Constants and Enum Mappings
// =============================================

const TYPE_COLORS = {
    0: 'rgb(180,140,60)',   // MINION = gold
    1: 'rgb(30,140,120)',   // MAGIC = teal
    2: 'rgb(160,40,100)',   // REACT = magenta
};
const TYPE_NAMES = ['Minion', 'Magic', 'React'];
const TYPE_CSS = ['card-type-minion', 'card-type-magic', 'card-type-react'];

const ELEMENT_MAP = {
    0: { name: 'Wood',  color: 'rgb(102,187,106)', css: 'attr-wood' },
    1: { name: 'Fire',  color: 'rgb(220,40,30)',   css: 'attr-fire' },
    2: { name: 'Earth', color: 'rgb(140,100,40)',   css: 'attr-earth' },
    3: { name: 'Water', color: 'rgb(66,165,245)',   css: 'attr-water' },
    4: { name: 'Metal', color: 'rgb(189,189,189)',  css: 'attr-metal' },
    5: { name: 'Dark',  color: 'rgb(130,50,180)',   css: 'attr-dark' },
    6: { name: 'Light', color: 'rgb(240,220,40)',   css: 'attr-light' },
};
const NEUTRAL_ELEMENT = { name: 'Neutral', color: 'rgb(128,128,128)', css: 'attr-neutral' };

const PHASE_DISPLAY = {
    0: { label: 'ACTION', cssClass: 'phase-action', bg: 'var(--cyan)' },
    1: { label: 'REACT',  cssClass: 'phase-react',  bg: 'var(--yellow)' },
};

const EFFECT_TYPE_NAMES = [
    'Damage', 'Heal', 'Buff ATK', 'Buff HP', 'Negate',
    'Deploy Self', 'Rally Forward', 'Promote', 'Tutor', 'Destroy'
];
const TRIGGER_NAMES = ['On Play', 'On Death', 'On Attack', 'On Damaged', 'On Move'];
const TARGET_NAMES = ['Single Target', 'All Enemies', 'Adjacent', 'Self/Owner'];

const MAX_DECK_SIZE = 30;
const MAX_COPIES = 3;
const MAX_SLOTS = 5;
const STORAGE_KEY = 'gt_deck_slots';

// =============================================
// Section 2: Client State Variables
// =============================================

let socket = null;
let cardDefs = {};           // numeric_id -> CardInfo (from game_start or get_card_defs)
let gameState = null;        // latest filtered state
let myPlayerIdx = null;      // 0 or 1
let legalActions = [];       // current legal actions
let sessionToken = null;     // from room_created/room_joined
let roomCode = null;         // current room code
let opponentName = '';       // from game_start
let myName = '';             // display name entered in lobby

// Deck builder state
let currentDeck = {};        // { numericId: count }
let currentSlotIdx = 0;
let allCardDefs = null;      // set from server on game_start or card_defs event
let deckFilterType = 'all';     // 'all', 'minion', 'magic', 'react'
let deckFilterElement = 'all';  // 'all', or element int as string
let deckFilterMana = 'all';     // 'all', '1', '2', '3', '4', '5+'
let deckSearchQuery = '';       // search text

// =============================================
// Section 3: Screen Manager
// =============================================

function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(function(el) {
        el.classList.remove('active');
    });
    var target = document.getElementById(screenId);
    if (target) {
        target.classList.add('active');
    }
    // Update nav button active state
    document.querySelectorAll('.nav-btn').forEach(function(btn) {
        if (btn.dataset.screen === screenId.replace('screen-', '')) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    // Render deck builder when switching to it
    if (screenId === 'screen-deck-builder' && allCardDefs) {
        renderDeckBuilder();
    }
}
window.showScreen = showScreen;

function setupNavHandlers() {
    document.querySelectorAll('.nav-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var screenName = btn.dataset.screen;
            if (screenName) {
                showScreen('screen-' + screenName);
            }
        });
    });
}

// =============================================
// Section 4: Socket.IO Connection
// =============================================

function initSocket() {
    socket = io();
    socket.on('connect', function() {
        document.getElementById('conn-dot').className = 'dot on';
        document.getElementById('conn-text').textContent = 'Connected';
        // Request card_defs for deck builder
        socket.emit('get_card_defs', {});
    });
    socket.on('disconnect', function() {
        document.getElementById('conn-dot').className = 'dot off';
        document.getElementById('conn-text').textContent = 'Disconnected';
    });
    // Register all event handlers
    socket.on('room_created', onRoomCreated);
    socket.on('room_joined', onRoomJoined);
    socket.on('player_joined', onPlayerJoined);
    socket.on('player_ready', onPlayerReady);
    socket.on('game_start', onGameStart);
    socket.on('state_update', onStateUpdate);
    socket.on('game_over', onGameOver);
    socket.on('error', onError);
    socket.on('card_defs', onCardDefs);
}

// =============================================
// Section 5: Lobby Event Handlers
// =============================================

function onRoomCreated(data) {
    sessionToken = data.session_token;
    roomCode = data.room_code;
    showRoomPanel();
    document.getElementById('room-code-display').textContent = roomCode;
    var playerList = document.getElementById('player-list');
    playerList.innerHTML = '';
    addPlayerToList(myName, false);
    showLobbyStatus('Waiting for opponent...', 'info');
}

function onRoomJoined(data) {
    sessionToken = data.session_token;
    roomCode = data.room_code;
    showRoomPanel();
    document.getElementById('room-code-display').textContent = roomCode;
    var playerList = document.getElementById('player-list');
    playerList.innerHTML = '';
    if (data.players) {
        data.players.forEach(function(p) {
            addPlayerToList(p.name, p.ready);
        });
    }
    showLobbyStatus('Room joined! Select a deck and ready up.', 'info');
}

function onPlayerJoined(data) {
    addPlayerToList(data.display_name, false);
    showLobbyStatus('Opponent joined! Select a deck and ready up.', 'info');
}

function onPlayerReady(data) {
    // Mark player as ready in the player list
    var items = document.querySelectorAll('#player-list .player-item');
    items.forEach(function(item) {
        var nameEl = item.querySelector('.player-item-name');
        if (nameEl && nameEl.textContent === data.player_name) {
            var dot = item.querySelector('.dot');
            if (dot) {
                dot.className = 'dot on';
            }
        }
    });
}

function onCardDefs(data) {
    if (data && data.card_defs) {
        allCardDefs = data.card_defs;
        cardDefs = data.card_defs;
        // Re-render deck builder if visible
        if (document.getElementById('screen-deck-builder').classList.contains('active')) {
            renderDeckBuilder();
        }
    }
}

function onError(data) {
    var msg = data && data.msg ? data.msg : 'An error occurred.';
    showLobbyStatus(msg, 'error');
}

// =============================================
// Section 6: Lobby UI Handlers
// =============================================

function setupLobbyHandlers() {
    // Create Room
    var btnCreate = document.getElementById('btn-create-room');
    if (btnCreate) {
        btnCreate.addEventListener('click', function() {
            var nameInput = document.getElementById('input-name');
            var name = nameInput ? nameInput.value.trim() : '';
            if (!name) {
                showLobbyStatus('Please enter a display name.', 'error');
                return;
            }
            myName = name;
            socket.emit('create_room', { display_name: name });
        });
    }

    // Join Room
    var btnJoin = document.getElementById('btn-join-room');
    if (btnJoin) {
        btnJoin.addEventListener('click', function() {
            var nameInput = document.getElementById('input-name');
            var codeInput = document.getElementById('input-room-code');
            var name = nameInput ? nameInput.value.trim() : '';
            var code = codeInput ? codeInput.value.trim().toUpperCase() : '';
            if (!name) {
                showLobbyStatus('Please enter a display name.', 'error');
                return;
            }
            if (!code) {
                showLobbyStatus('Please enter a room code.', 'error');
                return;
            }
            myName = name;
            socket.emit('join_room', { display_name: name, room_code: code });
        });
    }

    // Room code input: enforce uppercase, max 6 chars
    var codeInput = document.getElementById('input-room-code');
    if (codeInput) {
        codeInput.addEventListener('input', function() {
            codeInput.value = codeInput.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);
        });
    }

    // Ready button
    var btnReady = document.getElementById('btn-ready');
    if (btnReady) {
        btnReady.addEventListener('click', function() {
            var deckSelector = document.getElementById('deck-selector');
            var selectedIdx = deckSelector ? deckSelector.value : '';
            var deckArray = null;
            if (selectedIdx !== '') {
                var slots = loadDeckSlots();
                var idx = parseInt(selectedIdx, 10);
                if (idx >= 0 && idx < slots.length) {
                    deckArray = getDeckAsArray(slots[idx].cards);
                }
            }
            socket.emit('ready', { deck: deckArray });
            btnReady.disabled = true;
            btnReady.textContent = 'Waiting...';
        });
    }

    // Populate deck selector dropdown from localStorage
    populateDeckSelector();
}

function showRoomPanel() {
    var panel = document.getElementById('room-panel');
    if (panel) panel.style.display = '';
}

function addPlayerToList(name, ready) {
    var playerList = document.getElementById('player-list');
    if (!playerList) return;
    var div = document.createElement('div');
    div.className = 'player-item';
    var dot = document.createElement('span');
    dot.className = ready ? 'dot on' : 'dot off';
    var nameSpan = document.createElement('span');
    nameSpan.className = 'player-item-name';
    nameSpan.textContent = name;
    div.appendChild(dot);
    div.appendChild(nameSpan);
    playerList.appendChild(div);
}

function showLobbyStatus(message, type) {
    var statusEl = document.getElementById('lobby-status');
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.className = 'lobby-status ' + (type || '');
}

function populateDeckSelector() {
    var selector = document.getElementById('deck-selector');
    if (!selector) return;
    // Clear existing options except the default
    selector.innerHTML = '<option value="">Default Deck</option>';
    var slots = loadDeckSlots();
    slots.forEach(function(slot, idx) {
        var totalCards = getDeckTotal(slot.cards);
        var opt = document.createElement('option');
        opt.value = idx;
        opt.textContent = slot.name + ' (' + totalCards + '/30)';
        selector.appendChild(opt);
    });
}

// =============================================
// Section 7: Deck Builder Logic
// =============================================

function loadDeckSlots() {
    try {
        var raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        var parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed;
    } catch (e) {
        return [];
    }
}

function saveDeckSlots(slots) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(slots));
}

function saveDeckSlot(idx, name, deckObj) {
    var slots = loadDeckSlots();
    while (slots.length <= idx) {
        slots.push({ name: 'Deck ' + (slots.length + 1), cards: {} });
    }
    slots[idx] = { name: name, cards: deckObj };
    saveDeckSlots(slots);
}

function deleteDeckSlot(idx) {
    var slots = loadDeckSlots();
    if (idx >= 0 && idx < slots.length) {
        slots.splice(idx, 1);
        saveDeckSlots(slots);
    }
}

function getDeckAsArray(deckObj) {
    var arr = [];
    if (!deckObj) return arr;
    Object.keys(deckObj).forEach(function(numId) {
        var count = deckObj[numId];
        for (var i = 0; i < count; i++) {
            arr.push(parseInt(numId, 10));
        }
    });
    return arr;
}

function getDeckTotal(deckObj) {
    if (!deckObj) return 0;
    var total = 0;
    Object.keys(deckObj).forEach(function(key) {
        total += deckObj[key];
    });
    return total;
}

function addCardToDeck(numericId) {
    var count = currentDeck[numericId] || 0;
    if (count >= MAX_COPIES) return;
    if (getDeckTotal(currentDeck) >= MAX_DECK_SIZE) return;
    currentDeck[numericId] = count + 1;
    renderDeckBuilder();
}

function removeCardFromDeck(numericId) {
    var count = currentDeck[numericId] || 0;
    if (count <= 0) return;
    count--;
    if (count === 0) {
        delete currentDeck[numericId];
    } else {
        currentDeck[numericId] = count;
    }
    renderDeckBuilder();
}

function renderDeckBuilder() {
    renderCardBrowser();
    renderDeckSidebar();
}

function renderCardBrowser() {
    var grid = document.getElementById('card-browser-grid');
    if (!grid) return;
    var defs = allCardDefs || cardDefs;
    if (!defs || Object.keys(defs).length === 0) {
        grid.innerHTML = '<div class="deck-empty-state"><h4>Loading cards...</h4><p>Connect to the server to browse cards</p></div>';
        return;
    }
    grid.innerHTML = '';
    // Type filter map: card_type int -> filter name
    var typeMap = {0: 'minion', 1: 'magic', 2: 'react'};
    var query = deckSearchQuery.toLowerCase().trim();
    // Sort by card_type then name
    var ids = Object.keys(defs).map(Number).sort(function(a, b) {
        var ca = defs[a], cb = defs[b];
        if (ca.card_type !== cb.card_type) return ca.card_type - cb.card_type;
        return (ca.name || '').localeCompare(cb.name || '');
    });
    ids.forEach(function(numId) {
        var c = defs[numId];
        // Type filter
        if (deckFilterType !== 'all' && typeMap[c.card_type] !== deckFilterType) return;
        // Element filter
        if (deckFilterElement !== 'all') {
            var cardElem = (c.attribute !== undefined && c.attribute !== null) ? String(c.attribute) : '-1';
            if (deckFilterElement !== cardElem) return;
        }
        // Mana filter
        if (deckFilterMana !== 'all') {
            var manaCost = c.mana_cost || 0;
            if (deckFilterMana === '5+') {
                if (manaCost < 5) return;
            } else {
                if (manaCost !== parseInt(deckFilterMana)) return;
            }
        }
        // Search filter
        if (query) {
            var searchable = (c.name || '').toLowerCase() + ' ' + (c.card_id || '').toLowerCase();
            if (searchable.indexOf(query) === -1) return;
        }
        var count = currentDeck[numId] || 0;
        var wrapper = document.createElement('div');
        wrapper.className = 'card-browser-item';
        if (count > 0) wrapper.classList.add('card-selected');
        wrapper.innerHTML = renderDeckBuilderCard(numId, count);
        // Click to add
        wrapper.addEventListener('click', function(e) {
            if (e.shiftKey) {
                removeCardFromDeck(numId);
            } else {
                addCardToDeck(numId);
            }
        });
        // Right-click to remove
        wrapper.addEventListener('contextmenu', function(e) {
            e.preventDefault();
            removeCardFromDeck(numId);
        });
        grid.appendChild(wrapper);
    });
}

function setupDeckFilters() {
    var searchInput = document.getElementById('card-search');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            deckSearchQuery = searchInput.value;
            renderCardBrowser();
        });
    }
    // Type filters
    document.querySelectorAll('#type-filters .filter-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            deckFilterType = btn.dataset.filter;
            document.querySelectorAll('#type-filters .filter-btn').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            renderCardBrowser();
        });
    });
    // Element filters
    document.querySelectorAll('#element-filters .filter-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            deckFilterElement = btn.dataset.filter;
            document.querySelectorAll('#element-filters .filter-btn').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            renderCardBrowser();
        });
    });
    // Mana filters
    document.querySelectorAll('#mana-filters .filter-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            deckFilterMana = btn.dataset.filter;
            document.querySelectorAll('#mana-filters .filter-btn').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            renderCardBrowser();
        });
    });
}

function renderDeckBuilderCard(numericId, count) {
    var c = allCardDefs ? allCardDefs[numericId] : cardDefs[numericId];
    if (!c) return '';
    var typeClass = TYPE_CSS[c.card_type] || '';
    var elem = (c.element !== null && c.element !== undefined)
        ? ELEMENT_MAP[c.element] : NEUTRAL_ELEMENT;

    var html = '<div class="card-frame card-frame-full ' + typeClass + '">';
    // Mana badge
    html += '<div class="card-mana">' + c.mana_cost + '</div>';
    // Art area with attribute circle and name overlay (YGO CardPreview style)
    var artStyle = c.card_id ? 'background-image:url(/static/art/' + c.card_id + '.png)' : '';
    html += '<div class="card-art card-art-full" style="' + artStyle + '">';
    html += '<div class="attr-circle ' + elem.css + '"><span class="attr-text">' + elem.name + '</span></div>';
    html += '<div class="card-art-overlay"></div>';
    html += '<div class="card-name-overlay">' + c.name + '</div>';
    html += '</div>';
    // Tribe badge (replaces type badge per user request)
    var tribe = c.tribe || '';
    if (tribe) {
        html += '<div class="card-type-badge">' + tribe + '</div>';
    }
    // Stats for minions
    if (c.card_type === 0 && c.attack != null) {
        html += '<div class="card-stats">';
        html += '<span class="card-atk">ATK/' + c.attack + '</span>';
        html += '<span class="card-hp">HP/' + c.health + '</span>';
        html += '</div>';
    }
    // Effect text (all card types)
    if (c.effects && c.effects.length > 0) {
        var desc = getEffectDescription(c.effects);
        html += '<div class="card-effect-full">' + desc + '</div>';
    }
    // Range for minions
    if (c.card_type === 0 && c.attack_range != null) {
        var rangeText = c.attack_range <= 1 ? 'Melee' : 'Range ' + c.attack_range;
        html += '<div class="card-range">' + rangeText + '</div>';
    }
    html += '</div>';
    // Count badge
    var badgeClass = count > 0 ? 'card-count-badge' : 'card-count-badge empty';
    html += '<div class="' + badgeClass + '">x' + count + '</div>';
    return html;
}

function renderDeckSidebar() {
    var total = getDeckTotal(currentDeck);
    var countEl = document.getElementById('deck-count');
    var statusEl = document.getElementById('deck-status');
    if (countEl) {
        countEl.textContent = total + '/30 cards';
        countEl.className = 'deck-count ' + (total === 30 ? 'valid' : 'invalid');
    }
    if (statusEl) {
        if (total === 30) {
            statusEl.textContent = 'Ready to play';
            statusEl.className = 'deck-status valid';
        } else {
            statusEl.textContent = 'Need 30 cards';
            statusEl.className = 'deck-status invalid';
        }
    }

    // Group cards by type
    var groups = { 0: [], 1: [], 2: [] };
    var defs = allCardDefs || cardDefs;
    Object.keys(currentDeck).forEach(function(numId) {
        var c = defs[numId];
        if (!c) return;
        var type = c.card_type;
        if (groups[type] === undefined) groups[type] = [];
        groups[type].push({ numId: numId, name: c.name, count: currentDeck[numId] });
    });

    // Render each group
    var containers = {
        0: document.getElementById('deck-minions'),
        1: document.getElementById('deck-magic'),
        2: document.getElementById('deck-react'),
    };
    [0, 1, 2].forEach(function(type) {
        var container = containers[type];
        if (!container) return;
        container.innerHTML = '';
        var items = groups[type] || [];
        items.sort(function(a, b) { return a.name.localeCompare(b.name); });
        items.forEach(function(item) {
            var div = document.createElement('div');
            div.className = 'deck-list-item';
            div.innerHTML = '<span class="deck-list-item-name">' + item.name + '</span>'
                + '<span class="deck-list-item-count">x' + item.count + '</span>';
            div.addEventListener('click', function() {
                removeCardFromDeck(parseInt(item.numId, 10));
            });
            container.appendChild(div);
        });
    });
}

function setupDeckBuilderHandlers() {
    // Back to Lobby
    var btnBack = document.getElementById('btn-back-lobby');
    if (btnBack) {
        btnBack.addEventListener('click', function() {
            showScreen('screen-lobby');
            populateDeckSelector();
        });
    }

    // Save Deck
    var btnSave = document.getElementById('btn-save-deck');
    if (btnSave) {
        btnSave.addEventListener('click', function() {
            var nameInput = document.getElementById('deck-slot-name');
            var name = nameInput ? nameInput.value.trim() : '';
            if (!name) name = 'Deck ' + (currentSlotIdx + 1);
            saveDeckSlot(currentSlotIdx, name, Object.assign({}, currentDeck));
            refreshLoadDropdown();
            showLobbyStatus('Deck saved!', 'info');
        });
    }

    // Load Dropdown
    var loadSelect = document.getElementById('deck-load-select');
    if (loadSelect) {
        loadSelect.addEventListener('change', function() {
            var idx = parseInt(loadSelect.value, 10);
            if (isNaN(idx)) return;
            var slots = loadDeckSlots();
            if (idx >= 0 && idx < slots.length) {
                currentSlotIdx = idx;
                currentDeck = Object.assign({}, slots[idx].cards || {});
                var nameInput = document.getElementById('deck-slot-name');
                if (nameInput) nameInput.value = slots[idx].name;
                renderDeckBuilder();
            }
        });
    }

    // Delete Slot with inline confirm
    var btnDelete = document.getElementById('btn-delete-slot');
    var deleteTimeout = null;
    if (btnDelete) {
        btnDelete.addEventListener('click', function() {
            if (btnDelete.dataset.confirming === 'true') {
                // Confirmed -- delete
                deleteDeckSlot(currentSlotIdx);
                currentDeck = {};
                currentSlotIdx = 0;
                var nameInput = document.getElementById('deck-slot-name');
                if (nameInput) nameInput.value = '';
                renderDeckBuilder();
                refreshLoadDropdown();
                populateDeckSelector();
                btnDelete.textContent = 'Delete Slot';
                btnDelete.dataset.confirming = 'false';
                if (deleteTimeout) clearTimeout(deleteTimeout);
            } else {
                // First click -- ask for confirm
                btnDelete.textContent = 'Confirm Delete?';
                btnDelete.dataset.confirming = 'true';
                deleteTimeout = setTimeout(function() {
                    btnDelete.textContent = 'Delete Slot';
                    btnDelete.dataset.confirming = 'false';
                }, 3000);
            }
        });
    }

    refreshLoadDropdown();
}

function refreshLoadDropdown() {
    var loadSelect = document.getElementById('deck-load-select');
    if (!loadSelect) return;
    loadSelect.innerHTML = '<option value="">Load Slot...</option>';
    var slots = loadDeckSlots();
    slots.forEach(function(slot, idx) {
        var opt = document.createElement('option');
        opt.value = idx;
        opt.textContent = slot.name + ' (' + getDeckTotal(slot.cards) + '/30)';
        loadSelect.appendChild(opt);
    });
}

// =============================================
// Section 8: DOMContentLoaded
// =============================================

document.addEventListener('DOMContentLoaded', function() {
    initSocket();
    setupLobbyHandlers();
    setupDeckBuilderHandlers();
    setupDeckFilters();
    setupNavHandlers();
});

// =============================================
// Section 9: Game Start / State Update Handlers
// =============================================

function onGameStart(data) {
    cardDefs = data.card_defs;
    allCardDefs = data.card_defs;
    gameState = data.state;
    myPlayerIdx = data.your_player_idx;
    legalActions = data.legal_actions;
    opponentName = data.opponent_name;
    showScreen('screen-game');
    // Set room code in game screen
    var roomCodeEl = document.getElementById('game-room-code');
    if (roomCodeEl && roomCode) {
        roomCodeEl.textContent = roomCode;
    }
    renderGame();
}

function onStateUpdate(data) {
    gameState = data.state;
    legalActions = data.legal_actions;
    renderGame();
}

function onGameOver(data) {
    // Phase 14 scope -- for now just log and keep showing final state
    console.log('Game over:', data);
    gameState = data.final_state;
    legalActions = [];
    renderGame();
}

// =============================================
// Section 10: renderGame() -- Master Render Function
// =============================================

function renderGame() {
    if (!gameState || !cardDefs) return;
    renderRoomBar();
    renderOpponentInfo();
    renderBoard();
    renderSelfInfo();
    renderHand();
}

// =============================================
// Section 11: renderRoomBar() (UI-04)
// =============================================

function renderRoomBar() {
    // Turn indicator: determine if it's my turn
    var isMyTurn = legalActions && legalActions.length > 0;
    var turnDot = document.getElementById('turn-dot');
    var turnText = document.getElementById('turn-text');

    if (turnDot) {
        if (isMyTurn) {
            turnDot.className = 'turn-dot pulse-dot';
        } else {
            turnDot.className = 'turn-dot pulse-dot inactive';
        }
    }
    if (turnText) {
        if (isMyTurn) {
            turnText.textContent = 'YOUR TURN';
            turnText.className = 'turn-text';
        } else {
            turnText.textContent = "OPPONENT'S TURN";
            turnText.className = 'turn-text opp-turn';
        }
    }

    // Phase badge
    var phaseBadge = document.getElementById('phase-badge');
    if (phaseBadge && gameState.phase !== undefined) {
        var phaseInfo = PHASE_DISPLAY[gameState.phase] || PHASE_DISPLAY[0];
        phaseBadge.textContent = phaseInfo.label;
        phaseBadge.className = 'phase-badge ' + phaseInfo.cssClass;
    }

    // Turn number
    var turnNum = document.getElementById('turn-number');
    if (turnNum && gameState.turn_number !== undefined) {
        turnNum.textContent = 'Turn ' + gameState.turn_number;
    }
}

// =============================================
// Section 12: renderOpponentInfo() (UI-03)
// =============================================

function renderOpponentInfo() {
    var oppIdx = 1 - myPlayerIdx;
    var oppPlayer = gameState.players[oppIdx];

    // Name
    var oppNameEl = document.getElementById('opp-name');
    if (oppNameEl) {
        oppNameEl.textContent = opponentName || 'PLAYER 2 (Opponent)';
    }

    // HP
    var oppHp = document.getElementById('opp-hp');
    if (oppHp) {
        oppHp.textContent = oppPlayer.hp;
    }

    // Mana
    var oppMana = document.getElementById('opp-mana');
    if (oppMana) {
        oppMana.textContent = oppPlayer.current_mana + '/' + oppPlayer.max_mana;
    }

    // Hand count
    var oppHand = document.getElementById('opp-hand');
    if (oppHand) {
        oppHand.textContent = oppPlayer.hand_count;
    }

    // Deck count
    var oppDeck = document.getElementById('opp-deck');
    if (oppDeck) {
        oppDeck.textContent = oppPlayer.deck_count;
    }
}

// =============================================
// Section 13: renderSelfInfo() (UI-03)
// =============================================

function renderSelfInfo() {
    var myPlayer = gameState.players[myPlayerIdx];

    // Name
    var selfNameEl = document.getElementById('self-name');
    if (selfNameEl) {
        selfNameEl.textContent = myName || 'PLAYER 1 (You)';
    }

    // HP
    var selfHp = document.getElementById('self-hp');
    if (selfHp) {
        selfHp.textContent = myPlayer.hp;
    }

    // Mana
    var selfMana = document.getElementById('self-mana');
    if (selfMana) {
        selfMana.textContent = myPlayer.current_mana + '/' + myPlayer.max_mana;
    }

    // Hand count
    var selfHand = document.getElementById('self-hand');
    if (selfHand) {
        selfHand.textContent = myPlayer.hand.length;
    }

    // Deck count
    var selfDeck = document.getElementById('self-deck');
    if (selfDeck) {
        selfDeck.textContent = myPlayer.deck_count;
    }
}

// =============================================
// Section 14: renderBoard() (UI-01, D-03, D-10)
// =============================================

function renderBoard() {
    var boardEl = document.getElementById('game-board');
    if (!boardEl) return;
    boardEl.innerHTML = '';

    // Build minion lookup: "row,col" -> minion object (Pitfall 6)
    var minionMap = {};
    (gameState.minions || []).forEach(function(m) {
        minionMap[m.position[0] + ',' + m.position[1]] = m;
    });

    // Display order depends on perspective (D-03)
    // P1 (idx 0): rows 0,1,2,3,4 top-to-bottom (opponent zone at top)
    // P2 (idx 1): rows 4,3,2,1,0 top-to-bottom (opponent zone at top)
    var rowOrder = myPlayerIdx === 0
        ? [0, 1, 2, 3, 4]
        : [4, 3, 2, 1, 0];

    // Zone classification from player's perspective
    // P1: rows 0-1 = opp zone, row 2 = neutral, rows 3-4 = self zone
    // P2: rows 3-4 = opp zone, row 2 = neutral, rows 0-1 = self zone
    var selfRows = myPlayerIdx === 0 ? [3, 4] : [0, 1];
    var oppRows = myPlayerIdx === 0 ? [0, 1] : [3, 4];

    rowOrder.forEach(function(row) {
        for (var col = 0; col < 5; col++) {
            var cell = document.createElement('div');
            cell.className = 'board-cell';
            cell.dataset.row = row;
            cell.dataset.col = col;

            // Zone tinting
            if (selfRows.indexOf(row) !== -1) {
                cell.classList.add('zone-self');
            } else if (row === 2) {
                cell.classList.add('zone-neutral');
            } else if (oppRows.indexOf(row) !== -1) {
                cell.classList.add('zone-opp');
            }

            // Check for minion at this position
            var minion = minionMap[row + ',' + col];
            if (minion) {
                cell.innerHTML = renderBoardMinion(minion);
            }

            boardEl.appendChild(cell);
        }
    });
}

// =============================================
// renderBoardMinion() -- Compact card (D-10)
// =============================================

function renderBoardMinion(minion) {
    var cardDef = cardDefs[minion.card_numeric_id];
    if (!cardDef) return '';
    var isOwn = minion.owner === myPlayerIdx;
    var ownerClass = isOwn ? 'owner-self' : 'owner-opp';
    var elem = (cardDef.element !== null && cardDef.element !== undefined)
        ? ELEMENT_MAP[cardDef.element] : NEUTRAL_ELEMENT;

    var atk = (cardDef.attack || 0) + (minion.attack_bonus || 0);
    var hp = minion.current_health;

    var boardArtStyle = cardDef.card_id ? 'background-image:url(/static/art/' + cardDef.card_id + '.png);background-size:cover;background-position:center;' : '';
    return '<div class="board-minion ' + ownerClass + '" style="' + boardArtStyle + '">'
        + '<div class="attr-circle-sm ' + elem.css + '"><span class="attr-text-sm">' + elem.name[0] + '</span></div>'
        + '<div class="board-minion-name">' + cardDef.name + '</div>'
        + '<div class="board-minion-stats">'
        + '<span class="board-minion-atk">' + atk + '</span>'
        + '<span class="board-minion-hp">' + hp + '</span>'
        + '</div>'
        + '</div>';
}

// =============================================
// Section 15: renderHand() (UI-02, D-05)
// =============================================

function renderHand() {
    var handEl = document.getElementById('hand-container');
    if (!handEl) return;
    handEl.innerHTML = '';

    var myPlayer = gameState.players[myPlayerIdx];
    var myMana = myPlayer.current_mana;

    myPlayer.hand.forEach(function(numericId, handIndex) {
        var cardHtml = renderHandCard(numericId, handIndex, myMana);
        var wrapper = document.createElement('div');
        wrapper.innerHTML = cardHtml;
        if (wrapper.firstChild) {
            handEl.appendChild(wrapper.firstChild);
        }
    });
}

// =============================================
// renderHandCard() -- Full YGO-style (D-05, D-06)
// =============================================

function renderHandCard(numericId, handIndex, currentMana) {
    var c = cardDefs[numericId];
    if (!c) return '';
    var typeClass = TYPE_CSS[c.card_type] || '';
    var canAfford = currentMana >= c.mana_cost;
    var dimClass = canAfford ? '' : ' card-dimmed';
    var elem = (c.element !== null && c.element !== undefined)
        ? ELEMENT_MAP[c.element] : NEUTRAL_ELEMENT;

    var html = '<div class="card-frame ' + typeClass + dimClass + '" data-hand-idx="' + handIndex + '" data-numeric-id="' + numericId + '">';
    // Mana badge
    html += '<div class="card-mana">' + c.mana_cost + '</div>';
    // Art area with attribute circle
    var handArtStyle = c.card_id ? 'background-image:url(/static/art/' + c.card_id + '.png)' : '';
    html += '<div class="card-art" style="' + handArtStyle + '">';
    html += '<div class="attr-circle ' + elem.css + '"><span class="attr-text">' + elem.name + '</span></div>';
    html += '</div>';
    // Card name
    html += '<div class="card-name">' + c.name + '</div>';
    // Stats or effect text
    if (c.card_type === 0 && c.attack != null) {
        html += '<div class="card-stats">';
        html += '<span class="card-atk">ATK/' + c.attack + '</span>';
        html += '<span class="card-hp">HP/' + c.health + '</span>';
        html += '</div>';
    } else if (c.effects && c.effects.length > 0) {
        var desc = getEffectDescription(c.effects);
        html += '<div class="card-effect">' + desc + '</div>';
    }
    html += '</div>';
    return html;
}

// =============================================
// Section 16: renderDeckBuilderCard (already defined above in Section 7)
// Section 17: Helper -- getEffectDescription()
// =============================================

function getEffectDescription(effects) {
    if (!effects || effects.length === 0) return '';
    var parts = [];
    effects.forEach(function(eff) {
        var trigger = TRIGGER_NAMES[eff.trigger] || 'On Play';
        var amount = eff.amount || 0;
        var type = eff.type;
        var target = eff.target;
        var desc = '';

        // Target descriptions
        var targetText = {
            0: 'an enemy',        // Single Target
            1: 'all enemies',     // All Enemies
            2: 'adjacent units',  // Adjacent
            3: 'itself',          // Self/Owner
        }[target] || 'a target';

        // Build natural English
        if (type === 0) { // Damage
            desc = trigger + ': Deal ' + amount + ' damage to ' + targetText;
        } else if (type === 1) { // Heal
            desc = trigger + ': Restore ' + amount + ' HP to ' + (target === 3 ? 'your hero' : targetText);
        } else if (type === 2) { // Buff ATK
            desc = trigger + ': Give ' + (target === 3 ? 'this minion' : targetText) + ' +' + amount + ' ATK';
        } else if (type === 3) { // Buff HP
            desc = trigger + ': Give ' + (target === 3 ? 'this minion' : targetText) + ' +' + amount + ' HP';
        } else if (type === 4) { // Negate
            desc = trigger + ': Negate ' + (target === 0 ? 'a spell' : 'an effect');
        } else if (type === 5) { // Deploy Self
            desc = trigger + ': Deploy this card to the field';
        } else if (type === 6) { // Rally Forward
            desc = trigger + ': All friendly units of this type advance forward';
        } else if (type === 7) { // Promote
            desc = trigger + ': Promote ' + (target === 3 ? 'itself' : targetText) + ' (' + amount + ')';
        } else if (type === 8) { // Tutor
            desc = trigger + ': Search your deck for a card and add it to your hand';
        } else if (type === 9) { // Destroy
            desc = trigger + ': Destroy ' + targetText;
        } else {
            desc = trigger + ': Special effect';
        }
        parts.push(desc);
    });
    return parts.join('. ');
}
