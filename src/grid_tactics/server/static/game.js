/* Grid Tactics - Client-Side Game Logic
   Socket.IO integration, lobby, deck builder, and game rendering.
   Vanilla JS (no modules, no build step). */

// =============================================
// Patch badge — fetch VERSION.json + render top-right
// =============================================
(function loadPatchBadge() {
    function render() {
        var badge = document.getElementById('patch-badge');
        if (!badge) {
            // DOM not ready yet — retry on DOMContentLoaded
            document.addEventListener('DOMContentLoaded', render, { once: true });
            return;
        }
        // Cache-bust so the badge always reflects the latest deploy
        fetch('/static/VERSION.json?t=' + Date.now())
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var version = data.version || '?.?.?';
                var channel = data.channel || '';
                var updatedIso = data.last_updated || '';
                var updatedStr = '';
                try {
                    var d = new Date(updatedIso);
                    if (!isNaN(d.getTime())) {
                        // Format in Dublin timezone: DD/MM HH:MM
                        var opts = {
                            timeZone: 'Europe/Dublin',
                            day: '2-digit', month: '2-digit',
                            hour: '2-digit', minute: '2-digit',
                            hour12: false,
                        };
                        updatedStr = d.toLocaleString('en-IE', opts).replace(',', '');
                    }
                } catch (e) {}
                badge.innerHTML =
                    '<div class="patch-version">Patch ' + version + ' ' + channel + '</div>' +
                    (updatedStr ? '<div class="patch-updated">Updated ' + updatedStr + ' Dublin</div>' : '');
            })
            .catch(function () { /* silent — badge stays empty */ });
    }
    render();
})();

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
const NAME_STORAGE_KEY = 'gt_display_name';

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
// Phase 14.4 spectator-mode: client-side flags. isSpectator gates all
// action-submitting code paths; spectatorGodMode toggles dual-hand rendering.
let isSpectator = false;
let spectatorGodMode = false;

// Game interaction state
let selectedHandIdx = null;  // index of selected hand card (for PLAY_CARD)
let selectedMinionId = null; // id of selected board minion (for MOVE/ATTACK)
let selectedDeployPos = null; // [row, col] when picking target for a minion with on-play effect
let interactionMode = null;  // 'play', 'move', 'attack', 'move_attack', 'target', 'activate_target', or null
let selectedAbilityMinionId = null; // minion whose activated ability is being targeted

// Deck builder state
let currentDeck = {};        // { numericId: count }
let currentSlotIdx = 0;
let allCardDefs = null;      // set from server on game_start or card_defs event
let deckFilterType = 'all';     // 'all', 'minion', 'magic', 'react'
let deckFilterElement = 'all';  // 'all', or element int as string
let deckFilterMana = 'all';     // 'all', '1', '2', '3', '4', '5+'
let deckFilterKeyword = 'all';  // 'all', 'tutor', 'promote', etc.
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
            // Block navigation while in an active game
            if (isInActiveGame()) {
                return;
            }
            var screenName = btn.dataset.screen;
            if (screenName) {
                showScreen('screen-' + screenName);
            }
        });
    });
}

function isInActiveGame() {
    return gameState && !gameState.is_game_over
        && document.getElementById('screen-game')?.classList.contains('active');
}

function updateNavLockState() {
    var inGame = isInActiveGame();
    document.querySelectorAll('.nav-btn').forEach(function(btn) {
        if (inGame) {
            btn.classList.add('nav-btn-locked');
            btn.title = 'Locked while in game';
        } else {
            btn.classList.remove('nav-btn-locked');
            btn.title = '';
        }
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
    socket.on('chat_message', onChatMessage);
    socket.on('rematch_waiting', onRematchWaiting);
    socket.on('spectator_joined', onSpectatorJoined);
}

// Phase 14.4: ack from server after spectate_room. Flips client into
// spectator mode; transition to the game screen happens on game_start
// (emitted immediately by the server when a game is already underway) or
// when the next game begins. We intentionally DO NOT call showScreen here
// because the lobby may not yet have a game in progress.
function onSpectatorJoined(data) {
    isSpectator = true;
    spectatorGodMode = !!(data && data.god_mode);
    if (data && data.session_token) sessionToken = data.session_token;
    if (data && data.room_code) roomCode = data.room_code;
    showLobbyStatus('Spectating room ' + (roomCode || '') + (spectatorGodMode ? ' (GOD MODE)' : '') + '. Waiting for game…', 'info');
}

// =============================================
// Section 5b: Chat & Activity Tabs
// =============================================

let chatActiveTab = 'log'; // 'log' or 'chat'
let chatUnreadCount = 0;

function setupActivityTabs() {
    document.querySelectorAll('.activity-tab').forEach(function(tab) {
        tab.addEventListener('click', function() {
            var tabName = tab.dataset.tab;
            switchActivityTab(tabName);
        });
    });

    var chatInput = document.getElementById('chat-input');
    var btnSend = document.getElementById('btn-chat-send');
    if (btnSend && chatInput) {
        btnSend.addEventListener('click', sendChatMessage);
        chatInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                sendChatMessage();
            }
        });
    }
}

function switchActivityTab(tabName) {
    chatActiveTab = tabName;
    document.querySelectorAll('.activity-tab').forEach(function(tab) {
        if (tab.dataset.tab === tabName) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });
    document.querySelectorAll('.activity-tab-content').forEach(function(content) {
        content.style.display = 'none';
    });
    var active = document.getElementById('tab-' + tabName);
    if (active) active.style.display = '';

    if (tabName === 'chat') {
        chatUnreadCount = 0;
        var unreadDot = document.getElementById('chat-unread');
        if (unreadDot) unreadDot.style.display = 'none';
        // Focus the input
        var input = document.getElementById('chat-input');
        if (input) setTimeout(function() { input.focus(); }, 50);
    }
}

function sendChatMessage() {
    var input = document.getElementById('chat-input');
    if (!input) return;
    var text = input.value.trim();
    if (!text) return;
    if (socket) {
        socket.emit('chat_message', { text: text });
    }
    input.value = '';
}

function onChatMessage(data) {
    var msgs = document.getElementById('chat-messages');
    if (!msgs) return;
    var msg = document.createElement('div');
    var isOwn = data.author === myName;
    msg.className = 'chat-message ' + (isOwn ? 'own' : 'opp');
    var authorSpan = document.createElement('span');
    authorSpan.className = 'chat-message-author';
    authorSpan.textContent = data.author + ':';
    var textSpan = document.createElement('span');
    textSpan.className = 'chat-message-text';
    textSpan.textContent = ' ' + data.text;
    msg.appendChild(authorSpan);
    msg.appendChild(textSpan);
    msgs.appendChild(msg);
    msgs.scrollTop = msgs.scrollHeight;

    // Show unread indicator if not on chat tab and not from self
    if (chatActiveTab !== 'chat' && !isOwn) {
        chatUnreadCount++;
        var unreadDot = document.getElementById('chat-unread');
        if (unreadDot) unreadDot.style.display = '';
    }

    // Easter egg: opponent typed a nudge keyword -> splat on our screen
    // (MSN-messenger-nudge style). Only fires for recipients, never the sender.
    if (!isOwn && data.text) {
        var keyword = data.text.trim().toLowerCase();
        if (NUDGES[keyword]) NUDGES[keyword]();
    }
}

// Generic chat-nudge runner. Mounts a fixed full-screen overlay with
// the given inner HTML + duration, removes itself when done.
function runNudge(id, innerHtml, durationMs) {
    var existing = document.getElementById(id);
    if (existing) existing.remove();
    var overlay = document.createElement('div');
    overlay.id = id;
    overlay.className = 'nudge-overlay ' + id;
    overlay.innerHTML = innerHtml;
    document.body.appendChild(overlay);
    setTimeout(function() {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    }, durationMs);
}

var NUDGES = {
    'egg': function() {
        playSfx('nudge_egg');
        runNudge('nudge-egg',
            '<div class="egg-splat-egg">🥚</div>' +
            '<div class="egg-splat-splat">🍳</div>',
            3200);
    },
    'boom': function() {
        playSfx('nudge_boom');
        runNudge('nudge-boom',
            '<div class="boom-bomb">💣</div>' +
            '<div class="boom-flash"></div>' +
            '<div class="boom-burst">💥</div>',
            3000);
    },
    'rain': function() {
        playSfx('nudge_rain');
        // Generate 40 rain drops at random horizontal positions
        var drops = '';
        for (var i = 0; i < 40; i++) {
            var left = Math.floor(Math.random() * 100);
            var delay = (Math.random() * 1.2).toFixed(2);
            var dur = (1.0 + Math.random() * 0.8).toFixed(2);
            drops += '<div class="rain-drop" style="left:' + left + 'vw;' +
                     'animation-delay:' + delay + 's;' +
                     'animation-duration:' + dur + 's;">💧</div>';
        }
        runNudge('nudge-rain',
            '<div class="rain-cloud">☁️</div>' + drops,
            3500);
    },
    'kiss': function() {
        playSfx('nudge_kiss');
        runNudge('nudge-kiss',
            '<div class="kiss-mark">💋</div>',
            3000);
    }
};

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

function loadSavedName() {
    try {
        return localStorage.getItem(NAME_STORAGE_KEY) || '';
    } catch (e) {
        return '';
    }
}

function saveDisplayName(name) {
    try {
        if (name) localStorage.setItem(NAME_STORAGE_KEY, name);
        else localStorage.removeItem(NAME_STORAGE_KEY);
    } catch (e) {}
}

function showSavedNameUI(name) {
    var inputSection = document.getElementById('name-input-section');
    var savedSection = document.getElementById('name-saved-section');
    var display = document.getElementById('saved-name-display');
    if (display) display.textContent = name;
    if (inputSection) inputSection.style.display = 'none';
    if (savedSection) savedSection.style.display = '';
}

function showNameInputUI() {
    var inputSection = document.getElementById('name-input-section');
    var savedSection = document.getElementById('name-saved-section');
    if (inputSection) inputSection.style.display = '';
    if (savedSection) savedSection.style.display = 'none';
    var nameInput = document.getElementById('input-name');
    if (nameInput) {
        nameInput.focus();
        nameInput.select();
    }
}

function getCurrentDisplayName() {
    // Check if saved-name section is visible — return that, else read input
    var savedSection = document.getElementById('name-saved-section');
    if (savedSection && savedSection.style.display !== 'none') {
        var display = document.getElementById('saved-name-display');
        return display ? display.textContent.trim() : '';
    }
    var nameInput = document.getElementById('input-name');
    return nameInput ? nameInput.value.trim() : '';
}

