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
    _deckCountsChanged();
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
    _deckCountsChanged();
}

// Perf (2026-07-05 audit): add/remove used to full-rebuild the browser grid —
// ~70-80ms of script re-creating ~1100 nodes per click. Only the badges and
// selected states change, so patch them in place; the sidebar rebuild is
// cheap (<3ms). Full renderCardBrowser() remains for filter/sort/def changes.
function _deckCountsChanged() {
    updateCardBrowserCounts();
    renderDeckSidebar();
}

function updateCardBrowserCounts() {
    var grid = document.getElementById('card-browser-grid');
    if (!grid) return;
    grid.querySelectorAll('.card-browser-item').forEach(function(w) {
        var numId = parseInt(w.dataset.numericId, 10);
        if (isNaN(numId) || w.classList.contains('card-nondeckable')) return;
        var count = currentDeck[numId] || 0;
        w.classList.toggle('card-selected', count > 0);
        var badge = w.querySelector('.card-count-badge');
        if (badge) {
            badge.textContent = 'x' + count;
            badge.classList.toggle('empty', count === 0);
        }
    });
}

function renderDeckBuilder() {
    renderCardBrowser();
    renderDeckSidebar();
    fitCardNames();
    fitCardEffects();
    try { if (typeof _renderCloudBadge === 'function') _renderCloudBadge(); } catch (e) {}
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
    // Full rebuild resets the container's scroll on some engines — clicking a
    // card to add it must not move the grid (user 2026-07-05). Save/restore.
    var prevScroll = grid.scrollTop;
    grid.innerHTML = '';
    // Type filter map: card_type int -> filter name
    var typeMap = {0: 'minion', 1: 'magic', 2: 'react'};
    var query = deckSearchQuery.toLowerCase().trim();
    // Sort by the fsort control's field/direction; ties fall back to name.
    // 'release' = numeric card id, i.e. set/collector order.
    var sorters = {
        name:    function(ca, cb) { return (ca.name || '').localeCompare(cb.name || ''); },
        attack:  function(ca, cb) { return (ca.attack || 0) - (cb.attack || 0); },
        health:  function(ca, cb) { return (ca.health || 0) - (cb.health || 0); },
        mana:    function(ca, cb) { return (ca.mana_cost || 0) - (cb.mana_cost || 0); },
        type:    function(ca, cb) { return ca.card_type - cb.card_type; }
    };
    var ids = Object.keys(defs).map(Number).sort(function(a, b) {
        var ca = defs[a], cb = defs[b];
        var d = deckSortField === 'release' ? (a - b) : sorters[deckSortField](ca, cb);
        if (d === 0 && deckSortField !== 'name') d = (ca.name || '').localeCompare(cb.name || '');
        return d * deckSortDir;
    });
    ids.forEach(function(numId) {
        var c = defs[numId];
        // Hide non-deckable cards unless checkbox is checked
        var showNonDeckable = document.getElementById('show-nondeckable') && document.getElementById('show-nondeckable').checked;
        if (c.deckable === false && !showNonDeckable) return;
        // Type filter (multi-select; empty = all). Multi-purpose cards — a
        // minion/magic card with a react mode — count as both types.
        if (deckFilterTypes.length) {
            var cardTypes = [typeMap[c.card_type]];
            if (c.react_condition != null && c.card_type !== 2) cardTypes.push('react');
            if (!cardTypes.some(function(t) { return deckFilterTypes.indexOf(t) !== -1; })) return;
        }
        // Element filter
        if (deckFilterElements.length) {
            var cardElem = (c.element !== undefined && c.element !== null) ? String(c.element) : '-1';
            if (deckFilterElements.indexOf(cardElem) === -1) return;
        }
        // Mana filter. Multi-purpose cards match on either of their two costs.
        if (deckFilterManas.length) {
            var costs = [c.mana_cost || 0];
            if (c.react_condition != null && c.react_mana_cost != null) costs.push(c.react_mana_cost);
            var manaOk = deckFilterManas.some(function(m) {
                return costs.some(function(mc) {
                    return m === '10+' ? mc >= 10 : mc === parseInt(m);
                });
            });
            if (!manaOk) return;
        }
        // Tribe filter ("Mage Rat" counts as both Mage and Rat)
        if (deckFilterTribes.length) {
            var cardTribes = (c.tribe || '').split(/\s+/);
            if (!deckFilterTribes.some(function(t) { return cardTribes.indexOf(t) !== -1; })) return;
        }
        // Keyword filter (card passes if it has ANY checked keyword)
        if (deckFilterKeywords.length) {
            if (!deckFilterKeywords.some(function(kw) { return cardHasKeyword(c, kw); })) return;
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
        wrapper.dataset.numericId = numId;
        if (isNonDeckable) wrapper.classList.add('card-nondeckable');
        if (count > 0) wrapper.classList.add('card-selected');
        wrapper.innerHTML = renderDeckBuilderCard(numId, count);
        // ! pin (user 2026-07-05): locks this card in the tooltip WITHOUT
        // adding it to the deck, so stray mouse-overs don't replace it.
        wrapper.appendChild(_makeTooltipPin(numId));
        // Click to add (disabled for non-deckable). On touch devices (no
        // hover) the FIRST tap only previews the card in the tooltip;
        // tapping it again adds it (user 2026-07-05). Desktop unchanged —
        // hover already previews there.
        if (!isNonDeckable) {
            wrapper.addEventListener('click', function(e) {
                if (deckDragSuppressClick) return;   // this click ended a drag
                if (e.shiftKey) {
                    removeCardFromDeck(numId);
                    return;
                }
                if (window.matchMedia('(hover: none)').matches && deckTapPreviewId !== numId) {
                    deckTapPreviewId = numId;
                    showCardTooltip(numId);
                    return;
                }
                addCardToDeck(numId);
            });
            // Right-click to remove
            wrapper.addEventListener('contextmenu', function(e) {
                e.preventDefault();
                removeCardFromDeck(numId);
            });
        }
        // Hover for tooltip — suspended while a card is pinned
        wrapper.addEventListener('mouseenter', function() { if (deckTooltipLockId == null) showCardTooltip(numId); });
        wrapper.addEventListener('mouseleave', function() { if (deckTooltipLockId == null) hideCardTooltip(); });
        grid.appendChild(wrapper);
    });
    grid.scrollTop = prevScroll;
}

// One card / one keyword check, shared by the multi-select keyword filter.
// 'rally' accepted for backward compat with any stale markup.
function cardHasKeyword(c, kw) {
    if (kw === 'tutor') return !!c.tutor_target;
    if (kw === 'promote') return !!c.promote_target;
    if (kw === 'march' || kw === 'rally') return !!(c.effects && c.effects.some(function(e) { return e.type === 6; }));
    if (kw === 'transform') return !!(c.transform_options && c.transform_options.length > 0);
    if (kw === 'discard') return !!c.discard_cost_tribe;
    if (kw === 'react') return c.react_condition != null;
    if (kw === 'unique') return !!c.unique;
    if (kw === 'negate') return !!(c.effects && c.effects.some(function(e) { return e.type === 4; }));
    if (kw === 'burn') return !!(c.effects && c.effects.some(function(e) { return e.type === 10; }));
    if (kw === 'end') return !!(c.effects && c.effects.some(function(e) { return e.trigger === 5 || e.type === 12; }));
    if (kw === 'draw') return !!(c.effects && c.effects.some(function(e) { return e.type === 18; }));
    if (kw === 'passive') return !!(c.effects && c.effects.some(function(e) { return e.trigger === 7; }));
    return false;
}

function setupDeckFilters() {
    var searchInput = document.getElementById('card-search');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            deckSearchQuery = searchInput.value;
            renderCardBrowser();
        });
    }
    // Dropdown filters with checkboxes (user 2026-07-05). Each .fdrop is one
    // group; checked values collect into the matching deckFilter* array.
    var applyByGroup = {
        type:    function(vals) { deckFilterTypes = vals; },
        element: function(vals) { deckFilterElements = vals; },
        tribe:   function(vals) { deckFilterTribes = vals; },
        keyword: function(vals) { deckFilterKeywords = vals; },
        mana:    function(vals) { deckFilterManas = vals; }
    };
    var drops = document.querySelectorAll('#filter-bar .fdrop');
    function closeAllDrops() {
        drops.forEach(function(d) { d.classList.remove('open'); });
    }
    // The tribe menu is built from card defs (tribes like "Mage Rat" count as
    // both tribes) the first time the dropdown opens after defs arrive.
    function populateTribeMenu(drop) {
        var menu = drop.querySelector('.fdrop-menu');
        if (menu.childElementCount > 0) return;
        var defs = allCardDefs || cardDefs;
        if (!defs || Object.keys(defs).length === 0) return;
        var tribes = {};
        Object.keys(defs).forEach(function(id) {
            var t = defs[id].tribe;
            if (t) t.split(/\s+/).forEach(function(x) { if (x) tribes[x] = true; });
        });
        Object.keys(tribes).sort().forEach(function(t) {
            var label = document.createElement('label');
            label.className = 'fdrop-opt';
            label.innerHTML = '<input type="checkbox" value="' + t + '">'
                + '<span class="fdrop-box" aria-hidden="true"></span><span>' + t + '</span>';
            menu.appendChild(label);
        });
    }
    drops.forEach(function(drop) {
        var btn = drop.querySelector('.fdrop-btn');
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            if (drop.dataset.group === 'tribe') populateTribeMenu(drop);
            var wasOpen = drop.classList.contains('open');
            closeAllDrops();
            if (!wasOpen) drop.classList.add('open');
        });
        // Clicks inside the menu (toggling boxes) must not close it
        drop.addEventListener('click', function(e) { e.stopPropagation(); });
        // Delegated so dynamically-built menus (tribe) work too. [value]
        // excludes the Non-Deckable toggle living in the Type menu — it has
        // its own handler and must not leak into the type filter.
        drop.querySelector('.fdrop-menu').addEventListener('change', function() {
            var vals = Array.prototype.slice.call(
                drop.querySelectorAll('.fdrop-opt input[value]:checked')
            ).map(function(i) { return i.value; });
            var apply = applyByGroup[drop.dataset.group];
            if (apply) apply(vals);
            var count = drop.querySelector('.fdrop-count');
            if (count) count.textContent = vals.length ? String(vals.length) : '';
            drop.classList.toggle('has-active', vals.length > 0);
            renderCardBrowser();
        });
    });
    document.addEventListener('click', closeAllDrops);
    // Sort control: chevrons pick direction (active one renders doubled),
    // the field button cycles Name/Attack/Health/Mana/Type/Release.
    var sortUp = document.getElementById('fsort-up');
    var sortDown = document.getElementById('fsort-down');
    var sortField = document.getElementById('fsort-field');
    function setSortDir(dir) {
        deckSortDir = dir;
        if (sortUp) sortUp.classList.toggle('active', dir === 1);
        if (sortDown) sortDown.classList.toggle('active', dir === -1);
        renderCardBrowser();
    }
    if (sortUp) sortUp.addEventListener('click', function() { setSortDir(1); });
    if (sortDown) sortDown.addEventListener('click', function() { setSortDir(-1); });
    if (sortField) sortField.addEventListener('click', function() {
        var idx = DECK_SORT_FIELDS.findIndex(function(f) { return f.key === deckSortField; });
        var next = DECK_SORT_FIELDS[(idx + 1) % DECK_SORT_FIELDS.length];
        deckSortField = next.key;
        sortField.textContent = next.label;
        renderCardBrowser();
    });
    // Non-deckable checkbox
    var nonDeckCheckbox = document.getElementById('show-nondeckable');
    if (nonDeckCheckbox) {
        nonDeckCheckbox.addEventListener('change', function() { renderCardBrowser(); });
    }
}

