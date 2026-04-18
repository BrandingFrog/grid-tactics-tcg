/* Grid Tactics - Client-Side Game Logic
   Socket.IO integration, lobby, deck builder, and game rendering.
   Vanilla JS (no modules, no build step). */

// Stat emoji wrappers — apply a drop-shadow halo and slightly larger
// font so 🗡️ and 🤍 look consistent next to numeric text with black stroke.
var SWORD_SVG = '<svg class="stat-icon stat-icon-sword" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M11 2h2l1 10h-4l1-10z" fill="currentColor"/><rect x="7" y="12" width="10" height="2.5" rx="1" fill="currentColor"/><rect x="10" y="14.5" width="4" height="5" rx="0.5" fill="currentColor"/><path d="M10 19.5h4l-0.5 2.5h-3l-0.5-2.5z" fill="currentColor"/></svg>';
var HEART_SVG = '<svg class="stat-icon stat-icon-heart" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 21.35L10.55 20.03C5.4 15.36 2 12.27 2 8.5C2 5.41 4.42 3 7.5 3C9.24 3 10.91 3.81 12 5.08C13.09 3.81 14.76 3 16.5 3C19.58 3 22 5.41 22 8.5C22 12.27 18.6 15.36 13.45 20.03L12 21.35Z" fill="currentColor"/></svg>';
var SWORD = '<span class="stat-emoji">' + SWORD_SVG + '</span>';
var HEART = '<span class="stat-emoji">' + HEART_SVG + '</span>';

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
                    '<span class="patch-version">Patch ' + version + ' ' + channel + '</span>' +
                    (updatedStr ? ' <span class="patch-updated">· ' + updatedStr + '</span>' : '');
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
    3: { name: 'Water', color: 'rgb(25,118,210)',   css: 'attr-water' },
    4: { name: 'Metal', color: 'rgb(120,120,135)',  css: 'attr-metal' },
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

const MAX_DECK_SIZE = 40;
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

// Phase 14.6: Sandbox mode state. These live alongside (not inside) the
// live-game globals. While screen-sandbox is active, sandboxActivate()
// snapshots the live-game globals into _sandboxPreSnapshot and reassigns
// gameState/myPlayerIdx/legalActions/isSpectator/spectatorGodMode/animatingTiles
// to sandbox-owned values so the existing renderers and click handlers
// (which read from module scope) see sandbox state without touching their
// 50+ read sites. Deactivation restores from the snapshot.
let sandboxMode = false;            // true while screen-sandbox is active
let sandboxState = null;            // latest sandbox state dict (god view, raw -- never filtered)
let sandboxLegalActions = [];       // current legal actions array
let sandboxActiveViewIdx = 0;       // which player the user is "controlling" (mirrors state.active_player_idx)
let sandboxUndoDepth = 0;
let sandboxRedoDepth = 0;
let sandboxCardDefs = null;         // separate from allCardDefs to avoid lobby pollution

// Phase 14.6-03: Sandbox toolbar state
let sandboxAddTargetIdx = 0;        // which player's zone the next added card goes into
let sandboxAddZone = 'hand';        // which zone the next added card goes into
let sandboxKnownSlots = [];         // last list of server slots from sandbox_slot_list
const SANDBOX_AUTOSAVE_KEY = 'gt_sandbox_autosave_v1';
let _sandboxToolbarBound = false;

// Phase 14.6: snapshot of pre-sandbox globals for restore on screen exit
let _sandboxPreSnapshot = null;

// Game interaction state
let selectedHandIdx = null;  // index of selected hand card (for PLAY_CARD)
let selectedMinionId = null; // id of selected board minion (for MOVE/ATTACK)
let selectedDeployPos = null; // [row, col] when picking target for a minion with on-play effect
let interactionMode = null;  // 'play', 'move', 'attack', 'move_attack', 'target', 'activate_target', or null
let selectedAbilityMinionId = null; // minion whose activated ability is being targeted

// Deck builder state
let currentDeck = {};        // { numericId: count }

// Strip non-deckable cards (tokens, summons, reward cards) from a deck
// object in-place. Returns an array of removed card names for reporting.
function stripUndeckable(deckObj) {
    var defs = allCardDefs || cardDefs;
    var removed = [];
    Object.keys(deckObj).forEach(function(numId) {
        var c = defs[numId];
        if (c && c.deckable === false) {
            removed.push(c.name || c.card_id || numId);
            delete deckObj[numId];
        }
    });
    return removed;
}
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
    // Phase 14.6: Sandbox screen activation / deactivation
    if (screenId === 'screen-sandbox') {
        if (!sandboxMode) {
            sandboxActivate();
        }
        testsExit();
    } else if (screenId === 'screen-tests') {
        // Tests piggybacks on the sandbox screen DOM. We flip the sandbox
        // screen on (so the board renders + sandbox_state messages fire)
        // and then layer the tests overlay on top.
        var sbScreen = document.getElementById('screen-sandbox');
        if (sbScreen) sbScreen.classList.add('active');
        if (!sandboxMode) sandboxActivate();
        testsActivate();
    } else {
        if (sandboxMode) {
            sandboxDeactivate();
        }
        testsExit();
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
        var dot = document.getElementById('conn-dot');
        var txt = document.getElementById('conn-text');
        if (dot) dot.className = 'dot on';
        if (txt) txt.textContent = 'Connected';
        // Request card_defs for deck builder
        socket.emit('get_card_defs', {});
    });
    socket.on('disconnect', function() {
        var dot = document.getElementById('conn-dot');
        var txt = document.getElementById('conn-text');
        if (dot) dot.className = 'dot off';
        if (txt) txt.textContent = 'Disconnected';
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
    // Phase 14.6: sandbox mode socket handlers
    setupSandboxSocketHandlers();
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
// No-action fatigue nudge — fires when the player has zero legal
// actions and the engine auto-passes, dealing 5 player HP damage.
// Big skull + -5❤️ + "NO ACTION AVAILABLE" in Montserrat Black.
function triggerNoActionNudge() {
    playSfx('defeat');
    runNudge('nudge-no-action',
        '<div class="no-action-skull">💀</div>' +
        '<div class="no-action-damage">-5❤️</div>' +
        '<div class="no-action-text">NO ACTION AVAILABLE</div>',
        3000);
}

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
                    // Clean undeckable cards before sending so the server
                    // doesn't reject the whole ready-up for a stale slot.
                    var cleaned = Object.assign({}, slots[idx].cards || {});
                    var removed = stripUndeckable(cleaned);
                    if (removed.length) {
                        saveDeckSlot(idx, slots[idx].name, cleaned);
                        showLobbyStatus('Stripped non-deckable from deck: ' + removed.join(', '), 'info');
                    }
                    deckArray = getDeckAsArray(cleaned);
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
        var ready = totalCards === 40;
        opt.textContent = (ready ? '' : '⚠ ') + slot.name + ' (' + totalCards + '/40)';
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

// =============================================
// Deck code export / import
// GT2 (preferred): raw bytes [stable_id, count, stable_id, count, ...]
//                  then base64url. ~40 chars for a full 30-card deck.
// GT1 (legacy):    JSON [[card_id, count], ...] then base64url.
// Cross-platform — src/grid_tactics/deck_code.py decodes the same format.
// =============================================
var DECK_CODE_PREFIX_V2 = 'GT2:';
var DECK_CODE_PREFIX_V1 = 'GT1:';

function _b64urlEncodeBytes(bytes) {
    var s = '';
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function _b64urlDecodeBytes(b64) {
    b64 = b64.replace(/-/g, '+').replace(/_/g, '/');
    while (b64.length % 4) b64 += '=';
    var s = atob(b64);
    var out = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out;
}

function encodeDeckCode(deckObj) {
    // deckObj is { numericId: count } — look up each card's stable_id from
    // cardDefs and pack as [stable_id, count] uint8 pairs.
    var defs = allCardDefs || cardDefs;
    var entries = [];
    for (var numId in deckObj) {
        var c = deckObj[numId];
        if (!c || c <= 0) continue;
        var def = defs[numId];
        if (!def) continue;
        var sid = def.stable_id;
        if (!sid || sid <= 0 || sid > 255) {
            throw new Error('card ' + (def.card_id || numId) + ' has no valid stable_id');
        }
        if (c > 255) throw new Error('count > 255 for ' + def.card_id);
        entries.push([sid, c]);
    }
    entries.sort(function (a, b) { return a[0] - b[0]; });
    var bytes = new Uint8Array(entries.length * 2);
    for (var i = 0; i < entries.length; i++) {
        bytes[i * 2] = entries[i][0];
        bytes[i * 2 + 1] = entries[i][1];
    }
    return DECK_CODE_PREFIX_V2 + _b64urlEncodeBytes(bytes);
}

function decodeDeckCode(code) {
    if (!code || typeof code !== 'string') throw new Error('Empty deck code');
    code = code.trim();
    var defs = allCardDefs || cardDefs;

    if (code.indexOf(DECK_CODE_PREFIX_V2) === 0) {
        var bytes = _b64urlDecodeBytes(code.slice(DECK_CODE_PREFIX_V2.length));
        if (bytes.length % 2 !== 0) throw new Error('GT2 payload length must be even');
        // Build stable_id -> numericId map
        var sidToNumId = {};
        for (var nid in defs) {
            var d = defs[nid];
            if (d && d.stable_id) sidToNumId[d.stable_id] = parseInt(nid, 10);
        }
        var deck = {};
        var unknown = [];
        for (var j = 0; j < bytes.length; j += 2) {
            var sid = bytes[j];
            var cnt = bytes[j + 1];
            if (!sid || !cnt) continue;
            if (!(sid in sidToNumId)) { unknown.push(sid); continue; }
            var numId2 = sidToNumId[sid];
            deck[numId2] = (deck[numId2] || 0) + cnt;
        }
        if (unknown.length) console.warn('[deck-code] unknown stable_ids:', unknown);
        return deck;
    }

    if (code.indexOf(DECK_CODE_PREFIX_V1) === 0) {
        // Legacy JSON format — kept so old exported codes still import
        var json = atob(code.slice(DECK_CODE_PREFIX_V1.length)
            .replace(/-/g, '+').replace(/_/g, '/')
            + '==='.slice(0, (4 - code.slice(DECK_CODE_PREFIX_V1.length).length % 4) % 4));
        var entries = JSON.parse(json);
        if (!Array.isArray(entries)) throw new Error('Malformed GT1 payload');
        var cardIdToNumId = {};
        for (var nid2 in defs) {
            if (defs[nid2] && defs[nid2].card_id) cardIdToNumId[defs[nid2].card_id] = parseInt(nid2, 10);
        }
        var deckLegacy = {};
        entries.forEach(function (e) {
            var nn = cardIdToNumId[e[0]];
            if (nn != null) deckLegacy[nn] = (deckLegacy[nn] || 0) + e[1];
        });
        return deckLegacy;
    }

    throw new Error('Invalid deck code — must start with GT2: or GT1:');
}

// Show a modal for exporting or importing a deck code.
// mode: 'export' (readonly textarea + Copy button) or 'import' (editable).
function showDeckCodeModal(mode, code) {
    hideDeckCodeModal();
    var overlay = document.createElement('div');
    overlay.id = 'deck-code-modal-overlay';
    overlay.className = 'deck-code-modal-overlay';

    var panel = document.createElement('div');
    panel.className = 'deck-code-modal';

    var title = document.createElement('div');
    title.className = 'deck-code-modal-title';
    title.textContent = mode === 'export' ? 'Export Deck Code' : 'Import Deck Code';
    panel.appendChild(title);

    var hint = document.createElement('div');
    hint.className = 'deck-code-modal-hint';
    hint.textContent = mode === 'export'
        ? 'Share this code to let others import your deck.'
        : 'Paste a deck code (GT2: or GT1:) below.';
    panel.appendChild(hint);

    var ta = document.createElement('textarea');
    ta.className = 'deck-code-modal-textarea';
    ta.value = code || '';
    ta.readOnly = (mode === 'export');
    ta.spellcheck = false;
    ta.rows = 4;
    panel.appendChild(ta);

    var row = document.createElement('div');
    row.className = 'deck-code-modal-row';

    if (mode === 'export') {
        var btnCopy = document.createElement('button');
        btnCopy.className = 'btn btn-primary btn-sm';
        btnCopy.textContent = 'Copy to Clipboard';
        btnCopy.addEventListener('click', function() {
            var val = ta.value;
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(val).then(function() {
                    btnCopy.textContent = 'Copied ✓';
                    setTimeout(function() { btnCopy.textContent = 'Copy to Clipboard'; }, 1500);
                }, function() {
                    ta.select();
                    document.execCommand('copy');
                    btnCopy.textContent = 'Copied ✓';
                    setTimeout(function() { btnCopy.textContent = 'Copy to Clipboard'; }, 1500);
                });
            } else {
                ta.select();
                document.execCommand('copy');
                btnCopy.textContent = 'Copied ✓';
                setTimeout(function() { btnCopy.textContent = 'Copy to Clipboard'; }, 1500);
            }
        });
        row.appendChild(btnCopy);
    } else {
        var btnApply = document.createElement('button');
        btnApply.className = 'btn btn-primary btn-sm';
        btnApply.textContent = 'Import';
        btnApply.addEventListener('click', function() {
            var val = (ta.value || '').trim();
            if (!val) return;
            try {
                var deck = decodeDeckCode(val);
                var removed = stripUndeckable(deck);
                currentDeck = deck;
                renderDeckSidebar();
                if (typeof renderCardBrowser === 'function') renderCardBrowser();
                hideDeckCodeModal();
                if (removed.length) {
                    showLobbyStatus('Deck imported — stripped non-deckable: ' + removed.join(', '), 'info');
                } else {
                    showLobbyStatus('Deck imported!', 'info');
                }
            } catch (e) {
                var err = panel.querySelector('.deck-code-modal-error');
                if (!err) {
                    err = document.createElement('div');
                    err.className = 'deck-code-modal-error';
                    panel.insertBefore(err, row);
                }
                err.textContent = 'Invalid code: ' + (e && e.message ? e.message : e);
            }
        });
        row.appendChild(btnApply);
    }

    var btnClose = document.createElement('button');
    btnClose.className = 'btn btn-secondary btn-sm';
    btnClose.textContent = mode === 'export' ? 'Close' : 'Cancel';
    btnClose.addEventListener('click', hideDeckCodeModal);
    row.appendChild(btnClose);

    panel.appendChild(row);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    // Auto-select the code for quick manual copy
    setTimeout(function() {
        ta.focus();
        if (mode === 'export') ta.select();
    }, 50);

    // Escape to close
    overlay.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') hideDeckCodeModal();
    });
}

function hideDeckCodeModal() {
    var existing = document.getElementById('deck-code-modal-overlay');
    if (existing) existing.remove();
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
    // Clean wireframe design: let CSS handle font sizes
}

function fitCardNames() {
    // Clean wireframe design: overflow handled by CSS text-overflow
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
            else if (kw === 'discard' && c.discard_cost_tribe) hasKeyword = true;
            else if (kw === 'react' && c.react_condition != null) hasKeyword = true;
            else if (kw === 'unique' && c.unique) hasKeyword = true;
            else if (kw === 'negate' && c.effects && c.effects.some(function(e) { return e.type === 4; })) hasKeyword = true;
            else if (kw === 'burn' && c.effects && c.effects.some(function(e) { return e.type === 10; })) hasKeyword = true;
            else if (kw === 'end' && c.effects && c.effects.some(function(e) { return e.trigger === 5 || e.type === 12; })) hasKeyword = true;
            else if (kw === 'draw' && c.effects && c.effects.some(function(e) { return e.type === 18; })) hasKeyword = true;
            else if (kw === 'passive' && c.effects && c.effects.some(function(e) { return e.trigger === 7; })) hasKeyword = true;
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
    'Start': 'This effect triggers at the start of the owner\'s turn, before any actions.',
    'End': 'This effect triggers at the end of the owner\'s turn, after all actions.',
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
    'Deploy': 'Summon this card onto the battlefield from your hand during a React window.',
    'Destroy': 'Remove a target minion from the board regardless of its 🤍.',
    'Transform': 'Pay mana to transform this minion into another form.',
    'Cost': 'An additional requirement or modifier that changes how much you pay to play this card.',
    'Discard': 'Send a card from your hand to the Exhaust Pile.',
    'Discarded': 'This effect triggers when this card is discarded from hand.',
    'Exhaust': 'Send a card to the Exhaust Pile from anywhere.',
    'Heal': 'Restore 🤍 to a target.',
    'Deal': 'Deal damage to a target.',
    'Burn': 'Applies Burning to affected enemies.',
    'Burning': 'A burning minion takes 5🤍 damage at Start. Burning persists until the minion dies.',
    'Dark Matter': 'A stacking resource used by Dark Mages. Buffs and costs scale with accumulated stacks.',
    'Leap': 'If blocked by an enemy, jump over to the next available tile. Cannot leap allies. If all tiles ahead are enemy-occupied, enables sacrifice.',
    'Conjure': 'Summon a card from your deck directly to the board.',
    'Revive': 'Summon a card from the Grave to the board.',
    'Draw': 'Draw cards from your deck to your hand.',
    'Passive': 'This effect is always active while the minion is on the board.',
};

// Build the shared content for a card tooltip. Both the deck-builder
// (#card-tooltip) and the in-game hover (#game-tooltip) call this so
// they stay in lockstep. Returns { name, statsHtml, bodyHtml } where:
//   name: plain text (the card name)
//   statsHtml: <span>…</span> chips for type/tribe/element/cost/atk/hp/range
//   bodyHtml: card text lines + flavour + matched keywords, all HTML
function buildCardTooltipContent(c) {
    if (!c) return { name: '', statsHtml: '', bodyHtml: '' };

    // Stats chips
    var statsHtml = '';
    var typeNames = ['Minion', 'Magic', 'React'];
    statsHtml += '<span style="color:var(--cyan)">' + (typeNames[c.card_type] || '') + '</span>';
    if (c.tribe) statsHtml += '<span>' + c.tribe + '</span>';
    var elem = (c.element !== null && c.element !== undefined) ? ELEMENT_MAP[c.element] : NEUTRAL_ELEMENT;
    statsHtml += '<span style="color:' + elem.color + '">' + elem.name + '</span>';
    statsHtml += '<span style="color:var(--cyan)">' + c.mana_cost + ' Mana</span>';
    if (c.attack != null) statsHtml += '<span style="color:var(--red)">' + c.attack + SWORD + '</span>';
    if (c.health != null) statsHtml += '<span style="color:var(--green)">' + c.health + HEART + '</span>';
    if (c.card_type === 0 && c.attack_range != null) {
        statsHtml += '<span>' + (c.attack_range === 0 ? 'Melee' : 'Range ' + c.attack_range) + '</span>';
    }

    // Card text lines (effect, activated ability, transform, react)
    var cardTextLines = [];
    var effectDesc = (c.effects && c.effects.length > 0) ? getEffectDescription(c.effects, c) : '';
    if (c.discard_cost_tribe) {
        var sacCount = c.discard_cost_count || 1;
        if (c.discard_cost_tribe === 'any') {
            cardTextLines.push('Cost: Discard ' + (sacCount > 1 ? sacCount + ' cards' : 'a card'));
        } else {
            cardTextLines.push('Cost: Discard any ' + (sacCount > 1 ? sacCount + ' ' : '') + c.discard_cost_tribe + (sacCount > 1 ? 's' : ''));
        }
    }
    if (c.unique) cardTextLines.push('Unique');
    if (c.cost_reduction === 'dark_matter') cardTextLines.push('Cost: Reduce mana cost by ' + _dmTokenLive());
    if (c.play_condition === 'discarded_last_turn') cardTextLines.push('Cost: Discard last turn');
    if (c.hp_cost) cardTextLines.push('Cost: Deal ' + c.hp_cost + HEART + ' to own face');
    if (effectDesc) cardTextLines.push(effectDesc);
    if (c.activated_ability) {
        var ab = c.activated_ability;
        var abDesc = ab.mana_cost > 0 ? 'Active (' + ab.mana_cost + '): ' : 'Active: ';
        if (ab.effect_type === 'conjure_rat_and_buff') {
            abDesc += 'Conjure Common Rat. Ally Rats gain ' + _dmTokenLive() + SWORD + HEART + '.';
        } else if (ab.effect_type === 'dark_matter_buff') {
            abDesc += 'Target gains ' + _dmTokenLive() + SWORD + '.';
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
            0: 'Magic or React', 1: 'Summon', 2: 'Attack',
            3: 'Magic or React', 4: 'Any action',
            5: 'Wood', 6: 'Fire', 7: 'Earth',
            8: 'Water', 9: 'Metal', 10: 'Dark',
            11: 'Light', 12: 'Sacrifice', 13: 'Discard',
            14: 'End of turn'
        };
        var condText = condMap[c.react_condition] || 'Enemy acts';
        var extraCond = c.react_requires_no_friendly_minions ? ' while no allies' : '';
        var costText = c.react_mana_cost > 0 ? ' (' + c.react_mana_cost + ')' : '';
        var reactEffectTooltip = '';
        if (c.react_effect && c.react_effect.type === 5) {
            reactEffectTooltip = ' ▶ Summon';
        } else if (c.react_effect) {
            reactEffectTooltip = ' ▶ ' + getEffectDescription([c.react_effect], c);
        } else if (c.effects && c.effects.length > 0) {
            reactEffectTooltip = ' ▶ ' + getEffectDescription(c.effects, c);
        }
        cardTextLines.push('React' + costText + ': ' + condText + extraCond + reactEffectTooltip);
    }

    var bodyHtml = '';
    if (cardTextLines.length > 0) {
        bodyHtml += '<div class="tooltip-text">' + cardTextLines.join('<br>') + '</div>';
    }
    if (c.flavour_text) {
        bodyHtml += '<div class="tooltip-flavour">"' + c.flavour_text + '"</div>';
    }

    // Matched keywords — helper to avoid duplicates
    var matchedKeywords = [];
    function addKw(kw) { if (matchedKeywords.indexOf(kw) === -1) matchedKeywords.push(kw); }

    // Card-level keywords
    if (c.unique) addKw('Unique');
    if (c.card_type === 0 && c.attack_range != null && c.attack_range === 0) addKw('Melee');
    if (c.card_type === 0 && c.attack_range != null && c.attack_range > 0) addKw('Range');
    if (c.discard_cost_tribe) { addKw('Cost'); addKw('Exhaust'); }
    if (c.cost_reduction) { addKw('Cost'); addKw('Dark Matter'); }
    if (c.transform_options && c.transform_options.length > 0) addKw('Transform');
    if (c.react_condition != null) addKw('React');
    if (c.react_condition != null && c.react_effect && c.react_effect.type === 5) addKw('Summon');

    // Activated ability keywords
    if (c.activated_ability) {
        addKw('Active');
        var abType = c.activated_ability.effect_type || '';
        if (abType.indexOf('conjure') !== -1) addKw('Conjure');
        if (abType.indexOf('dark_matter') !== -1 || abType.indexOf('buff') !== -1) addKw('Dark Matter');
    }

    // Effect-level keywords
    var skipSummon = false;
    if (c.effects) { c.effects.forEach(function(eff) { if (eff.type === 11) skipSummon = true; }); }
    if (c.effects && c.effects.length > 0) {
        c.effects.forEach(function(eff) {
            // Triggers
            if (eff.trigger === 0 && c.card_type === 0 && !skipSummon) addKw('Summon');
            if (eff.trigger === 1) addKw('Death');
            if (eff.trigger === 2) addKw('Attack');
            if (eff.trigger === 3) addKw('Damaged');
            if (eff.trigger === 4) addKw('Move');
            if (eff.trigger === 5) addKw('End');
            if (eff.trigger === 6) addKw('Discarded');
            // Effect types
            if (eff.type === 0) { addKw('Deal'); if (eff.scale_with === 'dark_matter') addKw('Dark Matter'); }
            if (eff.type === 1) addKw('Heal');
            if (eff.type === 3) addKw('Heal');
            if (eff.type === 4) addKw('Negate');
            if (eff.type === 5) addKw('Summon');
            if (eff.type === 6) addKw('Rally');
            if (eff.type === 7) addKw('Promote');
            if (eff.type === 8) addKw('Tutor');
            if (eff.type === 9) addKw('Destroy');
            if (eff.type === 10) addKw('Burn');
            if (eff.type === 11) { addKw('Active'); addKw('Dark Matter'); }
            if (eff.type === 12) { addKw('End'); addKw('Heal'); }
            if (eff.type === 13) addKw('Leap');
            if (eff.type === 14) addKw('Conjure');
            if (eff.type === 15) addKw('Burning');
            if (eff.type === 16) addKw('Dark Matter');
            if (eff.type === 17) addKw('Revive');
            if (eff.type === 18) addKw('Draw');
            if (eff.type === 19) { addKw('Passive'); addKw('Burn'); }
            if (eff.trigger === 7) addKw('Passive');
        });
    }
    matchedKeywords.forEach(function(kw) {
        bodyHtml += '<div class="tooltip-keyword"><span class="tooltip-keyword-name">' + kw + '</span> <span class="tooltip-keyword-desc">— ' + (KEYWORD_GLOSSARY[kw] || '') + '</span></div>';
    });

    return { name: c.name, statsHtml: statsHtml, bodyHtml: bodyHtml };
}