function setupLobbyHandlers() {
    // Initialize name UI from localStorage
    var savedName = loadSavedName();
    if (savedName) {
        myName = savedName;
        showSavedNameUI(savedName);
    } else {
        showNameInputUI();
    }

    // Save name button (when input is shown)
    var btnSaveName = document.getElementById('btn-save-name');
    if (btnSaveName) {
        btnSaveName.addEventListener('click', function() {
            var nameInput = document.getElementById('input-name');
            var name = nameInput ? nameInput.value.trim() : '';
            if (!name) {
                showLobbyStatus('Please enter a display name.', 'error');
                return;
            }
            myName = name;
            saveDisplayName(name);
            showSavedNameUI(name);
            showLobbyStatus('', '');
        });
    }

    // Change name button
    var btnChangeName = document.getElementById('btn-change-name');
    if (btnChangeName) {
        btnChangeName.addEventListener('click', function() {
            var savedName = loadSavedName();
            var nameInput = document.getElementById('input-name');
            if (nameInput) nameInput.value = savedName;
            showNameInputUI();
        });
    }

    // Show Save button only when input is non-empty (auto-save on Enter too)
    var nameInputEl = document.getElementById('input-name');
    if (nameInputEl) {
        var updateSaveBtn = function() {
            if (btnSaveName) btnSaveName.style.display = nameInputEl.value.trim() ? '' : 'none';
        };
        nameInputEl.addEventListener('input', updateSaveBtn);
        nameInputEl.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && btnSaveName) {
                e.preventDefault();
                btnSaveName.click();
            }
        });
        updateSaveBtn();
    }

    // Create Room
    var btnCreate = document.getElementById('btn-create-room');
    if (btnCreate) {
        btnCreate.addEventListener('click', function() {
            var name = getCurrentDisplayName();
            if (!name) {
                showLobbyStatus('Please enter a display name.', 'error');
                return;
            }
            myName = name;
            saveDisplayName(name);
            socket.emit('create_room', { display_name: name });
        });
    }

    // Join Room
    var btnJoin = document.getElementById('btn-join-room');
    if (btnJoin) {
        btnJoin.addEventListener('click', function() {
            var codeInput = document.getElementById('input-room-code');
            var name = getCurrentDisplayName();
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
            saveDisplayName(name);
            socket.emit('join_room', { display_name: name, room_code: code });
        });
    }

    // Spectate Room (Phase 14.4)
    var btnSpectate = document.getElementById('btn-spectate-room');
    if (btnSpectate) {
        btnSpectate.addEventListener('click', function() {
            var codeInput2 = document.getElementById('input-room-code');
            var name = getCurrentDisplayName();
            var code = codeInput2 ? codeInput2.value.trim().toUpperCase() : '';
            if (!name) {
                showLobbyStatus('Please enter a display name.', 'error');
                return;
            }
            if (!code) {
                showLobbyStatus('Please enter a room code.', 'error');
                return;
            }
            var godCb = document.getElementById('god-mode-checkbox');
            var god_mode = !!(godCb && godCb.checked);
            myName = name;
            saveDisplayName(name);
            socket.emit('spectate_room', { display_name: name, room_code: code, god_mode: god_mode });
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
    // Refresh deck selector in case decks were saved after page load
    populateDeckSelector();
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
    // Preserve current selection if possible
    var prevValue = selector.value;
    // Clear existing options except the default
    selector.innerHTML = '<option value="">Default Deck (Starter)</option>';
    var slots = loadDeckSlots();
    slots.forEach(function(slot, idx) {
        var totalCards = getDeckTotal(slot.cards);
        var opt = document.createElement('option');
        opt.value = idx;
        var ready = totalCards === 30;
        opt.textContent = (ready ? '' : '⚠ ') + slot.name + ' (' + totalCards + '/30)';
        if (!ready) {
            opt.disabled = true;
        }
        selector.appendChild(opt);
    });
    // Restore previous selection if still valid
    if (prevValue !== '') {
        var stillValid = false;
        for (var i = 0; i < selector.options.length; i++) {
            if (selector.options[i].value === prevValue && !selector.options[i].disabled) {
                stillValid = true;
                break;
            }
        }
        if (stillValid) selector.value = prevValue;
    }
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
    fitCardNames();
    fitCardEffects();
}

function fitCardEffects() {
    document.querySelectorAll('.card-effect-full').forEach(function(el) {
        el.style.fontSize = '12px';
        var size = 12;
        while (el.scrollHeight > el.clientHeight && size > 7) {
            size--;
            el.style.fontSize = size + 'px';
        }
    });
}

function fitCardNames() {
    document.querySelectorAll('.card-name-overlay').forEach(function(el) {
        el.style.transform = 'none';
        el.style.fontSize = '16px';
        var containerWidth = el.offsetWidth;
        var textWidth = el.scrollWidth;
        if (textWidth > containerWidth && containerWidth > 0) {
            var scale = containerWidth / textWidth;
            if (scale < 0.5) scale = 0.5;
            el.style.transform = 'scaleX(' + scale + ')';
        }
    });
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
        // Hide non-deckable cards unless checkbox is checked
        var showNonDeckable = document.getElementById('show-nondeckable') && document.getElementById('show-nondeckable').checked;
        if (c.deckable === false && !showNonDeckable) return;
        // Type filter
        if (deckFilterType !== 'all' && typeMap[c.card_type] !== deckFilterType) return;
        // Element filter
        if (deckFilterElement !== 'all') {
            var cardElem = (c.element !== undefined && c.element !== null) ? String(c.element) : '-1';
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
        // Keyword filter
        if (deckFilterKeyword !== 'all') {
            var hasKeyword = false;
            var kw = deckFilterKeyword;
            if (kw === 'tutor' && c.tutor_target) hasKeyword = true;
            else if (kw === 'promote' && c.promote_target) hasKeyword = true;
            else if (kw === 'rally' && c.effects && c.effects.some(function(e) { return e.type === 6; })) hasKeyword = true;
            else if (kw === 'transform' && c.transform_options && c.transform_options.length > 0) hasKeyword = true;
            else if (kw === 'discard' && c.summon_sacrifice_tribe) hasKeyword = true;
            else if (kw === 'react' && c.react_condition != null) hasKeyword = true;
            else if (kw === 'unique' && c.unique) hasKeyword = true;
            else if (kw === 'negate' && c.effects && c.effects.some(function(e) { return e.type === 4; })) hasKeyword = true;
            else if (kw === 'burn' && c.effects && c.effects.some(function(e) { return e.type === 10; })) hasKeyword = true;
            else if (kw === 'passive' && c.effects && c.effects.some(function(e) { return e.type === 12; })) hasKeyword = true;
            if (!hasKeyword) return;
        }
        // Search filter
        if (query) {
            var searchable = (c.name || '').toLowerCase() + ' ' + (c.card_id || '').toLowerCase();
            if (searchable.indexOf(query) === -1) return;
        }
        var isNonDeckable = c.deckable === false;
        var count = isNonDeckable ? -1 : (currentDeck[numId] || 0);
        var wrapper = document.createElement('div');
        wrapper.className = 'card-browser-item';
        if (isNonDeckable) wrapper.classList.add('card-nondeckable');
        if (count > 0) wrapper.classList.add('card-selected');
        wrapper.innerHTML = renderDeckBuilderCard(numId, count);
        // Click to add (disabled for non-deckable)
        if (!isNonDeckable) {
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
        }
        // Hover for tooltip
        wrapper.addEventListener('mouseenter', function() { showCardTooltip(numId); });
        wrapper.addEventListener('mouseleave', function() { hideCardTooltip(); });
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
    // Non-deckable checkbox
    var nonDeckCheckbox = document.getElementById('show-nondeckable');
    if (nonDeckCheckbox) {
        nonDeckCheckbox.addEventListener('change', function() { renderCardBrowser(); });
    }
    // Keyword filters
    document.querySelectorAll('#keyword-filters .filter-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            deckFilterKeyword = btn.dataset.filter;
            document.querySelectorAll('#keyword-filters .filter-btn').forEach(function(b) { b.classList.remove('active'); });
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

var KEYWORD_GLOSSARY = {
    // Trigger keywords
    'Summon': 'This effect activates when the minion is played onto the board.',
    'Death': 'This effect activates when the minion is destroyed.',
    'Move': 'This effect activates when the minion moves forward.',
    'Attack': 'This effect activates when the minion attacks.',
    'Damaged': 'This effect activates when the minion takes damage.',
    'Passive': 'This effect triggers automatically every turn.',
    'Active': 'This ability can be used once per turn instead of attacking.',
    // Mechanic keywords
    'Unique': 'Only one copy of this minion can exist on the board per player at a time.',
    'Melee': 'Attacks adjacent orthogonal tiles (1 tile).',
    'Range': 'Attacks X+1 tiles orthogonally, X tiles diagonally.',
    'Tutor': 'Search your deck for a specific card and add it to your hand.',
    'Promote': 'When this minion dies, specified minion transforms into this card.',
    'Rally': 'When this minion moves, all other friendly copies of it also advance forward.',
    'Negate': 'Cancel the effect of an opponent\'s spell or ability.',
    'React': 'This card can be played during the opponent\'s turn in response to their action.',
    'Deploy': 'Place this card onto the battlefield from your hand during a React window.',
    'Destroy': 'Remove a target minion from the board regardless of its ❤️.',
    'Transform': 'Pay mana to transform this minion into another form.',
    'Cost': 'An additional cost that must be paid to play this card.',
    'Discard': 'Remove a card from your hand.',
    'Heal': 'Restore ❤️ to a target.',
    'Deal': 'Deal damage to a target.',
    'Burn': 'A permanent passive debuff that deals damage each turn.',
    'Burning': 'A burning minion takes 5 damage at the start of its owner\'s turn. Burning persists until the minion dies.',
    'Dark Matter': 'Buff scales with Dark Matter stacks.',
    'Leap': 'If blocked by an enemy, advance to the next available tile instead.',
    'Conjure': 'Summon a card from outside your deck directly to the board.',
};

function showCardTooltip(numericId) {
    var defs = allCardDefs || cardDefs;
    var c = defs[numericId];
    if (!c) return;
    var tooltip = document.getElementById('card-tooltip');
    tooltip.style.display = '';

    // Full card art preview — reuse the deck-builder card renderer
    var artHost = document.getElementById('tooltip-card-art');
    if (artHost) artHost.innerHTML = renderDeckBuilderCard(numericId, -1);

    // Name
    document.getElementById('tooltip-name').textContent = c.name;

    // Stats line
    var statsHtml = '';
    var typeNames = ['Minion', 'Magic', 'React'];
    statsHtml += '<span style="color:var(--cyan)">' + (typeNames[c.card_type] || '') + '</span>';
    if (c.tribe) statsHtml += '<span>' + c.tribe + '</span>';
    var elem = (c.element !== null && c.element !== undefined) ? ELEMENT_MAP[c.element] : NEUTRAL_ELEMENT;
    statsHtml += '<span style="color:' + elem.color + '">' + elem.name + '</span>';
    statsHtml += '<span style="color:var(--cyan)">' + c.mana_cost + ' Mana</span>';
    if (c.attack != null) statsHtml += '<span style="color:var(--red)">' + c.attack + '🗡️</span>';
    if (c.health != null) statsHtml += '<span style="color:var(--green)">' + c.health + '❤️</span>';
    if (c.card_type === 0 && c.attack_range != null) {
        statsHtml += '<span>' + (c.attack_range === 0 ? 'Melee' : 'Range ' + c.attack_range) + '</span>';
    }
    document.getElementById('tooltip-stats').innerHTML = statsHtml;

    // Keywords
    var keywordsHtml = '';
    var effectDesc = (c.effects && c.effects.length > 0) ? getEffectDescription(c.effects, c) : '';
    // Card-specific text lines
    var cardTextLines = [];
    if (c.summon_sacrifice_tribe) cardTextLines.push('Sacrifice: ' + c.summon_sacrifice_tribe);
    if (c.unique) cardTextLines.push('Unique');
    if (effectDesc) cardTextLines.push(effectDesc);
    if (c.activated_ability) {
        var ab = c.activated_ability;
        var abDesc = 'Active (' + ab.mana_cost + '): ';
        if (ab.effect_type === 'conjure_rat_and_buff') {
            abDesc += 'Conjure Common Rat from deck. Ally Rats on board +1🗡️/+1❤️ (+Dark Matter × 1).';
        } else if (ab.effect_type === 'summon_token' && ab.summon_card_id) {
            abDesc += 'Summon ' + findCardNameById(ab.summon_card_id) + '.';
        } else {
            abDesc += (ab.name || ab.effect_type);
        }
        cardTextLines.push(abDesc);
    }
    if (c.transform_options && c.transform_options.length > 0) {
        var tLines = c.transform_options.map(function(opt) {
            return findCardNameById(opt.target) + ' (' + opt.mana_cost + ' mana)';
        });
        cardTextLines.push('Transform: ' + tLines.join(', '));
    }
    if (cardTextLines.length > 0) {
        keywordsHtml += '<div style="margin-bottom:8px;color:white;font-size:12px;font-weight:700;line-height:1.5;">' + cardTextLines.join('<br>') + '</div>';
    }
    if (c.flavour_text) {
        keywordsHtml += '<div style="margin-bottom:8px;color:var(--cyan);font-size:11px;font-style:italic;">"' + c.flavour_text + '"</div>';
    }
    // Match keywords from the effect text and card properties
    var matchedKeywords = [];
    // From card data
    if (c.unique) matchedKeywords.push('Unique');
    if (c.card_type === 0 && c.attack_range != null && c.attack_range === 0) matchedKeywords.push('Melee');
    if (c.card_type === 0 && c.attack_range != null && c.attack_range > 0) matchedKeywords.push('Range');
    if (c.summon_sacrifice_tribe) { matchedKeywords.push('Cost'); matchedKeywords.push('Discard'); }
    if (c.transform_options && c.transform_options.length > 0) matchedKeywords.push('Transform');
    if (c.react_condition != null) { matchedKeywords.push('React'); }
    if (c.react_condition != null && c.react_effect && c.react_effect.type === 5) { matchedKeywords.push('Deploy'); }
    // From effects
    // Check if any effect overrides Summon trigger (e.g. Active abilities use on_play trigger but aren't Summon)
    var skipSummon = false;
    if (c.effects) { c.effects.forEach(function(eff) { if (eff.type === 11) skipSummon = true; }); }
    if (c.effects && c.effects.length > 0) {
        c.effects.forEach(function(eff) {
            // Triggers
            if (eff.trigger === 0 && c.card_type === 0 && !skipSummon) { if (matchedKeywords.indexOf('Summon') === -1) matchedKeywords.push('Summon'); }
            if (eff.trigger === 1) { if (matchedKeywords.indexOf('Death') === -1) matchedKeywords.push('Death'); }
            if (eff.trigger === 2) { if (matchedKeywords.indexOf('Attack') === -1) matchedKeywords.push('Attack'); }
            if (eff.trigger === 3) { if (matchedKeywords.indexOf('Damaged') === -1) matchedKeywords.push('Damaged'); }
            if (eff.trigger === 4) { if (matchedKeywords.indexOf('Move') === -1) matchedKeywords.push('Move'); }
            if (eff.trigger === 5) { if (matchedKeywords.indexOf('Passive') === -1) matchedKeywords.push('Passive'); }
            // Effect types
            if (eff.type === 0) { if (matchedKeywords.indexOf('Deal') === -1) matchedKeywords.push('Deal'); }
            if (eff.type === 1) { if (matchedKeywords.indexOf('Heal') === -1) matchedKeywords.push('Heal'); }
            if (eff.type === 3) { if (matchedKeywords.indexOf('Heal') === -1) matchedKeywords.push('Heal'); } // buff_health
            if (eff.type === 4) { if (matchedKeywords.indexOf('Negate') === -1) matchedKeywords.push('Negate'); }
            if (eff.type === 5) { if (matchedKeywords.indexOf('Deploy') === -1) matchedKeywords.push('Deploy'); }
            if (eff.type === 6) { if (matchedKeywords.indexOf('Rally') === -1) matchedKeywords.push('Rally'); }
            if (eff.type === 7) { if (matchedKeywords.indexOf('Promote') === -1) matchedKeywords.push('Promote'); }
            if (eff.type === 8) { if (matchedKeywords.indexOf('Tutor') === -1) matchedKeywords.push('Tutor'); }
            if (eff.type === 9) { if (matchedKeywords.indexOf('Destroy') === -1) matchedKeywords.push('Destroy'); }
            if (eff.type === 10) { if (matchedKeywords.indexOf('Burn') === -1) matchedKeywords.push('Burn'); }
            if (eff.type === 11) { if (matchedKeywords.indexOf('Active') === -1) matchedKeywords.push('Active'); if (matchedKeywords.indexOf('Dark Matter') === -1) matchedKeywords.push('Dark Matter'); }
            if (eff.type === 12) { if (matchedKeywords.indexOf('Passive') === -1) matchedKeywords.push('Passive'); if (matchedKeywords.indexOf('Heal') === -1) matchedKeywords.push('Heal'); }
            if (eff.type === 13) { if (matchedKeywords.indexOf('Leap') === -1) matchedKeywords.push('Leap'); }
            if (eff.type === 14) { if (matchedKeywords.indexOf('Conjure') === -1) matchedKeywords.push('Conjure'); }
        });
    }
    matchedKeywords.forEach(function(kw) {
        keywordsHtml += '<div class="tooltip-keyword"><span class="tooltip-keyword-name">' + kw + '</span> <span class="tooltip-keyword-desc">— ' + KEYWORD_GLOSSARY[kw] + '</span></div>';
    });
    document.getElementById('tooltip-keywords').innerHTML = keywordsHtml;

    // Related cards
    // Related cards: only direct references (this card mentions them or they mention this card)
    var relatedIds = [];
    // This card references:
    if (c.tutor_target) relatedIds.push(c.tutor_target);
    if (c.promote_target) relatedIds.push(c.promote_target);
    if (c.transform_options) {
        c.transform_options.forEach(function(opt) {
            if (relatedIds.indexOf(opt.target) === -1) relatedIds.push(opt.target);
        });
    }
    // Other cards that reference this card:
    for (var nid2 in defs) {
        var d = defs[nid2];
        if (d.card_id === c.card_id) continue;
        if (d.tutor_target === c.card_id && relatedIds.indexOf(d.card_id) === -1) relatedIds.push(d.card_id);
        if (d.promote_target === c.card_id && relatedIds.indexOf(d.card_id) === -1) relatedIds.push(d.card_id);
        if (d.transform_options) {
            d.transform_options.forEach(function(opt) {
                if (opt.target === c.card_id && relatedIds.indexOf(d.card_id) === -1) relatedIds.push(d.card_id);
            });
        }
    }

    var relatedLabel = document.getElementById('tooltip-related-label');
    var relatedContainer = document.getElementById('tooltip-related');
    if (relatedIds.length > 0) {
        relatedLabel.style.display = '';
        var relHtml = '';
        relatedIds.forEach(function(rid) {
            var rc = null;
            for (var nid3 in defs) {
                if (defs[nid3].card_id === rid) { rc = defs[nid3]; break; }
            }
            if (!rc) return;
            var artBg = 'background-image:url(/static/art/' + rc.card_id + '.png)';
            relHtml += '<div class="tooltip-related-card">';
            relHtml += '<div class="tooltip-related-art" style="' + artBg + '"></div>';
            relHtml += '<div class="tooltip-related-info">';
            relHtml += '<div class="tooltip-related-name">' + rc.name + '</div>';
            var rElem = (rc.element !== null && rc.element !== undefined) ? ELEMENT_MAP[rc.element] : NEUTRAL_ELEMENT;
            var rStats = rc.mana_cost + ' Mana';
            if (rc.tribe) rStats += ' | ' + rc.tribe;
            rStats += ' | ' + rElem.name;
            if (rc.attack != null) rStats += ' | ' + rc.attack + '🗡️ | ' + rc.health + '❤️';
            if (rc.attack_range != null) rStats += ' | ' + (rc.attack_range === 0 ? 'Melee' : 'Range ' + rc.attack_range);
            relHtml += '<div class="tooltip-related-stats">' + rStats + '</div>';
            var rEffect = '';
            if (rc.unique) rEffect += 'Unique. ';
            if (rc.effects && rc.effects.length > 0) rEffect += getEffectDescription(rc.effects, rc);
            if (rEffect) relHtml += '<div class="tooltip-related-effect">' + rEffect + '</div>';
            relHtml += '</div></div>';
        });
        relatedContainer.innerHTML = relHtml;
    } else {
        relatedLabel.style.display = 'none';
        relatedContainer.innerHTML = '';
    }
}

function hideCardTooltip() {
    var tooltip = document.getElementById('card-tooltip');
    if (tooltip) tooltip.style.display = 'none';
}

// =============================================
// Game Tooltip (for hand cards and board minions)
// =============================================

function showGameTooltip(numericId, anchorEl) {
    var c = cardDefs[numericId];
    if (!c) return;
    var tooltip = document.getElementById('game-tooltip');
    if (!tooltip) return;
    tooltip.style.display = '';

    // Name
    tooltip.querySelector('.gtt-name').textContent = c.name;

    // Stats line
    var statsHtml = '';
    var typeNames = ['Minion', 'Magic', 'React'];
    statsHtml += '<span style="color:var(--cyan)">' + (typeNames[c.card_type] || '') + '</span>';
    if (c.tribe) statsHtml += '<span>' + c.tribe + '</span>';
    var elem = (c.element !== null && c.element !== undefined) ? ELEMENT_MAP[c.element] : NEUTRAL_ELEMENT;
    statsHtml += '<span style="color:' + elem.color + '">' + elem.name + '</span>';
    statsHtml += '<span style="color:var(--cyan)">' + c.mana_cost + ' Mana</span>';
    if (c.attack != null) statsHtml += '<span style="color:var(--red)">' + c.attack + '🗡️</span>';
    if (c.health != null) statsHtml += '<span style="color:var(--green)">' + c.health + '❤️</span>';
    if (c.card_type === 0 && c.attack_range != null) {
        statsHtml += '<span>' + (c.attack_range === 0 ? 'Melee' : 'Range ' + c.attack_range) + '</span>';
    }
    tooltip.querySelector('.gtt-stats').innerHTML = statsHtml;

    // Card text + keywords
    var bodyHtml = '';
    var effectDesc = (c.effects && c.effects.length > 0) ? getEffectDescription(c.effects, c) : '';
    var cardTextLines = [];
    if (c.summon_sacrifice_tribe) cardTextLines.push('Sacrifice: ' + c.summon_sacrifice_tribe);
    if (c.unique) cardTextLines.push('Unique');
    if (effectDesc) cardTextLines.push(effectDesc);
    if (c.activated_ability) {
        var ab = c.activated_ability;
        var abDesc = 'Active (' + ab.mana_cost + '): ';
        if (ab.effect_type === 'conjure_rat_and_buff') {
            abDesc += 'Conjure Common Rat from deck. Ally Rats on board +1🗡️/+1❤️ (+Dark Matter × 1).';
        } else if (ab.effect_type === 'summon_token' && ab.summon_card_id) {
            abDesc += 'Summon ' + findCardNameById(ab.summon_card_id) + '.';
        } else {
            abDesc += (ab.name || ab.effect_type);
        }
        cardTextLines.push(abDesc);
    }
    if (c.transform_options && c.transform_options.length > 0) {
        var tLines = c.transform_options.map(function(opt) {
            return findCardNameById(opt.target) + ' (' + opt.mana_cost + ' mana)';
        });
        cardTextLines.push('Transform: ' + tLines.join(', '));
    }
    if (c.react_condition != null && c.react_mana_cost != null) {
        var condMap = {
            0: 'Enemy plays Magic', 1: 'Enemy summons Minion', 2: 'Enemy attacks',
            3: 'Enemy plays React', 4: 'Any enemy action',
            5: 'Enemy plays any Wood', 6: 'Enemy plays any Fire', 7: 'Enemy plays any Earth',
            8: 'Enemy plays any Water', 9: 'Enemy plays any Metal', 10: 'Enemy plays any Dark',
            11: 'Enemy plays any Light', 12: 'Enemy sacrifices'
        };
        var condText = condMap[c.react_condition] || 'Enemy acts';
        var extraCond = c.react_requires_no_friendly_minions ? ' & No friendly minions' : '';
        var costText = c.react_mana_cost > 0 ? ' (' + c.react_mana_cost + ')' : '';
        cardTextLines.push('React' + costText + ': ' + condText + extraCond + ' ▶ Deploy');
    }
    if (cardTextLines.length > 0) {
        bodyHtml += '<div class="gtt-text">' + cardTextLines.join('<br>') + '</div>';
    }
    if (c.flavour_text) {
        bodyHtml += '<div class="gtt-flavour">"' + c.flavour_text + '"</div>';
    }

    // Keywords
    var matchedKeywords = [];
    if (c.unique) matchedKeywords.push('Unique');
    if (c.card_type === 0 && c.attack_range != null && c.attack_range === 0) matchedKeywords.push('Melee');
    if (c.card_type === 0 && c.attack_range != null && c.attack_range > 0) matchedKeywords.push('Range');
    if (c.summon_sacrifice_tribe) { matchedKeywords.push('Cost'); matchedKeywords.push('Discard'); }
    if (c.transform_options && c.transform_options.length > 0) matchedKeywords.push('Transform');
    if (c.react_condition != null) matchedKeywords.push('React');
    if (c.react_condition != null && c.react_effect && c.react_effect.type === 5) matchedKeywords.push('Deploy');
    var skipSummon = false;
    if (c.effects) { c.effects.forEach(function(eff) { if (eff.type === 11) skipSummon = true; }); }
    if (c.effects && c.effects.length > 0) {
        c.effects.forEach(function(eff) {
            if (eff.trigger === 0 && c.card_type === 0 && !skipSummon) { if (matchedKeywords.indexOf('Summon') === -1) matchedKeywords.push('Summon'); }
            if (eff.trigger === 1) { if (matchedKeywords.indexOf('Death') === -1) matchedKeywords.push('Death'); }
            if (eff.trigger === 2) { if (matchedKeywords.indexOf('Attack') === -1) matchedKeywords.push('Attack'); }
            if (eff.trigger === 3) { if (matchedKeywords.indexOf('Damaged') === -1) matchedKeywords.push('Damaged'); }
            if (eff.trigger === 4) { if (matchedKeywords.indexOf('Move') === -1) matchedKeywords.push('Move'); }
            if (eff.trigger === 5) { if (matchedKeywords.indexOf('Passive') === -1) matchedKeywords.push('Passive'); }
            if (eff.type === 0) { if (matchedKeywords.indexOf('Deal') === -1) matchedKeywords.push('Deal'); }
            if (eff.type === 1) { if (matchedKeywords.indexOf('Heal') === -1) matchedKeywords.push('Heal'); }
            if (eff.type === 3) { if (matchedKeywords.indexOf('Heal') === -1) matchedKeywords.push('Heal'); }
            if (eff.type === 4) { if (matchedKeywords.indexOf('Negate') === -1) matchedKeywords.push('Negate'); }
            if (eff.type === 5) { if (matchedKeywords.indexOf('Deploy') === -1) matchedKeywords.push('Deploy'); }
            if (eff.type === 6) { if (matchedKeywords.indexOf('Rally') === -1) matchedKeywords.push('Rally'); }
            if (eff.type === 7) { if (matchedKeywords.indexOf('Promote') === -1) matchedKeywords.push('Promote'); }
            if (eff.type === 8) { if (matchedKeywords.indexOf('Tutor') === -1) matchedKeywords.push('Tutor'); }
            if (eff.type === 9) { if (matchedKeywords.indexOf('Destroy') === -1) matchedKeywords.push('Destroy'); }
            if (eff.type === 10) { if (matchedKeywords.indexOf('Burn') === -1) matchedKeywords.push('Burn'); }
            if (eff.type === 11) { if (matchedKeywords.indexOf('Active') === -1) matchedKeywords.push('Active'); if (matchedKeywords.indexOf('Dark Matter') === -1) matchedKeywords.push('Dark Matter'); }
            if (eff.type === 12) { if (matchedKeywords.indexOf('Passive') === -1) matchedKeywords.push('Passive'); if (matchedKeywords.indexOf('Heal') === -1) matchedKeywords.push('Heal'); }
            if (eff.type === 13) { if (matchedKeywords.indexOf('Leap') === -1) matchedKeywords.push('Leap'); }
            if (eff.type === 14) { if (matchedKeywords.indexOf('Conjure') === -1) matchedKeywords.push('Conjure'); }
        });
    }
    matchedKeywords.forEach(function(kw) {
        bodyHtml += '<div class="gtt-keyword"><span class="gtt-kw-name">' + kw + '</span> <span class="gtt-kw-desc">— ' + (KEYWORD_GLOSSARY[kw] || '') + '</span></div>';
    });

    tooltip.querySelector('.gtt-body').innerHTML = bodyHtml;
}

function hideGameTooltip() {
    var tooltip = document.getElementById('game-tooltip');
    if (tooltip) tooltip.style.display = 'none';
}

// Auto-fit for hand card names (scaleX for overflow)
function fitHandCardNames() {
    document.querySelectorAll('.card-frame-hand .card-name-overlay').forEach(function(el) {
        el.style.transform = 'none';
        var containerWidth = el.offsetWidth;
        var textWidth = el.scrollWidth;
        if (textWidth > containerWidth && containerWidth > 0) {
            var scale = containerWidth / textWidth;
            if (scale < 0.5) scale = 0.5;
            el.style.transform = 'scaleX(' + scale + ')';
        }
    });
}

// Auto-fit for hand card effects (shrink font)
function fitHandCardEffects() {
    document.querySelectorAll('.card-frame-hand .card-effect-full').forEach(function(el) {
        el.style.fontSize = '10px';
        var size = 10;
        while (el.scrollHeight > el.clientHeight && size > 6) {
            size--;
            el.style.fontSize = size + 'px';
        }
    });
}

function renderDeckBuilderCard(numericId, count) {
    var c = allCardDefs ? allCardDefs[numericId] : cardDefs[numericId];
    if (!c) return '';
    var typeClass = TYPE_CSS[c.card_type] || '';
    var elem = (c.element !== null && c.element !== undefined)
        ? ELEMENT_MAP[c.element] : NEUTRAL_ELEMENT;

    var html = '<div class="card-frame card-frame-full ' + typeClass + '">';
    // Mana badge (top-left, direct child of card-frame)
    html += '<div class="card-mana">' + c.mana_cost + '</div>';
    // Element circle (top-right, direct child of card-frame)
    html += '<div class="attr-circle ' + elem.css + '"><span class="attr-text">' + elem.name + '</span></div>';
    // Art area with name overlay (YGO CardPreview style)
    var artStyle = c.card_id ? 'background-image:url(/static/art/' + c.card_id + '.png)' : '';
    html += '<div class="card-art card-art-full" style="' + artStyle + '">';
    html += '<div class="card-art-overlay"></div>';
    html += '<div class="card-name-overlay">' + c.name + '</div>';
    html += '</div>';
    // Bottom section: ATK circle | tribe+range | HP circle
    if (c.card_type === 0 && c.attack != null) {
        var tribe = c.tribe || '';
        var rangeText = (c.attack_range != null) ? (c.attack_range === 0 ? 'MELEE' : 'RANGE ' + c.attack_range) : '';
        html += '<div class="card-bottom-section">';
        html += '<div class="card-stat-atk">' + c.attack + '</div>';
        html += '<div class="card-bottom-center">';
        if (tribe) html += '<div class="card-bottom-tribe">' + tribe + '</div>';
        if (rangeText) html += '<div class="card-bottom-range">' + rangeText + '</div>';
        html += '</div>';
        html += '<div class="card-stat-hp">' + c.health + '</div>';
        html += '</div>';
    }
    // Summon sacrifice cost
    if (c.summon_sacrifice_tribe) {
        html += '<div class="card-effect-full">Cost: Discard any ' + c.summon_sacrifice_tribe + '</div>';
    }
    // Unique tag
    if (c.unique) {
        html += '<div class="card-effect-full">Unique</div>';
    }
    // Effect text (all card types)
    if (c.effects && c.effects.length > 0) {
        var desc = getEffectDescription(c.effects, c);
        html += '<div class="card-effect-full">' + desc + '</div>';
    }
    // Activated ability — auto-derive description from the ability block
    if (c.activated_ability) {
        var ab = c.activated_ability;
        var abDesc = 'Active (' + ab.mana_cost + '): ';
        if (ab.effect_type === 'conjure_rat_and_buff') {
            abDesc += 'Conjure Common Rat from deck. Ally Rats on board +1🗡️/+1❤️ (+Dark Matter × 1).';
        } else if (ab.effect_type === 'summon_token' && ab.summon_card_id) {
            abDesc += 'Summon ' + findCardNameById(ab.summon_card_id) + '.';
        } else {
            abDesc += (ab.name || ab.effect_type);
        }
        html += '<div class="card-effect-full">' + abDesc + '</div>';
    }
    // Transform options (Reanimated Bones) — compact list
    if (c.transform_options && c.transform_options.length > 0) {
        var tLines = c.transform_options.map(function(opt) {
            return '(' + opt.mana_cost + ') ' + findCardNameById(opt.target);
        });
        html += '<div class="card-effect-full">Transform: ' + tLines.join(', ') + '</div>';
    }
    // React ability (multi-purpose cards like Dark Sentinel)
    if (c.react_condition != null && c.react_mana_cost != null) {
        var condMap = {
            0: 'Enemy plays Magic', 1: 'Enemy summons Minion', 2: 'Enemy attacks',
            3: 'Enemy plays React', 4: 'Any enemy action',
            5: 'Enemy plays any Wood', 6: 'Enemy plays any Fire', 7: 'Enemy plays any Earth',
            8: 'Enemy plays any Water', 9: 'Enemy plays any Metal', 10: 'Enemy plays any Dark',
            11: 'Enemy plays any Light', 12: 'Enemy sacrifices'
        };
        var condText = condMap[c.react_condition] || 'Enemy acts';
        var extraCond = c.react_requires_no_friendly_minions ? ' & No friendly minions' : '';
        var costText = c.react_mana_cost > 0 ? ' (' + c.react_mana_cost + ')' : '';
        html += '<div class="card-effect-full">React' + costText + ': ' + condText + extraCond + '</div>';
        html += '<div class="card-effect-full">▶ Deploy</div>';
    }
    // Flavour text — only when the card has no other text content
    if (c.flavour_text
            && (!c.effects || c.effects.length === 0)
            && !c.activated_ability
            && c.react_condition == null
            && (!c.transform_options || c.transform_options.length === 0)) {
        html += '<div class="card-flavour">' + c.flavour_text + '</div>';
    }
    // Range already shown in bottom center for minions
    html += '</div>';
    // Count badge
    if (count === -1) {
        html += '<div class="card-count-badge prohibited">🚫</div>';
    } else {
        var badgeClass = count > 0 ? 'card-count-badge' : 'card-count-badge empty';
        html += '<div class="' + badgeClass + '">x' + count + '</div>';
    }
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
            populateDeckSelector();  // refresh lobby dropdown too
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
    setupActivityTabs();
    setupGameHandlers();
});

// =============================================
// Section: AnimationQueue (Phase 14.3)
// =============================================
//
// Serializes state-update application behind animations so pending UIs
// (react window, tutor modal, post-move-attack pick) never open mid-animation.
//
// Job shape: { type: 'summon'|'move'|'attack'|'noop', payload: {...},
//              stateAfter: <frame>, legalActionsAfter: <list>, durationMs: <int> }
//
// Contract:
//   enqueueAnimation(job)  — push + kick the queue
//   runQueue()             — shifts next job, runs playAnimation, then
//                            applyStateFrame(job.stateAfter, job.legalActionsAfter)
//   playAnimation(job,done)— Wave 1: all branches are setTimeout(done,0) no-ops.
//                            Waves 2-4 replace branches with real visuals.
//   applyStateFrame(frame,legal) — single point of state application; calls
//                            renderGame() which drives all pending UI sync.
//   isAnimating()          — true while a job is running OR queue has pending jobs

var animQueue = [];
var animRunning = false;
// Registry of tiles currently animating: { "<row>,<col>": "summon"|"move"|... }
// Read by renderBoard() to apply the matching .anim-* class to .board-cell.
// Wave 3/4 (move/attack) will reuse this same registry.
var animatingTiles = {};

function enqueueAnimation(job) {
    animQueue.push(job);
    runQueue();
}

function runQueue() {
    if (animRunning) return;
    if (animQueue.length === 0) return;
    var job = animQueue.shift();
    animRunning = true;
    playAnimation(job, function onAnimDone() {
        // Apply the buffered state frame AFTER the animation completes,
        // unless the branch already applied it (e.g. summon applies up-front
        // so the minion is visible during scale-in and sets job.stateApplied).
        if (!job.stateApplied) {
            applyStateFrame(job.stateAfter, job.legalActionsAfter);
        }
        animRunning = false;
        runQueue();
    });
}

function playAnimation(job, done) {
    // Phase 14.3 contract: branches call done() when their animation
    // finishes. Some branches (summon) apply state at the START of the
    // animation; others (move/attack, future waves) apply state at
    // different points. The default applyStateFrame call in runQueue is
    // suppressed by setting job.stateApplied = true inside the branch.
    switch (job && job.type) {
        case 'summon':
            playSummonAnimation(job, done);
            return;
        case 'attack':
            playAttackAnimation(job, done);
            return;
        case 'move':
            playMoveAnimation(job, done);
            return;
        case 'noop':
        default:
            setTimeout(done, 0);
            return;
    }
}

// =============================================
// Section: Floating popups + status badges (Phase 14.3 Wave 7)
// =============================================
// Reusable popup system. One function, five variants. Adding a new
// status (frozen, stunned, etc.) is one CSS variant + one diff hook.
//
// Variant glyph convention:
//   combat-damage: '⚔️ -X'
//   heal:          '💚 +X'
//   burn-tick:     '🔥 -X'
//   buff:          '⬆️ +X ATK'
//   debuff:        '⬇️ -X ATK'
//
// tileEl should be the .board-cell (already position:relative). The
// popup is absolutely positioned and self-removes after the rise+fade
// keyframe completes (~1200ms; 1400ms setTimeout fallback).
// =============================================
// Audio system (CC0 Kenney sounds in /static/sfx/)
// =============================================
var SFX_FILES = {
    card_play:    '/static/sfx/card_play.ogg',
    move:         '/static/sfx/move.ogg',
    attack_hit:   '/static/sfx/attack_hit.ogg',
    damage:       '/static/sfx/damage.ogg',
    heal:         '/static/sfx/heal.ogg',
    burn_tick:    '/static/sfx/burn_tick.ogg',
    button_click: '/static/sfx/button_click.ogg',
    victory:      '/static/sfx/victory.ogg',
    defeat:       '/static/sfx/defeat.ogg',
    nudge_egg:    '/static/sfx/nudge_egg.ogg',
    nudge_boom:   '/static/sfx/nudge_boom.ogg',
    nudge_rain:   '/static/sfx/nudge_rain.ogg',
    nudge_kiss:   '/static/sfx/nudge_kiss.ogg',
};
var sfxBuffers = {};
var sfxVolume = 0.6;
var sfxMuted = (function () {
    try { return localStorage.getItem('gt_sfx_muted') === '1'; } catch (e) { return false; }
})();
(function preloadSfx() {
    for (var k in SFX_FILES) {
        var a = new Audio(SFX_FILES[k]);
        a.preload = 'auto';
        sfxBuffers[k] = a;
    }
})();
function playSfx(name) {
    if (sfxMuted) return;
    var src = sfxBuffers[name];
    if (!src) return;
    // Clone so overlapping plays work (Audio elements can't double-play themselves)
    try {
        var node = src.cloneNode();
        node.volume = sfxVolume;
        var p = node.play();
        if (p && p.catch) p.catch(function () { /* autoplay blocked, ignore */ });
    } catch (e) {}
}
function setSfxMuted(muted) {
    sfxMuted = !!muted;
    try { localStorage.setItem('gt_sfx_muted', sfxMuted ? '1' : '0'); } catch (e) {}
}

function showFloatingPopup(tileEl, text, variant) {
    if (!tileEl) return;
    // Sound for the popup variant
    if (variant === 'combat-damage') playSfx('damage');
    else if (variant === 'heal') playSfx('heal');
    else if (variant === 'burn-tick') playSfx('burn_tick');
    var el = document.createElement('div');
    el.className = 'floating-popup ' + variant;
    el.textContent = text;
    tileEl.appendChild(el);
    var removed = false;
    var cleanup = function () {
        if (removed) return;
        removed = true;
        if (el.parentNode) el.parentNode.removeChild(el);
    };
    el.addEventListener('animationend', cleanup);
    setTimeout(cleanup, 2400);
}

// Helper: flatten all board minions from a state frame.
function collectMinions(state) {
    if (!state || !state.minions) return [];
    return state.minions;
}

// Helper: locate the .board-cell DOM node for a minion's position.
function getTileElForMinion(m) {
    if (!m || !m.position) return null;
    return document.querySelector(
        '.board-cell[data-row="' + m.position[0] + '"][data-col="' + m.position[1] + '"]');
}

// Wave 4 (Phase 14.3-04): Attack animation.
// Rubber-band pullback (180ms) -> pause (100ms) -> snap strike (120ms) ->
// target flash + damage popup -> return tween (300ms) -> apply state.
// Total ~800ms. State is applied by runQueue's default after done(),
// so killed minions disappear AFTER the strike, not before.
function playAttackAnimation(job, done) {
    playSfx('attack_hit');
    var payload = (job && job.payload) || {};
    var attackerPos = payload.attackerPos;
    var targetPos = payload.targetPos;
    var damage = payload.damage;

    if (!attackerPos || !targetPos) { setTimeout(done, 0); return; }

    var attackerCell = document.querySelector(
        '.board-cell[data-row="' + attackerPos[0] + '"][data-col="' + attackerPos[1] + '"]');
    var targetCell = document.querySelector(
        '.board-cell[data-row="' + targetPos[0] + '"][data-col="' + targetPos[1] + '"]');

    if (!attackerCell || !targetCell) { setTimeout(done, 0); return; }

    // Branch on attacker range: ranged minions get a projectile-arrow, melee
    // gets the rubber-band rush. Look up the attacker's CardDef via the .board-minion
    // element's data-numeric-id (set by renderBoardMinion).
    var attackerMinionEl = attackerCell.querySelector('.board-minion');
    var atkRange = 0;
    if (attackerMinionEl) {
        var nid = parseInt(attackerMinionEl.getAttribute('data-numeric-id'), 10);
        var def = !isNaN(nid) ? cardDefs[nid] : null;
        if (def && typeof def.attack_range === 'number') atkRange = def.attack_range;
    }
    if (atkRange >= 1) {
        return playRangedAttackAnimation(attackerCell, targetCell, damage, done);
    }

    // Animate the inner .board-minion if present so the cell border stays put.
    var attackerEl = attackerCell.querySelector('.board-minion') || attackerCell;

    var aRect = attackerCell.getBoundingClientRect();
    var tRect = targetCell.getBoundingClientRect();
    var dx = (tRect.left + tRect.width / 2) - (aRect.left + aRect.width / 2);
    var dy = (tRect.top + tRect.height / 2) - (aRect.top + aRect.height / 2);

    var pullX = -0.3 * dx, pullY = -0.3 * dy;
    var strikeX = 0.7 * dx, strikeY = 0.7 * dy;

    function cleanupAttacker() {
        attackerEl.classList.remove('anim-attack-windup');
        attackerEl.classList.remove('anim-attack-strike');
        attackerEl.style.transform = '';
    }

    // PHASE A — pullback (0-180ms)
    attackerEl.classList.add('anim-attack-windup');
    attackerEl.style.transform = 'translate(' + pullX + 'px,' + pullY + 'px)';

    setTimeout(function () {
        // PHASE B — pause (180-280ms)
        setTimeout(function () {
            // PHASE C — strike (280-400ms)
            attackerEl.classList.remove('anim-attack-windup');
            attackerEl.classList.add('anim-attack-strike');
            attackerEl.style.transform = 'translate(' + strikeX + 'px,' + strikeY + 'px)';

            setTimeout(function () {
                // PHASE D — impact: flash + damage popup
                targetCell.classList.add('anim-target-hit');
                setTimeout(function () {
                    targetCell.classList.remove('anim-target-hit');
                }, 420);

                // Phase 14.3 Wave 7: route combat damage through the unified
                // showFloatingPopup pathway. Replaces the Wave 4 inline
                // .damage-popup span. The .damage-popup CSS block is now
                // unused (harmless to leave behind).
                if (damage != null && damage > 0) {
                    showFloatingPopup(targetCell, '⚔️ -' + damage, 'combat-damage');
                }

                // PHASE E — return tween (400-700ms)
                attackerEl.classList.remove('anim-attack-strike');
                attackerEl.classList.add('anim-attack-windup');
                attackerEl.style.transform = 'translate(0,0)';

                setTimeout(function () {
                    // PHASE F — finish; runQueue's default applyStateFrame
                    // will fire on done() and remove dead minions.
                    cleanupAttacker();
                    done();
                }, 300);
            }, 120);
        }, 100);
    }, 180);
}

// Ranged attack animation: SVG arrow drawn from attacker to target.
// Phase A: arrow grows from attacker (~350ms via stroke-dasharray)
// Phase B: target flash + damage popup
// Phase C: arrow fades (~300ms) then removed
// Total ~850ms.
function playRangedAttackAnimation(attackerCell, targetCell, damage, done) {
    var aRect = attackerCell.getBoundingClientRect();
    var tRect = targetCell.getBoundingClientRect();
    var ax = aRect.left + aRect.width / 2;
    var ay = aRect.top + aRect.height / 2;
    var tx = tRect.left + tRect.width / 2;
    var ty = tRect.top + tRect.height / 2;

    // Recoil the attacker slightly back along the firing axis
    var attackerEl = attackerCell.querySelector('.board-minion') || attackerCell;
    var dx = tx - ax, dy = ty - ay;
    var len = Math.max(1, Math.sqrt(dx * dx + dy * dy));
    var ux = dx / len, uy = dy / len;
    var recoilX = -8 * ux, recoilY = -8 * uy;
    attackerEl.style.transition = 'transform 120ms ease-out';
    attackerEl.style.transform = 'translate(' + recoilX + 'px,' + recoilY + 'px)';

    // SVG overlay covering the viewport so the arrow can span anywhere
    var SVG_NS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'ranged-attack-svg');
    svg.style.position = 'fixed';
    svg.style.left = '0';
    svg.style.top = '0';
    svg.style.width = '100vw';
    svg.style.height = '100vh';
    svg.style.pointerEvents = 'none';
    svg.style.zIndex = '900';

    // Arrowhead marker
    var defs = document.createElementNS(SVG_NS, 'defs');
    var marker = document.createElementNS(SVG_NS, 'marker');
    marker.setAttribute('id', 'ranged-arrowhead');
    marker.setAttribute('viewBox', '0 0 10 10');
    marker.setAttribute('refX', '8');
    marker.setAttribute('refY', '5');
    marker.setAttribute('markerWidth', '6');
    marker.setAttribute('markerHeight', '6');
    marker.setAttribute('orient', 'auto-start-reverse');
    var arrowPath = document.createElementNS(SVG_NS, 'path');
    arrowPath.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
    arrowPath.setAttribute('fill', '#ffd84a');
    marker.appendChild(arrowPath);
    defs.appendChild(marker);
    svg.appendChild(defs);

    // The line itself: black halo underneath, gold on top, animated draw
    var halo = document.createElementNS(SVG_NS, 'line');
    halo.setAttribute('x1', ax); halo.setAttribute('y1', ay);
    halo.setAttribute('x2', tx); halo.setAttribute('y2', ty);
    halo.setAttribute('stroke', 'rgba(0,0,0,0.85)');
    halo.setAttribute('stroke-width', '7');
    halo.setAttribute('stroke-linecap', 'round');
    var line = document.createElementNS(SVG_NS, 'line');
    line.setAttribute('x1', ax); line.setAttribute('y1', ay);
    line.setAttribute('x2', tx); line.setAttribute('y2', ty);
    line.setAttribute('stroke', '#ffd84a');
    line.setAttribute('stroke-width', '4');
    line.setAttribute('stroke-linecap', 'round');
    line.setAttribute('marker-end', 'url(#ranged-arrowhead)');

    // Stroke-dasharray draw-on effect
    [halo, line].forEach(function (el) {
        el.style.strokeDasharray = len + ' ' + len;
        el.style.strokeDashoffset = len;
        el.style.transition = 'stroke-dashoffset 350ms ease-out, opacity 300ms ease-out';
    });
    svg.appendChild(halo);
    svg.appendChild(line);
    document.body.appendChild(svg);

    // Trigger the draw on next frame
    requestAnimationFrame(function () {
        halo.style.strokeDashoffset = '0';
        line.style.strokeDashoffset = '0';
    });

    setTimeout(function () {
        // Impact: target flash + damage popup
        targetCell.classList.add('anim-target-hit');
        setTimeout(function () { targetCell.classList.remove('anim-target-hit'); }, 420);
        if (damage != null && damage > 0) {
            showFloatingPopup(targetCell, '⚔️ -' + damage, 'combat-damage');
        }

        // Recoil return
        attackerEl.style.transform = 'translate(0,0)';

        // Fade out the arrow
        halo.style.opacity = '0';
        line.style.opacity = '0';

        setTimeout(function () {
            if (svg.parentNode) svg.parentNode.removeChild(svg);
            attackerEl.style.transition = '';
            attackerEl.style.transform = '';
            done();
        }, 300);
    }, 380);
}

// Tile-rect measurement helper. Returns the pixel delta between the centers
// of two board tiles, or null if either tile is missing from the DOM.
// Shared by move (Wave 3) and available for future animations.
function getTileDelta(fromPos, toPos) {
    if (!fromPos || !toPos) return null;
    var fromCell = document.querySelector(
        '.board-cell[data-row="' + fromPos[0] + '"][data-col="' + fromPos[1] + '"]');
    var toCell = document.querySelector(
        '.board-cell[data-row="' + toPos[0] + '"][data-col="' + toPos[1] + '"]');
    if (!fromCell || !toCell) return null;
    var fr = fromCell.getBoundingClientRect();
    var tr = toCell.getBoundingClientRect();
    return {
        dx: (tr.left + tr.width / 2) - (fr.left + fr.width / 2),
        dy: (tr.top + tr.height / 2) - (fr.top + fr.height / 2),
        fromCell: fromCell,
        toCell: toCell,
    };
}

// Wave 3 (Phase 14.3-03): Move animation.
// PHASE A — lift   (0ms):    add .anim-move-lift to source minion (scale + shadow)
// PHASE B — translate (120ms): add .anim-move-translate, set inline transform
//                              translate(dx,dy) scale(1.15). Wait 350ms.
// PHASE C — apply state + drop (470ms): applyStateFrame so the board re-renders
//   with the minion at the destination tile. The animatingTiles registry causes
//   renderBoard to tag the destination .board-cell with .anim-move-drop, which
//   plays a 120ms drop keyframe back to scale 1.0. Wait 120ms.
// PHASE D — cleanup, done().
//
// State application happens MID-animation (like summon, unlike attack), so we
// set job.stateApplied = true to suppress runQueue's default applyStateFrame.
function playMoveAnimation(job, done) {
    playSfx('move');
    var payload = (job && job.payload) || {};
    var from = payload.from;
    var to = payload.to;

    // Bail to a no-op if we don't have valid coords; runQueue will still
    // apply the state frame after done() because we don't set stateApplied.
    if (!from || !to) { setTimeout(done, 0); return; }

    var delta = getTileDelta(from, to);
    if (!delta) { setTimeout(done, 0); return; }

    var minionEl = delta.fromCell.querySelector('.board-minion');
    if (!minionEl) {
        // Source minion isn't in the DOM (race / reconnection). Skip visuals.
        setTimeout(done, 0);
        return;
    }

    var dx = delta.dx, dy = delta.dy;
    var destKey = to[0] + ',' + to[1];
    var srcKey = from[0] + ',' + from[1];

    // Bug B fix: .board-cell has overflow:hidden (for the cover-art bg).
    // The translated minion gets clipped at the source cell's bounds and
    // visually escapes only along the overflow edge — appearing "below the
    // grid" to the user. Lift overflow on the source cell for the duration
    // of the slide; Phase C re-renders the board so we don't need to
    // restore it explicitly (the cell is rebuilt by renderBoard).
    var prevOverflow = delta.fromCell.style.overflow;
    delta.fromCell.style.overflow = 'visible';
    // Also lift the parent stacking — z-index on board-minion won't escape
    // the cell otherwise. board-cell is position:relative so we can stack it.
    var prevZ = delta.fromCell.style.zIndex;
    delta.fromCell.style.zIndex = '30';

    // PHASE A — lift
    minionEl.classList.add('anim-move-lift');

    setTimeout(function () {
        // PHASE B — translate. The lift transform (scale 1.15) is preserved
        // explicitly because setting style.transform overrides the class rule.
        minionEl.classList.add('anim-move-translate');
        minionEl.style.transform = 'translate(' + dx + 'px,' + dy + 'px) scale(1.15)';

        setTimeout(function () {
            // PHASE C — apply state + drop. The board re-renders; the source
            // tile is now empty and the destination tile holds the minion.
            // animatingTiles[destKey] makes renderBoard tag that .board-cell
            // with .anim-move-drop so the freshly-rendered minion plays the
            // drop keyframe.
            animatingTiles[destKey] = 'move-drop';
            try {
                applyStateFrame(job.stateAfter, job.legalActionsAfter);
            } catch (e) { /* defensive */ }
            job.stateApplied = true;

            setTimeout(function () {
                // PHASE D — cleanup
                delete animatingTiles[destKey];
                delete animatingTiles[srcKey];
                try { renderBoard(); } catch (e) { /* defensive */ }
                done();
            }, 130);
        }, 350);
    }, 120);
}

// Wave 2: summon animation.
// Contract deviation from move/attack: state is applied at the START so the
// summoned minion is visible during its scale-in. We mark the destination
// tile in animatingTiles so renderBoard adds .anim-summon to that .board-cell.
function playSummonAnimation(job, done) {
    playSfx('card_play');
    var pos = job.payload && job.payload.pos;
    if (!pos) { setTimeout(done, 0); return; }
    var key = pos[0] + ',' + pos[1];

    // 1. Mark the tile so the next renderBoard tags it with .anim-summon.
    animatingTiles[key] = 'summon';

    // 2. Apply the post-summon state NOW (minion appears) and prevent the
    //    queue's default post-animation applyStateFrame.
    applyStateFrame(job.stateAfter, job.legalActionsAfter);
    job.stateApplied = true;

    // 3. Shake the board container.
    var boardEl = document.getElementById('game-board');
    if (boardEl) {
        boardEl.classList.remove('anim-grid-shake');
        // Force reflow so re-adding the class restarts the animation.
        void boardEl.offsetWidth;
        boardEl.classList.add('anim-grid-shake');
        setTimeout(function() {
            if (boardEl) boardEl.classList.remove('anim-grid-shake');
        }, 360);
    }

    // 4. After one full scale-in cycle, drop the registry entry, re-render
    //    the board so the .anim-summon class falls off, and signal done.
    setTimeout(function() {
        delete animatingTiles[key];
        try { renderBoard(); } catch (e) { /* defensive: never block done() */ }
        done();
    }, 650);
}

// Single point of state application. Called directly for non-action frames
// (initial join, react open/close, lobby) and from runQueue() for queued
// action frames. All pending-UI sync lives downstream in renderGame() so
// it automatically runs post-animation.
// Cinder/paper-burn death animation. Adds .anim-cinder-death to the OLD
// .board-minion DOM node and sprinkles a few floating embers above it.
// Calls `done` after the animation completes (~1000ms). Used by
// applyStateFrame to defer state-swap on burn deaths so the player sees
// the kill animate instead of the minion vanishing instantly.
function playBurnDeathAnimation(prevMinion, done) {
    var tile = getTileElForMinion(prevMinion);
    if (!tile) { done && done(); return; }
    var minionEl = tile.querySelector('.board-minion');
    if (!minionEl) { done && done(); return; }

    playSfx('burn_tick');

    // Spawn 4 embers drifting up at slight horizontal offsets.
    var embers = [];
    for (var i = 0; i < 4; i++) {
        var em = document.createElement('span');
        em.className = 'cinder-ember';
        em.style.setProperty('--ex', ((i - 1.5) * 6) + 'px');
        em.style.animationDelay = (i * 80) + 'ms';
        tile.appendChild(em);
        embers.push(em);
    }

    minionEl.classList.add('anim-cinder-death');

    setTimeout(function () {
        try { minionEl.classList.remove('anim-cinder-death'); } catch (e) {}
        embers.forEach(function (e) { try { e.remove(); } catch (_) {} });
        done && done();
    }, 1000);
}

function applyStateFrame(frame, legal) {
    var prevState = gameState;

    // Detect burn-deaths: minions that were is_burning in prevState and
    // are MISSING from the next frame. We assume these died from the
    // start-of-turn burn tick (combat-killed minions are removed by other
    // code paths after their own animations).
    try {
        if (prevState && prevState.minions && frame && frame.minions) {
            var nextIds = {};
            collectMinions(frame).forEach(function (m) {
                if (m && m.instance_id != null) nextIds[m.instance_id] = true;
            });
            var burnDying = [];
            collectMinions(prevState).forEach(function (m) {
                if (!m || m.instance_id == null) return;
                if (nextIds[m.instance_id]) return;
                if (m.is_burning) burnDying.push(m);
            });
            if (burnDying.length > 0) {
                var pending = burnDying.length;
                var finish = function () {
                    pending -= 1;
                    if (pending <= 0) _applyStateFrameImmediate(frame, legal, prevState);
                };
                burnDying.forEach(function (m) { playBurnDeathAnimation(m, finish); });
                return;
            }
        }
    } catch (e) { /* defensive — fall through to immediate apply */ }

    _applyStateFrameImmediate(frame, legal, prevState);
}

function _applyStateFrameImmediate(frame, legal, prevState) {
    if (prevState === undefined) prevState = gameState;

    // Phase 14.3 Wave 7: per-minion HP delta hooks BEFORE state mutates.
    // - Heal popup: any current_health increase between frames.
    // - Burn-tick popup: HP decrease on a burning minion at the moment
    //   the active player flips (the only frame where the engine ticks
    //   burning). Popups anchor to the OLD tile so lethal burns still
    //   show the number before the minion vanishes on the next render.
    // NOTE: Phase 14.3 now has 7 plans (waves 6+7 added). Re-run
    // /gsd:plan-phase Wave 5 closeout or update STATE.md/ROADMAP.md
    // manually after this lands.
    try {
        if (prevState && prevState.minions && frame && frame.minions) {
            var prevMinions = {};
            collectMinions(prevState).forEach(function (m) {
                if (m && m.instance_id != null) prevMinions[m.instance_id] = m;
            });
            var turnFlipped = prevState.active_player_idx !== frame.active_player_idx;
            collectMinions(frame).forEach(function (m) {
                var p = prevMinions[m.instance_id];
                if (!p) return; // newly summoned this frame
                var prevHp = p.current_health;
                var nextHp = m.current_health;
                var tileEl = getTileElForMinion(m);

                // Heal: HP went UP
                if (nextHp > prevHp) {
                    showFloatingPopup(tileEl, '💚 +' + (nextHp - prevHp), 'heal');
                }

                // Burn tick: turn just flipped, prev was burning, and HP
                // went DOWN. The engine ticks burn at the start of the
                // owner's turn — only fire the popup when the new active
                // player is the owner. Anchor to the prev tile so lethal
                // burns still show the number before the minion vanishes.
                if (turnFlipped && p.is_burning && nextHp < prevHp
                        && frame.active_player_idx === p.owner) {
                    var burnTile = getTileElForMinion(p) || tileEl;
                    showFloatingPopup(burnTile, '🔥 -' + (prevHp - nextHp), 'burn-tick');
                }
            });
        }
    } catch (e) { /* defensive: never block state application */ }

    gameState = frame;
    if (legal !== undefined) legalActions = legal;
    // Phase 14.4: keep spectator flags in sync with authoritative frame.
    if (frame && frame.is_spectator) {
        isSpectator = true;
        if (typeof frame.spectator_god_mode === 'boolean') {
            spectatorGodMode = frame.spectator_god_mode;
        }
    }
    logStateDiff(prevState, gameState);
    renderGame();
}

function isAnimating() {
    return animRunning || animQueue.length > 0;
}

// Temporary debug hook (Phase 14.3). Safe to leave — no side effects.
if (typeof window !== 'undefined') {
    window.__animDebug = {
        get animQueue() { return animQueue; },
        get animRunning() { return animRunning; },
        isAnimating: isAnimating,
    };
}

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
    // Phase 14.4: spectators receive is_spectator=true on game_start and in
    // every state frame. Pick it up from the game_start payload too so the
    // first render is already gated correctly.
    if (data.is_spectator || (data.state && data.state.is_spectator)) {
        isSpectator = true;
        if (data.state && typeof data.state.spectator_god_mode === 'boolean') {
            spectatorGodMode = data.state.spectator_god_mode;
        }
    }
    // Reset log for a new game
    clearGameLog();
    addLogEntry('Game started. ' + (opponentName || 'Opponent') + ' joined.');
    // If we're coming from a rematch, hide the game over modal
    hideGameOver();
    resetRematchUI();
    showScreen('screen-game');
    // Set room code in game screen
    var roomCodeEl = document.getElementById('game-room-code');
    if (roomCodeEl && roomCode) {
        roomCodeEl.textContent = roomCode;
    }
    renderGame();
}

// Phase 14.3: onStateUpdate no longer applies state directly. It diffs
// prev vs next to derive an animation job, enqueues it, and lets the
// AnimationQueue call applyStateFrame() when the animation completes.
// Non-action frames (initial join, react open/close, lobby/meta frames)
// bypass the queue and apply immediately so UIs stay responsive.
function onStateUpdate(data) {
    var next = data.state;
    var nextLegal = data.legal_actions;
    var prev = gameState;

    // First frame or no prior state: apply immediately, no animation.
    if (!prev) {
        applyStateFrame(next, nextLegal);
        return;
    }

    // Derive a job from the prev->next diff.
    var job = deriveAnimationJob(prev, next);

    // Non-action transitions (noop with no meaningful diff) bypass the queue
    // entirely. This keeps react-window open/close, tutor-modal open/close,
    // turn-change banners, and passive state refreshes instantaneous.
    if (!job || job.type === 'noop') {
        applyStateFrame(next, nextLegal);
        return;
    }

    job.stateAfter = next;
    job.legalActionsAfter = nextLegal;
    enqueueAnimation(job);
}

// Derive an animation job from a prev->next state diff. Wave 1 is
// deliberately conservative: it only tags summon/move/attack from
// pending_action when present, and returns noop otherwise. Later waves
// will sharpen the diff (damage numbers, kill detection, etc.).
function deriveAnimationJob(prev, next) {
    // Phase 14.3-04: Prefer next.last_action (authoritative server payload)
    // for ATTACK so we get attacker_pos, target_pos, damage, and killed
    // directly without diffing minion lists. Falls through to the legacy
    // pending_action diff for summon/move and any frame missing last_action.
    var la = next && next.last_action;
    if (la && la.type === 'ATTACK') {
        return { type: 'attack', payload: {
            attackerPos: la.attacker_pos || null,
            targetPos: la.target_pos || null,
            damage: la.damage,
            killed: !!la.killed,
        } };
    }
    // Phase 14.3-03: Prefer last_action for MOVE too. attacker_pos = pre-action
    // source, target_pos = destination (per enrich_last_action schema).
    if (la && la.type === 'MOVE') {
        return { type: 'move', payload: {
            from: la.attacker_pos || null,
            to: la.target_pos || null,
        } };
    }

    var pa = next && next.pending_action;
    if (!pa) return { type: 'noop', payload: {} };

    var t = pa.action_type;
    // ActionType: 0=PLAY_CARD, 1=MOVE, 2=ATTACK
    if (t === 0) {
        // Only minion deploys get a summon animation; magic/tutor -> noop.
        // Wave 2 emits pos + card_id (numeric_id). card_id is informational
        // for now; the destination tile in next.minions carries authoritative
        // identity for renderBoardMinion.
        if (pa.position) {
            // Confirm a minion actually appeared at pa.position in next that
            // wasn't there in prev — guards against magic-with-position cards.
            var pkey = pa.position[0] + ',' + pa.position[1];
            var prevHas = (prev.minions || []).some(function(m) {
                return m.position && (m.position[0] + ',' + m.position[1]) === pkey;
            });
            var nextMinion = (next.minions || []).find(function(m) {
                return m.position && (m.position[0] + ',' + m.position[1]) === pkey;
            });
            if (!prevHas && nextMinion) {
                return { type: 'summon', payload: {
                    pos: pa.position,
                    card_id: nextMinion.card_numeric_id,
                } };
            }
        }
        return { type: 'noop', payload: {} };
    }
    if (t === 1) {
        return { type: 'move', payload: {
            from: pa.source_position || null,
            to: pa.target_position || pa.position || null,
        } };
    }
    if (t === 2) {
        return { type: 'attack', payload: {
            attackerPos: pa.source_position || null,
            targetPos: pa.target_position || pa.position || null,
        } };
    }
    return { type: 'noop', payload: {} };
}

// Game log helpers
function clearGameLog() {
    var entries = document.getElementById('log-entries');
    if (entries) entries.innerHTML = '';
}

function addLogEntry(text, type) {
    var entries = document.getElementById('log-entries');
    if (!entries) return;
    var entry = document.createElement('div');
    entry.className = 'log-entry' + (type ? ' log-' + type : '');
    var time = new Date();
    var timeStr = String(time.getHours()).padStart(2, '0') + ':' + String(time.getMinutes()).padStart(2, '0') + ':' + String(time.getSeconds()).padStart(2, '0');
    entry.innerHTML = '<span class="log-time">' + timeStr + '</span> ' + text;
    entries.appendChild(entry);
    entries.scrollTop = entries.scrollHeight;
}

// Log differences between previous and new state
function logStateDiff(prev, next) {
    if (!prev || !next) return;
    var myName = (gameState && myPlayerIdx != null && gameState.players && gameState.players[myPlayerIdx]) ? 'You' : 'You';
    var oppName = opponentName || 'Opponent';

    // Turn change
    if (prev.turn_number !== next.turn_number) {
        var who = next.active_player_idx === myPlayerIdx ? 'Your' : oppName + "'s";
        addLogEntry('Turn ' + next.turn_number + ' — ' + who + ' turn');
    }

    // Phase change to REACT (someone took an action)
    if (prev.phase !== next.phase && next.phase === 1 && next.pending_action) {
        var pa = next.pending_action;
        var actor = next.active_player_idx === myPlayerIdx ? 'You' : oppName;
        var msg = describeAction(pa, prev, next, actor);
        if (msg) addLogEntry(msg);
    }

    // HP changes
    for (var i = 0; i < 2; i++) {
        var prevHp = prev.players?.[i]?.hp;
        var nextHp = next.players?.[i]?.hp;
        if (prevHp != null && nextHp != null && prevHp !== nextHp) {
            var diff = nextHp - prevHp;
            var who = i === myPlayerIdx ? 'You' : oppName;
            if (diff < 0) {
                addLogEntry(who + ' took ' + (-diff) + ' damage (' + nextHp + ' HP)', 'damage');
            } else {
                addLogEntry(who + ' healed +' + diff + ' (' + nextHp + ' HP)', 'heal');
            }
        }
    }

    // Minion count change
    var prevMinions = prev.minions?.length || 0;
    var nextMinions = next.minions?.length || 0;
    if (nextMinions > prevMinions) {
        addLogEntry((nextMinions - prevMinions) + ' minion(s) deployed');
    } else if (nextMinions < prevMinions) {
        addLogEntry((prevMinions - nextMinions) + ' minion(s) destroyed');
    }

    // Phase 14.2: tutor pick is now an explicit modal flow (showTutorModal),
    // not a silent hand-growth detection. The old auto-tutor heuristic that
    // lived here has been removed — pending_tutor_player_idx in state frames
    // drives the modal directly via syncPendingTutorUI().
}

function describeAction(pa, prevState, nextState, actor) {
    if (!pa) return null;
    var t = pa.action_type;
    if (t === 0) {
        // PLAY_CARD — try to find what was played
        if (pa.position) {
            return actor + ' played a card at row ' + (pa.position[0] + 1) + ' col ' + (pa.position[1] + 1);
        }
        return actor + ' cast a magic card';
    }
    if (t === 1) return actor + ' moved a minion';
    if (t === 2) return actor + ' attacked';
    if (t === 3) return actor + ' drew a card';
    if (t === 6) return actor + ' sacrificed a minion for damage';
    return null;
}

function onGameOver(data) {
    gameState = data.final_state;
    legalActions = [];
    renderGame();
    var winner = data.final_state && data.final_state.winner;
    if (winner != null && myPlayerIdx != null) {
        playSfx(winner === myPlayerIdx ? 'victory' : 'defeat');
    }
    showGameOver(data);
}

// Phase 14 PLAY-03: game over modal

function deriveGameOverReason(finalState) {
    if (finalState == null || finalState.winner == null) {
        return 'Draw';
    }
    var winner = finalState.winner;
    var loser = 1 - winner;
    var loserHp = (finalState.players && finalState.players[loser]) ? finalState.players[loser].hp : null;
    if (loserHp != null && loserHp <= 0) {
        return 'HP depleted';
    }
    return 'Sacrifice damage';
}

function showGameOver(data) {
    var overlay = document.getElementById('game-over-overlay');
    if (!overlay) return;
    resetRematchUI();

    var finalState = data.final_state;
    var winner = (data.winner != null) ? data.winner : (finalState ? finalState.winner : null);
    var iWon = (winner != null) && (winner === myPlayerIdx);
    var isDraw = (winner == null);

    var resultEl = document.getElementById('game-over-result');
    if (resultEl) {
        if (isDraw) {
            resultEl.textContent = 'DRAW';
            resultEl.className = 'game-over-result draw';
        } else if (iWon) {
            resultEl.textContent = 'VICTORY';
            resultEl.className = 'game-over-result victory';
        } else {
            resultEl.textContent = 'DEFEAT';
            resultEl.className = 'game-over-result defeat';
        }
    }

    var reasonEl = document.getElementById('game-over-reason');
    if (reasonEl) {
        reasonEl.textContent = deriveGameOverReason(finalState);
    }

    if (finalState && finalState.players && myPlayerIdx != null) {
        var selfPlayer = finalState.players[myPlayerIdx];
        var oppPlayer  = finalState.players[1 - myPlayerIdx];
        var selfNameEl = document.getElementById('game-over-self-name');
        var selfHpEl   = document.getElementById('game-over-self-hp');
        var oppNameEl  = document.getElementById('game-over-opp-name');
        var oppHpEl    = document.getElementById('game-over-opp-hp');
        if (selfNameEl) selfNameEl.textContent = (myName || 'You');
        if (selfHpEl)   selfHpEl.textContent   = selfPlayer ? selfPlayer.hp : '?';
        if (oppNameEl)  oppNameEl.textContent  = (opponentName || 'Opponent');
        if (oppHpEl)    oppHpEl.textContent    = oppPlayer ? oppPlayer.hp : '?';
    }

    overlay.style.display = 'flex';
}

function hideGameOver() {
    var overlay = document.getElementById('game-over-overlay');
    if (overlay) overlay.style.display = 'none';
}

function resetGameClientState() {
    gameState = null;
    legalActions = [];
    myPlayerIdx = null;
    opponentName = '';
    roomCode = null;
    sessionToken = null;
    selectedHandIdx = null;
    selectedMinionId = null;
    interactionMode = null;

    var roomPanel = document.getElementById('room-panel');
    if (roomPanel) roomPanel.style.display = 'none';
    var roomCodeDisplay = document.getElementById('room-code-display');
    if (roomCodeDisplay) roomCodeDisplay.textContent = '';
    var playerList = document.getElementById('player-list');
    if (playerList) playerList.innerHTML = '';
    var lobbyStatus = document.getElementById('lobby-status');
    if (lobbyStatus) {
        lobbyStatus.textContent = '';
        lobbyStatus.className = 'lobby-status';
    }
    var gameRoomCode = document.getElementById('game-room-code');
    if (gameRoomCode) gameRoomCode.textContent = '';

    var reactBanner = document.getElementById('react-banner');
    if (reactBanner) reactBanner.remove();
    var actionBar = document.getElementById('action-bar');
    if (actionBar) actionBar.remove();

    // Reset ready button
    var btnReady = document.getElementById('btn-ready');
    if (btnReady) {
        btnReady.disabled = false;
        btnReady.textContent = 'Ready Up';
    }
}

function returnToLobby() {
    hideGameOver();
    resetGameClientState();
    showScreen('screen-lobby');
    updateNavLockState();
}

function setupGameHandlers() {
    var btnLeave = document.getElementById('btn-leave');
    if (btnLeave) {
        btnLeave.addEventListener('click', returnToLobby);
    }
    var btnBackToLobby = document.getElementById('btn-back-to-lobby');
    if (btnBackToLobby) {
        btnBackToLobby.addEventListener('click', returnToLobby);
    }
    var btnRematch = document.getElementById('btn-rematch');
    if (btnRematch) {
        btnRematch.addEventListener('click', requestRematch);
    }
    var btnMute = document.getElementById('sfx-mute-btn');
    if (btnMute) {
        var refreshMuteBtn = function () { btnMute.textContent = sfxMuted ? '🔇' : '🔊'; };
        refreshMuteBtn();
        btnMute.addEventListener('click', function () {
            setSfxMuted(!sfxMuted);
            refreshMuteBtn();
            if (!sfxMuted) playSfx('button_click');
        });
    }
}

// POLISH-03 Rematch
function requestRematch() {
    if (!socket) return;
    socket.emit('request_rematch', {});
    var btnRematch = document.getElementById('btn-rematch');
    if (btnRematch) {
        btnRematch.disabled = true;
        btnRematch.textContent = 'Waiting...';
    }
    var statusEl = document.getElementById('game-over-status');
    if (statusEl) {
        statusEl.textContent = 'Waiting for opponent...';
        statusEl.className = 'game-over-status waiting';
    }
}

function onRematchWaiting(data) {
    var statusEl = document.getElementById('game-over-status');
    if (!statusEl) return;
    if (data.requester === 'opponent') {
        var name = data.name || 'Opponent';
        statusEl.textContent = name + ' wants a rematch — click Rematch to accept';
        statusEl.className = 'game-over-status incoming';
    }
}

function resetRematchUI() {
    var btnRematch = document.getElementById('btn-rematch');
    if (btnRematch) {
        btnRematch.disabled = false;
        btnRematch.textContent = 'Rematch';
    }
    var statusEl = document.getElementById('game-over-status');
    if (statusEl) {
        statusEl.textContent = '';
        statusEl.className = 'game-over-status';
    }
}

// =============================================
// Section 10: renderGame() -- Master Render Function
// =============================================

function renderGame() {
    if (!gameState || !cardDefs) return;
    clearSelection();
    renderRoomBar();
    renderOpponentInfo();
    renderBoard();
    renderSelfInfo();
    renderHand();
    renderActionBar();
    // Phase 14.3: do not open react window mid-animation; gated because
    // renderGame runs from applyStateFrame which the AnimationQueue only
    // calls AFTER the triggering animation completes.
    renderReactBanner();
    // Phase 14.1: if server says a melee minion has just moved and a post-move
    // attack decision is pending, auto-enter the attack-pick UI mode and show
    // the decline button. Must run BEFORE highlightBoard so highlights reflect it.
    // Phase 14.3: do not open post-move-attack picker mid-animation; the
    // AnimationQueue guarantees applyStateFrame (which calls renderGame)
    // only runs AFTER the triggering animation completes.
    syncPendingPostMoveAttackUI();
    // Phase 14.2: pending_tutor modal sync. Caster sees full-card-art picker;
    // opponent sees a passive "Opponent is tutoring…" toast.
    // Phase 14.3: do not open tutor modal mid-animation; gated by the
    // AnimationQueue via applyStateFrame as above.
    syncPendingTutorUI();
    // Always refresh highlights — even when it's not my turn — so stale
    // .card-playable classes from the previous render are cleared.
    highlightBoard();
    updateHandHighlights();
    updateNavLockState();
}

// =============================================
// Section 10b: Game Interaction System
// =============================================

function clearSelection() {
    selectedHandIdx = null;
    selectedMinionId = null;
    selectedDeployPos = null;
    selectedAbilityMinionId = null;
    interactionMode = null;
    hideMinionActionMenu();
    hideDeclinePostMoveAttackButton();
}

function submitAction(actionData) {
    if (isSpectator) { console.warn('spectator cannot submit action'); return; }
    if (socket) {
        socket.emit('submit_action', actionData);
    }
    clearSelection();
}

// Get legal actions filtered by type
function getLegalByType(actionType) {
    return legalActions.filter(function(a) { return a.action_type === actionType; });
}

// Phase 14 PLAY-02: react window helpers

// True when the server has put us in a react window
function isReactWindow() {
    return gameState
        && gameState.phase === 1
        && gameState.react_player_idx === myPlayerIdx
        && legalActions
        && legalActions.length > 0;
}

// Hand indices that are legal as PLAY_REACT (action_type 5)
function getLegalReactCardIndices() {
    var indices = {};
    legalActions.forEach(function(a) {
        if (a.action_type === 5 && a.card_index != null) {
            indices[a.card_index] = true;
        }
    });
    return indices;
}

// Describe the pending opponent action for the react banner
function describePendingAction(pa) {
    if (!pa) {
        if (gameState && gameState.react_stack && gameState.react_stack.length > 0) {
            var top = gameState.react_stack[gameState.react_stack.length - 1];
            var topName = (top.card_numeric_id != null && cardDefs[top.card_numeric_id])
                ? cardDefs[top.card_numeric_id].name : 'a react card';
            return 'Opponent is responding with ' + topName;
        }
        return 'Opponent action pending';
    }
    var t = pa.action_type;
    if (t === 0) {
        if (pa.position) {
            return 'Opponent is playing a card at row ' + (pa.position[0] + 1) + ' col ' + (pa.position[1] + 1);
        }
        return 'Opponent is casting a card';
    }
    if (t === 1) {
        return 'Opponent is moving a minion';
    }
    if (t === 2) {
        if (pa.target_id != null && gameState && gameState.minions) {
            var tgt = null;
            gameState.minions.forEach(function(m) { if (m.instance_id === pa.target_id) tgt = m; });
            if (tgt) {
                var tgtName = (cardDefs[tgt.card_numeric_id]) ? cardDefs[tgt.card_numeric_id].name : 'minion';
                if (tgt.owner === myPlayerIdx) {
                    return 'Opponent is attacking your ' + tgtName;
                }
                return 'Opponent is attacking their own ' + tgtName;
            }
        }
        return 'Opponent is attacking';
    }
    if (t === 5) {
        if (gameState && gameState.react_stack && gameState.react_stack.length > 0) {
            var entry = gameState.react_stack[gameState.react_stack.length - 1];
            var rname = (entry.card_numeric_id != null && cardDefs[entry.card_numeric_id])
                ? cardDefs[entry.card_numeric_id].name : 'a react card';
            return 'Opponent is responding with ' + rname;
        }
        return 'Opponent is responding with a react card';
    }
    if (t === 6) {
        if (pa.minion_id != null && gameState && gameState.minions) {
            var src = null;
            gameState.minions.forEach(function(m) { if (m.instance_id === pa.minion_id) src = m; });
            if (src) {
                var sName = (cardDefs[src.card_numeric_id]) ? cardDefs[src.card_numeric_id].name : 'minion';
                return 'Opponent is sacrificing their ' + sName + ' for damage';
            }
        }
        return 'Opponent is sacrificing for damage';
    }
    return 'Opponent action pending';
}

// Render the react banner above the action bar
function renderReactBanner() {
    var existing = document.getElementById('react-banner');
    if (existing) existing.remove();
    if (!isReactWindow()) return;

    var banner = document.createElement('div');
    banner.id = 'react-banner';
    banner.className = 'react-banner';
    var label = document.createElement('span');
    label.className = 'react-banner-label';
    label.textContent = 'REACT WINDOW';
    var desc = document.createElement('span');
    desc.className = 'react-banner-desc';
    desc.textContent = describePendingAction(gameState.pending_action);
    banner.appendChild(label);
    banner.appendChild(desc);

    // Insert banner above the hand container
    var handEl = document.getElementById('hand-container');
    if (handEl && handEl.parentNode) {
        handEl.parentNode.insertBefore(banner, handEl);
    }
}

// Check if a specific hand card can be played to a specific position
function canPlayCardAt(handIdx, row, col) {
    return legalActions.some(function(a) {
        return a.action_type === 0 && a.card_index === handIdx
            && a.position && a.position[0] === row && a.position[1] === col;
    });
}

// Get unique deploy positions for a hand card (deduped)
function getDeployPositions(handIdx) {
    var seen = {};
    var positions = [];
    legalActions.forEach(function(a) {
        if (a.action_type === 0 && a.card_index === handIdx && a.position) {
            var key = a.position[0] + ',' + a.position[1];
            if (!seen[key]) {
                seen[key] = true;
                positions.push(a.position);
            }
        }
    });
    return positions;
}

// Get unique target positions for a hand card. If deployPos is provided,
// only return targets that go with that deploy position (for minions with on-play targeting).
function getTargetPositions(handIdx, deployPos) {
    var seen = {};
    var positions = [];
    legalActions.forEach(function(a) {
        if (a.action_type !== 0 || a.card_index !== handIdx) return;
        if (!a.target_pos) return;
        if (deployPos != null) {
            if (!a.position) return;
            if (a.position[0] !== deployPos[0] || a.position[1] !== deployPos[1]) return;
        }
        var key = a.target_pos[0] + ',' + a.target_pos[1];
        if (!seen[key]) {
            seen[key] = true;
            positions.push(a.target_pos);
        }
    });
    return positions;
}

// Find a legal action for this card matching position+target_pos
function findCardAction(handIdx, deployPos, targetPos) {
    for (var i = 0; i < legalActions.length; i++) {
        var a = legalActions[i];
        if (a.action_type !== 0 || a.card_index !== handIdx) continue;
        if (deployPos != null) {
            if (!a.position) continue;
            if (a.position[0] !== deployPos[0] || a.position[1] !== deployPos[1]) continue;
        } else {
            if (a.position) continue;
        }
        if (targetPos != null) {
            if (!a.target_pos) continue;
            if (a.target_pos[0] !== targetPos[0] || a.target_pos[1] !== targetPos[1]) continue;
        } else {
            if (a.target_pos) continue;
        }
        return a;
    }
    return null;
}

// Get unique sacrifice card indices for this card (for cards with summon_sacrifice_tribe)
function getSacrificeChoices(handIdx, deployPos, targetPos) {
    var seen = {};
    var choices = [];
    legalActions.forEach(function(a) {
        if (a.action_type !== 0 || a.card_index !== handIdx) return;
        if (a.sacrifice_card_index == null) return;
        if (deployPos != null && a.position) {
            if (a.position[0] !== deployPos[0] || a.position[1] !== deployPos[1]) return;
        }
        if (targetPos != null && a.target_pos) {
            if (a.target_pos[0] !== targetPos[0] || a.target_pos[1] !== targetPos[1]) return;
        }
        if (!seen[a.sacrifice_card_index]) {
            seen[a.sacrifice_card_index] = true;
            choices.push(a.sacrifice_card_index);
        }
    });
    return choices;
}

// Get valid move positions for a minion
function getMovePositions(minionId) {
    var positions = [];
    legalActions.forEach(function(a) {
        if (a.action_type === 1 && a.minion_id === minionId && a.position) {
            positions.push(a.position);
        }
    });
    return positions;
}

// Get available transform actions for a minion
function getTransformActions(minionId) {
    var transforms = [];
    legalActions.forEach(function(a) {
        if (a.action_type === 7 && a.minion_id === minionId && a.transform_target) {
            transforms.push(a);
        }
    });
    return transforms;
}

// Get valid attack targets for a minion
function getAttackTargets(minionId) {
    var targets = [];
    legalActions.forEach(function(a) {
        if (a.action_type === 2 && a.minion_id === minionId && a.target_id != null) {
            targets.push(a.target_id);
        }
    });
    return targets;
}

// Can this minion be sacrificed?
function canSacrifice(minionId) {
    return legalActions.some(function(a) {
        return a.action_type === 6 && a.minion_id === minionId;
    });
}

// Can this hand card be played (any legal PLAY_CARD with this index)?
function canPlayCard(handIdx) {
    return legalActions.some(function(a) {
        return a.action_type === 0 && a.card_index === handIdx;
    });
}

// Handle clicking a hand card
function onHandCardClick(handIdx) {
    if (isSpectator) return;  // spectators cannot play cards
    // Phase 14 PLAY-02: react window has its own click semantics
    if (isReactWindow()) {
        var reactAction = null;
        legalActions.forEach(function(a) {
            if (a.action_type === 5 && a.card_index === handIdx) reactAction = a;
        });
        if (reactAction) {
            var payload = { action_type: 5, card_index: handIdx };
            if (reactAction.target_pos) payload.target_pos = reactAction.target_pos;
            submitAction(payload);
        }
        return;
    }
    var isMyTurn = legalActions && legalActions.length > 0;
    if (!isMyTurn) return;

    // If already selected, deselect
    if (selectedHandIdx === handIdx && (interactionMode === 'play' || interactionMode === 'target')) {
        clearSelection();
        highlightBoard();
        updateHandHighlights();
        return;
    }

    var deployPositions = getDeployPositions(handIdx);
    var targetOnly = getTargetPositions(handIdx, null); // for magics with no deploy

    // Untargeted magic: find action with no position and no target
    var untargeted = findCardAction(handIdx, null, null);
    if (deployPositions.length === 0 && targetOnly.length === 0 && untargeted) {
        submitAction({ action_type: 0, card_index: handIdx });
        return;
    }

    // Magic with target selection: no deploy positions, only target_pos
    if (deployPositions.length === 0 && targetOnly.length > 0) {
        selectedHandIdx = handIdx;
        selectedMinionId = null;
        selectedDeployPos = null;
        interactionMode = 'target';
        highlightBoard();
        updateHandHighlights();
        return;
    }

    // Minion deployment (with or without on-play targets)
    if (deployPositions.length > 0) {
        selectedHandIdx = handIdx;
        selectedMinionId = null;
        selectedDeployPos = null;
        interactionMode = 'play';
        highlightBoard();
        updateHandHighlights();
    }
}

// Handle clicking a board cell
function onBoardCellClick(row, col) {
    if (isSpectator) return;  // spectators are read-only
    if (isReactWindow()) return;  // board clicks are inert during react window
    var isMyTurn = legalActions && legalActions.length > 0;
    if (!isMyTurn) return;

    // Phase 14.1: post-move attack-pick mode. Only valid enemy targets are
    // clickable; everything else is inert (use Decline button to exit).
    if (interactionMode === 'post_move_attack_pick') {
        var enemy = getMinionAt(row, col);
        if (!enemy) return;
        var attackerId = gameState && gameState.pending_post_move_attacker_id;
        if (attackerId == null) return;
        // Primary: trust server-provided pending_attack_valid_targets.
        var validTargets = (gameState && gameState.pending_attack_valid_targets) || [];
        var isValidTargetTile = validTargets.some(function(p) { return p[0] === row && p[1] === col; });
        // Fallback: any legal ATTACK action by the pending attacker against
        // this enemy (defensive — should always match the target list but
        // guards against desync between view_filter and legal_actions).
        var isLegalAttack = (legalActions || []).some(function(a) {
            return a.action_type === 2 && a.minion_id === attackerId && a.target_id === enemy.instance_id;
        });
        if (!isValidTargetTile && !isLegalAttack) return;
        submitAction({
            action_type: 2,
            minion_id: attackerId,
            target_id: enemy.instance_id,
        });
        return;
    }

    // Activated ability target picking (e.g. Ratchanter Summon Rat)
    if (interactionMode === 'activate_target' && selectedAbilityMinionId !== null) {
        var isLegal = (legalActions || []).some(function(a) {
            return a.action_type === 11
                && a.minion_id === selectedAbilityMinionId
                && a.target_pos && a.target_pos[0] === row && a.target_pos[1] === col;
        });
        if (isLegal) {
            submitAction({
                action_type: 11,
                minion_id: selectedAbilityMinionId,
                target_pos: [row, col],
            });
            selectedAbilityMinionId = null;
            interactionMode = null;
        }
        return;
    }

    // If we have a hand card selected for deploy
    if (interactionMode === 'play' && selectedHandIdx !== null) {
        if (canPlayCardAt(selectedHandIdx, row, col)) {
            // Check if this card has on-play targeting at this deploy position
            var targetsForDeploy = getTargetPositions(selectedHandIdx, [row, col]);
            if (targetsForDeploy.length > 0) {
                // Two-stage: deploy now locked, ask for target
                selectedDeployPos = [row, col];
                interactionMode = 'target';
                highlightBoard();
                return;
            }
            // Check for sacrifice choices (summon_sacrifice_tribe card)
            var sacChoices = getSacrificeChoices(selectedHandIdx, [row, col], null);
            if (sacChoices.length > 1) {
                selectedDeployPos = [row, col];
                showSacrificePicker(selectedHandIdx, [row, col], null, sacChoices);
                return;
            }
            // No targeting/sacrifice needed — submit now
            var payload = { action_type: 0, card_index: selectedHandIdx, position: [row, col] };
            if (sacChoices.length === 1) payload.sacrifice_card_index = sacChoices[0];
            submitAction(payload);
        }
        return;
    }

    // Target selection mode (magic targeting OR minion on-play target after deploy was picked)
    if (interactionMode === 'target' && selectedHandIdx !== null) {
        var validTarget = getTargetPositions(selectedHandIdx, selectedDeployPos).some(function(p) {
            return p[0] === row && p[1] === col;
        });
        if (validTarget) {
            // Check for sacrifice choices at this combo
            var sacChoices2 = getSacrificeChoices(selectedHandIdx, selectedDeployPos, [row, col]);
            if (sacChoices2.length > 1) {
                showSacrificePicker(selectedHandIdx, selectedDeployPos, [row, col], sacChoices2);
                return;
            }
            var payload = { action_type: 0, card_index: selectedHandIdx, target_pos: [row, col] };
            if (selectedDeployPos) payload.position = selectedDeployPos;
            if (sacChoices2.length === 1) payload.sacrifice_card_index = sacChoices2[0];
            submitAction(payload);
        }
        return;
    }

    // If we have a minion selected for move, try to move here
    if ((interactionMode === 'move' || interactionMode === 'move_attack') && selectedMinionId !== null) {
        var movePositions = getMovePositions(selectedMinionId);
        var validMove = movePositions.some(function(p) { return p[0] === row && p[1] === col; });
        if (validMove) {
            submitAction({ action_type: 1, minion_id: selectedMinionId, position: [row, col] });
            return;
        }
        // In move_attack mode, clicking a non-valid-move empty cell should not block
        // the "click own minion to reselect" path below. In pure move mode we return.
        if (interactionMode === 'move') return;
    }

    // Click on any minion — route to minion handler so the attack/target/
    // post-move-attack/reselect branches all run. Previously gated on
    // `owner === myPlayerIdx`, which made enemy clicks a dead-end in
    // interactionMode === 'attack' / 'move_attack' (Bug C).
    var minion = getMinionAt(row, col);
    if (minion) {
        onBoardMinionClick(minion);
    }
}

// Handle clicking a board minion
function onBoardMinionClick(minion) {
    if (isSpectator) return;  // spectators are read-only
    if (isReactWindow()) return;  // board clicks are inert during react window
    var isMyTurn = legalActions && legalActions.length > 0;
    if (!isMyTurn) return;

    // Phase 14.1: in post-move attack-pick mode, only enemy clicks on valid
    // target tiles are honored — selecting other minions is inert.
    if (interactionMode === 'post_move_attack_pick') {
        onBoardCellClick(minion.position[0], minion.position[1]);
        return;
    }

    // If in target-selection mode (magic with target), use this minion's position as target
    if (interactionMode === 'target' && selectedHandIdx !== null) {
        onBoardCellClick(minion.position[0], minion.position[1]);
        return;
    }

    // If in attack mode and clicking an enemy — attack it
    if ((interactionMode === 'attack' || interactionMode === 'move_attack') && selectedMinionId !== null && minion.owner !== myPlayerIdx) {
        var targets = getAttackTargets(selectedMinionId);
        if (targets.indexOf(minion.instance_id) !== -1) {
            submitAction({ action_type: 2, minion_id: selectedMinionId, target_id: minion.instance_id });
            return;
        }
    }

    // If clicking own minion — show action menu
    if (minion.owner === myPlayerIdx) {
        // If already selected, deselect
        if (selectedMinionId === minion.instance_id) {
            clearSelection();
            hideMinionActionMenu();
            highlightBoard();
            updateHandHighlights();
            return;
        }

        selectedMinionId = minion.instance_id;
        selectedHandIdx = null;
        // Don't auto-enter move/attack mode — wait for menu choice
        interactionMode = null;

        var moves = getMovePositions(minion.instance_id);
        var attacks = getAttackTargets(minion.instance_id);
        var transforms = getTransformActions(minion.instance_id);
        var canSac = canSacrifice(minion.instance_id);

        showMinionActionMenu(minion, moves, attacks, transforms, canSac);

        // Clear any stale highlights — they'll appear when a menu option is picked
        highlightBoard();
        updateHandHighlights();
    }
}

// Show a popup action menu sticking out from the selected minion's tile.
// Always shows Move/Attack/Effects/Cancel — options are disabled or hidden if not applicable.
// Uses fixed positioning anchored to the cell rect so it can't be clipped by
// .board-cell's overflow:hidden (which exists for the card-art background).
function showMinionActionMenu(minion, moves, attacks, transforms, canSac) {
    hideMinionActionMenu();
    var cell = document.querySelector('.board-cell[data-row="' + minion.position[0] + '"][data-col="' + minion.position[1] + '"]');
    if (!cell) return;
    var rect = cell.getBoundingClientRect();

    var menu = document.createElement('div');
    menu.id = 'minion-action-menu';
    menu.className = 'minion-action-menu';

    function addBtn(label, cls, handler, disabled) {
        var btn = document.createElement('button');
        btn.className = 'minion-action-btn ' + (cls || '');
        btn.textContent = label;
        if (disabled) {
            btn.disabled = true;
            btn.classList.add('disabled');
        } else {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                handler();
            });
        }
        menu.appendChild(btn);
    }

    // Move
    if (moves && moves.length > 0) {
        addBtn('Move', 'move', function() {
            interactionMode = (attacks && attacks.length > 0) ? 'move_attack' : 'move';
            hideMinionActionMenu();
            highlightBoard();
            renderActionBar();
        });
    }

    // Attack
    if (attacks && attacks.length > 0) {
        addBtn('Attack', 'attack', function() {
            interactionMode = 'attack';
            hideMinionActionMenu();
            highlightBoard();
            renderActionBar();
        });
    }

    // Activated ability (e.g. Ratchanter "Summon Rat (1)")
    var minionCard = cardDefs[minion.card_numeric_id];
    var ability = minionCard && minionCard.activated_ability;
    if (ability) {
        var myMana = (gameState && gameState.players && gameState.players[myPlayerIdx])
            ? gameState.players[myPlayerIdx].current_mana : 0;
        var abilityActions = (legalActions || []).filter(function(a) {
            return a.action_type === 11 && a.minion_id === minion.instance_id;
        });
        var canActivate = myMana >= ability.mana_cost && abilityActions.length > 0;
        addBtn(ability.name + ' (' + ability.mana_cost + ')', 'ability', function() {
            hideMinionActionMenu();
            if (ability.target === 'none') {
                // Untargeted self-ability -- submit directly.
                submitAction({
                    action_type: 11,
                    minion_id: minion.instance_id,
                    target_pos: null,
                });
                return;
            }
            selectedAbilityMinionId = minion.instance_id;
            interactionMode = 'activate_target';
            highlightBoard();
            renderActionBar();
        }, !canActivate);
    }

    // Effects: Sacrifice + Transform options (only if any apply)
    if (canSac) {
        addBtn('Sacrifice for damage', 'sacrifice', function() {
            submitAction({ action_type: 6, minion_id: minion.instance_id });
        });
    }
    if (transforms && transforms.length > 0) {
        // Look up the SOURCE minion's card def so we can read the per-target
        // transform cost from `transform_options` (the engine charges this,
        // NOT the target card's base mana_cost). Without this, the menu used
        // to display the target's BASE cost which often differed from the
        // actual transform cost, confusing the player about affordability.
        var sourceCard = cardDefs[minion.card_numeric_id];
        var transformCostByTarget = {};
        if (sourceCard && sourceCard.transform_options) {
            sourceCard.transform_options.forEach(function(opt) {
                transformCostByTarget[opt.target] = opt.mana_cost;
            });
        }
        transforms.forEach(function(t) {
            var targetCard = null;
            for (var nid in cardDefs) {
                if (cardDefs[nid].card_id === t.transform_target) { targetCard = cardDefs[nid]; break; }
            }
            var name = targetCard ? targetCard.name : t.transform_target;
            var cost = transformCostByTarget[t.transform_target];
            if (cost == null) cost = targetCard ? targetCard.mana_cost : '?';
            addBtn('Transform → ' + name + ' (' + cost + ')', 'transform', function() {
                submitAction({
                    action_type: 7,
                    minion_id: minion.instance_id,
                    transform_target: t.transform_target,
                });
            });
        });
    }

    // Cancel — always present
    addBtn('Cancel', 'cancel', function() {
        clearSelection();
        hideMinionActionMenu();
        highlightBoard();
        updateHandHighlights();
    });

    // Append to body and position via fixed coordinates so the menu escapes
    // .board-cell's overflow:hidden clip.
    document.body.appendChild(menu);
    menu.style.left = (rect.left + rect.width / 2) + 'px';
    menu.style.top = (rect.top - 8) + 'px';
}