// =============================================
// Board gap forgiveness (user 2026-07-06): on the tilted board, clicks that
// land in the 6px gutters (or the projected slop at tile edges) hit the
// board background instead of the tile the player was visually aiming at.
// Forward those to the cell whose (slightly inflated) rect contains the
// point, so every visual part of a tile is clickable.
// =============================================
function setupBoardGapForgiveness() {
    ['game-board', 'sandbox-board'].forEach(function(id) {
        var board = document.getElementById(id);
        if (!board) return;
        board.addEventListener('click', function(e) {
            if (e.target !== board) return;   // direct cell hits pass through
            var PAD = 8;
            var cells = board.querySelectorAll('.board-cell');
            for (var i = 0; i < cells.length; i++) {
                var r = cells[i].getBoundingClientRect();
                if (e.clientX >= r.left - PAD && e.clientX <= r.right + PAD &&
                    e.clientY >= r.top - PAD && e.clientY <= r.bottom + PAD) {
                    cells[i].click();
                    return;
                }
            }
        });
    });
}

// =============================================
// In-game tooltip tabs (user 2026-07-06): the left panel gets Card | Log |
// Chat tabs and the right activity sidebar disappears, freeing stage width.
// The log/chat DOM nodes are MOVED (not copied) so every id-based handler
// (chat send, log append, unread badge) keeps working untouched.
// =============================================
function setupTooltipTabs() {
    var sidebar = document.querySelector('#screen-game .game-tooltip-sidebar');
    var logPane = document.getElementById('tab-log');
    var chatPane = document.getElementById('tab-chat');
    var leaveBtn = document.querySelector('#screen-game .game-sidebar .btn.full-width');
    if (!sidebar || !logPane || !chatPane) return;

    var strip = document.createElement('div');
    strip.className = 'ttab-strip';
    strip.innerHTML =
        '<button class="ttab active" data-t="card" type="button">Card</button>' +
        '<button class="ttab" data-t="log" type="button">Log</button>' +
        '<button class="ttab" data-t="chat" type="button">Chat' +
        '<span class="ttab-unread" id="ttab-chat-unread" style="display:none;"></span></button>';

    // wrap the existing tooltip content into a "card" pane
    var cardPane = document.createElement('div');
    cardPane.className = 'ttab-pane ttab-pane-card';
    while (sidebar.firstChild) cardPane.appendChild(sidebar.firstChild);
    sidebar.appendChild(strip);
    sidebar.appendChild(cardPane);
    sidebar.appendChild(logPane);
    sidebar.appendChild(chatPane);
    // LEAVE GAME floats top-right of the stage as a compact ✕ (user
    // 2026-07-06) — appended to the layout root so nothing clips it.
    if (leaveBtn) {
        leaveBtn.textContent = '✕';
        leaveBtn.title = 'Leave game';
        leaveBtn.classList.add('leave-x');
        document.querySelector('#screen-game .game-layout').appendChild(leaveBtn);
    
    // Compliance audit 2026-07-06: the game room-bar is display:none, which
    // orphaned the SFX mute + react-prompt-mode controls and the SPECTATING
    // badge. Relocate them onto the stage beside the X.
    var gameLayout = document.querySelector('#screen-game .game-layout');
    var muteBtn = document.getElementById('sfx-mute-btn');
    if (muteBtn && gameLayout) {
        muteBtn.classList.add('stage-corner-btn');
        gameLayout.appendChild(muteBtn);
    }
    var reactModeBtn = document.getElementById('react-mode-btn');
    if (reactModeBtn && gameLayout) {
        reactModeBtn.classList.add('stage-corner-btn');
        gameLayout.appendChild(reactModeBtn);
    }
    var specBadge = document.getElementById('spectating-badge');
    if (specBadge && gameLayout) gameLayout.appendChild(specBadge);
}
    logPane.classList.add('ttab-pane');
    chatPane.classList.add('ttab-pane');
    logPane.style.display = 'none';
    chatPane.style.display = 'none';

    strip.addEventListener('click', function(e) {
        var b = e.target.closest('.ttab');
        if (!b) return;
        strip.querySelectorAll('.ttab').forEach(function(x) { x.classList.toggle('active', x === b); });
        cardPane.style.display = b.dataset.t === 'card' ? '' : 'none';
        logPane.style.display = b.dataset.t === 'log' ? '' : 'none';
        chatPane.style.display = b.dataset.t === 'chat' ? '' : 'none';
        if (b.dataset.t === 'chat') {
            var unread = document.getElementById('ttab-chat-unread');
            if (unread) { unread.style.display = 'none'; unread.textContent = ''; }
        }
        if (b.dataset.t === 'log') {
            // Entries appended while the pane was display:none can't scroll
            // (zero scrollHeight) — jump to the newest entry on open.
            var le = document.getElementById('log-entries');
            if (le) le.scrollTop = le.scrollHeight;
        }
    });
    document.body.classList.add('ttabs-on');
}

