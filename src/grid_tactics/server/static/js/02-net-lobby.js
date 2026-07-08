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
        // Compliance audit 2026-07-06: #conn-dot/#conn-text don't exist in
        // the current DOM — show a stage toast during games instead.
        try {
            var gsEl = document.getElementById('screen-game');
            if (gsEl && gsEl.classList.contains('active')
                    && !document.getElementById('conn-lost-toast')) {
                var t = document.createElement('div');
                t.id = 'conn-lost-toast';
                t.className = 'tutor-toast';
                t.style.background = '#6e2a18';
                t.textContent = '⚡ Connection lost — reconnecting…';
                _stageMount().appendChild(t);
            }
        } catch (e) { /* defensive */ }
    });
    socket.on('connect', function() {
        var tGone = document.getElementById('conn-lost-toast');
        if (tGone) tGone.remove();
        // PREGAME (2026-07-08): if the socket dropped mid-pregame, ask the
        // server to re-emit the current stage. (Full token-based reconnect
        // is Phase 15 — this covers same-sid transport recoveries.)
        try {
            if (window._pregameActive) socket.emit('pregame_resync', {});
        } catch (e) { /* defensive */ }
    });
    // Register all event handlers
    socket.on('room_created', onRoomCreated);
    socket.on('room_joined', onRoomJoined);
    socket.on('rooms_list', onRoomsList);
    socket.on('player_joined', onPlayerJoined);
    socket.on('player_ready', onPlayerReady);
    socket.on('game_start', onGameStart);
    // PREGAME (user 2026-07-08): RPS decides who goes first, then mulligan,
    // then the normal game_start arrives. Handlers live in 10-modals.js.
    socket.on('pregame_rps', onPregameRps);
    socket.on('rps_result', onRpsResult);
    socket.on('pregame_mulligan', onPregameMulligan);
    socket.on('pregame_status', onPregameStatus);
    socket.on('state_update', onStateUpdate);
    // Phase 14.8-04a: subscribe to the new engine_events stream from live PvP.
    // Handler enqueues each event into the eventQueue; the legacy state_update
    // path still applies state authoritatively in 04a (snapshot path is
    // removed in plan 05).
    socket.on('engine_events', onEngineEvents);
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
        // Multiline box (user 2026-07-06): Enter sends, Shift+Enter = newline
        chatInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
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
// Fatigue nudge — turn-structure redesign (2026-07): fatigue now fires
// ONLY when the turn-start auto-draw finds an empty deck, dealing
// escalating damage (10/20/30...). PASS is free and NEVER deals fatigue.
// Big skull + -N❤️ + "DECK EMPTY — FATIGUE" in Montserrat Black.
function triggerFatigueNudge(damage, playerIdx) {
    playSfx('defeat');
    var dmgText = (typeof damage === 'number' && damage > 0)
        ? ('-' + damage + '❤️') : '💔';
    var who = 'DECK EMPTY — FATIGUE';
    try {
        if (playerIdx != null) {
            if (sandboxMode || isSpectator) {
                who = 'P' + (playerIdx + 1) + ' — ' + who;
            } else if (myPlayerIdx != null && playerIdx !== myPlayerIdx) {
                who = (opponentName || 'OPPONENT').toUpperCase() + ' — ' + who;
            }
        }
    } catch (e) { /* defensive — label is cosmetic */ }
    runNudge('nudge-no-action',
        '<div class="no-action-skull">💀</div>' +
        '<div class="no-action-damage">' + dmgText + '</div>' +
        '<div class="no-action-text">' + who + '</div>',
        3000);
}