function hideMinionActionMenu() {
    var existing = document.getElementById('minion-action-menu');
    if (existing) existing.remove();
}

// Sacrifice picker — shown when a card requires a tribe sacrifice and there are multiple candidates
function showSacrificePicker(handIdx, deployPos, targetPos, sacChoices) {
    hideSacrificePicker();
    var myPlayer = gameState.players[myPlayerIdx];
    var modal = document.createElement('div');
    modal.id = 'sacrifice-picker';
    modal.className = 'sacrifice-picker-overlay';
    var inner = document.createElement('div');
    inner.className = 'sacrifice-picker-modal';
    var title = document.createElement('div');
    title.className = 'sacrifice-picker-title';
    title.textContent = 'Choose card to discard';
    inner.appendChild(title);
    var row = document.createElement('div');
    row.className = 'sacrifice-picker-row';
    sacChoices.forEach(function(sacIdx) {
        var cardId = myPlayer.hand[sacIdx];
        var c = cardDefs[cardId];
        if (!c) return;
        var btn = document.createElement('button');
        btn.className = 'sacrifice-picker-card';
        btn.innerHTML = '<div class="sp-name">' + c.name + '</div><div class="sp-meta">' + (c.tribe || '') + '</div>';
        btn.addEventListener('click', function() {
            var payload = { action_type: 0, card_index: handIdx, sacrifice_card_index: sacIdx };
            if (deployPos) payload.position = deployPos;
            if (targetPos) payload.target_pos = targetPos;
            hideSacrificePicker();
            submitAction(payload);
        });
        row.appendChild(btn);
    });
    inner.appendChild(row);
    var cancel = document.createElement('button');
    cancel.className = 'btn btn-secondary';
    cancel.textContent = 'Cancel';
    cancel.addEventListener('click', function() {
        hideSacrificePicker();
        clearSelection();
        highlightBoard();
        updateHandHighlights();
    });
    inner.appendChild(cancel);
    modal.appendChild(inner);
    document.body.appendChild(modal);
}

