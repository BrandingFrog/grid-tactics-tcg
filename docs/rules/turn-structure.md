# Turn Structure & Priority System — Design Spec (v5)

Authoritative turn flow, phase boundaries, react windows, and effect-resolution priority rules for Grid Tactics TCG. Single source of truth when implementing or modifying turn logic, react timing, or stack/queue behavior.

> **ACTIVE RULES (2026-07-14 v5)** (`GT_MANUAL_DRAW=1`, the default for live,
> headless, and RL play; `GT_MANUAL_DRAW=0` selects legacy compatibility rules):
> - NO turn-start auto-draw or turn-start empty-deck fatigue.
> - Each player has a public **Action Point bank**: gain 1 on each own turn, bank up
>   to 3. Every primary action — including MAGIC — spends 1. Reactions,
>   modal choices, and the optional post-move attack/decline spend 0.
> - After each action and its complete reaction/modal chain, play returns to the same
>   player's Action Phase while at least one point remains.
> - **REST** (DRAW slot) is the existing rewarded no-action turn end. It is legal
>   only before a point is spent, costs 0, banks the full pool, grants +1 mana,
>   draws the Fortune ante, and offers a Handshake. After any point is spent,
>   REST changes to **PASS**: cost 0, no effect, end the turn.
> - Two consecutive RESTs seal a Handshake. React-window passes never count.
> - **Handshake payout: BOTH players gain +1 mana AND draw a card**. REST is the
>   regular built-in draw source; card effects may draw as written.
> - Automatic turn mana and REST cards both start at 1. Each completed Fortune round
>   raises both by 1, effective immediately when the postponed incoming turn resumes.
> Everything else in this spec is unchanged. Flag: `grid_tactics.types.manual_draw_variant()`.

Decided by the product owner 2026-07-02. Supersedes the v2 three-phase spec.

Reuse existing UI: the spell-stage center-screen react animation drives react windows; the tutor modal (renderDeckBuilderCard) drives same-player priority picking.

**Terminology note:** The `TurnPhase.START_OF_TURN` / `TurnPhase.END_OF_TURN` enum values STAY as-is (append-only enum rule). **Rally** and **Decay** are the player-facing names for those phases, used in all card text, docs, events, and UI. `ON_START_OF_TURN` is the implementation home for Rally triggers; `ON_END_OF_TURN` is the implementation home for Decay triggers.

---

## 1. Turn Banner

Big message animates on screen at the start of every turn:

- Line 1: `TURN X`
- Line 2: `PLAYER X`

Non-blocking — game state progression runs concurrently. Auto-dismisses after a short duration.

---

## 2. Phase Sequence

Each turn consists of five ordered phases:

1. **Turn Start** — Action Point gain + automatic mana gain
2. **Rally Phase** — positive once-per-turn triggers
3. **Action Phase** — spend banked Action Points or end early
4. **Decay Phase** — negative once-per-turn effects
5. **Turn End** — Handshake payout, cleanup, turn passes

Priority begins with the turn player in every phase.

---

## 3. Turn Start

Under active rules, the player gains 1 Action Point (cap 3) and gains mana
equal to the current Fortune ante. There is no automatic draw.

### 3.1 Mana Pool

Mana is a **single pool** — there are no crystals:

- +1 mana at every turn start before any Fortune; +1 more after each completed Fortune round.
- Spending mana **permanently depletes** it until rebuilt (+1 per turn, plus Handshake payouts).
- `MAX_MANA_CAP = 10` — a pool of 10 is "full"; turn-start gain does not raise it past 10.

### 3.2 Fatigue (legacy standard rules only)

`GT_MANUAL_DRAW=0` retains escalating fatigue on an empty-deck automatic
turn-start draw. Active rules have no automatic draw, so they have no
turn-start fatigue; an empty-deck REST still grants its mana and draws nothing.

### 3.3 Overdraw Burns

If the player's hand is full (`MAX_HAND_SIZE = 10`), the drawn card is sent to the **Exhaust Pile, revealed to both players**, instead of entering the hand. See §9 — this applies to ALL draw paths, not just the turn-start draw.