// =============================================
// Unified tooltip renderer — populates ANY host element that has the
// standard child class structure (.tooltip-card-art, .tooltip-name,
// .tooltip-stats, .tooltip-keywords, and optionally .tooltip-related-label
// + .tooltip-related). Both #card-tooltip (deck builder) and #game-tooltip
// (in-game hover) share this exact inner structure, so one function drives
// both. Pass opts.showRelated=true to render the "Related Cards" section.
// =============================================
function populateTooltip(hostEl, numericId, opts) {
    if (!hostEl) return;
    opts = opts || {};
    var defs = allCardDefs || cardDefs;
    var c = defs[numericId];
    if (!c) return;

    hostEl.style.display = '';

    // Full card art preview — shared renderer
    var artHost = hostEl.querySelector('.tooltip-card-art');
    if (artHost) artHost.innerHTML = renderDeckBuilderCard(numericId, undefined);

    // Shared content (name, stats chips, body)
    var content = buildCardTooltipContent(c);
    var nameEl = hostEl.querySelector('.tooltip-name');
    if (nameEl) nameEl.textContent = content.name;
    var statsEl = hostEl.querySelector('.tooltip-stats');
    if (statsEl) statsEl.innerHTML = content.statsHtml;
    var bodyEl = hostEl.querySelector('.tooltip-keywords');
    if (bodyEl) bodyEl.innerHTML = content.bodyHtml;

    // Related cards (deck-builder only — game tooltip omits)
    var relatedLabel = hostEl.querySelector('.tooltip-related-label');
    var relatedContainer = hostEl.querySelector('.tooltip-related');
    if (!opts.showRelated || !relatedLabel || !relatedContainer) {
        if (relatedLabel) relatedLabel.style.display = 'none';
        if (relatedContainer) relatedContainer.innerHTML = '';
        return;
    }

    var relatedIds = [];
    function addRelated(cid) { if (cid && relatedIds.indexOf(cid) === -1) relatedIds.push(cid); }

    // Forward references from this card
    if (c.tutor_target) {
        if (typeof c.tutor_target === 'string') addRelated(c.tutor_target);
    }
    if (c.promote_target) addRelated(c.promote_target);
    if (c.summon_token_target) addRelated(c.summon_token_target);
    if (c.revive_card_id) addRelated(c.revive_card_id);
    if (c.transform_options) {
        c.transform_options.forEach(function(opt) { addRelated(opt.target); });
    }
    // Activated ability references
    if (c.activated_ability && c.activated_ability.summon_card_id) {
        addRelated(c.activated_ability.summon_card_id);
    }

    // Reverse references: other cards that mention this card
    for (var nid2 in defs) {
        var d = defs[nid2];
        if (d.card_id === c.card_id) continue;
        if (d.tutor_target === c.card_id) addRelated(d.card_id);
        if (d.promote_target === c.card_id) addRelated(d.card_id);
        if (d.summon_token_target === c.card_id) addRelated(d.card_id);
        if (d.revive_card_id === c.card_id) addRelated(d.card_id);
        if (d.activated_ability && d.activated_ability.summon_card_id === c.card_id) addRelated(d.card_id);
        if (d.transform_options) {
            d.transform_options.forEach(function(opt) {
                if (opt.target === c.card_id) addRelated(d.card_id);
            });
        }
        // Selector-based tutor targeting tribe
        if (d.tutor_target && typeof d.tutor_target === 'object' && d.tutor_target.tribe && c.tribe) {
            if (c.tribe.indexOf(d.tutor_target.tribe) !== -1) addRelated(d.card_id);
        }
    }

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
            if (rc.attack != null) rStats += ' | ' + rc.attack + SWORD + ' | ' + rc.health + HEART;
            if (rc.attack_range != null) rStats += ' | ' + (rc.attack_range === 0 ? 'Melee' : 'Range ' + rc.attack_range);
            relHtml += '<div class="tooltip-related-stats">' + rStats + '</div>';
            var rEffect = '';
            if (rc.unique) rEffect += 'Unique. ';
            if (rc.effects && rc.effects.length > 0) rEffect += getEffectDescription(rc.effects, rc);
            if (rc.activated_ability) {
                var rab = rc.activated_ability;
                var rabDesc = rab.mana_cost > 0 ? 'Active (' + rab.mana_cost + '): ' : 'Active: ';
                if (rab.effect_type === 'conjure_rat_and_buff') rabDesc += 'Conjure + DM buff';
                else if (rab.effect_type === 'dark_matter_buff') rabDesc += 'Target gains (DM)' + SWORD;
                else if (rab.effect_type === 'summon_token') rabDesc += 'Summon ' + (rab.summon_card_id || '');
                else rabDesc += rab.name || rab.effect_type;
                rEffect += rabDesc;
            }
            if (rEffect) relHtml += '<div class="tooltip-related-effect">' + rEffect + '</div>';
            relHtml += '</div></div>';
        });
        relatedContainer.innerHTML = relHtml;
    } else {
        relatedLabel.style.display = 'none';
        relatedContainer.innerHTML = '';
    }
}

// Deck-builder tooltip: includes Related Cards section.
function showCardTooltip(numericId) {
    populateTooltip(document.getElementById('card-tooltip'), numericId, { showRelated: true });
    var hint = document.getElementById('deck-tooltip-hint');
    if (hint) hint.style.display = 'none';
}

function hideCardTooltip() {
    var tooltip = document.getElementById('card-tooltip');
    if (tooltip) tooltip.style.display = 'none';
    var hint = document.getElementById('deck-tooltip-hint');
    if (hint) hint.style.display = '';
}

// =============================================
// Game Tooltip (hand cards + board minions) — same renderer, no related.
// =============================================
function showGameTooltip(numericId, anchorEl) {
    var tooltipId = sandboxMode ? 'sandbox-tooltip' : 'game-tooltip';
    var hintId = sandboxMode ? 'sandbox-tooltip-hint' : 'game-tooltip-hint';
    populateTooltip(document.getElementById(tooltipId), numericId, { showRelated: false });
    var hint = document.getElementById(hintId);
    if (hint) hint.style.display = 'none';
}

function hideGameTooltip() {
    var tooltipId = sandboxMode ? 'sandbox-tooltip' : 'game-tooltip';
    var hintId = sandboxMode ? 'sandbox-tooltip-hint' : 'game-tooltip-hint';
    var tooltip = document.getElementById(tooltipId);
    if (tooltip) tooltip.style.display = 'none';
    var hint = document.getElementById(hintId);
    if (hint) hint.style.display = '';
}

// Pin a hand card's full preview in the left tooltip sidebar on click.
// Removes pin from any previously pinned card, toggles if same card clicked.
function pinHandCardPreview(numericId, cardEl) {
    var wasPinned = cardEl.classList.contains('card-preview-pinned');
    // Unpin all
    document.querySelectorAll('.card-preview-pinned').forEach(function(el) {
        el.classList.remove('card-preview-pinned');
    });
    if (wasPinned) {
        hideGameTooltip();
        return;
    }
    // Pin this card
    cardEl.classList.add('card-preview-pinned');
    showGameTooltip(numericId, cardEl);
}

// Auto-fit for hand card names — clean wireframe: CSS handles overflow
function fitHandCardNames() {}

// Auto-fit for hand card effects — clean wireframe: CSS handles sizing
function fitHandCardEffects() {}

// =============================================
// renderCardFrame(c, opts) -- SHARED full-size card renderer
// Single source of truth for deck builder, hand, tooltip preview, and
// (Wave 5) pile modals. Returns an HTML string for a full YGO-style card.
//
// opts: {
//   context: 'deck-builder' | 'hand' | 'tooltip' | 'pile' (default 'deck-builder')
//   count:   number (deck-builder badge; -1 = prohibited/no badge variant,
//            undefined = no badge)
//   handIndex:  number (hand context; stamped as data-hand-idx)
//   numericId:  number (hand/deck-builder; stamped as data-numeric-id)
//   dim:        bool   (adds .card-dimmed — hand can't-afford/not-my-turn)
//   showReactDeploy: bool (deck-builder shows the '▶ Summon' react hint;
//                          hand suppresses it to match original behavior)
// }
// =============================================
function renderCardFrame(c, opts) {
    if (!c) return '';
    opts = opts || {};
    var context = opts.context || 'deck-builder';
    var typeClass = TYPE_CSS[c.card_type] || '';
    var elem = (c.element !== null && c.element !== undefined)
        ? ELEMENT_MAP[c.element] : NEUTRAL_ELEMENT;

    // Context class: hand context still carries .card-frame-hand so all
    // existing state selectors (.card-frame-hand.card-playable,
    // .card-selected-hand, .card-react-playable, mobile sizing) keep working.
    var contextClass = '';
    var artClass = 'card-art-full';
    if (context === 'hand') {
        contextClass = ' card-frame-hand';
        artClass = 'card-art-hand';
    } else if (context === 'pile') {
        contextClass = ' card-frame-pile';
    } else if (context === 'tooltip') {
        contextClass = ' card-frame-tooltip';
    }

    var dimClass = opts.dim ? ' card-dimmed' : '';
    var dataAttrs = '';
    if (opts.handIndex != null) dataAttrs += ' data-hand-idx="' + opts.handIndex + '"';
    if (opts.numericId != null) dataAttrs += ' data-numeric-id="' + opts.numericId + '"';

    var html = '<div class="card-frame card-frame-full ' + typeClass + contextClass + dimClass + '"' + dataAttrs + '>';
    // Art area with mana + element badges + name overlay inside
    var artStyle = c.card_id ? 'background-image:url(/static/art/' + c.card_id + '.png)' : '';
    html += '<div class="card-art ' + artClass + '" style="' + artStyle + '">';
    html += '<div class="card-mana">' + c.mana_cost + '</div>';
    html += '<div class="attr-circle ' + elem.css + '"><span class="attr-text">' + elem.name + '</span></div>';
    html += '<div class="card-name-overlay">' + c.name + '</div>';
    html += '</div>';
    // Type badge bar — show tribe for minions, card type for spells
    var isMultiPurpose = c.react_condition != null && c.react_mana_cost != null && (c.card_type === 0 || c.card_type === 1);
    var badgeText = c.card_type === 0 ? (c.tribe || 'MINION').toUpperCase() : (c.card_type === 1 ? 'MAGIC' : 'REACT');
    if (isMultiPurpose) html += '<div class="card-multi-wrapper"><div class="card-multi-half">';
    html += '<div class="card-type-badge">' + badgeText + '</div>';

    // === MINION SECTION: effects, activated, transform, flavour ===
    if (c.discard_cost_tribe) {
        var sacN = c.discard_cost_count || 1;
        if (c.discard_cost_tribe === 'any') {
            html += '<div class="card-effect-full">Cost: Discard ' + (sacN > 1 ? sacN + ' cards' : 'a card') + '</div>';
        } else {
            html += '<div class="card-effect-full">Cost: Discard any ' + (sacN > 1 ? sacN + ' ' : '') + c.discard_cost_tribe + (sacN > 1 ? 's' : '') + '</div>';
        }
    }
    if (c.unique) {
        html += '<div class="card-effect-full">Unique</div>';
    }
    if (c.cost_reduction === 'dark_matter') {
        html += '<div class="card-effect-full">Cost: Reduce mana cost by ' + _dmTokenLive() + '</div>';
    }
    if (c.play_condition === 'discarded_last_turn') {
        html += '<div class="card-effect-full">Cost: Discard last turn</div>';
    }
    if (c.hp_cost) {
        html += '<div class="card-effect-full">Cost: Deal ' + c.hp_cost + HEART + ' to own face</div>';
    }
    if (c.effects && c.effects.length > 0 && c.card_type !== 2) {
        // Skip effects block for pure REACT cards — their effects render in the react section
        var desc = getEffectDescription(c.effects, c);
        desc.split('. ').forEach(function(line) {
            if (line) html += '<div class="card-effect-full">' + line + '</div>';
        });
    }
    if (c.activated_ability) {
        var ab = c.activated_ability;
        var abDesc = ab.mana_cost > 0 ? 'Active (' + ab.mana_cost + '): ' : 'Active: ';
        if (ab.effect_type === 'conjure_rat_and_buff') {
            abDesc += 'Conjure Common Rat. Ally Rats gain ' + _dmTokenLive() + SWORD + HEART + '.';
        } else if (ab.effect_type === 'dark_matter_buff') {
            abDesc += 'Target gains ' + _dmTokenLive() + SWORD + '.';
        } else if (ab.effect_type === 'summon_token' && ab.summon_card_id) {
            abDesc += 'Summon ' + findCardNameById(ab.summon_card_id) + '.';
        } else {
            abDesc += (ab.name || ab.effect_type);
        }
        html += '<div class="card-effect-full">' + abDesc + '</div>';
    }
    if (c.transform_options && c.transform_options.length > 0) {
        var tLines = c.transform_options.map(function(opt) {
            return '(' + opt.mana_cost + ') ' + findCardNameById(opt.target);
        });
        html += '<div class="card-effect-full">Transform: ' + tLines.join(', ') + '</div>';
    }
    // Flavour text — always show if present
    if (c.flavour_text) {
        html += '<div class="card-flavour">' + c.flavour_text + '</div>';
    }

    // === REACT SECTION: condition + effect for react and multi-purpose cards ===
    if (c.react_condition != null) {
        if (isMultiPurpose) {
            html += '</div><div class="card-multi-half">';
            html += '<div class="card-type-badge card-react-bar">REACT<span class="react-mana-circle">' + c.react_mana_cost + '</span></div>';
        }
        var condMap = {
            0: 'Magic or React', 1: 'Summon', 2: 'Attack',
            3: 'Magic or React', 4: 'Any action',
            5: 'Wood', 6: 'Fire', 7: 'Earth',
            8: 'Water', 9: 'Metal', 10: 'Dark',
            11: 'Light', 12: 'Sacrifice', 13: 'Discard',
            14: 'End of turn'
        };
        var condText = condMap[c.react_condition] || 'Enemy acts';
        var extraCond = c.react_requires_no_friendly_minions ? ' while no allies' : '';
        var costText = c.react_mana_cost > 0 ? ' (' + c.react_mana_cost + ')' : '';
        var reactEffectText = '';
        if (c.react_effect && c.react_effect.type === 5) {
            reactEffectText = 'Summon';
        } else if (c.react_effect) {
            reactEffectText = getEffectDescription([c.react_effect], c);
        } else if (c.effects && c.effects.length > 0) {
            reactEffectText = getEffectDescription(c.effects, c);
        }
        html += '<div class="card-effect-full">' + condText + extraCond + (reactEffectText ? ' ▶ ' + reactEffectText : '') + '</div>';
        if (isMultiPurpose) html += '</div></div>';
    }
    // Stats row at bottom: ATK | RANGE | HP (minions only)
    if (c.card_type === 0 && c.attack != null) {
        var rangeText = (c.attack_range != null) ? (c.attack_range === 0 ? 'MELEE' : 'RANGE ' + c.attack_range) : '';
        html += '<div class="card-bottom-section">';
        html += '<div class="card-stat-atk"><span class="stat-emoji-bg">' + SWORD + '</span> <span class="stat-num">' + c.attack + '</span></div>';
        html += '<div class="card-bottom-center">';
        if (rangeText) html += '<div class="card-bottom-range">' + rangeText + '</div>';
        html += '</div>';
        html += '<div class="card-stat-hp"><span class="stat-emoji-bg">' + HEART + '</span> <span class="stat-num">' + c.health + '</span></div>';
        html += '</div>';
    }
    html += '</div>';
    // Count badge (deck-builder / tooltip contexts)
    if (opts.count != null) {
        if (opts.count === -1) {
            html += '<div class="card-count-badge prohibited">🚫</div>';
        } else {
            var badgeClass = opts.count > 0 ? 'card-count-badge' : 'card-count-badge empty';
            html += '<div class="' + badgeClass + '">x' + opts.count + '</div>';
        }
    }
    return html;
}

// Thin wrapper: deck-builder tiles / tooltip full-art previews.
function renderDeckBuilderCard(numericId, count) {
    var c = allCardDefs ? allCardDefs[numericId] : cardDefs[numericId];
    return renderCardFrame(c, {
        context: 'deck-builder',
        count: count,
        numericId: numericId,
        showReactDeploy: true,
    });
}

