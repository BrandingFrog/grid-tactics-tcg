// =============================================
// Game Tooltip (hand cards + board minions) — same renderer, no related.
// =============================================
// Clicking a card anywhere pins it in the tooltip (user 2026-07-06); while
// pinned, hover show/hide is ignored unless the caller forces it.
let gameTooltipPin = null;   // { nid, el }
var activePlayerPreviewIdx = null;

function showGameTooltip(numericId, anchorEl, minion, opts) {
    if (gameTooltipPin && !(opts && opts.force)) return;
    activePlayerPreviewIdx = null;
    var tooltipId = sandboxMode ? 'sandbox-tooltip' : 'game-tooltip';
    var hintId = sandboxMode ? 'sandbox-tooltip-hint' : 'game-tooltip-hint';
    var tooltipEl = document.getElementById(tooltipId);
    // Related-card discovery belongs in the deck builder. In a match it
    // made inspected AI/opponent cards (especially To The Ratmobile) grow a
    // seemingly random list of extra cards in the player sidebar.
    populateTooltip(tooltipEl, numericId, { showRelated: false });
    var hint = document.getElementById(hintId);
    if (hint) hint.style.display = 'none';
    _applyLiveStatTones(tooltipEl, minion || null);
    _renderMinionStatusPanels(tooltipEl, minion);
}

// Buff/debuff rework (user 2026-07-10): when the tooltip shows a BOARD
// minion, patch the printed stat values to the live ones and tag them
// with the same golden-pulse / grey-drain stroke animation the board
// stats use. Net sign vs the printed stat decides which — a stat both
// buffed and debuffed animates by whether it ended up better or worse.
function _applyLiveStatTones(tooltipEl, minion) {
    if (!tooltipEl) return;
    var stats = tooltipEl.querySelectorAll('.cf2-stat');
    for (var i = 0; i < stats.length; i++) {
        var lbl = stats[i].querySelector('.cf2-stat-lbl');
        var val = stats[i].querySelector('.cf2-stat-val');
        if (!lbl || !val) continue;
        val.classList.remove('stat-buffed', 'stat-debuffed');
        if (!minion) continue;  // fresh printed markup — nothing to patch
        var def = (cardDefs && cardDefs[minion.card_numeric_id]) || {};
        var net = 0;
        if (/attack/i.test(lbl.textContent)) {
            net = minion.attack_bonus | 0;
            val.textContent = (def.attack || 0) + net;
        } else if (/health/i.test(lbl.textContent)) {
            net = minion.max_health_bonus | 0;
            val.textContent = (def.health || 0) + net;
        }
        if (net > 0) val.classList.add('stat-buffed');
        else if (net < 0) val.classList.add('stat-debuffed');
    }
}

function hideGameTooltip(opts) {
    if (gameTooltipPin && !(opts && opts.force)) return;
    activePlayerPreviewIdx = null;
    var tooltipId = sandboxMode ? 'sandbox-tooltip' : 'game-tooltip';
    var hintId = sandboxMode ? 'sandbox-tooltip-hint' : 'game-tooltip-hint';
    var tooltip = document.getElementById(tooltipId);
    if (tooltip) tooltip.style.display = 'none';
    var hint = document.getElementById(hintId);
    if (hint) hint.style.display = '';
    _renderMinionStatusPanels(tooltip, null);
}

// Delegated: any click on a hand card or board minion pins that card in the
// tooltip and highlights it; clicking the same one again unpins. Game click
// actions (select/target) still run — pinning never swallows the event.
function setupGameTooltipPin() {
    document.addEventListener('click', function(e) {
        if (!document.querySelector('#screen-game.active, #screen-sandbox.active')) return;
        var el = e.target.closest('.card-frame-hand, .board-minion');
        if (!el) return;
        var nid = parseInt(el.dataset.numericId, 10);
        if (isNaN(nid)) return;
        if (gameTooltipPin && gameTooltipPin.el === el) {
            gameTooltipPin = null;
            inspectedMinionId = null;
            el.classList.remove('tooltip-pinned-card');
            if (typeof highlightBoard === 'function') highlightBoard();
            return;
        }
        document.querySelectorAll('.tooltip-pinned-card').forEach(function(x) {
            x.classList.remove('tooltip-pinned-card');
        });
        gameTooltipPin = { nid: nid, el: el };
        inspectedMinionId = el.classList.contains('board-minion') && el._minionRef
            ? el._minionRef.instance_id : null;
        el.classList.add('tooltip-pinned-card');
        showGameTooltip(nid, el, el._minionRef || null, { force: true });
        if (typeof highlightBoard === 'function') highlightBoard();
    // Capture before the board-cell action handler. Some cell actions render
    // the board synchronously, replacing the clicked minion before a bubbling
    // document listener can recover its instance id.
    }, true);
}

