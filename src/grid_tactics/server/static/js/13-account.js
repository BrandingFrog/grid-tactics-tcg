// =============================================
// Section 13: Discord account + cloud deck sync (user 2026-07-08)
//
// Optional login. Guests are unaffected: with the feature unconfigured
// server-side (/api/me login_available:false) the login button stays
// hidden and everything runs on localStorage as before. When logged in,
// the Discord avatar becomes the player's PFP and deck slots sync to
// Supabase (localStorage stays the working cache; the server is the
// source of truth pulled on login).
// =============================================

window.__account = { loginAvailable: false, cloudDecks: false, loggedIn: false, user: null };

function _accountAvatarUrl() {
    var a = window.__account;
    return (a && a.loggedIn && a.user && a.user.avatar_url) ? a.user.avatar_url : null;
}

// Consumed by _renderAvatarPod (11-hud-board-hand.js). self = my login;
// opp = whatever the server relays on the player object (avatar_url).
function _podAvatarUrl(which, playerIdx, playerObj) {
    if (which === 'self') return _accountAvatarUrl();
    if (playerObj && playerObj.avatar_url) return playerObj.avatar_url;
    return null;
}

function _renderAccountChip() {
    var a = window.__account;
    var loginBtn = document.getElementById('discord-login-btn');
    var chip = document.getElementById('account-chip');
    if (!loginBtn || !chip) return;
    if (!a.loginAvailable) {
        loginBtn.style.display = 'none';
        chip.style.display = 'none';
        return;
    }
    if (a.loggedIn && a.user) {
        loginBtn.style.display = 'none';
        chip.style.display = '';
        var img = document.getElementById('account-chip-avatar');
        var nm = document.getElementById('account-chip-name');
        if (img) img.src = a.user.avatar_url || '';
        if (nm) nm.textContent = a.user.display_name || a.user.username || 'Player';
    } else {
        loginBtn.style.display = '';
        chip.style.display = 'none';
    }
}

// ---- cloud deck sync -------------------------------------------------

function _localDeckSlots() {
    try {
        var raw = localStorage.getItem(STORAGE_KEY);
        var parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
    } catch (e) { return []; }
}

// Push the full local slot array to the server so the cloud mirrors it
// exactly (upsert each present slot, delete trailing ones). Debounced.
var _deckPushTimer = null;
function _pushDecksToCloud(slots) {
    var a = window.__account;
    if (!a.loggedIn || !a.cloudDecks) return;
    if (_deckPushTimer) clearTimeout(_deckPushTimer);
    _deckPushTimer = setTimeout(function() {
        _deckPushTimer = null;
        var arr = Array.isArray(slots) ? slots : _localDeckSlots();
        arr.forEach(function(s, i) {
            fetch('/api/decks', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ slot: i, name: (s && s.name) || ('Deck ' + (i + 1)),
                    cards: (s && s.cards) || {} }),
            }).catch(function() {});
        });
        // Delete any server slots past the current count (best-effort probe
        // a few beyond the array length).
        for (var d = arr.length; d < arr.length + 6; d++) {
            fetch('/api/decks/' + d, { method: 'DELETE', credentials: 'same-origin' }).catch(function() {});
        }
    }, 600);
}

// Monkeypatch the deck-builder's localStorage writer so every save also
// syncs to the cloud when logged in. The bare `saveDeckSlots(...)` calls
// across the client resolve this global binding.
(function _wrapSaveDeckSlots() {
    if (typeof saveDeckSlots !== 'function') return;
    var _orig = saveDeckSlots;
    window.saveDeckSlots = function(slots) {
        _orig(slots);
        _pushDecksToCloud(slots);
    };
})();

function _writeLocalSlots(slots) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(slots || [])); } catch (e) {}
    try { if (typeof populateDeckSelector === 'function') populateDeckSelector(); } catch (e) {}
    try { if (typeof renderDeckBuilder === 'function') renderDeckBuilder(); } catch (e) {}
}