function runNudge(id, innerHtml, durationMs) {
    var existing = document.getElementById(id);
    if (existing) existing.remove();
    var overlay = document.createElement('div');
    overlay.id = id;
    overlay.className = 'nudge-overlay ' + id;
    overlay.innerHTML = innerHtml;
    // Stage-centered: in-game banners center between the tooltip column's
    // right edge and the screen's right edge (mount inside scaled layout).
    (document.querySelector('.screen.active .game-layout') || document.body).appendChild(overlay);
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
            drops += '<div class="rain-drop" style="left:' + left + '%;' +
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

// Render the public open-rooms list. Fired on connect, on manual refresh,
// and pushed by the server whenever a room is created or fills up.
function onRoomsList(data) {
    var listEl = document.getElementById('rooms-list');
    if (!listEl) return;
    var rooms = (data && Array.isArray(data.rooms)) ? data.rooms : [];
    listEl.innerHTML = '';
    if (rooms.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'lobby2-rooms-empty';
        empty.textContent = 'No open games yet — create one to start.';
        listEl.appendChild(empty);
        return;
    }
    var nowSec = Date.now() / 1000;
    rooms.forEach(function(r, idx) {
        var row = document.createElement('div');
        row.className = 'lobby2-room-row';
        // staggered reveal on fresh-list render
        row.style.setProperty('--row-delay', (idx * 45) + 'ms');
        row.innerHTML =
            '<span class="lobby2-room-who"></span>' +
            '<span class="lobby2-room-rcode"></span>' +
            '<span class="lobby2-room-age"></span>' +
            '<span class="lobby2-room-go">Join ▸</span>';
        row.querySelector('.lobby2-room-who').textContent = r.creator_name || '(anon)';
        row.querySelector('.lobby2-room-rcode').textContent = r.code;
        var age = Math.max(0, Math.floor(nowSec - (r.created_at || nowSec)));
        var ageLabel = age < 60 ? (age + 's')
                     : age < 3600 ? (Math.floor(age / 60) + 'm')
                     : (Math.floor(age / 3600) + 'h');
        row.querySelector('.lobby2-room-age').textContent = ageLabel;
        row.addEventListener('click', function() {
            var name = (typeof getCurrentDisplayName === 'function') ? getCurrentDisplayName() : null;
            if (!name) {
                showLobbyStatus('Please enter your name first.', 'error');
                return;
            }
            myName = name;
            saveDisplayName(name);
            socket.emit('join_room', { display_name: name, room_code: r.code });
        });
        listEl.appendChild(row);
    });
}

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
        // Fill the lobby hero with a real rendered card
        renderLobbyHero();
    }
}