function hideSacrificePicker() {
    var existing = document.getElementById('sacrifice-picker');
    if (existing) existing.remove();
}

function getMinionAt(row, col) {
    if (!gameState || !gameState.minions) return null;
    for (var i = 0; i < gameState.minions.length; i++) {
        var m = gameState.minions[i];
        if (m.position[0] === row && m.position[1] === col) return m;
    }
    return null;
}

// Phase 14.1: post-move attack-pick mode sync. Reads server-provided
// pending_post_move_attacker_id and sets interactionMode + decline button.
function syncPendingPostMoveAttackUI() {
    var pendingId = gameState && gameState.pending_post_move_attacker_id;
    if (pendingId != null) {
        // Find the attacker minion to determine ownership; only the owner
        // (the player whose turn it is) sees the picker UI.
        var attacker = null;
        (gameState.minions || []).forEach(function(m) {
            if (m.instance_id === pendingId) attacker = m;
        });
        if (attacker && attacker.owner === myPlayerIdx) {
            interactionMode = 'post_move_attack_pick';
            selectedMinionId = pendingId;
            showDeclinePostMoveAttackButton();
            return;
        }
    }
    // Not pending (or not my pending) — make sure the button is gone.
    hideDeclinePostMoveAttackButton();
}

function showDeclinePostMoveAttackButton() {
    if (document.getElementById('decline-post-move-attack-btn')) return;
    var btn = document.createElement('button');
    btn.id = 'decline-post-move-attack-btn';
    btn.className = 'btn btn-action btn-decline-attack';
    btn.textContent = 'Decline Attack';
    btn.title = 'End the action without attacking';
    btn.addEventListener('click', function(e) {
        e.stopPropagation();
        // ActionType.DECLINE_POST_MOVE_ATTACK = 8 (Phase 14.1)
        submitAction({ action_type: 8 });
    });
    var bar = document.getElementById('hand-action-bar');
    (bar || document.body).appendChild(btn);
}