// On login: pull cloud decks into the local cache. If the cloud is empty
// but the browser has local decks, offer to upload them (first-login
// migration, user's chosen behaviour).
function _syncDecksOnLogin() {
    var a = window.__account;
    if (!a.loggedIn || !a.cloudDecks) return;
    fetch('/api/decks', { credentials: 'same-origin' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var cloud = (data && data.decks) || [];
            var local = _localDeckSlots();
            if (cloud.length > 0) {
                // Cloud is source of truth — cache it locally (sorted by slot).
                var byslot = cloud.slice().sort(function(x, y) { return x.slot - y.slot; });
                _writeLocalSlots(byslot.map(function(d) {
                    return { name: d.name, cards: d.cards || {} };
                }));
            } else if (local.length > 0) {
                _promptDeckMigration(local);
            }
        })
        .catch(function() {});
}

function _promptDeckMigration(local) {
    if (document.getElementById('deck-migrate-modal')) return;
    var overlay = document.createElement('div');
    overlay.id = 'deck-migrate-modal';
    overlay.className = 'account-modal-overlay';
    overlay.innerHTML =
        '<div class="account-modal">'
        + '<div class="account-modal-title">Import your decks?</div>'
        + '<div class="account-modal-body">You have ' + local.length
        + ' deck' + (local.length === 1 ? '' : 's')
        + ' saved on this device. Upload them to your Discord account so they '
        + 'sync everywhere?</div>'
        + '<div class="account-modal-actions">'
        + '<button class="account-btn-secondary" id="deck-migrate-skip">Not now</button>'
        + '<button class="account-btn-primary" id="deck-migrate-go">Import</button>'
        + '</div></div>';
    document.body.appendChild(overlay);
    document.getElementById('deck-migrate-skip').addEventListener('click', function() {
        overlay.remove();
    });
    document.getElementById('deck-migrate-go').addEventListener('click', function() {
        overlay.remove();
        fetch('/api/decks/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ slots: local.map(function(s, i) {
                return { slot: i, name: s.name, cards: s.cards || {} }; }) }),
        }).then(function(r) { return r.json(); })
          .then(function(res) {
              if (res && res.decks) {
                  var byslot = res.decks.slice().sort(function(x, y) { return x.slot - y.slot; });
                  _writeLocalSlots(byslot.map(function(d) { return { name: d.name, cards: d.cards || {} }; }));
              }
          }).catch(function() {});
    });
}

// ---- bootstrap -------------------------------------------------------

function bootstrapAccount() {
    fetch('/api/me', { credentials: 'same-origin' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            window.__account = {
                loginAvailable: !!data.login_available,
                cloudDecks: !!data.cloud_decks,
                loggedIn: !!data.logged_in,
                user: data.user || null,
            };
            _renderAccountChip();
            if (window.__account.loggedIn) {
                // Adopt the Discord display name if the player hasn't set one.
                try {
                    var input = document.getElementById('input-name');
                    var stored = (typeof loadSavedName === 'function') ? loadSavedName() : '';
                    if (!stored && window.__account.user && window.__account.user.display_name) {
                        var dn = window.__account.user.display_name.slice(0, 14);
                        if (input) input.value = dn;
                        myName = dn;
                        if (typeof saveDisplayName === 'function') saveDisplayName(dn);
                    }
                } catch (e) { /* defensive */ }
                _syncDecksOnLogin();
            }
        })
        .catch(function() { /* feature simply stays off */ });
}

function _bindAccountButtons() {
    var loginBtn = document.getElementById('discord-login-btn');
    if (loginBtn) {
        loginBtn.addEventListener('click', function() {
            window.location.href = '/auth/discord/login?next=/';
        });
    }
    var logoutBtn = document.getElementById('account-logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', function() {
            fetch('/auth/discord/logout', { method: 'POST', credentials: 'same-origin' })
                .then(function() { window.location.href = '/'; })
                .catch(function() { window.location.href = '/'; });
        });
    }
}

document.addEventListener('DOMContentLoaded', function() {
    _bindAccountButtons();
    bootstrapAccount();
});