function renderDeckSidebar() {
    var total = getDeckTotal(currentDeck);
    var countEl = document.getElementById('deck-count');
    var statusEl = document.getElementById('deck-status');
    if (countEl) {
        countEl.textContent = total + '/40 cards';
        countEl.className = 'deck-count ' + (total === 40 ? 'valid' : 'invalid');
    }
    if (statusEl) {
        if (total === 40) {
            statusEl.textContent = 'Ready to play';
            statusEl.className = 'deck-status valid';
        } else {
            statusEl.textContent = 'Need 40 cards';
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

    // Export Code — show the code in a modal with a Copy button
    var btnExport = document.getElementById('btn-export-deck');
    if (btnExport) {
        btnExport.addEventListener('click', function() {
            try {
                var code = encodeDeckCode(currentDeck);
                showDeckCodeModal('export', code);
            } catch (e) {
                showLobbyStatus('Export failed: ' + e.message, 'error');
            }
        });
    }

    // Import Code — show a modal with a textarea to paste a code into
    var btnImport = document.getElementById('btn-import-deck');
    if (btnImport) {
        btnImport.addEventListener('click', function() {
            showDeckCodeModal('import', '');
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
                var removed = stripUndeckable(currentDeck);
                if (removed.length) {
                    // Persist the cleaned deck back to localStorage so the
                    // stale entries don't reappear on the next load.
                    saveDeckSlot(currentSlotIdx, slots[idx].name, currentDeck);
                    showLobbyStatus('Stripped non-deckable cards: ' + removed.join(', '), 'info');
                }
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
        opt.textContent = slot.name + ' (' + getDeckTotal(slot.cards) + '/40)';
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
    setupPileHandlers();
});

// =============================================
// Phase 14.5 Wave 5: Pile UI (grave / exhaust viewer + opp hand row)
// =============================================

// Shared modal for all four pile buttons. Renders every card in the pile as
// a full YGO-style frame via renderCardFrame(context: 'pile').
// Phase 14.6-03: Optional third arg `sandboxCtx = { pileType, playerIdx }`
// injects a "Move to..." button into each card cell when sandboxMode is true.
function showPileModal(title, cardNumericIds, sandboxCtx) {
    var modal = document.getElementById('pileModal');
    var titleEl = document.getElementById('pileModalTitle');
    var grid = document.getElementById('pileModalGrid');
    if (!modal || !titleEl || !grid) return;
    titleEl.textContent = title || 'Pile';
    grid.innerHTML = '';
    var ids = cardNumericIds || [];
    if (ids.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'pile-grid-empty';
        empty.textContent = 'Empty.';
        grid.appendChild(empty);
    } else {
        ids.forEach(function(nid) {
            var c = (allCardDefs && allCardDefs[nid]) || cardDefs[nid];
            if (!c) return;
            var cell = document.createElement('div');
            cell.className = 'pile-grid-cell';
            cell.innerHTML = renderCardFrame(c, {
                context: 'pile',
                numericId: nid,
                showReactDeploy: false
            });
            // Phase 14.6-03: Move-to button in sandbox mode
            if (sandboxMode && sandboxCtx && typeof makeSandboxMoveButton === 'function') {
                var pileType = sandboxCtx.pileType;
                var srcZone;
                if (pileType === 'graveyard') srcZone = 'graveyard';
                else if (pileType === 'exhaust') srcZone = 'exhaust';
                else srcZone = 'deck_top';
                cell.appendChild(makeSandboxMoveButton(sandboxCtx.playerIdx, nid, srcZone));
            }
            grid.appendChild(cell);
        });
    }
    modal.style.display = 'flex';
}

function hidePileModal() {
    var modal = document.getElementById('pileModal');
    if (modal) modal.style.display = 'none';
}

// Render N face-down card backs in the opp hand row. Count-only, no identities.
function renderOppHandRow(count) {
    var row = document.getElementById('oppHandRow');
    if (!row) return;
    row.innerHTML = '';
    var n = count | 0;
    for (var i = 0; i < n; i++) {
        var back = document.createElement('div');
        back.className = 'opp-hand-card-back';
        back.style.setProperty('--i', i);
        back.style.setProperty('--n', n);
        row.appendChild(back);
    }
}

// Update the 4 pile button counts from the current gameState.
function updatePileButtonCounts() {
    if (!gameState || !gameState.players || myPlayerIdx == null) return;
    var me = gameState.players[myPlayerIdx];
    var opp = gameState.players[1 - myPlayerIdx];
    function setCount(id, n) {
        var btn = document.getElementById(id);
        if (!btn) return;
        var countEl = btn.querySelector('.pile-count');
        if (countEl) countEl.textContent = n | 0;
    }
    setCount('pileBtnOwnGrave', (me && me.grave) ? me.grave.length : 0);
    setCount('pileBtnOwnExhaust',   (me && me.exhaust)   ? me.exhaust.length   : 0);
    setCount('pileBtnOppGrave', (opp && opp.grave) ? opp.grave.length : 0);
    setCount('pileBtnOppExhaust',   (opp && opp.exhaust)   ? opp.exhaust.length   : 0);
}

function setupPileHandlers() {
    function bind(id, titleFn, idsFn) {
        var btn = document.getElementById(id);
        if (!btn) return;
        btn.addEventListener('click', function() {
            if (!gameState || !gameState.players || myPlayerIdx == null) return;
            showPileModal(titleFn(), idsFn() || []);
        });
    }
    bind('pileBtnOwnGrave',
        function() { return 'Your Grave'; },
        function() { return gameState.players[myPlayerIdx].grave; });
    bind('pileBtnOwnExhaust',
        function() { return 'Your Exhaust'; },
        function() { return gameState.players[myPlayerIdx].exhaust; });
    bind('pileBtnOppGrave',
        function() { return "Opponent's Grave"; },
        function() { return gameState.players[1 - myPlayerIdx].grave; });
    bind('pileBtnOppExhaust',
        function() { return "Opponent's Exhaust"; },
        function() { return gameState.players[1 - myPlayerIdx].exhaust; });

    var closeBtn = document.getElementById('pileModalClose');
    if (closeBtn) closeBtn.addEventListener('click', hidePileModal);
    var modal = document.getElementById('pileModal');
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) hidePileModal();
        });
    }
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            var m = document.getElementById('pileModal');
            if (m && m.style.display !== 'none') hidePileModal();
        }
    });
}

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
        case 'draw_own':
            playDrawOwnAnimation(job, done);
            return;
        case 'draw_opp':
            playDrawOppAnimation(job, done);
            return;
        case 'card_fly':
            playCardFlyAnimation(job, done);
            return;
        case 'hp_damage_popup':
            playHpDamagePopup(job, done);
            return;
        case 'sacrifice_transcend':
            playSacrificeTranscendAnimation(job, done);
            return;
        case 'noop':
        default:
            setTimeout(done, 0);
            return;
    }
}

// =============================================
// Phase 14.5 Wave 6: Card-draw animations
// =============================================
// Two pure-visual job types that run via the Phase 14.3 AnimationQueue:
//   draw_own — card flies from a source point into its hand slot (~600ms)
//   draw_opp — face-down card back pops into #oppHandRow           (~400ms)
//
// Both jobs assume state has ALREADY been applied before they run
// (job.stateApplied === true is set at enqueue time). Targets are resolved
// lazily at animation time so we read the live post-render DOM.
//
// Job shape (draw_own):
//   { type:'draw_own', cardNumericId:<int>, fromPos:'deck'|'center'|{x,y},
//     toSlotIndex:<int>, stateApplied:true }
// Job shape (draw_opp):
//   { type:'draw_opp', stateApplied:true }

function _resolveDrawFromPoint(fromPos) {
    // 'deck' → own deck pile button (closest thing to a deck visual);
    // 'center' → viewport center fallback;
    // {x,y} → absolute coords.
    if (fromPos && typeof fromPos === 'object' && typeof fromPos.x === 'number') {
        return { x: fromPos.x, y: fromPos.y };
    }
    if (fromPos === 'deck') {
        // No dedicated deck pile DOM yet; use the own grave pile button
        // as a proxy origin (sits on the self info bar, visually "off-board").
        var btn = document.getElementById('pileBtnOwnGrave');
        if (btn) {
            var r = btn.getBoundingClientRect();
            return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
        }
    }
    // Default: viewport center.
    return { x: window.innerWidth / 2, y: window.innerHeight / 2 };
}

function playDrawOwnAnimation(job, done) {
    var handEl = document.getElementById('hand-container');
    if (!handEl) { setTimeout(done, 0); return; }
    var slotIdx = (job && typeof job.toSlotIndex === 'number') ? job.toSlotIndex : -1;
    var slotEl = slotIdx >= 0
        ? handEl.querySelector('.card-frame-hand[data-hand-idx="' + slotIdx + '"]')
        : null;
    // Fallback: last child of hand-container.
    if (!slotEl) {
        var cards = handEl.querySelectorAll('.card-frame-hand');
        if (cards.length > 0) slotEl = cards[cards.length - 1];
    }
    if (!slotEl) { setTimeout(done, 0); return; }

    var def = cardDefs && cardDefs[job.cardNumericId];
    if (!def) { setTimeout(done, 0); return; }

    var toRect = slotEl.getBoundingClientRect();
    var toCx = toRect.left + toRect.width / 2;
    var toCy = toRect.top + toRect.height / 2;
    var from = _resolveDrawFromPoint(job.fromPos);

    // Build a floating clone of the hand card at the target position.
    var floater = document.createElement('div');
    floater.className = 'draw-fly-in';
    floater.style.left = (toRect.left) + 'px';
    floater.style.top = (toRect.top) + 'px';
    floater.style.width = toRect.width + 'px';
    floater.style.height = toRect.height + 'px';
    // Starting transform offset (source → target delta), set as CSS vars
    // consumed by the keyframes.
    var dx = from.x - toCx;
    var dy = from.y - toCy;
    floater.style.setProperty('--draw-fly-dx', dx + 'px');
    floater.style.setProperty('--draw-fly-dy', dy + 'px');
    floater.innerHTML = renderCardFrame(def, {
        context: 'hand',
        numericId: job.cardNumericId,
        interactive: false,
        showReactDeploy: false,
    });
    document.body.appendChild(floater);

    // Hide the real slot until the floater lands, so we don't double-render.
    slotEl.style.visibility = 'hidden';

    playSfx('card_play');

    var finished = false;
    function finish() {
        if (finished) return;
        finished = true;
        if (floater.parentNode) floater.parentNode.removeChild(floater);
        slotEl.style.visibility = '';
        done();
    }
    floater.addEventListener('animationend', finish);
    // Fallback timeout in case animationend is swallowed (e.g. tab hidden).
    setTimeout(finish, 800);
}

function playDrawOppAnimation(job, done) {
    var row = document.getElementById('oppHandRow');
    if (!row) { setTimeout(done, 0); return; }
    // State has already been applied, so renderOppHandRow just added a new
    // .opp-hand-card-back at the end. Stamp the pop-in class on the LAST
    // child and let the keyframe fire.
    var backs = row.querySelectorAll('.opp-hand-card-back');
    if (backs.length === 0) { setTimeout(done, 0); return; }
    var target = backs[backs.length - 1];
    target.classList.add('pop-in');

    var finished = false;
    function finish() {
        if (finished) return;
        finished = true;
        target.classList.remove('pop-in');
        done();
    }
    target.addEventListener('animationend', finish);
    setTimeout(finish, 600);
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

    // Fatigue nudge: if either player's fatigue_counts just incremented,
    // trigger the NO ACTION AVAILABLE overlay on the fatigued player's screen.
    try {
        if (prevState && prevState.fatigue_counts && frame && frame.fatigue_counts) {
            for (var fi = 0; fi < 2; fi++) {
                var prevFat = prevState.fatigue_counts[fi] || 0;
                var nextFat = frame.fatigue_counts[fi] || 0;
                if (nextFat > prevFat && fi === myPlayerIdx) {
                    triggerNoActionNudge();
                    break;
                }
            }
        }
    } catch (e) {}

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

    // Phase 14.5-06: detect hand-size increases (draws/tutors/conjures) and
    // build pure-visual draw animation jobs. These run AFTER state is applied
    // so their target DOM (hand slot / opp card-back) already exists.
    var drawJobs = deriveDrawJobs(prev, next);

    // Card-fly jobs (hand → grave / exhaust). Derived BEFORE apply so we can
    // capture the live hand-slot rect of each outgoing card — after
    // applyStateFrame runs, the slot is gone.
    var flyJobs = deriveCardFlyJobs(prev, next);

    // Spell-cast center stage. Detect before apply because we look at the
    // grave/react_stack diff; trigger after a short tick so the new frame
    // is on screen first.
    var spellNid = detectSpellCast(prev, next);
    if (spellNid != null) {
        setTimeout(function() { _showSpellStage(spellNid); }, 0);
    }

    var hpJobs = derivePlayerHpDeltaAnims(prev, next);

    // Non-action transitions (noop with no meaningful diff) bypass the queue
    // entirely. This keeps react-window open/close, tutor-modal open/close,
    // turn-change banners, and passive state refreshes instantaneous.
    if (!job || job.type === 'noop') {
        applyStateFrame(next, nextLegal);
        // State already applied; each draw job is pure-visual.
        for (var fi = 0; fi < flyJobs.length; fi++) {
            enqueueAnimation(flyJobs[fi]);
        }
        for (var hi = 0; hi < hpJobs.length; hi++) {
            enqueueAnimation(hpJobs[hi]);
        }
        for (var i = 0; i < drawJobs.length; i++) {
            var dj = drawJobs[i];
            dj.stateApplied = true;
            enqueueAnimation(dj);
        }
        return;
    }

    // Main action job runs first (applies state at its own rhythm). Draw
    // jobs run after with state already applied by the main branch.
    job.stateAfter = next;
    job.legalActionsAfter = nextLegal;
    enqueueAnimation(job);
    for (var fj = 0; fj < flyJobs.length; fj++) {
        enqueueAnimation(flyJobs[fj]);
    }
    for (var hj = 0; hj < hpJobs.length; hj++) {
        enqueueAnimation(hpJobs[hj]);
    }
    for (var j = 0; j < drawJobs.length; j++) {
        var dj2 = drawJobs[j];
        dj2.stateApplied = true;
        enqueueAnimation(dj2);
    }
}

// Diff player HP across a state update and enqueue a floating damage
// popup over each player whose HP dropped. Triggered for any cause
// (hp_cost spells, fatigue, minion-attack-on-player, etc.) so every
// life-total hit is visible.
function derivePlayerHpDeltaAnims(prev, next) {
    var jobs = [];
    if (!prev || !next || !prev.players || !next.players) return jobs;
    for (var i = 0; i < 2; i++) {
        var prevP = prev.players[i];
        var nextP = next.players[i];
        if (!prevP || !nextP) continue;
        if (typeof prevP.hp !== 'number' || typeof nextP.hp !== 'number') continue;
        var delta = nextP.hp - prevP.hp;
        if (delta < 0) {
            jobs.push({
                type: 'hp_damage_popup',
                playerIdx: i,
                delta: delta,
                stateApplied: true,
            });
        }
    }
    return jobs;
}

function _hpStatElementId(playerIdx) {
    if (sandboxMode) return 'sandbox-p' + playerIdx + '-hp';
    return playerIdx === myPlayerIdx ? 'self-hp' : 'opp-hp';
}

function playHpDamagePopup(job, done) {
    var el = document.getElementById(_hpStatElementId(job.playerIdx));
    if (!el) { setTimeout(done, 0); return; }
    var rect = el.getBoundingClientRect();
    var pop = document.createElement('div');
    pop.className = 'damage-popup hp-damage-popup';
    pop.style.position = 'fixed';
    pop.style.left = (rect.left + rect.width / 2 - 20) + 'px';
    pop.style.top = (rect.top - 8) + 'px';
    pop.textContent = job.delta;  // already negative (e.g. "-25")
    document.body.appendChild(pop);
    // Red flash on the HP stat to draw the eye.
    el.classList.add('hp-flash');
    var finished = false;
    function finish() {
        if (finished) return;
        finished = true;
        if (pop.parentNode) pop.parentNode.removeChild(pop);
        el.classList.remove('hp-flash');
        done();
    }
    setTimeout(finish, 950);
}

// ============================================================
// Sacrifice transcend animation: the minion morphs into a purple-
// outlined jumper silhouette, leaps toward the enemy HP display, and
// fades out. The HP damage popup fires in parallel via the normal
// derivePlayerHpDeltaAnims pipeline.
// ============================================================
var SACRIFICE_JUMPER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-50 -20 300 290" width="100%" height="100%">'
    + '<defs><filter id="sjglow" x="-50%" y="-50%" width="200%" height="200%">'
    + '<feMorphology in="SourceAlpha" operator="dilate" radius="3" result="wR"/>'
    + '<feFlood flood-color="#ffffff" result="wF"/>'
    + '<feComposite in="wF" in2="wR" operator="in" result="wL"/>'
    + '<feGaussianBlur in="wR" stdDeviation="8" result="wB"/>'
    + '<feFlood flood-color="#ffffff" result="wF2"/>'
    + '<feComposite in="wF2" in2="wB" operator="in" result="wG"/>'
    + '<feMorphology in="SourceAlpha" operator="dilate" radius="1" result="pR"/>'
    + '<feFlood flood-color="#b347ff" result="pF"/>'
    + '<feComposite in="pF" in2="pR" operator="in" result="pL"/>'
    + '<feGaussianBlur in="pR" stdDeviation="3" result="pB"/>'
    + '<feFlood flood-color="#b347ff" result="pF2"/>'
    + '<feComposite in="pF2" in2="pB" operator="in" result="pG"/>'
    + '<feMerge>'
    + '<feMergeNode in="wG"/><feMergeNode in="wG"/><feMergeNode in="wL"/>'
    + '<feMergeNode in="pG"/><feMergeNode in="pG"/><feMergeNode in="pL"/>'
    + '<feMergeNode in="SourceGraphic"/>'
    + '</feMerge></filter></defs>'
    + '<g transform="rotate(-15 100 100)" fill="#111" filter="url(#sjglow)">'
    + '<ellipse cx="100" cy="28" rx="36" ry="36"/>'
    + '<polygon points="86,52 114,52 116,74 84,74"/>'
    + '<polygon points="72,68 128,68 124,108 118,122 124,134 76,134 82,122 76,108"/>'
    + '<polygon points="86,70 29,22 15,42 76,82"/>'
    + '<circle cx="18" cy="26" r="22"/>'
    + '<polygon points="114,70 171,22 185,42 124,82"/>'
    + '<circle cx="182" cy="26" r="22"/>'
    + '<polygon points="78,132 94,132 40,198 20,184"/>'
    + '<polygon points="106,132 122,132 180,184 160,198"/>'
    + '<g transform="translate(30 191) rotate(30)"><ellipse cx="-20" cy="0" rx="32" ry="18"/></g>'
    + '<g transform="translate(170 191) rotate(-30)"><ellipse cx="20" cy="0" rx="32" ry="18"/></g>'
    + '</g></svg>'
);

// Dispatcher — picks a sacrifice animation variant based on
// window.__sacrificeVariant (set by the Tests tab when a scenario
// specifies a sacrifice_animation hint, or manually in the console).
// Default is 'shatter' — the jumper-leap-into-shard-explosion combo
// the user picked as the canonical sacrifice visual.
function playSacrificeTranscendAnimation(job, done) {
    var variant = (typeof window !== 'undefined' && window.__sacrificeVariant)
        || 'shatter';
    var impl = ({
        jumper: _playSacJumper,
        ghost:  _playSacGhostRise,
        shatter: _playSacShatter,
        portal: _playSacPortal,
    })[variant] || _playSacShatter;
    impl(job, done);
}

// Shared helpers — resolve the source tile rect and the enemy-face vector.
function _sacrificeTileContext(job) {
    var pos = job.payload && job.payload.pos;
    if (!pos) return null;
    var tile = document.querySelector(
        '.board-cell[data-row="' + pos[0] + '"][data-col="' + pos[1] + '"]');
    if (!tile) return null;
    var minionEl = tile.querySelector('.board-minion');
    var rect = (minionEl || tile).getBoundingClientRect();
    if (minionEl) minionEl.style.visibility = 'hidden';
    var enemyIdx = (pos[0] === 4) ? 1 : 0;
    var enemyHpEl = document.getElementById(_hpStatElementId(enemyIdx));
    var jumpDx = 0;
    var jumpDy = enemyIdx === 1 ? -140 : 140;
    if (enemyHpEl) {
        var hpRect = enemyHpEl.getBoundingClientRect();
        var mCx = rect.left + rect.width / 2;
        var mCy = rect.top + rect.height / 2;
        var hCx = hpRect.left + hpRect.width / 2;
        var hCy = hpRect.top + hpRect.height / 2;
        jumpDx = (hCx - mCx) * 0.45;
        jumpDy = (hCy - mCy) * 0.45;
    }
    return { rect: rect, enemyIdx: enemyIdx, jumpDx: jumpDx, jumpDy: jumpDy };
}

// A — Jumper silhouette leaps toward enemy face, fades.
function _playSacJumper(job, done) {
    var ctx = _sacrificeTileContext(job);
    if (!ctx) { setTimeout(done, 0); return; }
    var jumper = document.createElement('div');
    jumper.className = 'sacrifice-jumper sac-anim-overlay';
    jumper.style.cssText = 'position:fixed;left:' + ctx.rect.left + 'px;top:' + ctx.rect.top + 'px;width:' + ctx.rect.width + 'px;height:' + ctx.rect.height + 'px;z-index:150;pointer-events:none;transition:transform 850ms cubic-bezier(0.2,0.6,0.3,1),opacity 850ms ease-in;will-change:transform,opacity;';
    jumper.innerHTML = SACRIFICE_JUMPER_SVG;
    document.body.appendChild(jumper);
    requestAnimationFrame(function() { requestAnimationFrame(function() {
        jumper.style.transform = 'translate(' + ctx.jumpDx + 'px,' + ctx.jumpDy + 'px) scale(1.3)';
        jumper.style.opacity = '0';
    }); });
    setTimeout(function() {
        if (jumper.parentNode) jumper.parentNode.removeChild(jumper);
        done();
    }, 880);
}

// B — Ghost rise: purple ghost silhouette ascends out of the tile and
// dissolves while the original sprite tinges purple before fading.
function _playSacGhostRise(job, done) {
    var ctx = _sacrificeTileContext(job);
    if (!ctx) { setTimeout(done, 0); return; }
    var ghost = document.createElement('div');
    ghost.className = 'sac-anim-overlay sac-ghost';
    ghost.style.cssText = 'position:fixed;left:' + ctx.rect.left + 'px;top:' + ctx.rect.top + 'px;width:' + ctx.rect.width + 'px;height:' + ctx.rect.height + 'px;z-index:150;pointer-events:none;transition:transform 1000ms cubic-bezier(0.3,0,0.4,1),opacity 1000ms ease-out,filter 1000ms ease-out;will-change:transform,opacity,filter;';
    ghost.innerHTML = (
        '<div style="position:absolute;inset:0;border-radius:12px;background:radial-gradient(circle at 50% 60%, rgba(179,71,255,0.75) 0%, rgba(130,30,200,0.55) 35%, rgba(40,0,80,0.2) 65%, transparent 85%);mix-blend-mode:screen;filter:blur(2px);"></div>'
        + '<div style="position:absolute;inset:-12% 10% 30% 10%;border-radius:50%;background:radial-gradient(ellipse at 50% 40%, rgba(255,255,255,0.85) 0%, rgba(217,168,255,0.55) 35%, transparent 75%);mix-blend-mode:screen;filter:blur(3px);"></div>'
    );
    document.body.appendChild(ghost);
    requestAnimationFrame(function() { requestAnimationFrame(function() {
        ghost.style.transform = 'translate(' + (ctx.jumpDx * 0.3) + 'px,' + (ctx.jumpDy * 0.7 - 40) + 'px) scale(1.4)';
        ghost.style.opacity = '0';
        ghost.style.filter = 'blur(8px)';
    }); });
    setTimeout(function() {
        if (ghost.parentNode) ghost.parentNode.removeChild(ghost);
        done();
    }, 1050);
}