function hideDeclinePostMoveAttackButton() {
    var existing = document.getElementById('decline-post-move-attack-btn');
    if (existing) existing.remove();
}

// =============================================
// Phase 14.2: Tutor-pick modal
// =============================================

var tutorModalOpen = false;

function syncPendingTutorUI() {
    if (!gameState) {
        if (tutorModalOpen) closeTutorModal();
        hideOpponentTutoringToast();
        return;
    }
    var pendingIdx = gameState.pending_tutor_player_idx;
    if (pendingIdx == null) {
        if (tutorModalOpen) closeTutorModal();
        hideOpponentTutoringToast();
        return;
    }
    if (pendingIdx === myPlayerIdx) {
        // I'm the caster — show the picker modal.
        hideOpponentTutoringToast();
        if (!tutorModalOpen) {
            var matches = gameState.pending_tutor_matches || [];
            var deckSize = (gameState.players && gameState.players[myPlayerIdx])
                ? (gameState.players[myPlayerIdx].deck_count || 0)
                : 0;
            var totals = gameState.pending_tutor_total_copies_owned || {};
            showTutorModal(matches, deckSize, totals);
        }
    } else {
        // Opponent is choosing — passive toast, no modal.
        if (tutorModalOpen) closeTutorModal();
        showOpponentTutoringToast();
    }
}