// Hearthstone-style stacked status panels rendered as siblings under
// the main card tooltip. Surfaces live minion buffs/debuffs/statuses so
// hovering a board minion shows what's actually applied to THIS instance,
// not just the printed card text.
function _renderMinionStatusPanels(tooltipEl, minion) {
    if (!tooltipEl || !tooltipEl.parentNode) return;
    var sidebar = tooltipEl.parentNode;
    var stack = sidebar.querySelector('.tooltip-status-stack');
    if (!stack) {
        stack = document.createElement('div');
        stack.className = 'tooltip-status-stack';
        // Insert right after the main tooltip so it stacks vertically.
        tooltipEl.insertAdjacentElement('afterend', stack);
    }
    stack.innerHTML = '';
    if (!minion) {
        stack.style.display = 'none';
        return;
    }
    var panels = [];
    // Buff/debuff rework (user 2026-07-10): the +X Attack / +X Max Health
    // panels are GONE — they ate the tooltip. The tooltip card's own stat
    // values are patched to the LIVE numbers with the same golden-pulse /
    // grey-drain stroke animations as the board (see _applyLiveStatTones).
    if (minion.is_burning) {
        panels.push({
            icon: '🔥',
            name: 'Burning',
            desc: 'Takes 5🤍 damage in its owner\'s Decay Phase.',
            tone: 'debuff',
        });
    }
    var dm = minion.dark_matter_stacks | 0;
    if (dm > 0) {
        panels.push({
            icon: '🌑',
            name: 'Dark Matter ×' + dm,
            desc: 'Stacks consumed by Dark Mage spells (e.g. Dark Matter Barrage).',
            tone: 'aura',
        });
    }
    if (panels.length === 0) {
        stack.style.display = 'none';
        return;
    }
    stack.style.display = '';
    for (var p = 0; p < panels.length; p++) {
        var panel = panels[p];
        var el = document.createElement('div');
        el.className = 'tooltip-status-panel tooltip-status-' + panel.tone;
        el.innerHTML =
            '<div class="tooltip-status-icon">' + panel.icon + '</div>' +
            '<div class="tooltip-status-body">' +
              '<div class="tooltip-status-name">' + panel.name + '</div>' +
              '<div class="tooltip-status-desc">' + panel.desc + '</div>' +
            '</div>';
        stack.appendChild(el);
    }
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
// --- renderCardFrame helpers (2026-07 full-art frame redesign) -----------
// Collector number NNN/033 derives from stable_id ranked 1..N across the set.
// Memoised on first use; recomputed only while defs are still empty.
var _cf2CollectorMap = null;
var _cf2CollectorTotal = 33;
function _cf2Collector(c) {
    var defs = allCardDefs || cardDefs;
    if ((!_cf2CollectorMap || _cf2CollectorTotal === 0) && defs) {
        var ids = [];
        for (var k in defs) {
            if (defs[k] && defs[k].stable_id != null) ids.push(defs[k].stable_id);
        }
        if (ids.length) {
            ids.sort(function(a, b) { return a - b; });
            _cf2CollectorMap = {};
            ids.forEach(function(sid, i) { _cf2CollectorMap[sid] = i + 1; });
            _cf2CollectorTotal = ids.length;
        }
    }
    var pad = function(n) { n = '' + n; while (n.length < 3) n = '0' + n; return n; };
    var num = (c && c.stable_id != null && _cf2CollectorMap && _cf2CollectorMap[c.stable_id])
        ? _cf2CollectorMap[c.stable_id] : null;
    return (num != null ? pad(num) : '—') + '/' + pad(_cf2CollectorTotal || 33);
}

// Render one effect sentence as an ◆-bulleted (or plain) ability line, bolding
// the leading keyword when the sentence is "Keyword: rest" shaped.
function _cf2Line(line, bullet) {
    if (!line) return '';
    var pre = bullet ? '<span class="cf2-bullet">◆</span>' : '';
    var m = /^([^:<]{1,22}):\s*([\s\S]*)$/.exec(line);
    if (m) {
        return '<div class="cf2-ability">' + pre + '<b>' + m[1] + '</b> — ' + m[2] + '</div>';
    }
    return '<div class="cf2-ability">' + pre + line + '</div>';
}

// React timing phrasing keyed by react_condition (matches the approved frame).
var _CF2_REACT_TIMING = {
    0: "opponent plays a magic or react card",
    1: "opponent summons a minion",
    2: "opponent attacks",
    3: "opponent plays a magic or react card",
    4: "opponent takes an action",
    5: "a Wood card is played",
    6: "a Fire card is played",
    7: "an Earth card is played",
    8: "a Water card is played",
    9: "a Metal card is played",
    10: "a Dark card is played",
    11: "a Light card is played",
    12: "opponent sacrifices",
    13: "a card is discarded",
    14: "opponent's Decay Phase",
    18: "opponent tutors",
};

function renderCardFrame(c, opts) {
    if (!c) return '';
    opts = opts || {};
    var context = opts.context || 'deck-builder';
    var typeClass = TYPE_CSS[c.card_type] || '';
    var elem = (c.element !== null && c.element !== undefined)
        ? ELEMENT_MAP[c.element] : NEUTRAL_ELEMENT;
    var palette = (elem === NEUTRAL_ELEMENT) ? 'neutral' : elem.name.toLowerCase();
    var elemEmoji = EL_EMOJI[palette] || EL_EMOJI.neutral;
    var isMinion = c.card_type === 0;

    // Context class: hand context still carries .card-frame-hand so all
    // existing state selectors (.card-frame-hand.card-playable,
    // .card-selected-hand, .card-react-playable, mobile sizing) keep working.
    var contextClass = '';
    if (context === 'hand') {
        contextClass = ' card-frame-hand';
    } else if (context === 'pile') {
        contextClass = ' card-frame-pile';
    } else if (context === 'tooltip') {
        contextClass = ' card-frame-tooltip';
    } else if (context === 'spell-stage') {
        contextClass = ' card-frame-spell-stage';
    }
    // 'deck-builder' (default) carries no extra context class — the base
    // .card-frame-full.cf2 frame IS the deck-builder look; its x2/x3 count
    // badge is overlaid below via opts.count.

    var dimClass = opts.dim ? ' card-dimmed' : '';
    // cf2 = full-art frame marker; palette drives the element tint vars;
    // cf2-spell strips the minion stat rail for magic/react cards.
    // Deckle paper edge (default). A stable hash of the card id picks one of 12
    // fray variants (.cf2-deckle-N) so each card's edge wears differently but
    // consistently. (Seeded crease is OFF for now — to re-enable, also append
    // ' cf2-crease-' + (deckleSeed % 12); those 12 variants live in game.css.)
    var _cid = ((c && c.card_id) || '') + '', _seed = 0;
    for (var _i = 0; _i < _cid.length; _i++) _seed = (_seed * 31 + _cid.charCodeAt(_i)) >>> 0;
    var frameClasses = ' cf2 cf2-' + palette + (isMinion ? '' : ' cf2-spell') + ' cf2-deckle-' + (_seed % 12);
    var dataAttrs = '';
    if (opts.handIndex != null) dataAttrs += ' data-hand-idx="' + opts.handIndex + '"';
    if (opts.numericId != null) dataAttrs += ' data-numeric-id="' + opts.numericId + '"';

    // --- cost notes (rendered as bulleted lines inside the mode box) ---
    var costLines = [];
    if (c.discard_cost_tribe) {
        var sacN = c.discard_cost_count || 1;
        if (c.discard_cost_tribe === 'any') {
            costLines.push('Cost: Discard ' + (sacN > 1 ? sacN + ' cards' : 'a card'));
        } else {
            costLines.push('Cost: Discard any ' + (sacN > 1 ? sacN + ' ' : '') + c.discard_cost_tribe + (sacN > 1 ? 's' : ''));
        }
    }
    if (c.magic_untargetable) costLines.push('Cannot be targeted by magic cards');
    if (c.cost_reduction === 'dark_matter') costLines.push('Cost: Reduce mana cost by ' + _dmTokenLive());
    if (c.cost_reduction === 'wyrms_discarded') {
        costLines.push('Cost: Costs 1 less for each Wyrm you have discarded');
    }
    if (c.playable_from_exhaust) {
        costLines.push('Discarded: May be summoned from the Exhaust Pile for '
            + (c.exhaust_play_discount || 0) + ' less');
    }
    if (c.cost_reduction === 'behind_on_board') {
        costLines.push('Cost: Costs ' + (c.cost_reduction_amount || 0)
            + ' less if your opponent has a minion and you have none');
    }
    // Alternate discard cost (Dark Wyrm, user 2026-07-11) — a CHOICE, not
    // an additional cost: pay mana OR discard N other cards for free.
    if (c.alt_cost_discard) costLines.push('Cost: You may discard ' + c.alt_cost_discard + ' cards: ' + c.name + ' costs 0');
    if (c.play_condition === 'discarded_last_turn') costLines.push('Cost: Discard last turn');
    if (c.hp_cost) costLines.push('Cost: Deal ' + c.hp_cost + HEART + ' to own face');

    // --- static keyword tags (Range / Melee / Unique) ---
    var tags = [];
    if (isMinion && c.attack_range != null) {
        tags.push(c.attack_range === 0 ? 'Melee' : 'Range ' + c.attack_range);
    }
    if (c.unique) tags.push('Unique');

    // --- react mode box (shared by pure-react + multi-purpose cards) ---
    function buildReactBox() {
        var cost = (c.react_mana_cost != null) ? c.react_mana_cost : c.mana_cost;
        var timing = _CF2_REACT_TIMING[c.react_condition] || 'opponent acts';
        if (c.react_requires_no_friendly_minions) timing += ' while you control no minions';
        var reactEffectText = '';
        if (c.react_effect && c.react_effect.type === 5) {
            reactEffectText = 'Summon';
        } else if (c.react_effect) {
            // noTrigger: inside a React box the trigger label is redundant —
            // and a react_effect tagged on_summon must not read "Summon: ...".
            reactEffectText = getEffectDescription([c.react_effect], c, { noTrigger: true });
        } else if (c.effects && c.effects.length > 0) {
            reactEffectText = getEffectDescription(c.effects, c, { noTrigger: true });
        }
        var body = '';
        (reactEffectText || '').split('. ').forEach(function(line) {
            if (line) body += _cf2Line(line, false);
        });
        return '<div class="cf2-mode cf2-react">'
            + '<span class="cf2-modehead">⚡ React · ' + cost + ' mana — ' + timing + '</span>'
            + body + '</div>';
    }

    // --- assemble the floating mode boxes for the card body ---
    var boxes = '';
    if (isMinion) {
        var minionInner = '';
        costLines.forEach(function(l) { minionInner += _cf2Line(l, true); });
        if (c.effects && c.effects.length > 0) {
            getEffectDescription(c.effects, c).split('. ').forEach(function(line) {
                if (line) minionInner += _cf2Line(line, true);
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
            minionInner += _cf2Line(abDesc, true);
        }
        if (c.transform_options && c.transform_options.length > 0) {
            var tLines = c.transform_options.map(function(opt) {
                return '(' + opt.mana_cost + ') ' + findCardNameById(opt.target);
            });
            minionInner += _cf2Line('Transform: ' + tLines.join(', '), true);
        }
        if (minionInner) {
            boxes += '<div class="cf2-mode cf2-minion">' + minionInner + '</div>';
        } else if (c.flavour_text) {
            // Vanilla minion with no abilities: flavour reads as the box body.
            boxes += '<div class="cf2-mode cf2-minion"><span class="cf2-flavor">' + c.flavour_text + '</span></div>';
        }
        // Multi-purpose minion (Minion + React) — stack the react box.
        if (c.react_condition != null) {
            boxes += '<div class="cf2-ordiv">or</div>' + buildReactBox();
        }
    } else if (c.card_type === 1) {
        // MAGIC — cast box (+ optional react half for dual-mode cards).
        var magicInner = '';
        costLines.forEach(function(l) { magicInner += _cf2Line(l, false); });
        if (c.effects && c.effects.length > 0) {
            getEffectDescription(c.effects, c).split('. ').forEach(function(line) {
                if (line) magicInner += _cf2Line(line, false);
            });
        }
        boxes += '<div class="cf2-mode cf2-magic">'
            + '<span class="cf2-modehead">✨ Cast · ' + c.mana_cost + ' mana — your turn</span>'
            + magicInner + '</div>';
        if (c.react_condition != null) {
            boxes += '<div class="cf2-ordiv">or</div>' + buildReactBox();
        }
    } else {
        // Pure REACT card.
        boxes += buildReactBox();
    }
    // Vanilla non-minion with only flavour (rare) — show it if nothing else.
    if (!boxes && c.flavour_text) {
        boxes = '<div class="cf2-mode cf2-minion"><span class="cf2-flavor">' + c.flavour_text + '</span></div>';
    }

    // --- floating stat chips (minions only) ---
    var rail = '';
    if (isMinion && c.attack != null) {
        rail = '<div class="cf2-rail">'
            + '<div class="cf2-stat"><span class="cf2-stat-lbl">Attack</span><span class="cf2-stat-val">' + c.attack + '</span></div>'
            + '<div class="cf2-stat"><span class="cf2-stat-lbl">Health</span><span class="cf2-stat-val">' + c.health + '</span></div>'
            + '</div>';
    }

    // --- header subtitle: ◆ Element ◆ Tribe (minions) / ◆ Element (spells) ---
    var subtitle = '<span class="cf2-d">◆</span> ' + elem.name;
    if (isMinion && c.tribe) subtitle += ' <span class="cf2-d">◆</span> ' + c.tribe;

    var tagsHtml = tags.length
        ? '<div class="cf2-tags">' + tags.map(function(t) { return '<span class="cf2-tag">' + t + '</span>'; }).join('') + '</div>'
        : '';
    var artStyle = c.card_id ? ' style="background-image:url(' + _cardArtUrl(c.card_id) + ')"' : '';

    var html = '<div class="card-frame card-frame-full ' + typeClass + contextClass + dimClass + frameClasses + '"' + dataAttrs + '>';
    html += '<div class="cf2-frame">';
    html += '<div class="cf2-artbg"' + artStyle + '></div>';
    html += '<div class="cf2-head">';
    html += '<div class="cf2-chip cf2-cost"><span class="cf2-chip-lbl">Mana</span><span class="cf2-cnum">' + c.mana_cost + '</span></div>';
    html += '<div class="cf2-namebox"><div class="cf2-name">' + c.name + '</div><div class="cf2-subtype">' + subtitle + '</div></div>';
    html += '<div class="cf2-chip cf2-elem"><span class="cf2-chip-lbl">' + elem.name + '</span><span class="cf2-eico">' + elemEmoji + '</span></div>';
    html += '</div>';
    html += tagsHtml;
    html += '<div class="cf2-artspace"></div>';
    html += '<div class="cf2-body"><div class="cf2-text">' + boxes + '</div>' + rail + '</div>';
    html += '<div class="cf2-foot"><span>' + _cf2Collector(c) + '</span><span>' + SET_NAME + '</span><span>&copy; 2026 Grid Tactics</span></div>';
    html += '</div>'; // .cf2-frame
    html += '</div>'; // .card-frame

    // Count badge (deck-builder / tooltip contexts) — sibling of .card-frame
    // exactly as before, so the deck tile is its positioning context and the
    // badge overhangs the card corner (not clipped by the frame overflow).
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

    // Flat list, no type groups (user 2026-07-05). Keep the built deck in the
    // same ascending mana-cost order as the card browser; names stabilize ties.
    // Multi-purpose cards still get their gradient type stripe.
    var container = document.getElementById('deck-flat');
    if (!container) return;
    var prevScroll = container.scrollTop;
    var defs = allCardDefs || cardDefs;
    var items = [];
    Object.keys(currentDeck).forEach(function(numId) {
        var c = defs[numId];
        if (!c) return;
        items.push({ numId: numId, name: c.name, count: currentDeck[numId], card: c });
    });
    items.sort(function(a, b) {
        var costDiff = (a.card.mana_cost || 0) - (b.card.mana_cost || 0);
        if (costDiff !== 0) return costDiff;
        return a.name.localeCompare(b.name);
    });
    container.innerHTML = '';
    items.forEach(function(item) {
        var div = document.createElement('div');
        div.className = 'deck-list-item ' + deckItemTypeClass(item.card);
        div.dataset.numericId = item.numId;
        // Qty stepper on the right: "- n +", or "- 3 =" at max copies
        // (user 2026-07-05). The = marks max; - stays clickable to decrement.
        var atMax = item.count >= MAX_COPIES;
        div.innerHTML = '<span class="deck-list-item-name">' + item.name + '</span>'
            + '<span class="deck-qty">'
            + '<button class="deck-qty-btn deck-qty-minus" type="button" aria-label="Remove one">&#8722;</button>'
            + '<span class="deck-qty-count">' + item.count + '</span>'
            + (atMax
                ? '<span class="deck-qty-btn deck-qty-max" title="Max copies">=</span>'
                : '<button class="deck-qty-btn deck-qty-plus" type="button" aria-label="Add one">+</button>')
            + '</span>';
        div.querySelector('.deck-qty-minus').addEventListener('click', function(e) {
            e.stopPropagation();
            removeCardFromDeck(parseInt(item.numId, 10));
        });
        var plusBtn = div.querySelector('.deck-qty-plus');
        if (plusBtn) plusBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            addCardToDeck(parseInt(item.numId, 10));
        });
        // ! pin on deck rows too (user 2026-07-05) — same shared behaviour
        div.insertBefore(_makeTooltipPin(parseInt(item.numId, 10)), div.firstChild);
        // Hovering a deck row previews the card in the tooltip (user
        // 2026-07-05), same pin-aware rules as the grid.
        div.addEventListener('mouseenter', function() {
            if (deckTooltipLockId == null) showCardTooltip(parseInt(item.numId, 10));
        });
        div.addEventListener('mouseleave', function() {
            if (deckTooltipLockId == null) hideCardTooltip();
        });
        container.appendChild(div);
    });
    container.scrollTop = prevScroll;
}

// Shared ! pin (grid cards + deck rows): locks the card in the tooltip
// without deck changes. One card pinned at a time; clicking again unpins.
function _makeTooltipPin(numId) {
    var pin = document.createElement('button');
    pin.type = 'button';
    pin.className = 'card-info-lock' + (deckTooltipLockId === numId ? ' locked' : '');
    pin.dataset.pinId = numId;
    pin.title = 'Pin card details';
    pin.textContent = '!';
    pin.addEventListener('click', function(e) {
        e.stopPropagation();
        if (deckTooltipLockId === numId) {
            deckTooltipLockId = null;           // unpin; tooltip follows hover again
        } else {
            deckTooltipLockId = numId;
            showCardTooltip(numId);
        }
        _syncTooltipPins();
    });
    return pin;
}

function _syncTooltipPins() {
    document.querySelectorAll('#screen-deck-builder .card-info-lock').forEach(function(b) {
        b.classList.toggle('locked',
            deckTooltipLockId != null && parseInt(b.dataset.pinId, 10) === deckTooltipLockId);
    });
}

// Colour-coding class for a deck-list row: base type, or a multi class when a
// minion/magic card also has a react mode (react_condition set).
function deckItemTypeClass(c) {
    var isMulti = c.react_condition != null && c.card_type !== 2;
    if (c.card_type === 0) return isMulti ? 'dli-minion-react' : 'dli-minion';
    if (c.card_type === 1) return isMulti ? 'dli-magic-react' : 'dli-magic';
    return 'dli-react';
}

// Drive the HUD readiness-cell meter in the Deck Builder Loadout panel.
// Reads "N/M cards" from #deck-count (updated elsewhere as cards are
// added/removed) and toggles .on on the first N of the 30 LED cells.
// Sets a bucket class (.hud-readiness-low / .hud-readiness-mid /
// .hud-readiness-ready) to drive the fill colour (red → amber → green).
function _wireDeckReadinessMeter() {
    var deckCountEl = document.getElementById('deck-count');
    var meter = document.querySelector('.hud-readiness-cells');
    if (!deckCountEl || !meter) return;
    var cells = meter.querySelectorAll('span');
    var update = function() {
        var m = /(\d+)\s*\/\s*(\d+)/.exec(deckCountEl.textContent || '');
        var filled = m ? parseInt(m[1], 10) : 0;
        var total = m ? parseInt(m[2], 10) : 30;
        var ratio = total > 0 ? (filled / total) : 0;
        // Continuous-fill rendering (one edge, no per-cell subpixel snapping);
        // CSS draws the bar from --fill. The .on cells remain for any legacy skin.
        meter.style.setProperty('--fill', String(ratio));
        var target = Math.min(cells.length, Math.round(ratio * cells.length));
        for (var i = 0; i < cells.length; i++) {
            cells[i].classList.toggle('on', i < target);
        }
        meter.classList.toggle('hud-readiness-ready', filled >= total && total > 0);
        meter.classList.toggle('hud-readiness-mid',   filled < total && ratio >= 0.5);
        meter.classList.toggle('hud-readiness-low',   ratio < 0.5);
    };
    update();
    var obs = new MutationObserver(update);
    obs.observe(deckCountEl, { childList: true, characterData: true, subtree: true });
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
            // Save-by-name (user 2026-07-11 'the game is overwriting my
            // decks even though i called them differently'): SAVE used to
            // always write currentSlotIdx (0 unless you loaded a slot), so
            // a fresh deck under a new name clobbered the loaded one. Now
            // the NAME picks the slot — an existing name updates that
            // slot, a new name appends a new one.
            var slots = loadDeckSlots();
            if (!name) name = 'Deck ' + (slots.length + 1);
            var targetIdx = -1;
            for (var si = 0; si < slots.length; si++) {
                if ((slots[si].name || '').toLowerCase() === name.toLowerCase()) {
                    targetIdx = si;
                    break;
                }
            }
            if (targetIdx === -1) targetIdx = slots.length;  // new slot
            currentSlotIdx = targetIdx;
            saveDeckSlot(targetIdx, name, Object.assign({}, currentDeck));
            refreshLoadDropdown();
            populateDeckSelector();  // refresh lobby dropdown too
            showLobbyStatus('Deck saved!', 'info');
        });
    }

    // Clear Deck — two-step confirm (first click arms, second clears;
    // disarms after 2.5s). No browser confirm() dialogs.
    var btnClear = document.getElementById('btn-clear-deck');
    if (btnClear) {
        var clearArmTimer = null;
        var clearLabel = btnClear.querySelector('span:last-child');
        var disarmClear = function() {
            if (clearArmTimer) clearTimeout(clearArmTimer);
            clearArmTimer = null;
            btnClear.classList.remove('armed');
            if (clearLabel) clearLabel.textContent = 'CLEAR';
        };
        btnClear.addEventListener('click', function() {
            if (clearArmTimer) {
                disarmClear();
                currentDeck = {};
                renderDeckBuilder();
            } else {
                btnClear.classList.add('armed');
                if (clearLabel) clearLabel.textContent = 'SURE?';
                clearArmTimer = setTimeout(disarmClear, 2500);
            }
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