// C — Jumper-Shatter combo: white-purple flash erupts on the tile, the
// pixel-art jumper silhouette leaps toward the enemy face; mid-arc it
// explodes into 8 purple shards that continue outward and fade. The
// jumper (variant A) is absorbed into this variant as the first beat.
function _playSacShatter(job, done) {
    var ctx = _sacrificeTileContext(job);
    if (!ctx) { setTimeout(done, 0); return; }
    var cx = ctx.rect.left + ctx.rect.width / 2;
    var cy = ctx.rect.top + ctx.rect.height / 2;

    // Beat 1 — tight launch flash under the silhouette's feet. Short
    // and small: a blink rather than a burst, so the jumper reads as
    // the main visual.
    var feetY = ctx.rect.top + ctx.rect.height * 0.82;
    var flashSize = 32;
    var flash = document.createElement('div');
    flash.className = 'sac-anim-overlay sac-flash';
    flash.style.cssText = 'position:fixed;left:' + (cx - flashSize / 2) + 'px;top:' + (feetY - flashSize / 2) + 'px;width:' + flashSize + 'px;height:' + flashSize + 'px;z-index:149;pointer-events:none;border-radius:50%;background:radial-gradient(circle,rgba(255,255,255,0.95) 0%,rgba(217,168,255,0.6) 40%,transparent 75%);opacity:0;transition:opacity 70ms ease-out,transform 70ms ease-out;';
    document.body.appendChild(flash);

    // Beat 2 — jumper silhouette rises out of the flash and leaps.
    var jumper = document.createElement('div');
    jumper.className = 'sacrifice-jumper sac-anim-overlay';
    jumper.style.cssText = 'position:fixed;left:' + ctx.rect.left + 'px;top:' + ctx.rect.top + 'px;width:' + ctx.rect.width + 'px;height:' + ctx.rect.height + 'px;z-index:152;pointer-events:none;transition:transform 400ms cubic-bezier(0.2,0.6,0.3,1),opacity 400ms ease-out;will-change:transform,opacity;';
    jumper.innerHTML = SACRIFICE_JUMPER_SVG;
    document.body.appendChild(jumper);

    // Beat 3 — shards pre-built at the tile, kicked off when the jumper
    // "explodes" mid-arc. Launch position follows the jumper's mid-arc
    // delta so the explosion happens where the silhouette lands.
    var shardDx = ctx.jumpDx * 0.6;
    var shardDy = ctx.jumpDy * 0.6;
    var fragEls = [];
    var N = 8;
    for (var i = 0; i < N; i++) {
        var frag = document.createElement('div');
        var angle = (i / N) * Math.PI * 2;
        var size = 18 + Math.random() * 14;
        frag.className = 'sac-anim-overlay sac-frag';
        frag.style.cssText = 'position:fixed;left:' + (cx - size/2) + 'px;top:' + (cy - size/2) + 'px;width:' + size + 'px;height:' + size + 'px;z-index:150;pointer-events:none;background:linear-gradient(135deg,#d9a8ff 0%,#8822cc 100%);box-shadow:0 0 12px rgba(179,71,255,0.8);clip-path:polygon(20% 0%,80% 0%,100% 50%,80% 100%,20% 100%,0% 50%);opacity:0;transform:translate(' + shardDx + 'px,' + shardDy + 'px) scale(0.4);transition:transform 650ms cubic-bezier(0.2,0.6,0.3,1),opacity 650ms ease-in;will-change:transform,opacity;';
        frag._angle = angle;
        frag._finalDx = Math.cos(angle) * (110 + Math.random() * 50) + shardDx;
        frag._finalDy = Math.sin(angle) * (110 + Math.random() * 50) + shardDy;
        frag._finalRot = Math.random() * 720 - 360;
        document.body.appendChild(frag);
        fragEls.push(frag);
    }

    // A small tilt feels like momentum — pick a sign based on jump
    // direction so the rotation leans INTO the enemy face.
    var tiltMid = (ctx.jumpDx >= 0 ? 1 : -1) * 8;
    var tiltEnd = (ctx.jumpDx >= 0 ? 1 : -1) * 14;

    // Kick beat 1+2 on the next frame pair.
    requestAnimationFrame(function() { requestAnimationFrame(function() {
        flash.style.opacity = '1';
        flash.style.transform = 'scale(1.8)';
        jumper.style.transform = 'translate(' + (ctx.jumpDx * 0.6) + 'px,' + (ctx.jumpDy * 0.6) + 'px) scale(1.15) rotate(' + tiltMid + 'deg)';
    }); });

    // Fade the flash out fast — a brief blink that seeds the jump.
    setTimeout(function() {
        flash.style.opacity = '0';
        flash.style.transform = 'scale(2)';
    }, 80);

    // Mid-arc: pop the jumper, launch the shards.
    setTimeout(function() {
        jumper.style.transition = 'transform 200ms ease-out,opacity 200ms ease-out,filter 200ms ease-out';
        jumper.style.transform = 'translate(' + (ctx.jumpDx * 0.65) + 'px,' + (ctx.jumpDy * 0.65) + 'px) scale(1.45) rotate(' + tiltEnd + 'deg)';
        jumper.style.opacity = '0';
        jumper.style.filter = 'brightness(2) saturate(1.3)';
        fragEls.forEach(function(f) {
            f.style.opacity = '1';
            f.style.transform = 'translate(' + f._finalDx + 'px,' + f._finalDy + 'px) rotate(' + f._finalRot + 'deg) scale(1)';
        });
        // Fade shards on the tail.
        setTimeout(function() {
            fragEls.forEach(function(f) { f.style.opacity = '0'; });
        }, 350);
    }, 420);

    // Cleanup.
    setTimeout(function() {
        fragEls.forEach(function(f) { if (f.parentNode) f.parentNode.removeChild(f); });
        if (flash.parentNode) flash.parentNode.removeChild(flash);
        if (jumper.parentNode) jumper.parentNode.removeChild(jumper);
        done();
    }, 1150);
}

// D — Portal warp: a swirling purple ring opens beneath the minion;
// the minion spirals inward while shrinking to a point, then the portal
// closes. Uses a clone of the minion so the CSS rotation doesn't spin
// the whole board cell.
function _playSacPortal(job, done) {
    var ctx = _sacrificeTileContext(job);
    if (!ctx) { setTimeout(done, 0); return; }
    var pos = job.payload && job.payload.pos;
    var tile = document.querySelector(
        '.board-cell[data-row="' + pos[0] + '"][data-col="' + pos[1] + '"]');
    var minionEl = tile && tile.querySelector('.board-minion');

    var cx = ctx.rect.left + ctx.rect.width / 2;
    var cy = ctx.rect.top + ctx.rect.height / 2;

    // Portal ring — a purple double-ring that grows then shrinks.
    var portal = document.createElement('div');
    portal.className = 'sac-anim-overlay sac-portal';
    portal.style.cssText = 'position:fixed;left:' + (cx - 90) + 'px;top:' + (cy - 90) + 'px;width:180px;height:180px;z-index:149;pointer-events:none;border-radius:50%;border:4px solid rgba(217,168,255,0.9);box-shadow:0 0 24px rgba(179,71,255,0.8),inset 0 0 32px rgba(179,71,255,0.7);background:radial-gradient(circle,rgba(40,0,80,0.7) 0%,rgba(179,71,255,0.3) 50%,transparent 80%);opacity:0;transform:scale(0.2) rotate(0deg);transition:transform 900ms cubic-bezier(0.2,0.6,0.3,1),opacity 900ms ease-out;animation:sac-portal-spin 900ms linear;';
    document.body.appendChild(portal);

    // Clone the minion so we can spiral/shrink it without touching the real tile.
    var clone = null;
    if (minionEl) {
        clone = minionEl.cloneNode(true);
        clone.className = 'sac-anim-overlay sac-portal-clone ' + minionEl.className;
        clone.style.cssText = 'position:fixed;left:' + ctx.rect.left + 'px;top:' + ctx.rect.top + 'px;width:' + ctx.rect.width + 'px;height:' + ctx.rect.height + 'px;z-index:150;pointer-events:none;visibility:visible;transition:transform 900ms cubic-bezier(0.4,0,1,0.7),opacity 900ms ease-in;will-change:transform,opacity;';
        document.body.appendChild(clone);
    }

    requestAnimationFrame(function() { requestAnimationFrame(function() {
        portal.style.opacity = '1';
        portal.style.transform = 'scale(1) rotate(360deg)';
        if (clone) {
            clone.style.transform = 'translate(' + (ctx.jumpDx * 0.2) + 'px,' + (ctx.jumpDy * 0.2) + 'px) scale(0.05) rotate(720deg)';
            clone.style.opacity = '0';
        }
    }); });

    // Close portal (shrink + fade) after main phase.
    setTimeout(function() {
        portal.style.transition = 'transform 300ms ease-in,opacity 300ms ease-in';
        portal.style.transform = 'scale(0.1) rotate(540deg)';
        portal.style.opacity = '0';
    }, 700);

    setTimeout(function() {
        if (portal.parentNode) portal.parentNode.removeChild(portal);
        if (clone && clone.parentNode) clone.parentNode.removeChild(clone);
        done();
    }, 1050);
}

// ============================================================
// Spell-cast center stage: when a magic or react is cast, show a
// giant [card art] ▶ [? / 👍] overlay in the middle of the screen.
// After 1s of react-window idleness the ? flips to 👍 and the stage
// fades; a new react landing before then slides the current card
// off-screen to the left and brings the new one in from the right.
// ============================================================
var _spellStage = {
    currentNid: null,
    cardEl: null,
    thumbsTimer: null,
    exitTimer: null,
};

function _spellStageEls() {
    return {
        root: document.getElementById('spell-stage'),
        card: document.getElementById('spell-stage-card'),
        react: document.getElementById('spell-stage-react'),
    };
}

function _showSpellStage(numericId) {
    var els = _spellStageEls();
    if (!els.root || !els.card || !els.react) return;
    var def = (cardDefs && cardDefs[numericId]) ||
              (window.sandboxCardDefs && window.sandboxCardDefs[numericId]);
    if (!def) return;

    // Same card re-pushed — just reset timers, don't re-animate.
    if (_spellStage.currentNid === numericId && !els.root.hidden) {
        _resetSpellStageTimers();
        _armSpellStageThumbs();
        return;
    }

    _clearSpellStageTimers();

    // Slide the previous card out to the left, then bring the new one in.
    var existing = els.card.firstChild;
    if (existing) {
        existing.classList.add('exiting-left');
        var oldCard = existing;
        setTimeout(function() {
            if (oldCard.parentNode) oldCard.parentNode.removeChild(oldCard);
        }, 380);
    }

    var cardInner = document.createElement('div');
    cardInner.innerHTML = renderCardFrame(def, {
        context: 'tooltip',
        numericId: numericId,
        interactive: false,
        showReactDeploy: false,
    });
    els.card.appendChild(cardInner.firstChild);
    els.card.style.position = 'relative';

    _spellStage.currentNid = numericId;
    els.root.hidden = false;
    els.root.classList.remove('exit');
    els.root.classList.remove('enter');
    // Force a reflow then re-add for the enter animation to retrigger.
    void els.root.offsetWidth;
    els.root.classList.add('enter');

    // React slot back to waiting state.
    els.react.textContent = '?';
    els.react.classList.remove('confirmed');

    _armSpellStageThumbs();
}

function _armSpellStageThumbs() {
    _spellStage.thumbsTimer = setTimeout(function() {
        var els = _spellStageEls();
        if (!els.react) return;
        els.react.textContent = '👍';
        els.react.classList.add('confirmed');
        // Linger briefly then fade out.
        _spellStage.exitTimer = setTimeout(_hideSpellStage, 900);
    }, 1000);
}

function _resetSpellStageTimers() {
    _clearSpellStageTimers();
}

function _clearSpellStageTimers() {
    if (_spellStage.thumbsTimer) { clearTimeout(_spellStage.thumbsTimer); _spellStage.thumbsTimer = null; }
    if (_spellStage.exitTimer) { clearTimeout(_spellStage.exitTimer); _spellStage.exitTimer = null; }
}

function _hideSpellStage() {
    _clearSpellStageTimers();
    var els = _spellStageEls();
    if (!els.root) return;
    els.root.classList.add('exit');
    setTimeout(function() {
        els.root.hidden = true;
        els.root.classList.remove('exit');
        els.root.classList.remove('enter');
        if (els.card) els.card.innerHTML = '';
        _spellStage.currentNid = null;
    }, 360);
}

// Detect spell-cast events from a prev→next state transition. Fires the
// stage for any new magic/react card that just entered grave or the top
// of the react_stack. Returns the last-detected nid (for chain display).
function detectSpellCast(prev, next) {
    if (!next) return null;
    var nid = null;

    // 1) New top of react_stack → that react was just played.
    var prevStack = (prev && prev.react_stack) || [];
    var nextStack = (next && next.react_stack) || [];
    if (nextStack.length > prevStack.length) {
        var entry = nextStack[nextStack.length - 1];
        if (entry && entry.card_numeric_id != null) nid = entry.card_numeric_id;
    }

    // 2) Otherwise, compare graves for a newly-landed MAGIC/REACT card.
    if (nid == null && prev && next.players) {
        for (var i = 0; i < next.players.length; i++) {
            var prevG = (prev.players && prev.players[i] && prev.players[i].grave) || [];
            var nextG = (next.players[i] && next.players[i].grave) || [];
            if (nextG.length <= prevG.length) continue;
            // Multiset diff — which nids entered grave this step?
            var prevCnt = {};
            for (var p = 0; p < prevG.length; p++) prevCnt[prevG[p]] = (prevCnt[prevG[p]] || 0) + 1;
            for (var q = 0; q < nextG.length; q++) {
                var gid = nextG[q];
                if (prevCnt[gid] > 0) { prevCnt[gid] -= 1; continue; }
                // gid is new this step — is it magic or react?
                var def = (cardDefs && cardDefs[gid]) ||
                          (window.sandboxCardDefs && window.sandboxCardDefs[gid]);
                if (def && (def.card_type === 1 || def.card_type === 2)) {
                    nid = gid;
                    break;
                }
            }
            if (nid != null) break;
        }
    }

    return nid;
}

// Diff hand → grave / exhaust transitions and emit card_fly jobs.
// Source hand-slot rects are captured at derive time (pre-apply) so the
// ghost starts exactly where the real card was sitting when it left.
// In sandbox, both players' hands are visible, so we diff both.
function deriveCardFlyJobs(prev, next) {
    if (!prev || !next) return [];
    var indices = [];
    if (sandboxMode) indices = [0, 1];
    else if (myPlayerIdx != null) indices = [myPlayerIdx];
    var out = [];
    for (var k = 0; k < indices.length; k++) {
        out = out.concat(_deriveFlyForPlayer(prev, next, indices[k]));
    }
    return out;
}

function _deriveFlyForPlayer(prev, next, playerIdx) {
    var jobs = [];
    var prevP = prev.players && prev.players[playerIdx];
    var nextP = next.players && next.players[playerIdx];
    if (!prevP || !nextP) return jobs;
    var prevHand = prevP.hand || [];
    var nextHand = nextP.hand || [];
    if (!Array.isArray(prevHand) || !Array.isArray(nextHand)) return jobs;

    var nextCount = {};
    for (var ni = 0; ni < nextHand.length; ni++) {
        var nid2 = nextHand[ni];
        nextCount[nid2] = (nextCount[nid2] || 0) + 1;
    }
    var removed = [];
    for (var pi = 0; pi < prevHand.length; pi++) {
        var id = prevHand[pi];
        if ((nextCount[id] || 0) > 0) {
            nextCount[id] -= 1;
        } else {
            removed.push({ nid: id, slotIdx: pi });
        }
    }
    if (removed.length === 0) return jobs;

    var graveDelta = _multisetDelta(prevP.grave, nextP.grave);
    var exhaustDelta = _multisetDelta(prevP.exhaust, nextP.exhaust);

    // Hand container differs between live game and sandbox (which shows
    // both hands in distinct divs). The "own" zone identifier also depends
    // on whose hand we're tracking, so the ghost flies to the correct pile.
    var handEl;
    var ownerTag;  // zone suffix for pile lookup
    if (sandboxMode) {
        handEl = document.getElementById('sandbox-hand-p' + playerIdx);
        // Sandbox UIs map playerIdx 0 → pileBtnOwnX, 1 → pileBtnOppX so the
        // ghost lands on the right-side pile button pair (when P1 is
        // the fixed perspective) — matches renderSandbox layout.
        ownerTag = (playerIdx === 0) ? 'own' : 'opp';
    } else {
        handEl = document.getElementById(
            playerIdx === myPlayerIdx ? 'hand-container' : 'oppHandRow'
        );
        ownerTag = (playerIdx === myPlayerIdx) ? 'own' : 'opp';
    }

    for (var r = 0; r < removed.length; r++) {
        var rem = removed[r];
        var toZone = null;
        if ((exhaustDelta[rem.nid] || 0) > 0) {
            toZone = 'exhaust_' + ownerTag;
            exhaustDelta[rem.nid] -= 1;
        } else if ((graveDelta[rem.nid] || 0) > 0) {
            toZone = 'grave_' + ownerTag;
            graveDelta[rem.nid] -= 1;
        }
        if (!toZone) continue;  // went to board; summon animation handles it

        var slot = handEl
            ? handEl.querySelector('.card-frame-hand[data-hand-idx="' + rem.slotIdx + '"]')
            : null;
        var rect = slot ? slot.getBoundingClientRect() : null;
        jobs.push({
            type: 'card_fly',
            cardNumericId: rem.nid,
            fromRect: rect ? {
                left: rect.left, top: rect.top,
                width: rect.width, height: rect.height,
            } : null,
            toZone: toZone,
            stateApplied: true,
        });
    }
    return jobs;
}

function _multisetDelta(prevList, nextList) {
    var d = {};
    if (prevList) {
        for (var i = 0; i < prevList.length; i++) {
            var id = prevList[i];
            d[id] = (d[id] || 0) - 1;
        }
    }
    if (nextList) {
        for (var j = 0; j < nextList.length; j++) {
            var jd = nextList[j];
            d[jd] = (d[jd] || 0) + 1;
        }
    }
    return d;
}

function _zoneButton(zone) {
    // In sandbox, each player's piles have their own DOM ids (P1 bottom,
    // P2 top); pile-modal buttons from live mode render but are zero-sized.
    // Prefer the sandbox-specific ids when they exist AND have layout.
    if (sandboxMode) {
        var sbMap = {
            'grave_own': 'sandbox-p0-grave',
            'exhaust_own': 'sandbox-p0-exhaust',
            'grave_opp': 'sandbox-p1-grave',
            'exhaust_opp': 'sandbox-p1-exhaust',
        };
        var sbEl = document.getElementById(sbMap[zone]);
        if (sbEl && sbEl.getBoundingClientRect().width > 0) return sbEl;
    }
    var liveMap = {
        'grave_own': 'pileBtnOwnGrave',
        'exhaust_own': 'pileBtnOwnExhaust',
        'grave_opp': 'pileBtnOppGrave',
        'exhaust_opp': 'pileBtnOppExhaust',
    };
    return document.getElementById(liveMap[zone]);
}

// Generic card-to-pile fly animation: ghost starts at fromRect, flies to
// the destination pile button, shrinking and fading as it goes.
function playCardFlyAnimation(job, done) {
    var from = job.fromRect;
    var toEl = _zoneButton(job.toZone);
    if (!from || !toEl) { setTimeout(done, 0); return; }
    var to = toEl.getBoundingClientRect();
    var def = cardDefs && cardDefs[job.cardNumericId];
    if (!def) { setTimeout(done, 0); return; }

    var ghost = document.createElement('div');
    ghost.className = 'card-fly-ghost';
    ghost.style.left = from.left + 'px';
    ghost.style.top = from.top + 'px';
    ghost.style.width = from.width + 'px';
    ghost.style.height = from.height + 'px';
    ghost.innerHTML = renderCardFrame(def, {
        context: 'hand',
        numericId: job.cardNumericId,
        interactive: false,
        showReactDeploy: false,
    });
    document.body.appendChild(ghost);

    var dx = (to.left + to.width / 2) - (from.left + from.width / 2);
    var dy = (to.top + to.height / 2) - (from.top + from.height / 2);
    var scale = Math.max(0.15, Math.min(1, to.width / from.width));

    // Force a reflow so the starting position is committed, then transition.
    void ghost.offsetWidth;
    ghost.style.transform = 'translate(' + dx + 'px, ' + dy + 'px) scale(' + scale + ')';
    ghost.style.opacity = '0';

    var finished = false;
    function finish() {
        if (finished) return;
        finished = true;
        if (ghost.parentNode) ghost.parentNode.removeChild(ghost);
        done();
    }
    ghost.addEventListener('transitionend', finish);
    setTimeout(finish, 750);
}