// Lobby hero: a slow carousel that fades through real rendered cards. Starts
// on a showpiece card, then cycles a shuffled deck. No-op until card defs have
// loaded and the #lobby-hero element exists. Pauses while the lobby is hidden.
var LOBBY_HERO_CARD = 'erebus';
var LOBBY_HERO_HOLD_MS = 7000;   // how long each card is shown
var LOBBY_HERO_FADE_MS = 800;    // crossfade duration (match the CSS transition)
var _lobbyHeroCards = null;   // shuffled array of card defs
var _lobbyHeroIdx = 0;
var _lobbyHeroTimer = null;
function renderLobbyHero() {
    var host = document.getElementById('lobby-hero');
    if (!host) return;
    var defs = allCardDefs || cardDefs;
    if (!defs) return;

    if (!_lobbyHeroCards) {
        _lobbyHeroCards = Object.keys(defs).map(function(k) { return defs[k]; }).filter(Boolean);
        // Fisher–Yates shuffle so the order is different each visit
        for (var i = _lobbyHeroCards.length - 1; i > 0; i--) {
            var j = Math.floor(Math.random() * (i + 1));
            var t = _lobbyHeroCards[i]; _lobbyHeroCards[i] = _lobbyHeroCards[j]; _lobbyHeroCards[j] = t;
        }
        // Lead with the showpiece card if it's present
        var ei = _lobbyHeroCards.findIndex(function(d) { return d.card_id === LOBBY_HERO_CARD; });
        if (ei > 0) { _lobbyHeroCards.unshift(_lobbyHeroCards.splice(ei, 1)[0]); }
        _lobbyHeroIdx = 0;
    }

    _showLobbyHeroCard(host, _lobbyHeroCards[_lobbyHeroIdx], true);
    _preloadHeroArt(_lobbyHeroCards[(_lobbyHeroIdx + 1) % _lobbyHeroCards.length]);

    if (_lobbyHeroTimer) clearInterval(_lobbyHeroTimer);
    _lobbyHeroTimer = setInterval(function() {
        var screen = document.getElementById('screen-lobby');
        if (!screen || !screen.classList.contains('active')) return;   // pause when hidden
        var h = document.getElementById('lobby-hero');
        if (!h || !_lobbyHeroCards || !_lobbyHeroCards.length) return;
        _lobbyHeroIdx = (_lobbyHeroIdx + 1) % _lobbyHeroCards.length;
        _showLobbyHeroCard(h, _lobbyHeroCards[_lobbyHeroIdx], false);
        // Preload the card AFTER this one so its art is cached before its turn.
        _preloadHeroArt(_lobbyHeroCards[(_lobbyHeroIdx + 1) % _lobbyHeroCards.length]);
    }, LOBBY_HERO_HOLD_MS);
}
// Warm the browser cache with a card's full-art PNG ahead of time.
function _preloadHeroArt(def) {
    if (!def || !def.card_id) return;
    var img = new Image();
    img.src = _cardArtUrl(def.card_id, true);
}
// Render the card straight to FULL art (no thumb→full pop): the art is already
// preloaded, so paint the full PNG immediately.
function _renderHeroNow(host, def) {
    host.innerHTML = renderCardFrame(def, { context: 'deck-builder' });
    var artEl = host.querySelector('.cf2-artbg, .card-art');
    if (artEl) {
        artEl.style.backgroundImage = 'url(' + _cardArtUrl(def.card_id, true) + ')';
        artEl.dataset.fullArt = '1';
    }
    // Give each card a slightly different tilt + tiny nudge, like flipping
    // through a physical stack. Centred on the base -6deg lean.
    var card = host.querySelector('.card-frame-full');
    if (card) {
        var rot = (-6 + (Math.random() * 2 - 1) * 5).toFixed(2);   // ~ -11deg .. -1deg
        var dx = ((Math.random() * 2 - 1) * 7).toFixed(1);
        var dy = ((Math.random() * 2 - 1) * 7).toFixed(1);
        card.style.transform = 'rotate(' + rot + 'deg) translate(' + dx + 'px, ' + dy + 'px)';
    }
    host.style.opacity = '1';
}
function _showLobbyHeroCard(host, def, instant) {
    if (!host || !def) return;
    if (instant) {
        // First paint: preload the image, then render (avoids an initial pop).
        var i0 = new Image();
        i0.onload = i0.onerror = function() { _renderHeroNow(host, def); };
        i0.src = _cardArtUrl(def.card_id, true);
        return;
    }
    // Crossfade: fade out, and only swap once BOTH the fade has finished AND the
    // next image is decoded — so the incoming card never flashes half-loaded.
    host.style.opacity = '0';
    var faded = false, loaded = false;
    var go = function() { if (faded && loaded) _renderHeroNow(host, def); };
    var img = new Image();
    img.onload = img.onerror = function() { loaded = true; go(); };
    img.src = _cardArtUrl(def.card_id, true);
    setTimeout(function() { faded = true; go(); }, LOBBY_HERO_FADE_MS);
}