// =============================================
// Lobby quick game view (testing, user 2026-07-06): polls /api/quickview for
// in-progress games and renders mini live boards — scores, turn, minion dots
// (gold = P1, rust = P2). Click a snapshot to spectate that room.
// =============================================
function setupLobbyQuickview() {
    var wrap = document.getElementById('lobby-quickview');
    var list = document.getElementById('lobby-quickview-list');
    if (!wrap || !list) return;

    // Game preview tile: solo preview game on the REAL duel screen (user
    // 2026-07-06 — no sandbox). game_start handles the screen switch.
    var previewBtn = document.getElementById('btn-game-preview');
    if (previewBtn) previewBtn.addEventListener('click', function() {
        socket.emit('preview_game', { display_name: getCurrentDisplayName() || 'Preview' });
    });

    function renderGames(games) {
        list.innerHTML = games.map(function(g) {
            var cells = '';
            var occ = {};
            g.minions.forEach(function(m) { occ[m.row + ',' + m.col] = m.owner; });
            for (var r = 0; r < 5; r++) {
                for (var c = 0; c < 5; c++) {
                    var o = occ[r + ',' + c];
                    cells += '<i' + (o === 0 ? ' class="qv-p0"' : o === 1 ? ' class="qv-p1"' : '') + '></i>';
                }
            }
            return '<div class="lobby2-qv-game" data-code="' + g.code + '" title="Watch ' + g.code + '">'
                + '<div class="qv-board">' + cells + '</div>'
                + '<div class="qv-meta">'
                + '<span class="qv-code">' + g.code + '</span>'
                + '<span class="qv-turn">Turn ' + g.turn + ' · ' + (g.phase || '') + '</span>'
                + '<span class="qv-score">' + g.players[0].name + ' <b>' + g.players[0].hp + '</b>'
                + ' vs <b>' + g.players[1].hp + '</b> ' + g.players[1].name + '</span>'
                + '</div></div>';
        }).join('');
        list.querySelectorAll('.lobby2-qv-game').forEach(function(el) {
            el.addEventListener('click', function() {
                var codeInput = document.querySelector('input[placeholder*="CODE" i], #input-room-code');
                if (codeInput) {
                    codeInput.value = el.dataset.code;
                    codeInput.dispatchEvent(new Event('input', { bubbles: true }));
                }
                var watchBtn = document.getElementById('btn-spectate-room');
                if (watchBtn) watchBtn.click();
            });
        });
    }

    function poll() {
        if (!document.getElementById('screen-lobby').classList.contains('active')) return;
        fetch('/api/quickview')
            .then(function(r) { return r.ok ? r.json() : []; })
            .then(renderGames)
            .catch(function() { /* lobby polling must never throw */ });
    }
    setInterval(poll, 3000);
    poll();
}