// Diff hands (own identity, opponent count) between prev and next and
// produce one draw_own job per newly-added own card and one draw_opp job
// per increment of the opponent's hand size. Multiset diff on own-side
// so re-ordered hands with identical contents yield zero jobs.
function deriveDrawJobs(prev, next) {
    var jobs = [];
    if (myPlayerIdx == null || !prev || !next) return jobs;
    var oppIdx = 1 - myPlayerIdx;

    var prevMe = prev.players && prev.players[myPlayerIdx];
    var nextMe = next.players && next.players[myPlayerIdx];
    if (prevMe && nextMe && Array.isArray(prevMe.hand) && Array.isArray(nextMe.hand)) {
        // Multiset subtract: count prev, then walk next and pick anything
        // that isn't cancelled by a prev occurrence. Remaining next entries
        // are newly-added cards (possibly with duplicates).
        var prevCounts = {};
        for (var pi = 0; pi < prevMe.hand.length; pi++) {
            var pid = prevMe.hand[pi];
            prevCounts[pid] = (prevCounts[pid] || 0) + 1;
        }
        for (var ni = 0; ni < nextMe.hand.length; ni++) {
            var nid = nextMe.hand[ni];
            if (prevCounts[nid] > 0) {
                prevCounts[nid] -= 1;
            } else {
                jobs.push({
                    type: 'draw_own',
                    cardNumericId: nid,
                    fromPos: 'deck',
                    toSlotIndex: ni,
                });
            }
        }
    }

    // Opponent: count-only (hidden info). Prefer hand_count, fall back to
    // hand.length (spectator god mode). Negative deltas (discards) → skip.
    var prevOpp = prev.players && prev.players[oppIdx];
    var nextOpp = next.players && next.players[oppIdx];
    function oppCount(p) {
        if (!p) return 0;
        if (typeof p.hand_count === 'number') return p.hand_count;
        if (Array.isArray(p.hand)) return p.hand.length;
        return 0;
    }
    var delta = oppCount(nextOpp) - oppCount(prevOpp);
    for (var k = 0; k < delta; k++) {
        jobs.push({ type: 'draw_opp' });
    }

    return jobs;
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
    if (la && la.type === 'SACRIFICE') {
        return { type: 'sacrifice_transcend', payload: {
            pos: la.attacker_pos || null,
        } };
    }
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
    // Phase 14.5 Wave 5: face-down opp hand row + pile button counts.
    (function() {
        if (!gameState || !gameState.players || myPlayerIdx == null) return;
        var opp = gameState.players[1 - myPlayerIdx];
        var hc = (opp.hand_count != null)
            ? opp.hand_count
            : (opp.hand ? opp.hand.length : 0);
        renderOppHandRow(hc);
        updatePileButtonCounts();
    })();
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
    syncPendingConjureDeployUI();
    syncPendingDeathTargetUI();
    syncPendingReviveUI();
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
        // === SANDBOX-EMIT-GATE-START ===
        if (sandboxMode) {
            socket.emit('sandbox_apply_action', actionData);
        } else {
            socket.emit('submit_action', actionData);
        }
        // === SANDBOX-EMIT-GATE-END ===
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
// Build a submit-ready payload for a PLAY_CARD action that preserves every
// optional field the server checks (position, target_pos, discard_card_index,
// discard_card_indices, destroyed_minion_id). Synthesising payloads from
// (handIdx, target) alone drops these and the server's `action not in
// valid_actions` check rejects it as "Illegal action".
function _playCardPayload(action) {
    var payload = { action_type: 0, card_index: action.card_index };
    if (action.position) payload.position = action.position;
    if (action.target_pos) payload.target_pos = action.target_pos;
    if (action.discard_card_index != null) payload.discard_card_index = action.discard_card_index;
    if (action.discard_card_indices && action.discard_card_indices.length > 0) {
        payload.discard_card_indices = action.discard_card_indices;
    }
    // destroyed_minion_id on the wire; accept legacy sacrifice_minion_id
    // from an older server frame so a half-deployed stack doesn't break.
    var destroyed = (action.destroyed_minion_id != null)
        ? action.destroyed_minion_id
        : action.sacrifice_minion_id;
    if (destroyed != null) payload.destroyed_minion_id = destroyed;
    return payload;
}

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

// Collect every discard-candidate hand index for this (handIdx, deployPos,
// targetPos) — the union of every index that appears in any legal action's
// discard_card_indices (falling back to the legacy single-index field).
// Without the union, multi-discard cards miss candidates because
// itertools.combinations is sorted, so the highest index never shows up as
// the first element.
function getSacrificeChoices(handIdx, deployPos, targetPos) {
    var seen = {};
    var choices = [];
    legalActions.forEach(function(a) {
        if (a.action_type !== 0 || a.card_index !== handIdx) return;
        if (deployPos != null && a.position) {
            if (a.position[0] !== deployPos[0] || a.position[1] !== deployPos[1]) return;
        }
        if (targetPos != null && a.target_pos) {
            if (a.target_pos[0] !== targetPos[0] || a.target_pos[1] !== targetPos[1]) return;
        }
        var indices = (a.discard_card_indices && a.discard_card_indices.length > 0)
            ? a.discard_card_indices
            : (a.discard_card_index != null ? [a.discard_card_index] : []);
        for (var k = 0; k < indices.length; k++) {
            var v = indices[k];
            if (!seen[v]) { seen[v] = true; choices.push(v); }
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

    // Second click on an already-armed untargeted magic → confirm and cast.
    // This is the commit half of the two-click-to-cast flow below, so
    // accidentally brushing a magic card doesn't fire it immediately.
    if (selectedHandIdx === handIdx && interactionMode === 'confirm') {
        var armed = findCardAction(handIdx, null, null);
        if (armed) submitAction(_playCardPayload(armed));
        clearSelection();
        highlightBoard();
        updateHandHighlights();
        return;
    }

    // If already selected in play/target mode, deselect.
    if (selectedHandIdx === handIdx && (interactionMode === 'play' || interactionMode === 'target')) {
        clearSelection();
        highlightBoard();
        updateHandHighlights();
        return;
    }

    var deployPositions = getDeployPositions(handIdx);
    var targetOnly = getTargetPositions(handIdx, null); // for magics with no deploy

    // Untargeted magic: find an action with no position and no target. Arm
    // the card and wait for a second click to confirm — prevents an
    // accidental tap from firing an expensive board-wide spell.
    var untargeted = findCardAction(handIdx, null, null);
    if (deployPositions.length === 0 && targetOnly.length === 0 && untargeted) {
        selectedHandIdx = handIdx;
        selectedMinionId = null;
        selectedDeployPos = null;
        interactionMode = 'confirm';
        highlightBoard();
        updateHandHighlights();
        return;
    }

    // Magic with exactly ONE legal target — auto-arm AND auto-target on
    // first click. Users kept failing to click the highlighted tile (the
    // enemy minion draws over the cell) so for a one-target spell there's
    // nothing for them to resolve — just submit directly. A second click
    // on the same card re-selects in case they want to back out.
    if (deployPositions.length === 0 && targetOnly.length === 1) {
        var onlyTarget = targetOnly[0];
        var onlyMatch = findCardAction(handIdx, null, onlyTarget);
        if (onlyMatch) {
            submitAction(_playCardPayload(onlyMatch));
            clearSelection();
            highlightBoard();
            updateHandHighlights();
            return;
        }
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
    // Sandbox: if a card is staged, click-to-place on empty cell
    if (sandboxMode) {
        var staged = document.getElementById('sandbox-staged-card');
        if (staged && !staged.hidden && staged.dataset.nid) {
            var nid = parseInt(staged.dataset.nid, 10);
            if (!isNaN(nid)) {
                socket.emit('sandbox_place_on_board', {
                    player_idx: sandboxAddTargetIdx,
                    card_numeric_id: nid,
                    row: row,
                    col: col,
                });
                // Clear staged card so normal gameplay clicks work
                staged.hidden = true;
                staged.dataset.nid = '';
                return;
            }
        }
    }
    if (isSpectator) return;  // spectators are read-only
    // Board clicks are inert during react window EXCEPT when a death
    // target pick is pending — the modal routes through the cell click
    // handler and must not be blocked by react-window gating.
    if (isReactWindow() && interactionMode !== 'death_target_pick') return;
    var isMyTurn = legalActions && legalActions.length > 0;
    if (!isMyTurn) return;

    // Death-target pick mode. Click a valid enemy minion tile to submit
    // DEATH_TARGET_PICK. Valid targets come from pending_death_valid_targets
    // on the state frame. Everything else is inert.
    if (interactionMode === 'death_target_pick') {
        var validDeath = (gameState && gameState.pending_death_valid_targets) || [];
        var isValidDeath = validDeath.some(function(p) { return p[0] === row && p[1] === col; });
        if (!isValidDeath) return;
        // ActionType.DEATH_TARGET_PICK = 14
        submitAction({ action_type: 14, target_pos: [row, col] });
        return;
    }

    // Phase 14.6: conjure deploy mode. Player picks a tile to deploy the
    // conjured card. Valid positions are highlighted; everything else is inert.
    if (interactionMode === 'conjure_deploy') {
        var validPos = (gameState && gameState.pending_conjure_deploy_positions) || [];
        var isValid = validPos.some(function(p) { return p[0] === row && p[1] === col; });
        if (!isValid) return;
        // ActionType.CONJURE_DEPLOY = 12
        submitAction({ action_type: 12, position: [row, col] });
        interactionMode = null;
        return;
    }

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

    // Armed untargeted magic: a click anywhere on the board (nothing to
    // target here) cancels the arm so the card doesn't stay committed
    // on deck after a stray click.
    if (interactionMode === 'confirm') {
        clearSelection();
        highlightBoard();
        updateHandHighlights();
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
            // Check for discard-cost choices (discard_cost_tribe card)
            var sacChoices = getSacrificeChoices(selectedHandIdx, [row, col], null);
            if (sacChoices.length > 1) {
                selectedDeployPos = [row, col];
                showSacrificePicker(selectedHandIdx, [row, col], null, sacChoices);
                return;
            }
            // No targeting/discard needed — submit via matched action so
            // destroyed_minion_id (minions with destroy_ally_cost — not
            // currently used by minions, but future-proof) propagates.
            var matched0 = findCardAction(selectedHandIdx, [row, col], null);
            if (matched0) {
                var payload = _playCardPayload(matched0);
                if (sacChoices.length === 1) payload.discard_card_index = sacChoices[0];
                submitAction(payload);
            }
        }
        return;
    }

    // Target selection mode (magic targeting OR minion on-play target after deploy was picked)
    if (interactionMode === 'target' && selectedHandIdx !== null) {
        var validTarget = getTargetPositions(selectedHandIdx, selectedDeployPos).some(function(p) {
            return p[0] === row && p[1] === col;
        });
        if (validTarget) {
            // Check for discard-cost choices at this combo
            var sacChoices2 = getSacrificeChoices(selectedHandIdx, selectedDeployPos, [row, col]);
            if (sacChoices2.length > 1) {
                showSacrificePicker(selectedHandIdx, selectedDeployPos, [row, col], sacChoices2);
                return;
            }
            // Find the FULL matched legal action and rebuild the payload from
            // it — carries destroyed_minion_id for destroy_ally_cost cards
            // (e.g. Feed the Shadow) that the synthesised payload used to
            // drop. First match wins the ally pick for cards with >1 ally.
            var matched = findCardAction(selectedHandIdx, selectedDeployPos, [row, col]);
            if (matched) {
                var payload = _playCardPayload(matched);
                if (sacChoices2.length === 1) payload.discard_card_index = sacChoices2[0];
                submitAction(payload);
            }
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
    // Board clicks are inert during react window EXCEPT when a death
    // target pick is pending (see onBoardCellClick comment).
    if (isReactWindow() && interactionMode !== 'death_target_pick') return;
    var isMyTurn = legalActions && legalActions.length > 0;
    if (!isMyTurn) return;

    // Phase 14.1: in post-move attack-pick mode, only enemy clicks on valid
    // target tiles are honored — selecting other minions is inert.
    if (interactionMode === 'post_move_attack_pick') {
        onBoardCellClick(minion.position[0], minion.position[1]);
        return;
    }

    // Death-target pick mode: defer to the cell click path so the same
    // valid-target filter runs.
    if (interactionMode === 'death_target_pick') {
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

// Discard-cost picker — collects one or more hand-index picks (based on
// the played card's discard_cost_count) then submits the matching PLAY_CARD
// action. Multi-pick cards re-render the grid after each click, disabling
// already-picked cards; submission fires when pick count reaches the
// required discard count.
function showSacrificePicker(handIdx, deployPos, targetPos, sacChoices) {
    hideSacrificePicker();
    var myPlayer = gameState.players[myPlayerIdx];
    var playedCardId = myPlayer.hand[handIdx];
    var playedDef = cardDefs[playedCardId];
    var discardCount = (playedDef && playedDef.discard_cost_count) || 1;
    var picks = [];

    // Class names mirror the "discard" semantics (cards go to Exhaust,
    // not the grave — it's not a sacrifice). CSS continues to provide
    // back-compat selectors for .sacrifice-picker-* while new markup
    // uses .discard-picker-* so the DOM reads correctly.
    var modal = document.createElement('div');
    modal.id = 'sacrifice-picker';
    modal.className = 'discard-picker-overlay sacrifice-picker-overlay';
    var inner = document.createElement('div');
    inner.className = 'discard-picker-modal sacrifice-picker-modal';
    var title = document.createElement('div');
    title.className = 'discard-picker-title sacrifice-picker-title';
    var progress = document.createElement('div');
    progress.className = 'discard-picker-progress sacrifice-picker-progress';
    inner.appendChild(title);
    inner.appendChild(progress);
    var row = document.createElement('div');
    row.className = 'discard-picker-row sacrifice-picker-row';
    inner.appendChild(row);

    function refresh() {
        title.textContent = discardCount > 1
            ? 'Pick ' + discardCount + ' cards to Discard'
            : 'Pick a card to Discard';
        progress.textContent = discardCount > 1
            ? (picks.length + ' / ' + discardCount + ' picked')
            : '';
        row.innerHTML = '';
        sacChoices.forEach(function(sacIdx) {
            var cardId = myPlayer.hand[sacIdx];
            var c = cardDefs[cardId];
            if (!c) return;
            var btn = document.createElement('button');
            btn.className = 'discard-picker-card sacrifice-picker-card';
            var picked = picks.indexOf(sacIdx) !== -1;
            if (picked) btn.className += ' picked';
            // Render the full card frame — same look as the tutor modal —
            // instead of a tiny name/tribe button. The badge stays on
            // top-right when picked.
            btn.innerHTML = renderCardFrame(c, {
                context: 'tooltip',
                numericId: cardId,
                interactive: false,
                showReactDeploy: false,
            }) + (picked ? '<div class="sp-badge">✓</div>' : '');
            btn.addEventListener('click', function() {
                if (picked) {
                    // Unpick
                    picks = picks.filter(function(i) { return i !== sacIdx; });
                    refresh();
                    return;
                }
                picks.push(sacIdx);
                if (picks.length < discardCount) {
                    refresh();
                    return;
                }
                // All picks collected — match the legal action.
                var sortedPicks = picks.slice().sort(function(a, b) { return a - b; });
                var matched = null;
                for (var mi = 0; mi < legalActions.length; mi++) {
                    var la = legalActions[mi];
                    if (la.action_type !== 0 || la.card_index !== handIdx) continue;
                    if (deployPos) {
                        if (!la.position || la.position[0] !== deployPos[0] || la.position[1] !== deployPos[1]) continue;
                    } else if (la.position) continue;
                    if (targetPos) {
                        if (!la.target_pos || la.target_pos[0] !== targetPos[0] || la.target_pos[1] !== targetPos[1]) continue;
                    } else if (la.target_pos) continue;
                    var laIndices = la.discard_card_indices || (la.discard_card_index != null ? [la.discard_card_index] : []);
                    if (laIndices.length !== sortedPicks.length) continue;
                    var sorted = laIndices.slice().sort(function(a, b) { return a - b; });
                    var same = sorted.every(function(v, i) { return v === sortedPicks[i]; });
                    if (same) { matched = la; break; }
                }
                var payload;
                if (matched) {
                    payload = _playCardPayload(matched);
                } else {
                    payload = { action_type: 0, card_index: handIdx };
                    if (deployPos) payload.position = deployPos;
                    if (targetPos) payload.target_pos = targetPos;
                    payload.discard_card_index = sortedPicks[0];
                    payload.discard_card_indices = sortedPicks;
                }
                hideSacrificePicker();
                submitAction(payload);
            });
            row.appendChild(btn);
        });
    }
    refresh();

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

// =============================================
// Revive modal — place revived minions from grave
// =============================================

var reviveModalOpen = false;

function syncPendingReviveUI() {
    if (!gameState) {
        if (reviveModalOpen) closeReviveModal();
        return;
    }
    var pendingIdx = gameState.pending_revive_player_idx;
    if (pendingIdx == null) {
        if (reviveModalOpen) closeReviveModal();
        if (interactionMode === 'revive_place') interactionMode = null;
        return;
    }
    // Sandbox is god-mode — always show the modal regardless of myPlayerIdx.
    var isPicker = sandboxMode || pendingIdx === myPlayerIdx;
    if (isPicker) {
        // Re-assert revive_place mode so highlightBoard draws cell-valid on
        // REVIVE_PLACE legal tiles. A prior clearSelection() may have wiped
        // interactionMode even while reviveModalOpen stayed true.
        interactionMode = 'revive_place';
        if (!reviveModalOpen) {
            showReviveModal();
        }
    } else {
        if (reviveModalOpen) closeReviveModal();
    }
}

function showReviveModal() {
    closeReviveModal();
    // closeReviveModal clears interactionMode — re-assert picker mode so the
    // subsequent highlightBoard sees revive_place and draws cell-valid.
    reviveModalOpen = true;
    interactionMode = 'revive_place';

    var remaining = gameState.pending_revive_remaining || 0;
    var cardNid = gameState.pending_revive_card_numeric_id;
    var cardDef = cardNid != null && window.cardDefs ? window.cardDefs[cardNid] : null;
    var cardName = cardDef ? cardDef.name : 'minion';

    // Revive modal is NON-blocking: the board must remain clickable so the
    // player can pick a target cell. Overlay uses pointer-events:none; only
    // the inner banner receives clicks (for the Skip button).
    var overlay = document.createElement('div');
    overlay.className = 'tutor-modal-overlay revive-modal-overlay-nonblock';
    overlay.id = 'revive-modal-overlay';
    overlay.style.cssText = 'position:fixed;top:70px;left:0;right:0;bottom:auto;background:transparent;backdrop-filter:none;pointer-events:none;display:flex;justify-content:center;z-index:10;';

    var modal = document.createElement('div');
    modal.className = 'tutor-modal';
    modal.style.cssText = 'pointer-events:auto;max-width:480px;background:rgba(20,25,45,0.95);border:2px solid #1b5a7a;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.6);';

    var header = document.createElement('div');
    header.className = 'tutor-modal-header';
    var title = document.createElement('div');
    title.className = 'tutor-modal-title';
    title.textContent = 'Revive: Click a tile to place ' + cardName + ' (' + remaining + ' remaining)';
    header.appendChild(title);
    modal.appendChild(header);

    var body = document.createElement('div');
    body.style.cssText = 'padding:16px;text-align:center;color:var(--muted);font-size:14px;';
    body.textContent = 'Click a highlighted cell on the board to place the revived minion.';
    modal.appendChild(body);

    var footer = document.createElement('div');
    footer.className = 'tutor-modal-footer';
    var skipBtn = document.createElement('button');
    skipBtn.className = 'btn btn-secondary';
    skipBtn.textContent = 'Done (skip remaining)';
    skipBtn.onclick = function() {
        submitAction({ action_type: 16 }); // DECLINE_REVIVE
    };
    footer.appendChild(skipBtn);
    modal.appendChild(footer);

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Highlight valid board cells
    highlightReviveCells();
}

function highlightReviveCells() {
    // Use legalActions to find valid REVIVE_PLACE positions
    if (!window.legalActions) return;
    var cells = document.querySelectorAll('.board-cell');
    cells.forEach(function(cell) {
        cell.classList.remove('cell-valid');
    });
    for (var i = 0; i < legalActions.length; i++) {
        var a = legalActions[i];
        if (a.action_type === 15 && a.position) { // REVIVE_PLACE
            var r = a.position[0], c = a.position[1];
            var cell = document.querySelector('.board-cell[data-row="' + r + '"][data-col="' + c + '"]');
            if (cell) {
                cell.classList.add('cell-valid');
                (function(row, col) {
                    cell.onclick = function() {
                        submitAction({ action_type: 15, position: [row, col] }); // REVIVE_PLACE
                    };
                })(r, c);
            }
        }
    }
}

function closeReviveModal() {
    var existing = document.getElementById('revive-modal-overlay');
    if (existing) existing.remove();
    reviveModalOpen = false;
    if (interactionMode === 'revive_place') interactionMode = null;
    // Clear cell highlights
    var cells = document.querySelectorAll('.board-cell.cell-valid');
    cells.forEach(function(cell) { cell.classList.remove('cell-valid'); });
}

// =============================================
// Phase 14.6: Conjure deploy tile-picking UI
// =============================================

var conjureDeployActive = false;

function syncPendingConjureDeployUI() {
    if (!gameState) {
        closeConjureDeployUI();
        return;
    }
    var pendingIdx = gameState.pending_conjure_deploy_player_idx;
    if (pendingIdx == null) {
        closeConjureDeployUI();
        return;
    }
    // Sandbox is god-mode — always show the deploy UI regardless of myPlayerIdx.
    var isDeployer = sandboxMode || pendingIdx === myPlayerIdx;
    if (isDeployer) {
        // Re-assert the mode on every state update; closeConjureDeployUI in
        // showConjureDeployUI will null it, so set AFTER opening too.
        interactionMode = 'conjure_deploy';
        if (!conjureDeployActive) {
            conjureDeployActive = true;
            showConjureDeployUI();
        }
    } else {
        // Opponent is deploying
        closeConjureDeployUI();
        showOpponentConjuringToast();
    }
}

function showConjureDeployUI() {
    // Show a header bar instructing the player to pick a tile
    closeConjureDeployUI();
    conjureDeployActive = true;
    interactionMode = 'conjure_deploy';

    var banner = document.createElement('div');
    banner.id = 'conjure-deploy-banner';
    banner.className = 'tutor-toast';
    banner.style.background = '#2a6b3a';
    banner.style.top = '60px';

    var cardNid = gameState.pending_conjure_deploy_card;
    var cardName = cardNid != null ? findCardNameByNid(cardNid) : 'card';
    banner.textContent = 'Deploy ' + cardName + ' — click a valid tile';

    var skipBtn = document.createElement('button');
    skipBtn.className = 'tutor-skip-button';
    skipBtn.style.marginLeft = '12px';
    skipBtn.style.display = 'inline';
    skipBtn.textContent = 'To Hand';
    skipBtn.title = 'Send the conjured card to your hand instead of deploying';
    skipBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        // ActionType.DECLINE_CONJURE = 13
        submitAction({ action_type: 13 });
    });
    banner.appendChild(skipBtn);

    document.body.appendChild(banner);

    // Highlight valid deploy tiles
    highlightBoard();
}

function closeConjureDeployUI() {
    var existing = document.getElementById('conjure-deploy-banner');
    if (existing) existing.remove();
    var toast = document.getElementById('opponent-conjuring-toast');
    if (toast) toast.remove();
    if (conjureDeployActive) {
        conjureDeployActive = false;
        if (interactionMode === 'conjure_deploy') interactionMode = null;
    }
}

function showOpponentConjuringToast() {
    if (document.getElementById('opponent-conjuring-toast')) return;
    var toast = document.createElement('div');
    toast.id = 'opponent-conjuring-toast';
    toast.className = 'tutor-toast';
    toast.textContent = 'Opponent is deploying a conjured card\u2026';
    document.body.appendChild(toast);
}

// =============================================
// Death-trigger modal UI (e.g. Lasercannon on_death destroy)
// =============================================

var deathTargetActive = false;

function syncPendingDeathTargetUI() {
    if (!gameState) {
        closeDeathTargetUI();
        return;
    }
    var ownerIdx = gameState.pending_death_target_owner_idx;
    if (ownerIdx == null) {
        closeDeathTargetUI();
        return;
    }
    // Sandbox is god-mode — always enter picker UI regardless of myPlayerIdx.
    var isPicker = sandboxMode || ownerIdx === myPlayerIdx;
    if (isPicker) {
        // Always (re-)enter the picker mode on every state update while the
        // modal is open — a prior clearSelection() may have wiped
        // interactionMode even though deathTargetActive remained true.
        interactionMode = 'death_target_pick';
        if (!deathTargetActive) {
            deathTargetActive = true;
            showDeathTargetPickerUI();
        }
    } else {
        // Opponent is picking — passive toast, no modal.
        closeDeathTargetUI();
        showOpponentDeathPickToast();
    }
}

function showDeathTargetPickerUI() {
    closeDeathTargetUI();
    // closeDeathTargetUI nulls interactionMode — re-assert picker mode
    // AFTER so the rest of this function (and downstream highlightBoard)
    // sees the right mode.
    deathTargetActive = true;
    interactionMode = 'death_target_pick';

    var banner = document.createElement('div');
    banner.id = 'death-target-banner';
    banner.className = 'tutor-toast';
    banner.style.background = '#7a1b1b';
    banner.style.top = '60px';

    var cardName = gameState.pending_death_card_name || 'Death effect';
    var filter = gameState.pending_death_filter || 'enemy_minion';
    var text;
    if (filter === 'friendly_promote') {
        banner.style.background = '#1b5a7a';
        text = 'Pick an ally to promote (' + cardName + ' death)';
    } else {
        text = 'Pick an enemy to destroy (' + cardName + ' death)';
    }
    banner.textContent = text;
    document.body.appendChild(banner);

    highlightBoard();
}

function closeDeathTargetUI() {
    var existing = document.getElementById('death-target-banner');
    if (existing) existing.remove();
    var toast = document.getElementById('opponent-death-pick-toast');
    if (toast) toast.remove();
    if (deathTargetActive) {
        deathTargetActive = false;
        if (interactionMode === 'death_target_pick') interactionMode = null;
    }
}

function showOpponentDeathPickToast() {
    if (document.getElementById('opponent-death-pick-toast')) return;
    var toast = document.createElement('div');
    toast.id = 'opponent-death-pick-toast';
    toast.className = 'tutor-toast';
    toast.style.background = '#7a1b1b';
    toast.textContent = 'Opponent is choosing a target for a Death effect\u2026';
    document.body.appendChild(toast);
}

function findCardNameByNid(nid) {
    // cardDefs is the nid-keyed map populated from sandbox_card_defs /
    // the game-start card defs payload; cardDefsMap was a stale name.
    var defs = (typeof cardDefs !== 'undefined' && cardDefs) ? cardDefs : null;
    if (defs && defs[nid]) return defs[nid].name || ('Card #' + nid);
    return 'Card #' + nid;
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

    // Revive placement tile highlighting (Ratical Resurrection modal).
    // Uses legalActions REVIVE_PLACE entries to mark valid tiles.
    if (interactionMode === 'revive_place' && legalActions) {
        for (var _i = 0; _i < legalActions.length; _i++) {
            var _a = legalActions[_i];
            if (_a.action_type === 15 && _a.position) {  // REVIVE_PLACE
                var _cell = document.querySelector('.board-cell[data-row="' + _a.position[0] + '"][data-col="' + _a.position[1] + '"]');
                if (_cell) _cell.classList.add('cell-valid');
            }
        }
        return;
    }

    // Death-target pick tile highlighting (click-target death modal).
    if (interactionMode === 'death_target_pick' && gameState) {
        var deathTargets = gameState.pending_death_valid_targets || [];
        deathTargets.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) {
                cell.classList.add('cell-attack');
                cell.classList.add('attack-valid-target');
            }
        });
        return;  // Skip regular highlighting
    }

    // Phase 14.6: conjure deploy tile highlighting.
    if (interactionMode === 'conjure_deploy' && gameState) {
        var deployPositions = gameState.pending_conjure_deploy_positions || [];
        deployPositions.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) cell.classList.add('cell-valid');
        });
        return;  // Skip regular highlighting
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
                            // Range N star footprint: orthogonal arm reaches
                            // N+1 tiles; diagonal arm reaches chebyshev<=N
                            // along the |dr|==|dc| lines.
                            // Mirrors action_resolver._can_attack.
                            var dr = Math.abs(rr - sr);
                            var dc = Math.abs(cc - sc);
                            var orthogonalInRange = orthogonal && manhattan <= range + 1;
                            var onDiagonal = (dr === dc && dr >= 1 && chebyshev <= range);
                            inRange = orthogonalInRange || onDiagonal;
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
        card.classList.remove('card-playable', 'card-selected-hand', 'card-react-playable', 'card-confirm-armed');
        if (selectedHandIdx === idx && interactionMode === 'confirm') {
            card.classList.add('card-confirm-armed');
        } else if (selectedHandIdx === idx && (interactionMode === 'play' || interactionMode === 'target')) {
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

function renderBoard(opts) {
    // Phase 14.6: opts param is additive + backward-compatible.
    // Zero-arg calls (existing live-game sites) fall through to the original
    // globals-driven behavior. Sandbox passes { mount, state, perspectiveIdx,
    // legalActions } to route rendering to a different DOM target.
    opts = opts || {};
    var boardEl = opts.mount || document.getElementById('game-board');
    var state = opts.state || gameState;
    var perspectiveIdx = (opts.perspectiveIdx != null) ? opts.perspectiveIdx : myPlayerIdx;
    // legal is accepted for signature parity with renderHand; renderBoard
    // itself doesn't gate on legal actions (click handlers do).
    var legal = opts.legalActions || legalActions;  // eslint-disable-line no-unused-vars
    if (!boardEl) return;
    if (!state) return;
    boardEl.innerHTML = '';

    // Build minion lookup: "row,col" -> minion object (Pitfall 6)
    var minionMap = {};
    (state.minions || []).forEach(function(m) {
        minionMap[m.position[0] + ',' + m.position[1]] = m;
    });

    // Display order depends on perspective (D-03).
    // Engine truth: P1 back row = 0, P2 back row = 4. Each player should see
    // their own back row at the BOTTOM (standard TCG convention).
    // P1 (idx 0): render rows 4,3,2,1,0 top-to-bottom -> row 0 (P1 back) at bottom
    // P2 (idx 1): render rows 0,1,2,3,4 top-to-bottom -> row 4 (P2 back) at bottom
    var rowOrder = perspectiveIdx === 0
        ? [4, 3, 2, 1, 0]
        : [0, 1, 2, 3, 4];

    // Zone classification matches engine: P1 zone = rows 0,1; P2 zone = rows 3,4.
    var selfRows = perspectiveIdx === 0 ? [0, 1] : [3, 4];
    var oppRows = perspectiveIdx === 0 ? [3, 4] : [0, 1];

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
                var isOwn = minion.owner === perspectiveIdx;
                cell.classList.add(isOwn ? 'cell-owner-self' : 'cell-owner-opp');
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
        badges.push('<span class="minion-badge badge-buff">⬆️+' + minion.attack_bonus + SWORD + '</span>');
    } else if (minion.attack_bonus < 0) {
        badges.push('<span class="minion-badge badge-debuff">⬇️' + minion.attack_bonus + SWORD + '</span>');
    }
    if (minion.max_health_bonus && minion.max_health_bonus > 0) {
        badges.push('<span class="minion-badge badge-buff">⬆️+' + minion.max_health_bonus + HEART + '</span>');
    }
    var badgesHtml = badges.length
        ? '<div class="minion-badges">' + badges.join('') + '</div>'
        : '';

    return '<div class="board-minion ' + ownerClass + ' ' + typeClass + '" data-numeric-id="' + minion.card_numeric_id + '" style="' + boardArtStyle + '">'
        + '<div class="board-minion-overlay"></div>'
        + '<div class="attr-circle-sm ' + elem.css + '"><span class="attr-text-sm">' + elem.name + '</span></div>'
        + '<div class="board-minion-name">' + cardDef.name + '</div>'
        + '<div class="board-minion-stats">'
        + '<span class="board-minion-atk"><span class="stat-emoji-bg">' + SWORD_SVG + '</span><span class="stat-num">' + atk + '</span></span>'
        + '<span class="board-minion-hp"><span class="stat-emoji-bg">' + HEART_SVG + '</span><span class="stat-num">' + hp + '</span></span>'
        + '</div>'
        + badgesHtml
        + '</div>';
}

// =============================================
// Section 15: renderHand() (UI-02, D-05)
// =============================================

function renderHand(opts) {
    // Phase 14.6: opts param is additive + backward-compatible.
    // Zero-arg calls (existing live-game sites) fall through to the original
    // globals-driven behavior. Sandbox passes { mount, state, ownerIdx,
    // godView, legalActions } to mount ONE player's hand into a sandbox
    // DOM target without walking the god-view spectator branch.
    //
    // When opts.godView is true (sandbox), we render ONLY the ownerIdx
    // player's hand face-up into the provided mount -- this is called
    // twice by renderSandbox(), once for P0 into #sandbox-hand-p0, once
    // for P1 into #sandbox-hand-p1. The spectator god-view branch below
    // is unchanged; it still fires for the live-game spectator path.
    opts = opts || {};
    var handEl = opts.mount || document.getElementById('hand-container');
    var state = opts.state || gameState;
    var ownerIdx = (opts.ownerIdx != null) ? opts.ownerIdx : myPlayerIdx;
    var legal = opts.legalActions || legalActions;
    if (!handEl) return;
    if (!state) return;
    handEl.innerHTML = '';

    var myPlayer = state.players[ownerIdx];
    var isMyTurn = legal && legal.length > 0;

    function appendHand(playerObj, label) {
        if (!playerObj || !playerObj.hand) return;
        if (label) {
            var lbl = document.createElement('div');
            lbl.className = 'spectator-hand-label';
            lbl.textContent = label;
            handEl.appendChild(lbl);
        }
        var totalCards = playerObj.hand.length;
        playerObj.hand.forEach(function(numericId, handIndex) {
            var mana = playerObj.current_mana;
            var cardHtml = renderHandCard(numericId, handIndex, mana, isMyTurn && !isSpectator);
            var wrapper = document.createElement('div');
            wrapper.innerHTML = cardHtml;
            if (wrapper.firstChild) {
                var cardEl = wrapper.firstChild;
                // Fan positioning via CSS custom properties
                cardEl.style.setProperty('--i', handIndex);
                cardEl.style.setProperty('--n', totalCards);
                cardEl.addEventListener('mouseenter', function() { showGameTooltip(numericId, this); });
                cardEl.addEventListener('mouseleave', function() {
                    // Only hide tooltip if this card is not pinned
                    if (!cardEl.classList.contains('card-preview-pinned')) {
                        hideGameTooltip();
                    }
                });
                (function(idx, nid) {
                    cardEl.addEventListener('click', function() {
                        // Pin preview in the tooltip sidebar
                        pinHandCardPreview(nid, this);
                        onHandCardClick(idx);
                    });
                })(handIndex, numericId);
                // Phase 14.6-03: additive "Move to..." affordance in sandbox
                // mode. The existing play-from-hand click handler above is
                // unchanged; this button is a sibling affordance.
                if (sandboxMode && typeof makeSandboxMoveButton === 'function') {
                    cardEl.appendChild(makeSandboxMoveButton(ownerIdx, numericId, 'hand'));
                }
                handEl.appendChild(cardEl);
            }
        });
    }

    // Phase 14.4: god-mode spectators see BOTH hands; non-god spectators
    // see only the perspective player (server sends the opponent as count).
    // Phase 14.6: opts.godView (sandbox) renders ONLY the ownerIdx hand
    // face-up -- the sandbox calls renderHand twice with distinct mounts,
    // once per player, so each mount shows exactly one hand.
    if (opts && opts.godView) {
        appendHand(myPlayer, null);
    } else if (isSpectator && spectatorGodMode) {
        var oppIdx = 1 - ownerIdx;
        appendHand(state.players[oppIdx], 'Player ' + (oppIdx + 1) + ' hand');
        appendHand(myPlayer, 'Player ' + (ownerIdx + 1) + ' hand');
    } else {
        appendHand(myPlayer, null);
    }
    // Auto-fit names and effects for hand cards
    fitHandCardNames();
    fitHandCardEffects();
}

// =============================================
// renderHandCard() -- thin wrapper over renderCardFrame (Wave 14.5-04)
// Single source of truth lives in renderCardFrame(). Hand context stamps
// data-hand-idx / data-numeric-id and dims on can't-afford OR not-my-turn.
// =============================================
function renderHandCard(numericId, handIndex, currentMana, isMyTurn) {
    var c = cardDefs[numericId];
    if (!c) return '';
    var canAfford = currentMana >= c.mana_cost;
    return renderCardFrame(c, {
        context: 'hand',
        handIndex: handIndex,
        numericId: numericId,
        dim: !(canAfford && isMyTurn),
        showReactDeploy: false,
    });
}

// =============================================
// Section 16: renderDeckBuilderCard (already defined above in Section 7)
// Section 17: Helper -- getEffectDescription()
// =============================================

// Sum of Dark Matter stacks across the viewing player's live minions.
// Returns null when not in an active game (deck builder, card DB) so the
// placeholder "(Dark Matter)" stays literal in those contexts.
function _viewerDarkMatterSum() {
    if (!gameState || !gameState.minions || myPlayerIdx == null) return null;
    var sum = 0;
    for (var i = 0; i < gameState.minions.length; i++) {
        var m = gameState.minions[i];
        if (m && m.owner === myPlayerIdx && (m.current_health == null || m.current_health > 0)) {
            sum += (m.dark_matter_stacks || 0);
        }
    }
    return sum;
}

// In card rules text, live games substitute "(Dark Matter)" with the
// viewer's current DM pool in purple, followed by the "(Dark Matter)"
// label so the number is unambiguous. Non-live contexts keep the literal.
function _dmTokenLive() {
    var dm = _viewerDarkMatterSum();
    if (dm == null) return '(Dark Matter)';
    return '<span class="dm-live-num">' + dm + '</span> (Dark Matter)';
}

function getEffectDescription(effects, cardData) {
    if (!effects || effects.length === 0) return '';
    var isMinion = cardData && cardData.card_type === 0;
    var DM = _dmTokenLive();
    var triggerMap = {0: isMinion ? 'Summon' : '', 1: 'Death', 2: 'Attack', 3: 'Damaged', 4: 'Move', 5: 'End', 6: 'Discarded'};
    // Coalesce sibling burn-all-minions effects that only differ in
    // target_tribe/target_element into a single rendered clause — so
    // Acidic Rain reads "Burn all Robots, Machines and Metal minions"
    // instead of three separate lines.
    effects = (function(effs) {
        var bucket = null;
        var out = [];
        effs.forEach(function(e) {
            var isBurnAll = e.type === 10 && e.target === 6;
            if (isBurnAll) {
                if (!bucket || bucket.trigger !== e.trigger) {
                    bucket = { type: 10, target: 6, trigger: e.trigger, amount: e.amount || 0, _tribes: [], _elements: [] };
                    out.push(bucket);
                }
                if (e.target_tribe && bucket._tribes.indexOf(e.target_tribe) < 0) bucket._tribes.push(e.target_tribe);
                if (e.target_element && bucket._elements.indexOf(e.target_element) < 0) bucket._elements.push(e.target_element);
            } else {
                bucket = null;
                out.push(e);
            }
        });
        return out;
    })(effects);
    var parts = [];
    effects.forEach(function(eff) {
        var trigger = triggerMap[eff.trigger];
        if (trigger === undefined) trigger = '';
        var prefix = trigger ? trigger + ': ' : '';
        var amount = eff.amount || 0;
        var type = eff.type;
        var desc = '';

        if (type === 0) { // Damage
            if (eff.scale_with === 'dark_matter') {
                desc = prefix + 'Deal ' + DM + ' damage';
                if (amount > 0) desc = prefix + 'Deal ' + amount + ' + ' + DM + ' damage';
            } else if (eff.scale_with === 'destroyed_attack_plus_dm' || eff.scale_with === 'sacrificed_attack_plus_dm') {
                desc = prefix + "Deal destroyed ally's " + SWORD + ' + ' + DM + ' as damage';
            } else if (eff.scale_with === 'destroyed_attack' || eff.scale_with === 'sacrificed_attack') {
                desc = prefix + "Deal destroyed ally's " + SWORD + ' as damage';
            } else {
                desc = prefix + 'Deal ' + amount + ' damage';
            }
            if (eff.target === 1) desc += ' to all enemies';
            else if (eff.target === 0) desc += ' to target';
            else if (eff.target === 4) desc += ' to face';
        } else if (type === 1) { // Heal
            desc = prefix + 'Heal ' + amount;
        } else if (type === 2) { // Buff ATK
            if (eff.scale_with === 'dark_matter') {
                // Check if next effect is BUFF_HP with same scale — merge icons
                var hasMatchingHp = effects.some(function(e2) {
                    return e2.type === 3 && e2.scale_with === 'dark_matter' && e2.target === eff.target;
                });
                var tribeName = eff.target_tribe === 'Mage' ? 'Dark Mages' : (eff.target_tribe ? eff.target_tribe + 's' : 'allies');
                var selfTarget = (eff.target === 3); // SELF_OWNER
                desc = prefix + (selfTarget ? 'Gain' : 'Ally ' + tribeName + ' gain') + ' ' + DM + SWORD + (hasMatchingHp ? HEART : '');
                if (eff.placement_condition === 'front_of_dark_ranged' && eff.condition_multiplier > 1) {
                    desc += '. ×' + eff.condition_multiplier + ' if in front of Dark Ranged ally';
                }
            } else {
                desc = prefix + '+' + amount + SWORD;
            }
        } else if (type === 3) { // Buff HP
            if (eff.scale_with === 'dark_matter') {
                // Skip if already merged with BUFF_ATK above
                var alreadyMerged = effects.some(function(e2) {
                    return e2.type === 2 && e2.scale_with === 'dark_matter' && e2.target === eff.target;
                });
                if (alreadyMerged) { desc = ''; return; }
                var tribeNameHp = eff.target_tribe === 'Mage' ? 'Dark Mages' : (eff.target_tribe ? eff.target_tribe + 's' : 'allies');
                desc = prefix + 'Ally ' + tribeNameHp + ' gain ' + DM + HEART;
            } else {
                desc = prefix + '+' + amount + HEART;
            }
        } else if (type === 4) { // Negate
            desc = prefix + 'Negate';
        } else if (type === 5) { // Deploy Self
            desc = prefix + 'Summon';
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
            var tutorCount = amount > 1 ? amount + ' ' : '';
            if (cardData && cardData.tutor_target) {
                var tt = cardData.tutor_target;
                if (typeof tt === 'string') {
                    var tutorName = findCardNameById(tt);
                    desc = prefix + 'Tutor ' + tutorCount + tutorName;
                } else if (typeof tt === 'object') {
                    // Selector dict: {tribe: "Rat"} etc.
                    var selParts = [];
                    if (tt.tribe) selParts.push(tt.tribe + (amount > 1 ? 's' : ''));
                    if (tt.element) selParts.push(tt.element);
                    if (tt.card_type) selParts.push(tt.card_type);
                    desc = prefix + 'Tutor ' + tutorCount + (selParts.join(' ') || 'card');
                } else {
                    desc = prefix + 'Tutor ' + tutorCount + tt;
                }
            } else {
                desc = prefix + 'Tutor';
            }
        } else if (type === 9) { // Destroy
            desc = prefix + 'Destroy target';
        } else if (type === 10) { // Burn
            var burnTarget;
            if (eff.target === 6) {
                // Either a coalesced bucket (see top of this fn) with
                // _tribes/_elements arrays, or a single-effect fallback.
                var tribes = eff._tribes || (eff.target_tribe ? [eff.target_tribe] : []);
                var elements = eff._elements || (eff.target_element ? [eff.target_element] : []);
                var cap = function(s) { return s.charAt(0).toUpperCase() + s.slice(1); };
                var tribeParts = tribes.map(function(t) { return t + 's'; });
                var elemParts = elements.map(function(el) { return cap(el); });
                var joined = tribeParts.concat(elemParts);
                if (joined.length === 0) burnTarget = ' all minions';
                else if (joined.length === 1) burnTarget = ' all ' + joined[0];
                else burnTarget = ' all ' + joined.slice(0, -1).join(', ') + ' and ' + joined.slice(-1)[0];
                if (elements.length > 0) burnTarget += ' minions';
            } else {
                burnTarget = {0: ' target', 1: ' all enemies', 2: ' adjacent enemies', 3: ' self'}[eff.target] || '';
            }
            desc = prefix + 'Burn' + burnTarget;
        } else if (type === 11) { // Dark Matter Buff
            desc = prefix + 'Target gains (Dark Matter)' + SWORD;
        } else if (type === 12) { // End Heal
            desc = 'End: Heal ' + amount;
        } else if (type === 13) { // Leap
            desc = 'Move: Leap';
        } else if (type === 14) { // Conjure
            var conjureName = (cardData && cardData.summon_token_target) ? findCardNameById(cardData.summon_token_target) : 'a card';
            var conjureCost = (cardData && cardData.summon_token_cost) ? ' (' + cardData.summon_token_cost + ')' : '';
            desc = 'Active' + conjureCost + ': Summon ' + conjureName + ' from deck';
            if (cardData && cardData.conjure_buff === 'dark_matter') {
                desc += '. Buff all ' + conjureName + ' by Dark Matter';
            }
        } else if (type === 15) { // Apply Burning
            var burnAmt = amount || 1;
            desc = prefix + 'Apply ' + burnAmt + ' Burning';
        } else if (type === 16) { // Grant Dark Matter
            desc = prefix + 'Dark Matter +' + amount;
            if (eff.target === 5 && eff.target_tribe === 'Mage') desc += ' per ally Dark Mage';
            else if (eff.target === 5 && eff.target_tribe) desc += ' per ally ' + eff.target_tribe;
            else if (eff.target === 5) desc += ' per ally';
        } else if (type === 17) { // Revive
            var reviveName = (cardData && cardData.revive_card_id) ? findCardNameById(cardData.revive_card_id) : 'minion';
            desc = prefix + 'Revive ' + amount + ' ' + reviveName + (amount > 1 ? 's' : '') + ' from Grave';
        } else if (type === 18) { // Draw
            var cardText = amount > 1 ? amount + ' cards' : '1 card';
            desc = prefix + 'Draw ' + cardText;
        } else if (type === 19) { // Burn Bonus (passive aura)
            desc = 'Passive: Burn +' + amount;
        } else {
            console.warn('[getEffectDescription] Unhandled effect type ' + type + ' on card "' + (cardData && cardData.card_id) + '". Add a case for EffectType ' + type + ' in getEffectDescription().');
            desc = prefix + 'Effect';
        }
        if (desc) parts.push(desc);
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

// === SANDBOX-SECTION-START ===
// Phase 14.6 sandbox screen. All sandbox-related JS lives between
// SANDBOX-SECTION-START and SANDBOX-SECTION-END so plan 14.6-03 (and any
// future sandbox extension) can locate insertion points by grep, not by
// fragile line numbers.
//
// LAYOUT INVARIANT (D1): The sandbox is fixed dual-perspective god view.
// P1 hand mounts at #sandbox-hand-p0 (visually TOP), P2 hand mounts at
// #sandbox-hand-p1 (visually BOTTOM). Both render with godView:true. The
// sandbox NEVER calls filter_state_for_player or filter_state_for_spectator
// -- it renders the raw state from the server. There is NO view-toggle,
// NO flip button, NO perspective-swap. The plan 14.6-03 "Controlling:
// P1 / P2" button mutates state.active_player_idx server-side; it does
// NOT change which DOM mount renders which player's hand.

// ----- Global-swap strategy ------------------------------------------------
// The live game's renderers and click handlers read 5 module-level globals:
//   gameState, myPlayerIdx, legalActions, isSpectator, spectatorGodMode
// (plus animatingTiles, which we reset to {} on activation).
//
// Refactoring 50+ read sites in onHandCardClick / onBoardCellClick /
// submitAction is infeasible. Instead, while the sandbox screen is visible,
// the sandbox OWNS those globals. On activation we snapshot them; on
// deactivation we restore them. The opts-refactored renderBoard/renderHand
// take the sandbox mount targets via opts, so the sandbox renders into
// #sandbox-board / #sandbox-hand-p0 / #sandbox-hand-p1 even while the
// globals are pointing at the sandbox state.

function sandboxActivate() {
    sandboxMode = true;
    // Snapshot the 5 globals + animatingTiles so we can restore on exit
    _sandboxPreSnapshot = {
        gameState: gameState,
        myPlayerIdx: myPlayerIdx,
        legalActions: legalActions,
        isSpectator: isSpectator,
        spectatorGodMode: spectatorGodMode,
        animatingTiles: animatingTiles,
    };
    // While in sandbox: god view, no spectator filter, no animations queued
    // (they'd target the live #game-board which isn't visible).
    isSpectator = false;
    spectatorGodMode = true;
    animatingTiles = {};
    // gameState / myPlayerIdx / legalActions get assigned by the
    // sandbox_state handler when payload arrives.
    initSandboxScreen();
}

function sandboxDeactivate() {
    sandboxMode = false;
    if (_sandboxPreSnapshot) {
        gameState = _sandboxPreSnapshot.gameState;
        myPlayerIdx = _sandboxPreSnapshot.myPlayerIdx;
        legalActions = _sandboxPreSnapshot.legalActions;
        isSpectator = _sandboxPreSnapshot.isSpectator;
        spectatorGodMode = _sandboxPreSnapshot.spectatorGodMode;
        animatingTiles = _sandboxPreSnapshot.animatingTiles;
        _sandboxPreSnapshot = null;
    }
}

// ============================================================
// Tests screen — structured UAT survey. Rides on top of the
// sandbox screen; each test loads a scenario server-side, the
// user performs the steps, then submits Pass/Fail/Skip. Results
// append to data/tests/results.jsonl on the server.
// ============================================================
var _testsState = {
    active: false,
    list: [],       // [{id, title}, ...]
    index: 0,       // index into list of the test currently shown
    currentId: null,
    results: [],    // local tally; server has the authoritative log
    wiredHandlers: false,
    wiredButtons: false,
};

function testsActivate() {
    if (_testsState.active) return;
    _testsState.active = true;
    _testsState.index = 0;
    _testsState.results = [];
    _wireTestsOnce();
    var ov = document.getElementById('tests-overlay');
    if (ov) ov.hidden = false;
    _setTestsTitle('Loading tests…');
    _setTestsInstructions('');
    _setTestsExpected('');
    _setTestsProgress('Test 0 / 0');
    _hideTestsSummary();
    if (socket && socket.connected) {
        socket.emit('tests_list');
    }
}

function testsExit() {
    if (!_testsState.active) return;
    _testsState.active = false;
    var ov = document.getElementById('tests-overlay');
    if (ov) ov.hidden = true;
}

function _wireTestsOnce() {
    if (!_testsState.wiredButtons) {
        _testsState.wiredButtons = true;
        var pass = document.getElementById('tests-btn-pass');
        var fail = document.getElementById('tests-btn-fail');
        var skip = document.getElementById('tests-btn-skip');
        var reset = document.getElementById('tests-btn-reset');
        var exitBtn = document.getElementById('tests-exit');
        if (pass) pass.addEventListener('click', function() { _submitTestResult('pass'); });
        if (fail) fail.addEventListener('click', function() { _submitTestResult('fail'); });
        if (skip) skip.addEventListener('click', function() { _submitTestResult('skip'); });
        if (reset) reset.addEventListener('click', function() {
            // Re-run the current test's setup without consuming the slot —
            // lets the user retry after mis-clicking.
            if (_testsState.currentId) {
                socket.emit('tests_load', { id: _testsState.currentId });
            } else if (_testsState.list.length > 0) {
                _loadCurrentTest();
            }
        });
        if (exitBtn) exitBtn.addEventListener('click', function() { showScreen('screen-sandbox'); });
        var minBtn = document.getElementById('tests-minimize');
        if (minBtn) minBtn.addEventListener('click', function() {
            var ov = document.getElementById('tests-overlay');
            if (!ov) return;
            var mini = ov.classList.toggle('is-minimized');
            minBtn.textContent = mini ? '▢' : '▁';
            minBtn.title = mini ? 'Expand' : 'Minimize';
        });
    }
    if (!_testsState.wiredHandlers && socket) {
        _testsState.wiredHandlers = true;
        socket.on('tests_list_result', function(data) {
            _testsState.list = (data && data.tests) || [];
            _testsState.index = 0;
            if (_testsState.list.length === 0) {
                _setTestsTitle('No tests available');
                _setTestsInstructions('The server test manifest is empty.');
                _setTestsExpected('');
                return;
            }
            _loadCurrentTest();
        });
        socket.on('tests_scenario_loaded', function(data) {
            if (!data) return;
            _testsState.currentId = data.id;
            _setTestsProgress('Test ' + (_testsState.index + 1) + ' / ' + _testsState.list.length);
            _setTestsTitle(data.title || data.id);
            _setTestsInstructions(data.instructions || '');
            _setTestsExpected(data.expected || '');
            var ta = document.getElementById('tests-comment');
            if (ta) ta.value = '';
            // Client hints — picks which animation variant a test wants.
            var hints = data.client_hints || {};
            window.__sacrificeVariant = hints.sacrifice_animation || null;
        });
        socket.on('tests_result_saved', function() {
            // Move to next test (or show summary when done).
            _testsState.index += 1;
            if (_testsState.index >= _testsState.list.length) {
                _renderTestsSummary();
            } else {
                _loadCurrentTest();
            }
        });
    }
}

function _loadCurrentTest() {
    var t = _testsState.list[_testsState.index];
    if (!t) return;
    _setTestsProgress('Loading ' + (_testsState.index + 1) + ' / ' + _testsState.list.length + '…');
    _setTestsTitle(t.title || t.id);
    _setTestsInstructions('');
    _setTestsExpected('');
    socket.emit('tests_load', { id: t.id });
}

function _submitTestResult(result) {
    if (!_testsState.currentId) return;
    var ta = document.getElementById('tests-comment');
    var comment = ta ? ta.value : '';
    _testsState.results.push({ id: _testsState.currentId, result: result, comment: comment });
    socket.emit('tests_submit_result', {
        id: _testsState.currentId,
        result: result,
        comment: comment,
    });
    _testsState.currentId = null;  // prevent double-submit until next loads
}

function _renderTestsSummary() {
    var pass = 0, fail = 0, skip = 0;
    for (var i = 0; i < _testsState.results.length; i++) {
        var r = _testsState.results[i].result;
        if (r === 'pass') pass++;
        else if (r === 'fail') fail++;
        else if (r === 'skip') skip++;
    }
    _setTestsTitle('Tests complete');
    _setTestsInstructions('');
    _setTestsExpected('');
    _setTestsProgress(_testsState.list.length + ' / ' + _testsState.list.length);
    var summary = document.getElementById('tests-summary');
    if (summary) {
        summary.hidden = false;
        summary.innerHTML =
            '<strong>Summary:</strong> ' +
            '<span style="color:var(--green)">' + pass + ' pass</span> · ' +
            '<span style="color:var(--red)">' + fail + ' fail</span> · ' +
            '<span style="color:var(--muted)">' + skip + ' skip</span>' +
            '<br><span style="color:var(--muted);font-size:0.9em">Results logged to data/tests/results.jsonl on the server.</span>';
    }
}

function _setTestsProgress(s) { var el = document.getElementById('tests-progress'); if (el) el.textContent = s; }
function _setTestsTitle(s) { var el = document.getElementById('tests-title'); if (el) el.textContent = s; }
function _setTestsInstructions(s) { var el = document.getElementById('tests-instructions'); if (el) el.textContent = s; }
function _setTestsExpected(s) { var el = document.getElementById('tests-expected'); if (el) el.textContent = s; }
function _hideTestsSummary() { var el = document.getElementById('tests-summary'); if (el) { el.hidden = true; el.innerHTML = ''; } }

function initSandboxScreen() {
    if (!socket || !socket.connected) {
        console.warn('[sandbox] socket not connected yet');
        return;
    }
    setupSandboxToolbar();
    _wireSandboxPileButtons();
    // Try restore from localStorage; fall back to a fresh sandbox.
    // Note: sandbox_load auto-creates the session server-side if it doesn't
    // exist (see events.py:handle_sandbox_load) and also emits sandbox_card_defs
    // so the renderers can resolve numeric ids.
    var restored = false;
    try {
        var raw = localStorage.getItem(SANDBOX_AUTOSAVE_KEY);
        if (raw) {
            var payload = JSON.parse(raw);
            socket.emit('sandbox_load', { payload: payload });
            restored = true;
        }
    } catch (e) { /* corrupt -- just create fresh */ }
    if (!restored) {
        socket.emit('sandbox_create');
    }
    // Refresh server slot list every time the screen activates
    socket.emit('sandbox_list_slots');
}

function setupSandboxSocketHandlers() {
    if (!socket) return;

    socket.on('sandbox_card_defs', function(data) {
        sandboxCardDefs = (data && data.card_defs) || {};
        // Mirror into allCardDefs only if it isn't already populated by the live game,
        // so the existing renderers (which read allCardDefs/cardDefs) work inside the sandbox.
        if (!allCardDefs) {
            allCardDefs = sandboxCardDefs;
        }
        // cardDefs is the primary render-time lookup -- mirror into it too
        // (additively, so we don't stomp existing entries) so renderBoardMinion
        // / renderHandCard can resolve numeric ids inside the sandbox.
        if (cardDefs && typeof cardDefs === 'object') {
            for (var k in sandboxCardDefs) {
                if (!cardDefs[k]) cardDefs[k] = sandboxCardDefs[k];
            }
        } else {
            cardDefs = sandboxCardDefs;
        }
    });

    // === SANDBOX-STATE-HANDLER-START ===
    socket.on('sandbox_state', function(payload) {
        // Capture previous state for card-fly derivation BEFORE we overwrite
        // it. The fly derive function reads the live DOM (which still shows
        // prev) to snapshot outgoing hand-slot rects; re-rendering with new
        // state then removes those slots, so order matters.
        var prevForFly = sandboxState;
        var flyJobs = (sandboxMode && prevForFly)
            ? deriveCardFlyJobs(prevForFly, payload.state)
            : [];
        var spellStageNid = (sandboxMode && prevForFly)
            ? detectSpellCast(prevForFly, payload.state)
            : null;
        var hpJobsSb = (sandboxMode && prevForFly)
            ? derivePlayerHpDeltaAnims(prevForFly, payload.state)
            : [];
        // Derive an action-keyed animation job (SACRIFICE / ATTACK / MOVE /
        // PLAY_CARD) from the `last_action` the server now enriches onto
        // sandbox_state (see server/events.py::_emit_sandbox_state). Without
        // this dispatch, the sandbox silently drops action animations — most
        // visibly the sacrifice transcend SVG jumper. `noop` results fall
        // through to the immediate-render path below.
        var actionJob = (sandboxMode && prevForFly)
            ? deriveAnimationJob(prevForFly, payload.state)
            : null;

        sandboxState = payload.state;
        sandboxLegalActions = payload.legal_actions || [];
        sandboxActiveViewIdx = payload.active_view_idx || 0;
        sandboxUndoDepth = payload.undo_depth || 0;
        sandboxRedoDepth = payload.redo_depth || 0;
        // Push sandbox state into the swapped globals so the renderers and
        // the click handlers see it as "the current state".
        // FIXED: myPlayerIdx stays 0 (P1 perspective) so the board never flips.
        // sandboxActiveViewIdx only controls which player's actions we submit.
        if (sandboxMode) {
            gameState = sandboxState;
            myPlayerIdx = 0;
            legalActions = sandboxLegalActions;
        }
        // Plan 14.6-03: autosave + toolbar state sync
        try {
            localStorage.setItem(SANDBOX_AUTOSAVE_KEY, JSON.stringify({
                state: sandboxState,
                active_view_idx: sandboxActiveViewIdx,
            }));
        } catch (e) { /* quota exceeded -- ignore */ }
        if (typeof renderSandboxToolbarState === 'function') renderSandboxToolbarState();
        renderSandbox();
        // Enqueue the action job FIRST (if any) so the board-level animation
        // (e.g. sacrifice transcend, summon pop, attack swing) plays before
        // subsidiary fly / hp-popup ghosts. In sandbox mode the state is
        // already applied by the renderSandbox() call above, so set
        // stateApplied=true to suppress the queue's post-anim applyStateFrame
        // (which would otherwise re-render and double-apply). Animations
        // that read cell positions (e.g. sacrifice transcend) only need the
        // .board-cell[data-row][data-col] selector — the cell survives
        // re-render even after its minion is removed.
        if (actionJob && actionJob.type && actionJob.type !== 'noop') {
            actionJob.stateApplied = true;
            enqueueAnimation(actionJob);
        }
        // After the new frame is on screen, fire the fly ghosts — each one
        // already captured its source rect from the now-stale DOM before
        // renderSandbox() replaced it.
        for (var _fi = 0; _fi < flyJobs.length; _fi++) {
            enqueueAnimation(flyJobs[_fi]);
        }
        for (var _hi = 0; _hi < hpJobsSb.length; _hi++) {
            enqueueAnimation(hpJobsSb[_hi]);
        }
        if (spellStageNid != null) {
            setTimeout(function() { _showSpellStage(spellStageNid); }, 0);
        }
    });
    // === SANDBOX-STATE-HANDLER-END ===

    socket.on('sandbox_save_blob', function(data) {
        // Plan 14.6-03: download the blob as a JSON file
        var payload = data && data.payload;
        if (!payload) return;
        var json = JSON.stringify(payload, null, 2);
        var blob = new Blob([json], { type: 'application/json' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        var ts = new Date().toISOString().replace(/[:.]/g, '-');
        a.download = 'sandbox-' + ts + '.json';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });

    // Phase 14.6-03: Server-side save slot events
    socket.on('sandbox_slot_list', function(data) {
        if (typeof renderSandboxSlotList === 'function') {
            renderSandboxSlotList((data && data.slots) || []);
        }
    });
    socket.on('sandbox_slot_saved', function(data) {
        var input = document.getElementById('sandbox-slot-name');
        if (input && data && input.value === data.slot_name) input.value = '';
    });
    socket.on('sandbox_slot_deleted', function(_data) {
        // No-op; the slot list refresh handles UI update via sandbox_slot_list
    });
}

function renderSandbox() {
    if (!sandboxState) return;

    // Renderer reuse contract: call the SAME renderBoard / renderHand,
    // passing sandbox mount targets via opts. The sandbox state is RAW
    // god view from the server -- we never call filter_state_for_player
    // or filter_state_for_spectator. Per spec D1: fixed dual-perspective,
    // no flip. HTML places P2 hand at TOP and P1 hand at BOTTOM; the
    // board orientation is locked to match (P2 back row at top, P1 back
    // row at bottom) regardless of which player is currently active.

    var boardMount = document.getElementById('sandbox-board');
    var handP0Mount = document.getElementById('sandbox-hand-p0');  // P1 hand, visual BOTTOM
    var handP1Mount = document.getElementById('sandbox-hand-p1');  // P2 hand, visual TOP

    // Fixed perspective: perspectiveIdx=0 → rowOrder=[4,3,2,1,0], so row 0
    // (P1 back row) renders at bottom near P1's hand, row 4 (P2 back row)
    // renders at top near P2's hand. Do NOT key this off sandboxActiveViewIdx
    // — that would flip the board every time the active player toggles.
    var SANDBOX_PERSPECTIVE = 0;

    if (boardMount && typeof renderBoard === 'function') {
        renderBoard({
            mount: boardMount,
            state: sandboxState,
            perspectiveIdx: SANDBOX_PERSPECTIVE,
            legalActions: sandboxLegalActions,
        });
    }
    if (handP0Mount && typeof renderHand === 'function') {
        renderHand({
            mount: handP0Mount,
            state: sandboxState,
            ownerIdx: 0,
            godView: true,
            legalActions: sandboxLegalActions,
        });
    }
    if (handP1Mount && typeof renderHand === 'function') {
        renderHand({
            mount: handP1Mount,
            state: sandboxState,
            ownerIdx: 1,
            godView: true,
            legalActions: sandboxLegalActions,
        });
    }
    renderSandboxStats();
    // Pending-state modals (tutor/death/revive/post-move-attack) — sandbox
    // reuses the live-game handlers so modal banners + valid-target cell
    // highlights behave the same as a real duel.
    if (typeof syncPendingPostMoveAttackUI === 'function') syncPendingPostMoveAttackUI();
    if (typeof syncPendingTutorUI === 'function') syncPendingTutorUI();
    if (typeof syncPendingConjureDeployUI === 'function') syncPendingConjureDeployUI();
    if (typeof syncPendingDeathTargetUI === 'function') syncPendingDeathTargetUI();
    if (typeof syncPendingReviveUI === 'function') syncPendingReviveUI();
    if (typeof highlightBoard === 'function') highlightBoard();
}

function renderSandboxStats() {
    // Phase 14.6 (redesign): now populates the live-game-style info bars
    // (opp-bar for P2 on top, self-bar for P1 on bottom) that live inside
    // #screen-sandbox, plus the room-bar header (active player / phase /
    // turn number). The old #sandbox-stats container has been removed.
    if (!sandboxState || !sandboxState.players) return;
    var p0 = sandboxState.players[0];
    var p1 = sandboxState.players[1];
    if (!p0 || !p1) return;

    function setText(id, val) {
        var el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    // Player 1 info bar (bottom)
    // Mana is a banking pool -- single number, not X/Y (matches duel screen).
    setText('sandbox-p0-hp', p0.hp);
    setText('sandbox-p0-mana', p0.current_mana);
    setText('sandbox-p0-handcount', p0.hand ? p0.hand.length : 0);
    setText('sandbox-p0-deck', p0.deck ? p0.deck.length : 0);
    setText('sandbox-p0-grave', p0.grave ? p0.grave.length : 0);
    setText('sandbox-p0-exhaust', p0.exhaust ? p0.exhaust.length : 0);

    // Player 2 info bar (top)
    setText('sandbox-p1-hp', p1.hp);
    setText('sandbox-p1-mana', p1.current_mana);
    setText('sandbox-p1-handcount', p1.hand ? p1.hand.length : 0);
    setText('sandbox-p1-deck', p1.deck ? p1.deck.length : 0);
    setText('sandbox-p1-grave', p1.grave ? p1.grave.length : 0);
    setText('sandbox-p1-exhaust', p1.exhaust ? p1.exhaust.length : 0);

    // Room bar
    setText('sandbox-active-label', 'Active: P' + ((sandboxState.active_player_idx || 0) + 1));
    var phaseLabel = (sandboxState.phase === 1) ? 'REACT' : 'ACTION';
    var phaseEl = document.getElementById('sandbox-phase-badge');
    if (phaseEl) {
        phaseEl.textContent = phaseLabel;
        phaseEl.classList.toggle('phase-react', sandboxState.phase === 1);
        phaseEl.classList.toggle('phase-action', sandboxState.phase !== 1);
    }
    setText('sandbox-turn-number', 'Turn ' + sandboxState.turn_number);
}

// Wire the static .sandbox-pile-btn buttons once at activation time.
// (Previously rebuilt on every renderSandboxStats -- now the buttons are
// static in the HTML info bars, so we attach listeners exactly once.)
function _wireSandboxPileButtons() {
    document.querySelectorAll('#screen-sandbox .sandbox-pile-btn').forEach(function(btn) {
        if (btn.dataset.sandboxPileBound === '1') return;
        btn.dataset.sandboxPileBound = '1';
        btn.addEventListener('click', function() {
            if (!sandboxState) return;
            var pileKey = btn.dataset.pile;
            var playerIdx = parseInt(btn.dataset.player, 10);
            var player = sandboxState.players[playerIdx];
            if (!player) return;
            var ids;
            var title;
            if (pileKey === 'graveyard') {
                ids = player.grave || [];
                title = 'P' + (playerIdx + 1) + ' Grave';
            } else if (pileKey === 'exhaust') {
                ids = player.exhaust || [];
                title = 'P' + (playerIdx + 1) + ' Exhaust';
            } else {
                ids = player.deck || [];
                title = 'P' + (playerIdx + 1) + ' Deck';
            }
            showPileModal(title, ids, { pileType: pileKey, playerIdx: playerIdx });
        });
    });
}

// ---------------------------------------------------------------------------
// Phase 14.6-03: Interactive toolbar wiring
// ---------------------------------------------------------------------------

function setupSandboxToolbar() {
    if (_sandboxToolbarBound) return;
    _sandboxToolbarBound = true;

    // ---- A1. Card search + zone-aware add (DEV-02) ----
    var searchInput = document.getElementById('sandbox-search');
    var resultsBox = document.getElementById('sandbox-search-results');
    if (searchInput && resultsBox) {
        searchInput.addEventListener('input', function() {
            var q = searchInput.value.trim().toLowerCase();
            if (!q) { resultsBox.hidden = true; resultsBox.innerHTML = ''; return; }
            if (!sandboxCardDefs) return;
            var matches = [];
            var keys = Object.keys(sandboxCardDefs);
            for (var i = 0; i < keys.length; i++) {
                var nidStr = keys[i];
                var def = sandboxCardDefs[nidStr];
                if (def && def.name && def.name.toLowerCase().indexOf(q) !== -1) {
                    matches.push({ nid: parseInt(nidStr, 10), def: def });
                    if (matches.length >= 30) break;
                }
            }
            resultsBox.innerHTML = matches.map(function(m) {
                var cost = (m.def.mana_cost != null) ? m.def.mana_cost : '-';
                return '<div class="sandbox-search-result" data-nid="' + m.nid + '">' +
                       '<span class="sandbox-search-result-name">' + escapeHtml(m.def.name) + '</span>' +
                       '<span class="sandbox-search-result-meta">cost ' + cost + '</span>' +
                       '</div>';
            }).join('');
            resultsBox.hidden = matches.length === 0;
        });
        resultsBox.addEventListener('click', function(e) {
            var row = e.target.closest('.sandbox-search-result');
            if (!row) return;
            var nid = parseInt(row.dataset.nid, 10);
            // Add to currently selected zone immediately
            socket.emit('sandbox_add_card_to_zone', {
                player_idx: sandboxAddTargetIdx,
                card_numeric_id: nid,
                zone: sandboxAddZone,
            });
            // Also stage for optional board click-to-place
            sandboxStageCard(nid);
            // Dismiss dropdown + clear search
            resultsBox.hidden = true;
            resultsBox.innerHTML = '';
            searchInput.value = '';
        });
        document.addEventListener('click', function(e) {
            if (!e.target.closest('.sandbox-search-wrap')) resultsBox.hidden = true;
        });
    }

    // ---- A2. Target toggle (which player to add to) ----
    document.querySelectorAll('.sandbox-target-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            sandboxAddTargetIdx = parseInt(btn.dataset.target, 10);
            document.querySelectorAll('.sandbox-target-btn').forEach(function(b) {
                b.classList.toggle('active', b === btn);
            });
        });
    });

    // ---- A3. Zone selector (button row + hidden select sync) ----
    var zoneSelect = document.getElementById('sandbox-zone-select');
    if (zoneSelect) {
        zoneSelect.addEventListener('change', function() {
            sandboxAddZone = zoneSelect.value;
        });
    }
    document.querySelectorAll('.sandbox-zone-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            sandboxAddZone = btn.dataset.zone;
            if (zoneSelect) zoneSelect.value = sandboxAddZone;
            document.querySelectorAll('.sandbox-zone-btn').forEach(function(b) {
                b.classList.toggle('active', b === btn);
            });
        });
    });

    // ---- A4. Control toggle (set active_player_idx server-side; layout does NOT change) ----
    document.querySelectorAll('.sandbox-control-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var idx = parseInt(btn.dataset.control, 10);
            socket.emit('sandbox_set_active_player', { player_idx: idx });
        });
    });

    // ---- A5. Undo / Redo / Reset ----
    var undoBtn = document.getElementById('sandbox-undo-btn');
    if (undoBtn) undoBtn.addEventListener('click', function() { socket.emit('sandbox_undo'); });
    var redoBtn = document.getElementById('sandbox-redo-btn');
    if (redoBtn) redoBtn.addEventListener('click', function() { socket.emit('sandbox_redo'); });
    var resetBtn = document.getElementById('sandbox-reset-btn');
    if (resetBtn) resetBtn.addEventListener('click', function() {
        if (confirm('Reset sandbox to empty? This will clear undo history.')) {
            socket.emit('sandbox_reset');
        }
    });

    // ---- A6. Save / Load (client-side JSON file) ----
    var saveBtn = document.getElementById('sandbox-save-btn');
    if (saveBtn) saveBtn.addEventListener('click', function() { socket.emit('sandbox_save'); });
    var loadBtn = document.getElementById('sandbox-load-btn');
    var fileInput = document.getElementById('sandbox-load-file');
    if (loadBtn && fileInput) {
        loadBtn.addEventListener('click', function() { fileInput.click(); });
        fileInput.addEventListener('change', function(e) {
            var file = e.target.files[0];
            if (!file) return;
            var reader = new FileReader();
            reader.onload = function(ev) {
                try {
                    var payload = JSON.parse(ev.target.result);
                    socket.emit('sandbox_load', { payload: payload });
                } catch (err) {
                    alert('Invalid JSON file: ' + err.message);
                }
                fileInput.value = '';
            };
            reader.readAsText(file);
        });
    }

    // ---- A7. Share code (TextEncoder/TextDecoder -- NEVER escape/unescape) ----
    var shareBtn = document.getElementById('sandbox-share-btn');
    if (shareBtn) shareBtn.addEventListener('click', function() {
        if (!sandboxState) return;
        var payload = { state: sandboxState, active_view_idx: sandboxActiveViewIdx };
        var code = sandboxEncodeShareCode(payload);
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(code).then(function() {
                alert('Sandbox code copied to clipboard (' + code.length + ' chars)');
            }, function() {
                window.prompt('Copy this sandbox code:', code);
            });
        } else {
            window.prompt('Copy this sandbox code:', code);
        }
    });
    var pasteBtn = document.getElementById('sandbox-paste-btn');
    if (pasteBtn) pasteBtn.addEventListener('click', function() {
        var code = window.prompt('Paste sandbox code:');
        if (!code) return;
        try {
            var payload = sandboxDecodeShareCode(code.trim());
            socket.emit('sandbox_load', { payload: payload });
        } catch (err) {
            alert('Invalid sandbox code: ' + err.message);
        }
    });

    // ---- B. Cheat inputs (DEV-06) --------------------------------------
    // Emit on blur OR Enter -- NEVER on every keystroke (would spam the
    // server and feel laggy). The server applies the value with NO
    // validation -- full cheat mode.
    document.querySelectorAll('.sandbox-cheat-input').forEach(function(input) {
        function commit() {
            var playerIdx = parseInt(input.dataset.player, 10);
            var field = input.dataset.field;
            var raw = input.value.trim();
            if (raw === '') return;
            var value = parseInt(raw, 10);
            if (Number.isNaN(value)) return;
            socket.emit('sandbox_set_player_field', {
                player_idx: playerIdx,
                field: field,
                value: value,
            });
        }
        input.addEventListener('blur', commit);
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                input.blur();  // triggers commit
            }
        });
    });

    // ---- C. Deck import (DEV-03) ---------------------------------------
    // Reuses the existing deck-builder localStorage helper loadDeckSlots()
    // which returns [{name, cards: {numericId: count}}, ...]
    var importDeckBtn = document.getElementById('sandbox-import-deck-btn');
    if (importDeckBtn) importDeckBtn.addEventListener('click', function() {
        var slots = (typeof loadDeckSlots === 'function') ? loadDeckSlots() : [];
        if (!slots.length) {
            alert('No saved decks found. Build one in the Deck Builder first.');
            return;
        }
        var lines = slots.map(function(s, i) {
            var total = (typeof getDeckTotal === 'function') ? getDeckTotal(s.cards) : '?';
            return i + ': ' + s.name + ' (' + total + ' cards)';
        });
        var choiceStr = window.prompt('Pick a deck to import:\n' + lines.join('\n') + '\n\nEnter index:');
        if (choiceStr == null) return;
        var choice = parseInt(choiceStr, 10);
        if (Number.isNaN(choice) || choice < 0 || choice >= slots.length) {
            alert('Invalid choice');
            return;
        }
        var targetStr = window.prompt('Import to which player? Enter 1 or 2:');
        if (targetStr == null) return;
        var targetIdx = parseInt(targetStr, 10) - 1;
        if (targetIdx !== 0 && targetIdx !== 1) {
            alert('Player must be 1 or 2');
            return;
        }
        var deckMap = slots[choice].cards || {};
        var flat = [];
        Object.keys(deckMap).forEach(function(nidStr) {
            var nid = parseInt(nidStr, 10);
            var count = deckMap[nidStr];
            for (var k = 0; k < count; k++) flat.push(nid);
        });
        socket.emit('sandbox_import_deck', {
            player_idx: targetIdx,
            deck_card_ids: flat,
        });
    });

    // ---- D. Server save slots (DEV-08) ---------------------------------
    var slotSaveBtn = document.getElementById('sandbox-slot-save-btn');
    if (slotSaveBtn) slotSaveBtn.addEventListener('click', function() {
        var input = document.getElementById('sandbox-slot-name');
        var name = (input && input.value || '').trim();
        if (!name) { alert('Enter a slot name'); return; }
        if (!/^[a-zA-Z0-9_-]{1,64}$/.test(name)) {
            alert('Slot name must be 1-64 chars of letters, digits, underscore, or dash.');
            return;
        }
        socket.emit('sandbox_save_slot', { slot_name: name });
    });
    var slotRefreshBtn = document.getElementById('sandbox-slot-refresh-btn');
    if (slotRefreshBtn) slotRefreshBtn.addEventListener('click', function() {
        socket.emit('sandbox_list_slots');
    });
}