function onError(data) {
    var msg = data && data.msg ? data.msg : 'An error occurred.';
    showLobbyStatus(msg, 'error');
    // Compliance audit 2026-07-06: during a game the lobby pill is invisible
    // — surface server rejections as a stage toast so the player sees them.
    try {
        var gsEl = document.getElementById('screen-game');
        if (gsEl && gsEl.classList.contains('active')) {
            var errToast = document.createElement('div');
            errToast.className = 'tutor-toast';
            errToast.style.background = '#6e2a18';
            errToast.style.borderColor = '#b5623a';
            errToast.textContent = '⚠ ' + msg;
            _stageMount().appendChild(errToast);
            setTimeout(function() {
                errToast.classList.add('fade-out');
                setTimeout(function() { errToast.remove(); }, 600);
            }, 2600);
        }
    } catch (e) { /* defensive */ }
    // Phase 14.8 fix: the server now rejects invalid decks in handle_ready
    // with an 'error' frame, but the ready-button click handler already
    // disabled the button and set 'Waiting...' BEFORE emitting. Without a
    // re-enable path here the player could never ready up again (short of
    // a page refresh). Only restore while still on the lobby screen so
    // in-game error frames don't touch lobby UI.
    var lobbyScreen = document.getElementById('screen-lobby');
    if (lobbyScreen && lobbyScreen.classList.contains('active')) {
        var btnReady = document.getElementById('btn-ready');
        if (btnReady && btnReady.disabled) {
            btnReady.disabled = false;
            if (btnReady.dataset && btnReady.dataset.readyLabelHtml) {
                btnReady.innerHTML = btnReady.dataset.readyLabelHtml;
            } else {
                btnReady.textContent = 'Ready';
            }
        }
    }
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
    // The saved/Change state was visually redundant with the input: we now
    // always show the input section and just prefill it with the saved name.
    // The Save button stays hidden until the user types something different
    // (wired via the 'input' listener in setupLobbyHandlers).
    var inputSection = document.getElementById('name-input-section');
    var savedSection = document.getElementById('name-saved-section');
    var nameInput = document.getElementById('input-name');
    if (nameInput) nameInput.value = name;
    if (inputSection) inputSection.style.display = '';
    if (savedSection) savedSection.style.display = 'none';
    var btnSaveName = document.getElementById('btn-save-name');
    if (btnSaveName) btnSaveName.style.display = 'none';
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

    // Auto-save callsign as the user types. No explicit Save button; every
    // keystroke persists to localStorage and updates `myName`. Empty input
    // just clears the saved value and falls back to guest flow at join time.
    var nameInputEl = document.getElementById('input-name');
    var btnSaveName = document.getElementById('btn-save-name');
    if (btnSaveName) btnSaveName.style.display = 'none';
    if (nameInputEl) {
        nameInputEl.addEventListener('input', function() {
            var name = nameInputEl.value.trim();
            myName = name;
            saveDisplayName(name);
            showLobbyStatus('', '');
        });
    }

    // Fullscreen toggle (user 2026-07-05). Works on desktop + Android;
    // iPhone Safari has no Fullscreen API for elements — hide the button.
    var btnFs = document.getElementById('lobby-fullscreen');
    if (btnFs) {
        var docEl = document.documentElement;
        var fsSupported = !!(docEl.requestFullscreen || docEl.webkitRequestFullscreen);
        if (!fsSupported) {
            btnFs.style.display = 'none';
        } else {
            var fsElement = function() {
                return document.fullscreenElement || document.webkitFullscreenElement || null;
            };
            btnFs.addEventListener('click', function() {
                if (fsElement()) {
                    (document.exitFullscreen || document.webkitExitFullscreen).call(document);
                } else {
                    (docEl.requestFullscreen || docEl.webkitRequestFullscreen).call(docEl);
                }
            });
            ['fullscreenchange', 'webkitfullscreenchange'].forEach(function(ev) {
                document.addEventListener(ev, function() {
                    btnFs.classList.toggle('fs-on', !!fsElement());
                    btnFs.title = fsElement() ? 'Exit fullscreen' : 'Fullscreen';
                    // The resize re-derives --mfu/--u and re-lays-out every
                    // screen; firing all CSS transitions at once during that
                    // reads as lag. Mute them for the switch.
                    document.body.classList.add('fs-switching');
                    setTimeout(function() { document.body.classList.remove('fs-switching'); }, 400);
                });
            });
        }
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

    // Refresh open-rooms list button (manual refresh; server also pushes
    // rooms_list on any state change so this is mainly for confidence).
    var btnRefreshRooms = document.getElementById('btn-refresh-rooms');
    if (btnRefreshRooms) {
        btnRefreshRooms.addEventListener('click', function() {
            socket.emit('list_rooms');
        });
    }

    // Ask for the initial list so the panel isn't empty on first render.
    if (socket && socket.connected) {
        socket.emit('list_rooms');
    } else if (socket) {
        socket.on('connect', function() { socket.emit('list_rooms'); });
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
            // Stash the original button markup once so onError can restore
            // it verbatim if the server rejects the ready-up (invalid deck).
            if (!btnReady.dataset.readyLabelHtml) {
                btnReady.dataset.readyLabelHtml = btnReady.innerHTML;
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
    statusEl.className = 'lobby2-status ' + (type || '');
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