function showTutorModal(matches, deckSize, totalCopiesByCardId) {
    closeTutorModal();
    tutorModalOpen = true;

    // Count remaining-in-deck per card_numeric_id (matches come from deck only).
    var remainingByNid = {};
    matches.forEach(function(m) {
        var k = String(m.card_numeric_id);
        remainingByNid[k] = (remainingByNid[k] || 0) + 1;
    });

    var overlay = document.createElement('div');
    overlay.className = 'tutor-modal-overlay';
    overlay.id = 'tutor-modal-overlay';

    var modal = document.createElement('div');
    modal.className = 'tutor-modal';

    var header = document.createElement('div');
    header.className = 'tutor-modal-header';
    var title = document.createElement('div');
    title.className = 'tutor-modal-title';
    title.textContent = 'Choose a card to tutor';
    var deckLine = document.createElement('div');
    deckLine.className = 'tutor-modal-deckline';
    deckLine.textContent = 'Deck: ' + deckSize + ' cards remaining';
    header.appendChild(title);
    header.appendChild(deckLine);
    modal.appendChild(header);

    var fan = document.createElement('div');
    fan.className = 'tutor-modal-cards';

    if (!matches || matches.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'tutor-modal-empty';
        empty.textContent = 'No matching cards.';
        fan.appendChild(empty);
    } else {
        matches.forEach(function(match) {
            var nid = match.card_numeric_id;
            var tile = document.createElement('div');
            tile.className = 'tutor-modal-card';
            tile.innerHTML = renderDeckBuilderCard(nid, -1);

            var key = String(nid);
            var remainingInDeck = remainingByNid[key] || 0;
            var totalOwned = (totalCopiesByCardId && totalCopiesByCardId[key]) || remainingInDeck;
            var pill = document.createElement('div');
            pill.className = 'tutor-copy-count';
            pill.textContent = remainingInDeck + ' of ' + totalOwned + ' copies remaining';
            tile.appendChild(pill);

            tile.addEventListener('click', function(e) {
                e.stopPropagation();
                // ActionType.TUTOR_SELECT = 9 (Phase 14.2). card_index reused as match index.
                submitAction({ action_type: 9, card_index: match.match_idx });
            });
            fan.appendChild(tile);
        });
    }
    modal.appendChild(fan);

    var footer = document.createElement('div');
    footer.className = 'tutor-modal-footer';
    var skipBtn = document.createElement('button');
    skipBtn.className = 'tutor-skip-button';
    skipBtn.textContent = 'Skip';
    skipBtn.title = 'Decline tutor — leave matching cards in deck';
    skipBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        // ActionType.DECLINE_TUTOR = 10 (Phase 14.2)
        submitAction({ action_type: 10 });
    });
    footer.appendChild(skipBtn);
    modal.appendChild(footer);

    overlay.appendChild(modal);
    // Block background clicks (no accidental dismiss — must Skip explicitly).
    overlay.addEventListener('click', function(e) { e.stopPropagation(); });
    document.body.appendChild(overlay);
}