// ---- E. Move-card popover (DEV-03) ----------------------------------------
// Called from showPileModal (in sandbox mode) and from renderHand (when
// sandboxMode is true). Opens a small zone-picker popover anchored to the
// clicked button; emits sandbox_move_card.
var SANDBOX_ALL_ZONES = [
    { value: 'hand',        label: 'Hand' },
    { value: 'deck_top',    label: 'Deck top' },
    { value: 'deck_bottom', label: 'Deck bottom' },
    { value: 'graveyard',   label: 'Graveyard' },
    { value: 'exhaust',     label: 'Exhaust' },
];

function openSandboxMovePopover(anchorEl, playerIdx, cardNumericId, srcZone) {
    document.querySelectorAll('.sandbox-move-popover').forEach(function(el) { el.remove(); });
    var pop = document.createElement('div');
    pop.className = 'sandbox-move-popover';
    SANDBOX_ALL_ZONES.forEach(function(z) {
        if (z.value === srcZone) return;
        var btn = document.createElement('button');
        btn.className = 'sandbox-move-btn';
        btn.textContent = z.label;
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            socket.emit('sandbox_move_card', {
                player_idx: playerIdx,
                card_numeric_id: cardNumericId,
                src_zone: srcZone,
                dst_zone: z.value,
            });
            pop.remove();
        });
        pop.appendChild(btn);
    });
    var rect = anchorEl.getBoundingClientRect();
    pop.style.top = (rect.bottom + window.scrollY) + 'px';
    pop.style.left = (rect.left + window.scrollX) + 'px';
    document.body.appendChild(pop);
    setTimeout(function() {
        document.addEventListener('click', function closeOnce(ev) {
            if (!pop.contains(ev.target)) {
                pop.remove();
                document.removeEventListener('click', closeOnce);
            }
        });
    }, 0);
}