// =============================================
// Deck builder drag & drop (user 2026-07-05): hold-and-drag a grid card onto
// the deck panel to add it; drag a deck row out of the panel to remove one.
// A blank card ghost follows the pointer. Pointer Events cover mouse + touch:
// mouse starts on hold (220ms) or movement while held; touch needs a
// long-press (280ms) so normal swipes still scroll.
// =============================================
var deckDragSuppressClick = false;

function setupDeckDragAndDrop() {
    // Touch gets a bigger slop: fingers jitter well past 8px during a
    // long-press, which silently cancelled the drag (user 2026-07-05).
    var SLOP = 8, TOUCH_SLOP = 16, HOLD_MOUSE = 220, HOLD_TOUCH = 260;
    var pending = null;   // pointer down, drag not yet started
    var drag = null;      // { numId, from: 'grid'|'deck' }
    var ghost = null;

    function ghostEl() {
        if (!ghost) {
            ghost = document.createElement('div');
            ghost.id = 'deck-drag-ghost';
            ghost.setAttribute('aria-hidden', 'true');
            document.body.appendChild(ghost);
        }
        return ghost;
    }
    function moveGhost(x, y) {
        var g = ghostEl();
        g.style.transform = 'translate(' + x + 'px,' + y + 'px) translate(-50%, -60%) rotate(-4deg)';
    }
    function sidebar() { return document.querySelector('#screen-deck-builder .deck-sidebar'); }
    function overSidebar(x, y) {
        var sb = sidebar();
        if (!sb) return false;
        var r = sb.getBoundingClientRect();
        return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
    }
    function begin(x, y) {
        if (!pending) return;
        drag = { numId: pending.numId, from: pending.from };
        pending = null;
        var g = ghostEl();
        g.style.display = 'block';
        moveGhost(x, y);
        document.body.classList.add('deck-dragging');
    }
    function end() {
        if (ghost) ghost.style.display = 'none';
        document.body.classList.remove('deck-dragging', 'deck-drop-ok');
        drag = null;
    }

    document.addEventListener('pointerdown', function(e) {
        var screen = document.getElementById('screen-deck-builder');
        if (!screen || !screen.classList.contains('active')) return;
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        if (e.target.closest('.deck-qty-btn, .card-info-lock, button, input, a')) return;
        var gridItem = e.target.closest('#card-browser-grid .card-browser-item');
        var deckRow = e.target.closest('#deck-flat .deck-list-item');
        var el = gridItem || deckRow;
        if (!el || el.classList.contains('card-nondeckable')) return;
        var numId = parseInt(el.dataset.numericId, 10);
        if (isNaN(numId)) return;
        pending = {
            numId: numId,
            from: gridItem ? 'grid' : 'deck',
            x: e.clientX, y: e.clientY,
            touch: e.pointerType === 'touch',
            timer: setTimeout(function() { begin(pending.x, pending.y); },
                              e.pointerType === 'touch' ? HOLD_TOUCH : HOLD_MOUSE)
        };
    });

    document.addEventListener('pointermove', function(e) {
        if (drag) {
            moveGhost(e.clientX, e.clientY);
            var ok = drag.from === 'grid' ? overSidebar(e.clientX, e.clientY)
                                          : !overSidebar(e.clientX, e.clientY);
            document.body.classList.toggle('deck-drop-ok', ok);
            return;
        }
        if (pending) {
            var slop = pending.touch ? TOUCH_SLOP : SLOP;
            var moved = Math.hypot(e.clientX - pending.x, e.clientY - pending.y) > slop;
            if (!moved) return;
            clearTimeout(pending.timer);
            if (pending.touch) {
                pending = null;                    // touch: early move = scroll
            } else {
                begin(e.clientX, e.clientY);       // mouse: drag intent
            }
        }
    });

    // Touch scrolling fights the long-press: if the browser commits to a
    // scroll during the hold it fires pointercancel and the drag never
    // starts. While a touch press is pending and still inside the slop,
    // suppress the native scroll so the hold can complete; once the drag is
    // live the finger drags the ghost, not the page.
    document.addEventListener('touchmove', function(e) {
        if (drag) { e.preventDefault(); return; }
        if (pending && pending.touch && e.touches.length === 1) {
            var t = e.touches[0];
            if (Math.hypot(t.clientX - pending.x, t.clientY - pending.y) <= TOUCH_SLOP) {
                e.preventDefault();
            }
        }
    }, { passive: false });

    document.addEventListener('pointerup', function(e) {
        if (pending) { clearTimeout(pending.timer); pending = null; }
        if (!drag) return;
        var inSidebar = overSidebar(e.clientX, e.clientY);
        if (drag.from === 'grid' && inSidebar) addCardToDeck(drag.numId);
        else if (drag.from === 'deck' && !inSidebar) removeCardFromDeck(drag.numId);
        end();
        // swallow the click that follows this pointerup
        deckDragSuppressClick = true;
        setTimeout(function() { deckDragSuppressClick = false; }, 0);
    });

    document.addEventListener('pointercancel', function() {
        if (pending) { clearTimeout(pending.timer); pending = null; }
        if (drag) end();
    });

    // Android fires contextmenu on long-press — that would eat the drag.
    // (Mouse right-click never creates a pending: button 0 only.)
    document.addEventListener('contextmenu', function(e) {
        if (drag || pending) e.preventDefault();
    });
}