### 3.4 Opening-Turn Exception (turns 1–2)

The full Turn Start sequence (§3) applies from **turn 3 onward**. The game's opening two turns deliberately deviate to keep the first-player advantage in check:

- **Turn 1 (P1's first turn):** P1 begins directly in Action with 1 point and starting mana.
- **Turn 2 (P2's first turn):** P2 receives its first Action Point; automatic mana is suppressed because both players already open at `STARTING_MANA = 1`.

Implementation home: `react_stack._close_end_of_turn_and_flip` (the turn-flip tail — turn 1 never runs it; turn 2 skips only the mana regen).

---

## 4. Rally Phase

Player-facing name for the start-of-turn trigger phase (implementation home: existing `ON_START_OF_TURN` machinery).

**ALL once-per-turn POSITIVE passives and triggers proc here** — e.g. Fallen Paladin's heal.

Big symbols and icons in the middle of the screen with blips from the relevant cards or areas affected.

React window opens before the phase ends.

---

## 5. Action Phase

The turn player spends from a shared bank of up to 3 Action Points. Each of
the following primary actions costs 1:

- Play a card (Minion or Magic, paying its cost)
- Move a friendly minion
- Attack with a friendly minion
- Sacrifice (minion at far edge crosses the board)
- Transform a friendly minion
- Play an eligible card from Exhaust
- Activate a unit's activated ability

REST is not a primary action. Before spending any point, the existing
end-turn control is **REST**: it costs 0 and banks all points.

REST uses the reserved DRAW action slot 1000; no protocol/action-space migration is required.

After spending at least one point, **PASS costs 0 and has no effect.** It ends
the turn immediately and preserves unspent points. It does not create a Handshake.
If the final Action Point is spent, the turn passes automatically after that
action and all of its React/modal continuations finish.

### 5.1 Melee Exception

MOVE plus its optional melee attack/decline costs 1 total, while retaining
**two separate react windows** — one after the move, one after the attack.

A React card is only triggered if its condition is valid for the action being reacted to.

### 5.2 Multiple React Windows Per Action

Some actions open multiple react windows.

**Example — Summoning a minion with a Summon: effect:**

1. **Window A — On Summon Declaration:** Pay the cost and declare the summon. Opponent may play a React that negates the summon. If successful, the player **loses both the cost and the summon**.
2. **Window B — On Summon: effect:** If the summon resolves and the minion has a `Summon:` ability, a second react window opens for the opponent to react to that ability.

The same pattern applies to **Death:** effects and any other triggered ability.

### 5.3 Priority and Fizzle

When multiple effects trigger at the same moment, the turn player resolves theirs first.

**Example — Player 1 RGB Laser Cannon vs Player 2 Giant Rat:**

Both have `Death:` effects. They kill each other. Because it is Player 1's turn:

1. RGB Laser Cannon's Death resolves first (turn-player priority).
2. Player 1 targets Player 2's other Rat on the field. A react window opens while Giant Rat's death effect sits in a queue.
3. If Player 1 destroys the other Rat, Giant Rat's Death effect no longer has a valid target and **fizzles** — enabling strategies for the turn player to pre-empt enemy death triggers.

**Multiple same-player triggers:** When the turn player has multiple cards that died with `Death:` effects, they see a modal window showing the **full card face** of each dying minion's source. They pick which effect resolves first; it resolves (with its own react window if needed); then they pick the next. After all turn-player effects resolve or fizzle, the opposing player does the same with theirs.

This is **not limited to Death: effects** — the same priority/queue/fizzle system applies to any effect that triggers simultaneously with others (Summon:, Rally-Phase (Start:) triggers, Decay-Phase (End:) triggers, activated-ability triggers, etc.).

---

## 6. React Windows

- LIFO stack: the last react played resolves first.
- Each react, when played, opens a new react window on top (chain reactions).
- A window closes when both players pass consecutively with no reacts played, OR no player has a legally playable react matching the trigger condition.
- **No design depth limit.** React chains may run as deep as players' cards allow. `MAX_REACT_STACK_DEPTH = 100` remains in code purely as a runaway-recursion failsafe (update its comment accordingly) — it is NOT a gameplay rule.
- UI: reuse the existing spell-stage center-screen animation (LEFT slot = card played, RIGHT slot = `?` awaiting react / `⚡` resolving / `👍` done). Every react window uses this stage regardless of trigger kind.

---

## 7. Decay Phase

Player-facing name for the end-of-turn trigger phase (implementation home: existing `ON_END_OF_TURN` machinery).

**ALL once-per-turn NEGATIVE effects proc here.**

Big symbols and icons in the middle of the screen with blips from the relevant cards or areas affected.

React window opens before the phase ends.

### 7.1 Burning

Burning moves from the old start-of-turn tick to the **Decay Phase of the MINION OWNER's turn**: a Burning minion takes 5🤍 in its owner's Decay Phase. Same once-per-round rate as before — just moved.

### 7.2 Per-Card Turn Scoping

The trigger machinery must support per-card scoping — card wording decides which turns an effect ticks on:

- **Every turn** (default — no scoping wording)
- **Owner's turn only** ("during your turn")
- **Opponent's turn only** ("during your opponent's turn")

See §11 for the wording rules.

---

## 8. Handshake

A REST offers a Handshake. If the opponent's immediately following turn also
ends with REST before any intervening paid action, a **Handshake** occurs.
PASS or a paid action declines/breaks the offer. React-window passes never count.

At the **end of that turn** (Decay/turn-end processing):

- **BOTH players gain +1 mana** (capped at 10).
- **BOTH players draw 1 card** (overdraw-burn rules apply — §9).

The REST streak then resets — no chaining. The next Handshake requires a fresh pair.

---

## 9. Hand Size & Overdraw-Burn

- `MAX_HAND_SIZE = 10` — a new shared constant in `types.py`. Replace every bare literal `10` hand-cap with it.
- **Overdraw burns:** any draw while the hand is full sends the drawn card to the **Exhaust Pile, revealed**, instead of fizzling. This applies to **ALL** draw paths:
  - Turn-start draw
  - Card-effect draws
  - Handshake draws
  - **Tutor-to-hand** (also burns, for consistency — no silent skip)

---

## 10. Keyword Rename: Rally → March

The movement keyword formerly named "Rally" (when this minion moves, all other friendly copies also advance) is renamed **March** everywhere, freeing "Rally" for the phase name:

- `data/GLOSSARY.md`
- `KEYWORD_GLOSSARY` in `src/grid_tactics/server/static/js/03-deck-builder.js`
- Card JSONs (`rally` → `march` effect key if present, plus card text)
- Wiki sync handles the rest on commit.

---

## 11. Turn-Scoping Wording Rules

- **"During your turn"** on a card restricts the effect to the card owner's action turn only.
- **"During your opponent's turn"** restricts it to the opponent's action turn only.
- Effects **without** such wording tick on **every player's turn** — "every player's turn is a turn."

---

## 12. Turn End

Handshake payout resolves (if triggered — §8), cleanup happens, and the turn passes to the next player.

---

## 13. Fizzle Rule

If an effect's target is no longer valid at resolution time (destroyed, moved, etc.), the effect fizzles silently — no error, no partial resolution. This is a core strategic mechanic.

---

## 14. Implementation Checklist

When touching turn logic, verify:

- [ ] Turn banner renders at turn start with `TURN X` + `PLAYER X`.
- [ ] Active Turn Start: gain 1 Action Point (cap 3) and Fortune-ante mana; no auto-draw.
- [ ] Legacy-only empty-deck turn-start draw = escalating fatigue (10/20/30...); active rules never apply turn-start fatigue.
- [ ] Rally Phase: all once-per-turn positive triggers proc via `ON_START_OF_TURN`; animate with center-screen icon + source/target blip.
- [ ] Action Phase: each primary action (including MAGIC) costs 1; reactions and continuations cost 0; same player continues while points remain.
- [ ] REST is the 0-AP rewarded no-action end, banks all points, grants +1 mana + ante cards, and offers Handshake. After an AP is used, only no-effect PASS remains.
- [ ] Decay Phase: all once-per-turn negative effects proc via `ON_END_OF_TURN`; Burning ticks 5🤍 in the minion OWNER's Decay Phase.
- [ ] Trigger machinery supports per-card turn scoping (every turn / owner's turn / opponent's turn) per card wording.
- [ ] Handshake: REST answered by REST → at turn end BOTH players +1 mana and draw 1 under active rules; counter resets.
- [ ] Each completed Fortune immediately raises automatic turn mana and REST cards by 1.
- [ ] `MAX_HAND_SIZE = 10` constant in `types.py` — no bare literal hand caps remain.
- [ ] Overdraw burns on ALL draw paths (turn-start, effects, Handshake, tutor-to-hand): card goes to Exhaust Pile, revealed.
- [ ] React window opens before Rally Phase ends, after each Action Phase action (including each melee sub-action and each compound sub-trigger), and before Decay Phase ends.
- [ ] Melee minions get **2 independent** react windows (one post-move, one post-attack).
- [ ] Summon actions open **two** react windows when the minion has a `Summon:` effect. Negate on Window A = cost AND summon are lost.
- [ ] React cards validate their condition against the trigger before allowing play.
- [ ] No design react depth limit — `MAX_REACT_STACK_DEPTH = 100` is a runaway failsafe only, with a comment saying so.
- [ ] Simultaneous effects: turn player's effects always resolve first.
- [ ] Player with multiple simultaneous triggers sees a **modal card picker** (full card face) to order their resolution.
- [ ] Effects with no valid target at resolution time **fizzle** cleanly (no error, no partial resolution).
- [ ] Stack is LIFO — reacts resolve in reverse play order.
- [ ] Priority rules apply to all effect types, not just Death.
- [ ] `TurnPhase.START_OF_TURN` / `END_OF_TURN` enum values unchanged; "Rally" / "Decay" used in player-facing text, docs, events, and UI.
- [ ] Movement keyword renamed Rally → March everywhere (GLOSSARY, browser `KEYWORD_GLOSSARY`, card JSONs).
- [ ] Existing modals (tutor-style) and animations (spell-stage) are reused, not replaced.

---

## 15. Glossary

- **Turn player:** The player whose turn it currently is. Has priority in all simultaneous-effect resolutions.
- **Rally Phase:** Player-facing name for the start-of-turn trigger phase (`ON_START_OF_TURN`). Positive once-per-turn effects proc here.
- **Decay Phase:** Player-facing name for the end-of-turn trigger phase (`ON_END_OF_TURN`). Negative once-per-turn effects proc here.
- **Action Point:** Public banked currency for primary actions; gain 1 per own turn, cap 3.
- **Handshake:** A REST answered by REST. Active payout gives both players +1 mana and draw 1.
- **Fatigue:** Escalating damage (10🤍/20🤍/30🤍...) taken when drawing at turn start with an empty deck. The only source of fatigue in the game.
- **Overdraw-burn:** A card drawn while the hand is full (10) goes to the Exhaust Pile, revealed, instead of the hand.
- **March:** Movement keyword (formerly "Rally") — when this minion moves, all other friendly copies also advance.
- **React window:** A bounded timing window during which eligible React cards may be played.
- **Fizzle:** An effect that fails to resolve because its target/condition is no longer valid.
- **Stack:** LIFO structure holding pending reacts — the last react played resolves first (§6).
- **Queue:** Priority-ordered list of simultaneous triggers — the turn player's effects resolve first, each owner picking the resolution order via the modal card picker (§5.3).
- **Summon: / Death: / Start (Rally Phase) / End (Decay Phase):** Triggered ability moments. Each opens its own react window when triggered.
- **Melee continuation:** The optional attack/decline after MOVE. It costs no additional point but keeps its own react window.