function makeSandboxMoveButton(playerIdx, cardNumericId, srcZone) {
    var btn = document.createElement('button');
    btn.className = 'sandbox-move-btn';
    btn.textContent = 'Move to...';
    btn.addEventListener('click', function(e) {
        e.stopPropagation();
        openSandboxMovePopover(btn, playerIdx, cardNumericId, srcZone);
    });
    return btn;
}

// ---- E2. Staged card preview + drag-to-zone --------------------------------
function sandboxStageCard(nid) {
    var defs = sandboxCardDefs || cardDefs;
    var def = defs && defs[nid];
    if (!def) return;
    var staged = document.getElementById('sandbox-staged-card');
    if (!staged) return;
    var artStyle = def.card_id
        ? 'background-image:url(/static/art/' + def.card_id + '.png)'
        : '';
    staged.innerHTML =
        '<div class="staged-art" style="' + artStyle + '"></div>' +
        '<span class="staged-name">' + escapeHtml(def.name) + '</span>' +
        '<span class="staged-cost">' + (def.mana_cost != null ? def.mana_cost : '-') + '\u{1F4A7}</span>' +
        '<span class="staged-drag-hint">CLICK CELL / DRAG</span>';
    staged.dataset.nid = nid;
    staged.hidden = false;
    // Click staged card → add to current zone selection
    if (!staged._clickBound) {
        staged._clickBound = true;
        staged.addEventListener('click', function() {
            var clickNid = parseInt(staged.dataset.nid, 10);
            if (isNaN(clickNid)) return;
            socket.emit('sandbox_add_card_to_zone', {
                player_idx: sandboxAddTargetIdx,
                card_numeric_id: clickNid,
                zone: sandboxAddZone,
            });
        });
    }
    // Wire drag handlers (idempotent — only binds once via the flag)
    if (!staged._dragBound) {
        staged._dragBound = true;
        staged.addEventListener('dragstart', function(e) {
            e.dataTransfer.setData('text/plain', staged.dataset.nid);
            e.dataTransfer.effectAllowed = 'copy';
            // Highlight all valid drop zones
            setTimeout(function() {
                document.querySelectorAll('#screen-sandbox .hand-container, #screen-sandbox .sandbox-pile-btn, #sandbox-board .board-cell')
                    .forEach(function(el) { el.classList.add('drop-target-active'); });
            }, 0);
        });
        staged.addEventListener('dragend', function() {
            document.querySelectorAll('.drop-target-active, .drop-target-hover')
                .forEach(function(el) {
                    el.classList.remove('drop-target-active');
                    el.classList.remove('drop-target-hover');
                });
        });
    }
    // Ensure drop zones are wired (idempotent)
    sandboxWireDropZones();
}