// Kept in sync with data/GLOSSARY.md (source of truth) — update BOTH when
// adding/changing/removing keywords.
var KEYWORD_GLOSSARY = {
    // Trigger keywords
    'Summon': 'This effect activates when the minion is played onto the board.',
    'Death': 'This effect activates when the minion is destroyed.',
    'Move': 'This effect activates when the minion moves forward.',
    'Attack': 'This effect activates when the minion attacks.',
    'Damaged': 'This effect activates when the minion takes damage.',
    'Start': 'This effect triggers in the Rally Phase at the start of the owner\'s turn, before any actions.',
    'End': 'This effect triggers in the Decay Phase at the end of the owner\'s turn, after all actions.',
    'Rally': 'The Rally Phase is the start-of-turn window (after the auto-draw) where positive once-per-turn effects trigger. "Rally:" effects proc here.',
    'Decay': 'The Decay Phase is the end-of-turn window where negative once-per-turn effects trigger. "Decay:" effects and Burning ticks proc here.',
    'Passive': 'This effect is always active while the minion is on the board.',
    'Active': 'This ability can be used once per turn instead of attacking.',
    'Discarded': 'This effect triggers when the card is discarded from hand (via a Cost or opponent effect).',
    // Mechanic keywords
    'Unique': 'Only one copy of this minion can exist on the board per player at a time.',
    'Melee': 'Attacks adjacent orthogonal tiles (1 tile).',
    'Range': 'Attacks X+1 tiles orthogonally, X tiles diagonally.',
    'Tutor': 'Search your deck for a specific card and add it to your hand.',
    'Promote': 'When this minion dies, specified minion transforms into this card.',
    'March': 'When this minion moves, all other friendly copies of it also advance forward.',
    'Negate': 'Cancel the effect of an opponent\'s spell or ability.',
    'React': 'This card can be played during the opponent\'s turn in response to their action.',
    'Destroy': 'Remove a target minion from the board regardless of its 🤍.',
    'Transform': 'Pay mana to transform this minion into another form.',
    'Cost': 'An additional requirement or modifier that changes how much you pay to play this card.',
    'Discard': 'Send a card from your hand to the Exhaust Pile.',
    'Exhaust': 'Send a card to the Exhaust Pile. Cards drawn while your hand is full are also exhausted, revealed.',
    'Heal': 'Restore 🤍 to a target.',
    'Deal': 'Deal damage to a target.',
    'Burn': 'Applies Burning to the affected minions — usually enemies, but some cards burn their own minion (e.g. Eclipse Shade\'s Summon).',
    'Burning': 'A burning minion takes 5🤍 in its owner\'s Decay Phase. Burning is a boolean status — re-applying it does nothing. It persists until the minion dies.',
    'Dark Matter': 'A stacking PLAYER resource pool, visible to both players. Gains add +1 per friendly Dark Mage on board (a minion with the Dark element and the Mage tribe — composite tribes like Mage Rat and Mage Undead count). Dark spells, buffs and costs scale with your pool; reading it never spends it.',
    'Leap': 'If blocked by an enemy, jump over to the next available tile. Cannot leap allies. If all tiles ahead are enemy-occupied, enables sacrifice.',
    'Conjure': 'Summon a card from your deck directly to the board.',
    'Cleanse': 'Removes all debuffs from the minion: Burning is cleared and negative \ud83d\udde1\ufe0f/\ud83e\udd0d marks reset to 0. Positive buffs stay; lost health is not restored.',
    'Untargetable': 'Cannot be targeted by magic cards \u2014 it is never a legal target for a magic card\u2019s single-target effect. Board-wide magic, minions and reacts still affect it.',
    'Revive': 'Summon minions from the Grave to the board. You pick which eligible grave card to revive and where it deploys (melee: any tile on your side; ranged: back row). Eligibility is limited by the text on the reviving card.',
    'Draw': 'Draw cards from your deck to your hand. If your hand is full (10 cards), the drawn card is sent to the Exhaust Pile, revealed, instead.',
    'Handshake': 'When a player passes and the opponent\'s previous action was also a pass, a Handshake occurs: at the end of that turn, both players gain +1 mana. A player whose mana is already full draws a card instead. The pass counter then resets — no chaining.',
};