function closeTutorModal() {
    var existing = document.getElementById('tutor-modal-overlay');
    if (existing) existing.remove();
    tutorModalOpen = false;
}

function showOpponentTutoringToast() {
    if (document.getElementById('opponent-tutoring-toast')) return;
    var toast = document.createElement('div');
    toast.id = 'opponent-tutoring-toast';
    toast.className = 'tutor-toast';
    toast.textContent = 'Opponent is tutoring…';
    document.body.appendChild(toast);
}

function hideOpponentTutoringToast() {
    var existing = document.getElementById('opponent-tutoring-toast');
    if (existing) existing.remove();
}

// Highlight valid board cells based on current selection
function highlightBoard() {
    document.querySelectorAll('.board-cell').forEach(function(cell) {
        cell.classList.remove('cell-valid', 'cell-attack', 'cell-selected',
                              'attack-range-footprint', 'attack-valid-target');
    });

    // Phase 14.1: post-move attack-pick layer (rendered first so the brighter
    // valid-target class can override the footprint visually).
    if (interactionMode === 'post_move_attack_pick' && gameState) {
        var rangeTiles = gameState.pending_attack_range_tiles || [];
        rangeTiles.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) cell.classList.add('attack-range-footprint');
        });
        var validTargets = gameState.pending_attack_valid_targets || [];
        validTargets.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) cell.classList.add('attack-valid-target');
        });
        // Mark the attacker's own cell as selected
        var pendingId = gameState.pending_post_move_attacker_id;
        (gameState.minions || []).forEach(function(m) {
            if (m.instance_id === pendingId) {
                var mc = document.querySelector('.board-cell[data-row="' + m.position[0] + '"][data-col="' + m.position[1] + '"]');
                if (mc) mc.classList.add('cell-selected');
            }
        });
        return;  // Skip the regular selection-driven highlighting
    }

    if (interactionMode === 'play' && selectedHandIdx !== null) {
        var positions = getDeployPositions(selectedHandIdx);
        positions.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) cell.classList.add('cell-valid');
        });
    }

    if (interactionMode === 'activate_target' && selectedAbilityMinionId !== null) {
        // Highlight the activator's tile as selected, plus every legal target
        // tile from ACTIVATE_ABILITY actions for this minion.
        (gameState.minions || []).forEach(function(m) {
            if (m.instance_id === selectedAbilityMinionId) {
                var ac = document.querySelector('.board-cell[data-row="' + m.position[0] + '"][data-col="' + m.position[1] + '"]');
                if (ac) ac.classList.add('cell-selected');
            }
        });
        (legalActions || []).forEach(function(a) {
            if (a.action_type === 11 && a.minion_id === selectedAbilityMinionId && a.target_pos) {
                var tc = document.querySelector('.board-cell[data-row="' + a.target_pos[0] + '"][data-col="' + a.target_pos[1] + '"]');
                if (tc) tc.classList.add('cell-valid');
            }
        });
    }

    if (interactionMode === 'target' && selectedHandIdx !== null) {
        // Highlight locked deploy position (if any) as selected
        if (selectedDeployPos) {
            var depCell = document.querySelector('.board-cell[data-row="' + selectedDeployPos[0] + '"][data-col="' + selectedDeployPos[1] + '"]');
            if (depCell) depCell.classList.add('cell-selected');
        }
        // Highlight target candidates in red
        var targets = getTargetPositions(selectedHandIdx, selectedDeployPos);
        targets.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) cell.classList.add('cell-attack');
        });
    }

    if (selectedMinionId !== null) {
        // Highlight minion's cell as selected
        var minion = null;
        (gameState.minions || []).forEach(function(m) { if (m.instance_id === selectedMinionId) minion = m; });
        if (minion) {
            var mCell = document.querySelector('.board-cell[data-row="' + minion.position[0] + '"][data-col="' + minion.position[1] + '"]');
            if (mCell) mCell.classList.add('cell-selected');
        }

        if (interactionMode === 'move' || interactionMode === 'move_attack') {
            var movePos = getMovePositions(selectedMinionId);
            movePos.forEach(function(p) {
                var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
                if (cell) cell.classList.add('cell-valid');
            });
        }

        if (interactionMode === 'attack' || interactionMode === 'move_attack') {
            // Bug 1 unification: render the attack-range footprint AND the
            // bright valid-target highlight, mirroring the post-move-attack
            // pick UI. Range tiles are computed client-side from the source
            // minion's card range using the same geometry as engine
            // _can_attack (action_resolver.py). This is a cosmetic / UX
            // change only — actual legal targets still come from
            // legalActions via getAttackTargets().
            var srcMinion = null;
            (gameState.minions || []).forEach(function(m) {
                if (m.instance_id === selectedMinionId) srcMinion = m;
            });
            if (srcMinion) {
                var srcCard = cardDefs[srcMinion.card_numeric_id];
                var range = (srcCard && srcCard.attack_range != null) ? srcCard.attack_range : 0;
                var sr = srcMinion.position[0], sc = srcMinion.position[1];
                for (var rr = 0; rr < 5; rr++) {
                    for (var cc = 0; cc < 5; cc++) {
                        if (rr === sr && cc === sc) continue;
                        var manhattan = Math.abs(rr - sr) + Math.abs(cc - sc);
                        var chebyshev = Math.max(Math.abs(rr - sr), Math.abs(cc - sc));
                        var orthogonal = (rr === sr || cc === sc);
                        var inRange = false;
                        if (range === 0) {
                            inRange = (manhattan === 1 && orthogonal);
                        } else {
                            // Range N: (N+1) tiles orthogonal + 1 diagonal.
                            // Mirrors action_resolver._can_attack.
                            var orthogonalInRange = orthogonal && manhattan <= range + 1;
                            var diagonalAdjacent = (chebyshev === 1 && !orthogonal);
                            inRange = orthogonalInRange || diagonalAdjacent;
                        }
                        if (inRange) {
                            var tile = document.querySelector('.board-cell[data-row="' + rr + '"][data-col="' + cc + '"]');
                            if (tile) tile.classList.add('attack-range-footprint');
                        }
                    }
                }
            }
            var atkTargets = getAttackTargets(selectedMinionId);
            (gameState.minions || []).forEach(function(m) {
                if (atkTargets.indexOf(m.instance_id) !== -1) {
                    var cell = document.querySelector('.board-cell[data-row="' + m.position[0] + '"][data-col="' + m.position[1] + '"]');
                    if (cell) {
                        cell.classList.add('cell-attack');
                        cell.classList.add('attack-valid-target');
                    }
                }
            });
        }
    }
}

// Highlight playable hand cards
function updateHandHighlights() {
    if (isReactWindow()) {
        var reactIdxMap = getLegalReactCardIndices();
        document.querySelectorAll('.card-frame-hand').forEach(function(card) {
            var idx = parseInt(card.dataset.handIdx, 10);
            card.classList.remove('card-playable', 'card-selected-hand');
            if (reactIdxMap[idx]) {
                card.classList.add('card-react-playable');
            } else {
                card.classList.remove('card-react-playable');
            }
        });
        return;
    }
    document.querySelectorAll('.card-frame-hand').forEach(function(card) {
        var idx = parseInt(card.dataset.handIdx, 10);
        card.classList.remove('card-playable', 'card-selected-hand', 'card-react-playable');
        if (selectedHandIdx === idx && (interactionMode === 'play' || interactionMode === 'target')) {
            card.classList.add('card-selected-hand');
        } else if (canPlayCard(idx)) {
            card.classList.add('card-playable');
        }
    });
}

