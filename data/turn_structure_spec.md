# Turn Structure & Priority System — Design Spec (v3)

Authoritative turn flow, phase boundaries, react windows, and effect-resolution priority rules for Grid Tactics TCG. Single source of truth when implementing or modifying turn logic, react timing, or stack/queue behavior.

> **ACTIVE RULES EXPERIMENT (2026-07-11 v4)** (`GT_MANUAL_DRAW=1`, on by default in
> `pvp_server.py`; the bare engine / test suite default to the standard rules below):
> - NO turn-start auto-draw (and no turn-start empty-deck fatigue). **REST** (the
>   reserved DRAW action slot) consumes the turn action for **+1 mana AND +1 draw**
>   (overdraw-burns on a full hand; empty deck skips the draw, mana still granted).
>   **PASS is a separate action and gives NO benefit** (v4, user 2026-07-11). BOTH
>   REST and PASS advance the Handshake streak — any two consecutive skips (rest/rest,
>   rest/pass, pass/pass) seal a Handshake.
> - **MAGIC casts do not consume the turn action**: after the cast resolves (including
>   its react windows / pending modals) play returns to the caster's ACTION phase on the
>   same turn (`GameState.magic_free_action_pending`, consumed at the after-action
>   react-window close; defensively cleared on turn flip).
> - **Handshake payout: BOTH players gain +1 mana AND draw a card** — the only built-in
>   draw source besides card effects.
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

1. **Turn Start** — automatic draw + mana gain
2. **Rally Phase** — positive once-per-turn triggers
3. **Action Phase** — exactly one action
4. **Decay Phase** — negative once-per-turn effects
5. **Turn End** — Handshake payout, cleanup, turn passes

Priority begins with the turn player in every phase.

---

## 3. Turn Start

The active player automatically:

1. **Draws 1 card** (mandatory — not an action).
2. **Gains 1 mana.**

### 3.1 Mana Pool

Mana is a **single pool** — there are no crystals:

- +1 mana at every turn start.
- Spending mana **permanently depletes** it until rebuilt (+1 per turn, plus Handshake payouts).
- `MAX_MANA_CAP = 10` — a pool of 10 is "full"; turn-start gain does not raise it past 10.

### 3.2 Fatigue (empty-deck draw ONLY)

If the deck is **empty** at the turn-start draw, the player takes **fatigue damage instead of drawing**: escalating **10🤍, 20🤍, 30🤍, ...** per empty-deck draw. Fatigue exists **only** here — no other game action deals fatigue damage (in particular, PASS is free — see §5).

### 3.3 Overdraw Burns

If the player's hand is full (`MAX_HAND_SIZE = 10`), the drawn card is sent to the **Exhaust Pile, revealed to both players**, instead of entering the hand. See §9 — this applies to ALL draw paths, not just the turn-start draw.

### 3.4 Opening-Turn Exception (turns 1–2)

The full Turn Start sequence (§3) applies from **turn 3 onward**. The game's opening two turns deliberately deviate to keep the first-player advantage in check:

- **Turn 1 (P1's first turn):** NO turn-start draw and NO mana gain. The game begins directly in P1's Action Phase. The asymmetric starting hands (`STARTING_HAND_P1 = 3`, `STARTING_HAND_P2 = 4`) plus both players opening at `STARTING_MANA = 1` stand in for it.
- **Turn 2 (P2's first turn):** the turn-start draw happens normally, but the **+1 mana gain is suppressed** so P2's first action starts at the same `STARTING_MANA` as P1's first action.

Implementation home: `react_stack._close_end_of_turn_and_flip` (the turn-flip tail — turn 1 never runs it; turn 2 skips only the mana regen).

---

## 4. Rally Phase

Player-facing name for the start-of-turn trigger phase (implementation home: existing `ON_START_OF_TURN` machinery).

**ALL once-per-turn POSITIVE passives and triggers proc here** — e.g. Fallen Paladin's heal.

Big symbols and icons in the middle of the screen with blips from the relevant cards or areas affected.

React window opens before the phase ends.

---

## 5. Action Phase

The turn player takes **exactly one action**:

- Play a card (Minion or Magic, paying its cost)
- Move a friendly minion
- Attack with a friendly minion
- Sacrifice (minion at far edge crosses the board)
- Activate a unit's activated ability
- **PASS**

**DRAW is removed as an action.** Action slot 1000 stays reserved in the action space but is never legal (auto-draw happens at Turn Start).

**PASS is FREE.** It must NOT deal fatigue damage — fatigue now exists only for empty-deck turn-start draws (§3.2). Passing is a legitimate strategic choice and feeds the Handshake mechanic (§8).

### 5.1 Melee Exception

Melee minions may take up to two actions in the Action Phase (one `move` + one `attack`) with **two separate react windows** — one after the move, one after the attack.

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

New mechanic. When a player **PASSES as their Action-Phase action** and the opponent's immediately-previous Action-Phase action was **also PASS**, a **Handshake** occurs. (Passes that merely close react windows do not count.)

At the **end of that turn** (Decay/turn-end processing):

- **BOTH players gain +1 mana.**
- A player whose mana is already full (10) **draws a card instead** (overdraw-burn rules apply — §9).

The consecutive-pass counter then **resets to 0** — no chaining. The next Handshake requires a fresh pair of consecutive passes.

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
- `KEYWORD_GLOSSARY` in `src/grid_tactics/server/static/game.js`
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
- [ ] Turn Start: active player auto-draws 1 card AND gains 1 mana (single pool, `MAX_MANA_CAP = 10`) — subject to the documented opening-turn exception (§3.4: no draw/mana on turn 1, no mana gain on turn 2).
- [ ] Empty deck at turn-start draw = escalating fatigue (10/20/30...) instead of the draw — and NOWHERE else.
- [ ] Rally Phase: all once-per-turn positive triggers proc via `ON_START_OF_TURN`; animate with center-screen icon + source/target blip.
- [ ] Action Phase: exactly one action; DRAW (slot 1000) reserved but never legal; PASS is free and deals NO fatigue.
- [ ] Decay Phase: all once-per-turn negative effects proc via `ON_END_OF_TURN`; Burning ticks 5🤍 in the minion OWNER's Decay Phase.
- [ ] Trigger machinery supports per-card turn scoping (every turn / owner's turn / opponent's turn) per card wording.
- [ ] Handshake: PASS answered by PASS → at turn end BOTH players +1 mana (full-mana player draws instead); counter resets to 0, no chaining.
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
- [ ] Movement keyword renamed Rally → March everywhere (GLOSSARY, game.js `KEYWORD_GLOSSARY`, card JSONs).
- [ ] Existing modals (tutor-style) and animations (spell-stage) are reused, not replaced.

---

## 15. Glossary

- **Turn player:** The player whose turn it currently is. Has priority in all simultaneous-effect resolutions.
- **Rally Phase:** Player-facing name for the start-of-turn trigger phase (`ON_START_OF_TURN`). Positive once-per-turn effects proc here.
- **Decay Phase:** Player-facing name for the end-of-turn trigger phase (`ON_END_OF_TURN`). Negative once-per-turn effects proc here.
- **Handshake:** A PASS answered by a PASS. At turn end both players gain +1 mana (a full-mana player draws instead); the pass counter resets.
- **Fatigue:** Escalating damage (10🤍/20🤍/30🤍...) taken when drawing at turn start with an empty deck. The only source of fatigue in the game.
- **Overdraw-burn:** A card drawn while the hand is full (10) goes to the Exhaust Pile, revealed, instead of the hand.
- **March:** Movement keyword (formerly "Rally") — when this minion moves, all other friendly copies also advance.
- **React window:** A bounded timing window during which eligible React cards may be played.
- **Fizzle:** An effect that fails to resolve because its target/condition is no longer valid.
- **Stack:** LIFO structure holding pending reacts — the last react played resolves first (§6).
- **Queue:** Priority-ordered list of simultaneous triggers — the turn player's effects resolve first, each owner picking the resolution order via the modal card picker (§5.3).
- **Summon: / Death: / Start (Rally Phase) / End (Decay Phase):** Triggered ability moments. Each opens its own react window when triggered.
- **Melee sub-action:** One of the two actions a melee minion may take in a single Action Phase (move or attack). Each opens its own react window.