// Build the shared content for a card tooltip. Both the deck-builder
// (#card-tooltip) and the in-game hover (#game-tooltip) call this so
// they stay in lockstep. Returns { name, statsHtml, bodyHtml } where:
//   name: plain text (the card name)
//   statsHtml: <span>…</span> chips for type/tribe/element/cost/atk/hp/range
//   bodyHtml: card text lines + flavour + matched keywords, all HTML
function buildCardTooltipContent(c) {
    if (!c) return { name: '', statsHtml: '', bodyHtml: '' };

    // Stats chips. Type is coloured by the brown/purple/pink type coding and
    // carries its emoji; element is plain coloured text + a dot (no highlight).
    var statsHtml = '';
    var typeNames = ['Minion', 'Magic', 'React'];
    var typeSlugs = ['minion', 'magic', 'react'];
    var typeEmoji = ['⚔️', '✨', '⚡'];  // ⚔️ ✨ ⚡
    statsHtml += '<span class="ts-type ts-type-' + (typeSlugs[c.card_type] || 'minion') + '">'
        + (typeEmoji[c.card_type] || '') + ' ' + (typeNames[c.card_type] || '') + '</span>';
    if (c.tribe) statsHtml += '<span class="ts-tribe">' + c.tribe + '</span>';
    var elem = (c.element !== null && c.element !== undefined) ? ELEMENT_MAP[c.element] : NEUTRAL_ELEMENT;
    statsHtml += '<span class="ts-elem ' + elem.css + '"><span class="ts-dot" aria-hidden="true"></span>' + elem.name + '</span>';
    statsHtml += '<span class="ts-mana">' + c.mana_cost + ' Mana</span>';
    if (c.attack != null) statsHtml += '<span class="ts-atk">' + c.attack + SWORD + '</span>';
    if (c.health != null) statsHtml += '<span class="ts-hp">' + c.health + HEART + '</span>';
    if (c.card_type === 0 && c.attack_range != null) {
        statsHtml += '<span class="ts-range">' + (c.attack_range === 0 ? 'Melee' : 'Range ' + c.attack_range) + '</span>';
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
    if (c.magic_untargetable) cardTextLines.push('Cannot be targeted by magic cards');
    if (c.cost_reduction === 'dark_matter') cardTextLines.push('Cost: Reduce mana cost by ' + _dmTokenLive());
    if (c.cost_reduction === 'behind_on_board') {
        cardTextLines.push('Cost: Costs ' + (c.cost_reduction_amount || 0)
            + ' less if your opponent has a minion and you have none');
    }
    if (c.alt_cost_discard) cardTextLines.push('Cost: You may discard ' + c.alt_cost_discard + ' cards: ' + c.name + ' costs 0');
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
    if (c.react_condition != null) {
        var condMap = {
            0: 'Magic or React', 1: 'Summon', 2: 'Attack',
            3: 'Magic or React', 4: 'Any action',
            5: 'Wood', 6: 'Fire', 7: 'Earth',
            8: 'Water', 9: 'Metal', 10: 'Dark',
            11: 'Light', 12: 'Sacrifice', 13: 'Discard',
            14: 'End of turn', 18: 'Tutor'
        };
        var condText = condMap[c.react_condition] || 'Enemy acts';
        var extraCond = c.react_requires_no_friendly_minions ? ' while no allies' : '';
        // Pure react cards (e.g. Prohibition) have no separate react_mana_cost —
        // their cost IS mana_cost. Fall back so the react line still renders
        // (the old gate required react_mana_cost != null and dropped it).
        var reactCost = (c.react_mana_cost != null) ? c.react_mana_cost : c.mana_cost;
        // Always show the cost — including 0 — so a 0-mana react reads
        // "React (0):" consistently with how mana is shown everywhere else.
        var costText = ' (' + reactCost + ')';
        var reactEffectTooltip = '';
        if (c.react_effect && c.react_effect.type === 5) {
            reactEffectTooltip = ' ▶ Summon';
        } else if (c.react_effect) {
            // noTrigger: react box already states the trigger — don't prefix
            // "Summon:" on a react_effect tagged on_summon (Tree Wyrm).
            reactEffectTooltip = ' ▶ ' + getEffectDescription([c.react_effect], c, { noTrigger: true });
        } else if (c.effects && c.effects.length > 0) {
            reactEffectTooltip = ' ▶ ' + getEffectDescription(c.effects, c, { noTrigger: true });
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
    if (c.magic_untargetable) addKw('Untargetable');
    if (c.cost_reduction) {
        addKw('Cost');
        if (c.cost_reduction === 'dark_matter') addKw('Dark Matter');
    }
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
            if (eff.trigger === 9) addKw('Rally');   // ON_START_OF_TURN — Rally Phase
            if (eff.trigger === 10) addKw('Decay');  // ON_END_OF_TURN — Decay Phase
            // Effect types
            if (eff.type === 0) { addKw('Deal'); if (_isDmScale(eff.scale_with)) addKw('Dark Matter'); }
            if (eff.type === 1) addKw('Heal');
            if ((eff.type === 2 || eff.type === 3) && _isDmScale(eff.scale_with)) addKw('Dark Matter');
            if (eff.type === 3) addKw('Heal');
            if (eff.type === 4) addKw('Negate');
            if (eff.type === 5) addKw('Summon');
            if (eff.type === 6) addKw('March');
            if (eff.type === 7) addKw('Promote');
            if (eff.type === 8) addKw('Tutor');
            if (eff.type === 9) addKw('Destroy');
            if (eff.type === 10) addKw('Burn');
            if (eff.type === 11) { addKw('Active'); addKw('Dark Matter'); }
            if (eff.type === 12) { addKw('Rally'); addKw('Heal'); }  // PASSIVE_HEAL fires in the Rally Phase (ON_START_OF_TURN)
            if (eff.type === 20) { addKw('Rally'); addKw('Cleanse'); }  // CLEANSE (Water Wyrm)
            if (eff.type === 13) addKw('Leap');
            if (eff.type === 14) addKw('Conjure');
            if (eff.type === 15) addKw('Burning');
            if (eff.type === 16) addKw('Dark Matter');
            if (eff.type === 17) addKw('Revive');
            if (eff.trigger === 11) addKw('Sacrifice');  // ON_SACRIFICE (Earth Wyrm)
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
    if (artHost) {
        artHost.innerHTML = renderDeckBuilderCard(numericId, undefined);
        // The render uses the 512px thumb for first paint. The tooltip
        // is the one place a player actually scrutinises art, so kick
        // off a background fetch of the full PNG and swap once decoded.
        _lazyUpgradeArt(artHost, c.card_id);
    }

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
        var relNumIds = [];
        relatedIds.forEach(function(rid) {
            var rc = null, rnid = null;
            for (var nid3 in defs) {
                if (defs[nid3].card_id === rid) { rc = defs[nid3]; rnid = nid3; break; }
            }
            if (!rc) return;
            relNumIds.push(rnid);
            var artBg = 'background-image:url(' + _cardArtUrl(rc.card_id) + ')';
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
        // Clicking a related card jumps the tooltip to that card (user 2026-07-05)
        relatedContainer.querySelectorAll('.tooltip-related-card').forEach(function(el, i) {
            el.addEventListener('click', function() {
                populateTooltip(hostEl, parseInt(relNumIds[i], 10), opts);
                var scroller = hostEl.querySelector('.tooltip-body');
                if (scroller) scroller.scrollTop = 0;
            });
        });
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