// Render action bar (pass / draw buttons) — lives ABOVE the hand so all
// player actions (cards, draw, skip, decline) are grouped together.
function renderActionBar() {
    var slot = document.getElementById('hand-action-bar');
    // Phase 14.4: spectators have no action bar whatsoever.
    if (isSpectator) {
        if (slot) slot.innerHTML = '';
        var hintSpec = document.getElementById('how-to-play-hint');
        if (hintSpec) hintSpec.style.display = 'none';
        return;
    }
    // Preserve the decline-post-move-attack button if present (managed
    // separately); rebuild only the draw/skip buttons.
    if (slot) {
        var keep = document.getElementById('decline-post-move-attack-btn');
        slot.innerHTML = '';
        if (keep) slot.appendChild(keep);
    }
    var hint = document.getElementById('how-to-play-hint');

    var isMyTurn = legalActions && legalActions.length > 0;
    if (!isMyTurn) {
        if (hint) hint.style.display = 'none';
        return;
    }

    // Auto-skip empty react: when in REACT phase and the only legal action is PASS
    // (no react cards in hand can react to this trigger), submit PASS automatically
    if (gameState.phase === 1 && legalActions.length === 1
            && legalActions[0].action_type === 4) {
        submitAction({ action_type: 4 });
        return;
    }

    // Action bar: show Draw Card / Skip React button
    if (slot) {
        if (gameState.phase === 1) {
            // REACT phase: show Skip React button (only when player has react cards available)
            var canPass = legalActions.some(function(a) { return a.action_type === 4; });
            if (canPass) {
                var skipBtn = document.createElement('button');
                skipBtn.className = 'btn btn-action btn-pass';
                skipBtn.textContent = 'Skip React';
                skipBtn.addEventListener('click', function() {
                    submitAction({ action_type: 4 });
                });
                slot.appendChild(skipBtn);
            }
        } else {
            // ACTION phase: show Draw Card button
            // Drawing IS the action — it counts as your turn's action and ends your turn.
            var canDraw = legalActions.some(function(a) { return a.action_type === 3; });
            if (canDraw) {
                var drawBtn = document.createElement('button');
                drawBtn.className = 'btn btn-action btn-draw';
                drawBtn.textContent = 'Draw Card';
                drawBtn.title = 'Draw a card (uses your turn action)';
                drawBtn.addEventListener('click', function() {
                    submitAction({ action_type: 3 });
                });
                slot.appendChild(drawBtn);
            }
        }

        // Bug 1 unification: when a minion is selected in a standalone
        // attack/move mode (NOT the pending post-move flow, which has its
        // own Decline button), show a Cancel button so the player has a
        // clear escape from the selection. Mirrors the post-move flow's
        // affordance and makes the two attack paths feel symmetric.
        if (gameState.phase !== 1
                && selectedMinionId !== null
                && interactionMode !== 'post_move_attack_pick'
                && (interactionMode === 'attack'
                    || interactionMode === 'move'
                    || interactionMode === 'move_attack')) {
            var cancelBtn = document.createElement('button');
            cancelBtn.className = 'btn btn-action btn-decline-attack';
            cancelBtn.textContent = 'Cancel';
            cancelBtn.title = 'Deselect this minion';
            cancelBtn.addEventListener('click', function() {
                clearSelection();
                hideMinionActionMenu();
                highlightBoard();
                updateHandHighlights();
                renderActionBar();
            });
            slot.appendChild(cancelBtn);
        }
    }

    // Show the hint during ACTION phase only (not during react)
    if (hint) {
        if (gameState.phase === 1) {
            hint.style.display = 'none';
        } else {
            hint.style.display = '';
        }
    }
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

    // Phase 14.4: SPECTATING badge visibility + god-mode label.
    var specBadge = document.getElementById('spectating-badge');
    if (specBadge) {
        if (isSpectator) {
            specBadge.textContent = spectatorGodMode ? 'SPECTATING (GOD MODE)' : 'SPECTATING';
            specBadge.classList.add('visible');
        } else {
            specBadge.classList.remove('visible');
        }
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

    // Mana (banking pool — single number, not X/Y)
    var oppMana = document.getElementById('opp-mana');
    if (oppMana) {
        oppMana.textContent = oppPlayer.current_mana;
    }

    // Hand count (god-mode spectator has the full hand array instead of a count)
    var oppHand = document.getElementById('opp-hand');
    if (oppHand) {
        var hc = (oppPlayer.hand_count != null)
            ? oppPlayer.hand_count
            : (oppPlayer.hand ? oppPlayer.hand.length : 0);
        oppHand.textContent = hc;
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

    // Mana (banking pool — single number, not X/Y)
    var selfMana = document.getElementById('self-mana');
    if (selfMana) {
        selfMana.textContent = myPlayer.current_mana;
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

    // Display order depends on perspective (D-03).
    // Engine truth: P1 back row = 0, P2 back row = 4. Each player should see
    // their own back row at the BOTTOM (standard TCG convention).
    // P1 (idx 0): render rows 4,3,2,1,0 top-to-bottom -> row 0 (P1 back) at bottom
    // P2 (idx 1): render rows 0,1,2,3,4 top-to-bottom -> row 4 (P2 back) at bottom
    var rowOrder = myPlayerIdx === 0
        ? [4, 3, 2, 1, 0]
        : [0, 1, 2, 3, 4];

    // Zone classification matches engine: P1 zone = rows 0,1; P2 zone = rows 3,4.
    var selfRows = myPlayerIdx === 0 ? [0, 1] : [3, 4];
    var oppRows = myPlayerIdx === 0 ? [3, 4] : [0, 1];

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

            // Phase 14.3: tag cell with the active animation class if its
            // tile key is in animatingTiles (set by the AnimationQueue).
            var animKind = animatingTiles[row + ',' + col];
            if (animKind) {
                cell.classList.add('anim-' + animKind);
            }

            // Check for minion at this position
            var minion = minionMap[row + ',' + col];
            if (minion) {
                cell.innerHTML = renderBoardMinion(minion);
                // Hover tooltip for board minions
                (function(m) {
                    cell.addEventListener('mouseenter', function() { showGameTooltip(m.card_numeric_id, this); });
                    cell.addEventListener('mouseleave', function() { hideGameTooltip(); });
                })(minion);
            }

            // Click handler for board cell
            (function(r, c) {
                cell.addEventListener('click', function() { onBoardCellClick(r, c); });
            })(row, col);

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
    var typeClass = TYPE_CSS[cardDef.card_type] || '';
    var elem = (cardDef.element !== null && cardDef.element !== undefined)
        ? ELEMENT_MAP[cardDef.element] : NEUTRAL_ELEMENT;

    var atk = (cardDef.attack || 0) + (minion.attack_bonus || 0);
    var hp = minion.current_health;

    var boardArtStyle = cardDef.card_id ? 'background-image:url(/static/art/' + cardDef.card_id + '.png);background-size:cover;background-position:center;' : '';

    // Phase 14.3 Wave 7: persistent status badges (burning / buff / debuff).
    var badges = [];
    if (minion.is_burning) {
        badges.push('<span class="minion-badge badge-burning" title="Burning">🔥</span>');
    }
    if (minion.attack_bonus > 0) {
        badges.push('<span class="minion-badge badge-buff">⬆️+' + minion.attack_bonus + '🗡️</span>');
    } else if (minion.attack_bonus < 0) {
        badges.push('<span class="minion-badge badge-debuff">⬇️' + minion.attack_bonus + '🗡️</span>');
    }
    if (minion.max_health_bonus && minion.max_health_bonus > 0) {
        badges.push('<span class="minion-badge badge-buff">⬆️+' + minion.max_health_bonus + '❤️</span>');
    }
    var badgesHtml = badges.length
        ? '<div class="minion-badges">' + badges.join('') + '</div>'
        : '';

    return '<div class="board-minion ' + ownerClass + ' ' + typeClass + '" data-numeric-id="' + minion.card_numeric_id + '" style="' + boardArtStyle + '">'
        + '<div class="board-minion-overlay"></div>'
        + '<div class="attr-circle-sm ' + elem.css + '"><span class="attr-text-sm">' + elem.name + '</span></div>'
        + '<div class="board-minion-name">' + cardDef.name + '</div>'
        + '<div class="board-minion-stats">'
        + '<span class="board-minion-atk">' + atk + '</span>'
        + '<span class="board-minion-hp">' + hp + '</span>'
        + '</div>'
        + badgesHtml
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
    var isMyTurn = legalActions && legalActions.length > 0;

    function appendHand(playerObj, label) {
        if (!playerObj || !playerObj.hand) return;
        if (label) {
            var lbl = document.createElement('div');
            lbl.className = 'spectator-hand-label';
            lbl.textContent = label;
            handEl.appendChild(lbl);
        }
        playerObj.hand.forEach(function(numericId, handIndex) {
            var mana = playerObj.current_mana;
            var cardHtml = renderHandCard(numericId, handIndex, mana, isMyTurn && !isSpectator);
            var wrapper = document.createElement('div');
            wrapper.innerHTML = cardHtml;
            if (wrapper.firstChild) {
                var cardEl = wrapper.firstChild;
                cardEl.addEventListener('mouseenter', function() { showGameTooltip(numericId, this); });
                cardEl.addEventListener('mouseleave', function() { hideGameTooltip(); });
                (function(idx) {
                    cardEl.addEventListener('click', function() { onHandCardClick(idx); });
                })(handIndex);
                handEl.appendChild(cardEl);
            }
        });
    }

    // Phase 14.4: god-mode spectators see BOTH hands; non-god spectators
    // see only the perspective player (server sends the opponent as count).
    if (isSpectator && spectatorGodMode) {
        var oppIdx = 1 - myPlayerIdx;
        appendHand(gameState.players[oppIdx], 'Player ' + (oppIdx + 1) + ' hand');
        appendHand(myPlayer, 'Player ' + (myPlayerIdx + 1) + ' hand');
    } else {
        appendHand(myPlayer, null);
    }
    // Auto-fit names and effects for hand cards
    fitHandCardNames();
    fitHandCardEffects();
}

// =============================================
// renderHandCard() -- Full YGO-style (D-05, D-06)
// =============================================

function renderHandCard(numericId, handIndex, currentMana, isMyTurn) {
    var c = cardDefs[numericId];
    if (!c) return '';
    var typeClass = TYPE_CSS[c.card_type] || '';
    var canAfford = currentMana >= c.mana_cost;
    // Dim if can't afford OR not my turn (cards aren't playable when not active)
    var dimClass = (canAfford && isMyTurn) ? '' : ' card-dimmed';
    var elem = (c.element !== null && c.element !== undefined)
        ? ELEMENT_MAP[c.element] : NEUTRAL_ELEMENT;

    var html = '<div class="card-frame card-frame-hand ' + typeClass + dimClass + '" data-hand-idx="' + handIndex + '" data-numeric-id="' + numericId + '">';
    // Mana badge (top-left)
    html += '<div class="card-mana">' + c.mana_cost + '</div>';
    // Element circle (top-right)
    html += '<div class="attr-circle ' + elem.css + '"><span class="attr-text">' + elem.name + '</span></div>';
    // Art area with overlay + name (YGO style matching deck builder)
    var handArtStyle = c.card_id ? 'background-image:url(/static/art/' + c.card_id + '.png)' : '';
    html += '<div class="card-art card-art-hand" style="' + handArtStyle + '">';
    html += '<div class="card-art-overlay"></div>';
    html += '<div class="card-name-overlay">' + c.name + '</div>';
    html += '</div>';
    // Bottom section: ATK circle | tribe+range | HP circle (minions)
    if (c.card_type === 0 && c.attack != null) {
        var tribe = c.tribe || '';
        var rangeText = (c.attack_range != null) ? (c.attack_range === 0 ? 'MELEE' : 'RANGE ' + c.attack_range) : '';
        html += '<div class="card-bottom-section">';
        html += '<div class="card-stat-atk">' + c.attack + '</div>';
        html += '<div class="card-bottom-center">';
        if (tribe) html += '<div class="card-bottom-tribe">' + tribe + '</div>';
        if (rangeText) html += '<div class="card-bottom-range">' + rangeText + '</div>';
        html += '</div>';
        html += '<div class="card-stat-hp">' + c.health + '</div>';
        html += '</div>';
    }
    // Summon sacrifice cost
    if (c.summon_sacrifice_tribe) {
        html += '<div class="card-effect-full">Cost: Discard any ' + c.summon_sacrifice_tribe + '</div>';
    }
    // Unique tag
    if (c.unique) {
        html += '<div class="card-effect-full">Unique</div>';
    }
    // Effect text (all card types)
    if (c.effects && c.effects.length > 0) {
        var desc = getEffectDescription(c.effects, c);
        html += '<div class="card-effect-full">' + desc + '</div>';
    }
    // Transform options
    if (c.transform_options && c.transform_options.length > 0) {
        var tLines = c.transform_options.map(function(opt) {
            return '(' + opt.mana_cost + ') ' + findCardNameById(opt.target);
        });
        html += '<div class="card-effect-full">Transform: ' + tLines.join(', ') + '</div>';
    }
    // React ability for multi-purpose cards
    if (c.react_condition != null && c.react_mana_cost != null) {
        var condMap = {
            0: 'Enemy plays Magic', 1: 'Enemy summons Minion', 2: 'Enemy attacks',
            3: 'Enemy plays React', 4: 'Any enemy action',
            5: 'Enemy plays any Wood', 6: 'Enemy plays any Fire', 7: 'Enemy plays any Earth',
            8: 'Enemy plays any Water', 9: 'Enemy plays any Metal', 10: 'Enemy plays any Dark',
            11: 'Enemy plays any Light', 12: 'Enemy sacrifices'
        };
        var condText = condMap[c.react_condition] || 'Enemy acts';
        var extraCond = c.react_requires_no_friendly_minions ? ' & No friendly minions' : '';
        var costText = c.react_mana_cost > 0 ? ' (' + c.react_mana_cost + ')' : '';
        html += '<div class="card-effect-full">React' + costText + ': ' + condText + extraCond + '</div>';
    }
    // Flavour text — only when the card has no other text content
    if (c.flavour_text
            && (!c.effects || c.effects.length === 0)
            && !c.activated_ability
            && c.react_condition == null
            && (!c.transform_options || c.transform_options.length === 0)) {
        html += '<div class="card-flavour">' + c.flavour_text + '</div>';
    }
    html += '</div>';
    return html;
}

// =============================================
// Section 16: renderDeckBuilderCard (already defined above in Section 7)
// Section 17: Helper -- getEffectDescription()
// =============================================

function getEffectDescription(effects, cardData) {
    if (!effects || effects.length === 0) return '';
    var isMinion = cardData && cardData.card_type === 0;
    var triggerMap = {0: isMinion ? 'Summon' : '', 1: 'Death', 2: 'Attack', 3: 'Damaged', 4: 'Move', 5: 'Passive'};
    var parts = [];
    effects.forEach(function(eff) {
        var trigger = triggerMap[eff.trigger];
        if (trigger === undefined) trigger = '';
        var prefix = trigger ? trigger + ': ' : '';
        var amount = eff.amount || 0;
        var type = eff.type;
        var desc = '';

        if (type === 0) { // Damage
            desc = prefix + 'Deal ' + amount + ' damage';
            if (eff.target === 1) desc += ' to all enemies';
        } else if (type === 1) { // Heal
            desc = prefix + 'Heal ' + amount;
        } else if (type === 2) { // Buff ATK
            desc = prefix + '+' + amount + '🗡️';
        } else if (type === 3) { // Buff HP
            desc = prefix + '+' + amount + '❤️';
        } else if (type === 4) { // Negate
            desc = prefix + 'Negate';
        } else if (type === 5) { // Deploy Self
            desc = prefix + 'Deploy';
        } else if (type === 6) { // Rally Forward
            var rallyName = (cardData && cardData.name) || 'this unit';
            desc = 'Move: Rally friendly ' + rallyName;
        } else if (type === 7) { // Promote
            if (cardData && cardData.promote_target) {
                var promoFrom = findCardNameById(cardData.promote_target);
                var promoteTribe = cardData.tribe || promoFrom;
                desc = prefix + 'Promote any ' + promoteTribe + ' to ' + (cardData.name || '?');
            } else {
                desc = prefix + 'Promote';
            }
        } else if (type === 8) { // Tutor
            if (cardData && cardData.tutor_target) {
                var tutorName = findCardNameById(cardData.tutor_target);
                desc = prefix + 'Tutor ' + tutorName;
            } else {
                desc = prefix + 'Tutor';
            }
        } else if (type === 9) { // Destroy
            desc = prefix + 'Destroy target';
        } else if (type === 10) { // Burn
            var burnTarget = {0: '', 1: ' all enemies', 2: ' adjacent enemies', 3: ''}[eff.target] || '';
            desc = prefix + 'Burn' + burnTarget;
        } else if (type === 11) { // Dark Matter Buff
            desc = 'Active: +' + amount + '🗡️ (+Dark Matter*1)';
        } else if (type === 12) { // Passive Heal
            desc = 'Passive: Heal ' + amount + ' per turn';
        } else if (type === 13) { // Leap
            desc = 'Move: Leap over enemies';
        } else if (type === 14) { // Conjure
            var conjureName = (cardData && cardData.summon_token_target) ? findCardNameById(cardData.summon_token_target) : 'a card';
            var conjureCost = (cardData && cardData.summon_token_cost) ? ' (' + cardData.summon_token_cost + ')' : '';
            desc = 'Active' + conjureCost + ': Summon ' + conjureName + ' from deck';
            if (cardData && cardData.conjure_buff === 'dark_matter') {
                desc += '. Buff all ' + conjureName + ' by Dark Matter';
            }
        } else {
            desc = prefix + 'Effect';
        }
        parts.push(desc);
    });
    return parts.join('. ');
}

function findCardNameById(cardId) {
    var defs = allCardDefs || cardDefs;
    for (var nid in defs) {
        if (defs[nid].card_id === cardId) return defs[nid].name;
    }
    return cardId; // fallback to raw id
}