var _sandboxDropZonesBound = false;
function sandboxWireDropZones() {
    if (_sandboxDropZonesBound) return;
    _sandboxDropZonesBound = true;

    function handleDrop(playerIdx, zone) {
        return function(e) {
            e.preventDefault();
            var nid = parseInt(e.dataTransfer.getData('text/plain'), 10);
            if (isNaN(nid)) return;
            socket.emit('sandbox_add_card_to_zone', {
                player_idx: playerIdx,
                card_numeric_id: nid,
                zone: zone,
            });
        };
    }
    function allowDrop(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
    }
    function hoverIn(e) { e.currentTarget.classList.add('drop-target-hover'); }
    function hoverOut(e) { e.currentTarget.classList.remove('drop-target-hover'); }

    // Hand containers
    var handP0 = document.getElementById('sandbox-hand-p0');
    var handP1 = document.getElementById('sandbox-hand-p1');
    if (handP0) {
        handP0.addEventListener('dragover', allowDrop);
        handP0.addEventListener('dragenter', hoverIn);
        handP0.addEventListener('dragleave', hoverOut);
        handP0.addEventListener('drop', handleDrop(0, 'hand'));
    }
    if (handP1) {
        handP1.addEventListener('dragover', allowDrop);
        handP1.addEventListener('dragenter', hoverIn);
        handP1.addEventListener('dragleave', hoverOut);
        handP1.addEventListener('drop', handleDrop(1, 'hand'));
    }

    // Pile buttons (grave / exhaust / deck)
    document.querySelectorAll('#screen-sandbox .sandbox-pile-btn').forEach(function(btn) {
        var playerIdx = parseInt(btn.dataset.player, 10);
        var pile = btn.dataset.pile;
        btn.addEventListener('dragover', allowDrop);
        btn.addEventListener('dragenter', hoverIn);
        btn.addEventListener('dragleave', hoverOut);
        btn.addEventListener('drop', handleDrop(playerIdx, pile));
    });

    // Board cells — drop places minion directly on the grid
    var boardEl = document.getElementById('sandbox-board');
    if (boardEl) {
        boardEl.addEventListener('dragover', allowDrop);
        boardEl.addEventListener('drop', function(e) {
            e.preventDefault();
            var cell = e.target.closest('.board-cell');
            if (!cell) return;
            var nid = parseInt(e.dataTransfer.getData('text/plain'), 10);
            if (isNaN(nid)) return;
            var row = parseInt(cell.dataset.row, 10);
            var col = parseInt(cell.dataset.col, 10);
            socket.emit('sandbox_place_on_board', {
                player_idx: sandboxAddTargetIdx,
                card_numeric_id: nid,
                row: row,
                col: col,
            });
        });
        // Per-cell hover highlight (delegated)
        boardEl.addEventListener('dragenter', function(e) {
            var cell = e.target.closest('.board-cell');
            if (cell) cell.classList.add('drop-target-hover');
        });
        boardEl.addEventListener('dragleave', function(e) {
            var cell = e.target.closest('.board-cell');
            if (cell) cell.classList.remove('drop-target-hover');
        });
    }
}

// ---- F. Server-saves list rendering --------------------------------------
function renderSandboxSlotList(slots) {
    sandboxKnownSlots = slots || [];
    var list = document.getElementById('sandbox-slots-list');
    if (!list) return;
    list.innerHTML = '';
    if (!sandboxKnownSlots.length) {
        list.innerHTML = '<div class="sandbox-slots-empty">No server slots yet</div>';
        return;
    }
    sandboxKnownSlots.forEach(function(name) {
        var row = document.createElement('div');
        row.className = 'sandbox-slot-row';
        row.dataset.slotName = name;  // stable test hook
        var nameSpan = document.createElement('span');
        nameSpan.className = 'sandbox-slot-name';
        nameSpan.textContent = name;
        var loadBtn = document.createElement('button');
        loadBtn.className = 'btn btn-sm sandbox-slot-load-btn';
        loadBtn.textContent = 'Load';
        loadBtn.addEventListener('click', function() {
            socket.emit('sandbox_load_slot', { slot_name: name });
        });
        var deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn btn-sm sandbox-slot-delete-btn';
        deleteBtn.textContent = 'Delete';
        deleteBtn.addEventListener('click', function() {
            if (confirm('Delete server slot "' + name + '"? This cannot be undone.')) {
                socket.emit('sandbox_delete_slot', { slot_name: name });
            }
        });
        row.appendChild(nameSpan);
        row.appendChild(loadBtn);
        row.appendChild(deleteBtn);
        list.appendChild(row);
    });
}

// ---- G. Share-code helpers (TextEncoder/TextDecoder, NOT escape/unescape) ----
function sandboxEncodeShareCode(stateDict) {
    var json = JSON.stringify(stateDict);
    var bytes = new TextEncoder().encode(json);
    var binary = '';
    for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
}
function sandboxDecodeShareCode(code) {
    var binary = atob(code);
    var bytes = Uint8Array.from(binary, function(c) { return c.charCodeAt(0); });
    var json = new TextDecoder().decode(bytes);
    return JSON.parse(json);
}
function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function(c) {
        return { '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c];
    });
}

// ---- H. Toolbar-state renderer --------------------------------------------
// Called from the sandbox_state handler. Updates history pill, active-control
// highlight, undo/redo enabled state, and syncs cheat inputs (without firing
// blur, which would cause a feedback loop).
function renderSandboxToolbarState() {
    var status = document.getElementById('sandbox-history-status');
    if (status) status.textContent = 'undo:' + sandboxUndoDepth + ' redo:' + sandboxRedoDepth;
    document.querySelectorAll('.sandbox-control-btn').forEach(function(btn) {
        var idx = parseInt(btn.dataset.control, 10);
        btn.classList.toggle('active', idx === sandboxActiveViewIdx);
    });
    var undoBtn = document.getElementById('sandbox-undo-btn');
    var redoBtn = document.getElementById('sandbox-redo-btn');
    if (undoBtn) undoBtn.disabled = sandboxUndoDepth === 0;
    if (redoBtn) redoBtn.disabled = sandboxRedoDepth === 0;
    // Sync cheat input values (skip focused input so we don't clobber typing)
    if (sandboxState && sandboxState.players) {
        document.querySelectorAll('.sandbox-cheat-input').forEach(function(input) {
            if (document.activeElement === input) return;
            var playerIdx = parseInt(input.dataset.player, 10);
            var field = input.dataset.field;
            var player = sandboxState.players[playerIdx];
            if (player && player[field] != null) {
                input.value = String(player[field]);
            }
        });
    }
}

// === SANDBOX-SECTION-END ===
