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

const EFFECT_TYPE_NAMES = ['Damage', 'Heal', 'Buff ATK', 'Buff HP', 'Negate'];
const TRIGGER_NAMES = ['On Play', 'On Death', 'On Attack', 'React'];
const TARGET_NAMES = ['Enemy Player', 'All Enemies', 'Self/Owner', 'Single Enemy', 'Self Minion'];

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
    // Sort by card_type then name
    var ids = Object.keys(defs).map(Number).sort(function(a, b) {
        var ca = defs[a], cb = defs[b];
        if (ca.card_type !== cb.card_type) return ca.card_type - cb.card_type;
        return (ca.name || '').localeCompare(cb.name || '');
    });
    ids.forEach(function(numId) {
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

function renderDeckBuilderCard(numericId, count) {
    var c = allCardDefs ? allCardDefs[numericId] : cardDefs[numericId];
    if (!c) return '';
    var typeClass = TYPE_CSS[c.card_type] || '';
    var elem = (c.element !== null && c.element !== undefined)
        ? ELEMENT_MAP[c.element] : NEUTRAL_ELEMENT;

    var html = '<div class="card-frame ' + typeClass + '">';
    // Mana badge
    html += '<div class="card-mana">' + c.mana_cost + '</div>';
    // Art area with attribute circle
    html += '<div class="card-art">';
    html += '<div class="attr-circle ' + elem.css + '"></div>';
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
    setupNavHandlers();
});
