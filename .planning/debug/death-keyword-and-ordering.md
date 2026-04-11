---
status: verifying
trigger: "Death: keyword does not fire; no ordering system for simultaneous death triggers"
created: 2026-04-11T00:00:00Z
updated: 2026-04-11T00:00:00Z
---

## Current Focus

hypothesis: Confirmed — on_death machinery EXISTS but is partially broken at the EffectType-dispatch level for the exact shapes the live cards use (DESTROY single_target, PROMOTE self_owner). Separately, ordering is by instance_id only (no active-player priority).
test: Read effect_resolver dispatch + tensor_engine/effects.py; compare to the two live cards (lasercannon, giant_rat); check tests.
expecting: Root cause has three distinct defects — see Resolution.
next_action: Await user approval for the fix plan below.

## Symptoms

expected:
  - Any minion with Death: / on_death effect resolves its effect on death (damage, spawn, etc.).
  - Multiple simultaneous deaths resolve sequentially in order: active player first, then by play order (instance_id asc).
  - Modal-friendly: one effect fully resolves before the next begins.

actual:
  - Death effects never fire — silent.
  - No ordering system for simultaneous deaths.

errors: none — silent failure.

reproduction:
  - Place minion with on_death effect, kill it, observe effect does not resolve.

started: unknown — just discovered.

## Eliminated

(none yet)

## Evidence

- checked: `src/grid_tactics/enums.py`
  found: `TriggerType.ON_DEATH = 1`, `EffectType.PROMOTE = 7`, `EffectType.DESTROY = 9`. All enums present.
  implication: Not a missing-enum problem. Schema exists.

- checked: `data/GLOSSARY.md` line 11 and `src/grid_tactics/server/static/game.js` (KEYWORD_GLOSSARY line 1246, TRIGGER_NAMES line 83)
  found: Both list "Death" / "On Death" and map trigger id 1 -> "Death". Rendering-side is fine.
  implication: Tooltip will display "Death:" prefix for any card with `trigger: on_death` — so the user sees the promise but the engine doesn't keep it.

- checked: `data/cards/*.json` for `"trigger": "on_death"`
  found: Exactly 2 live cards use on_death today:
    - `minion_rgb_lasercannon.json`: `{type: destroy, trigger: on_death, target: single_target, amount: 1}`
    - `minion_giant_rat.json`: `{type: promote, trigger: on_death, target: self_owner, amount: 10}` (with `promote_target: "rat"`, `unique: true`)
  implication: These are the two shapes that the on_death path must support. Neither is covered by existing tests.

- checked: `src/grid_tactics/action_resolver.py` lines 885-934, `_cleanup_dead_minions`
  found: Implementation does find dead minions, remove them from board, add to grave, then call `resolve_effects_for_trigger(state, ON_DEATH, dead_m, library)` sorted by `instance_id` ascending. Called from 4 action-resolver sites plus 3 react_stack sites. Runs BEFORE react window transition — correct placement for modal interaction.
  implication: Cleanup + trigger-dispatch plumbing is present. This is NOT "never implemented". The hook site is correct. The bug lives one layer deeper.

- checked: `src/grid_tactics/effect_resolver.py::resolve_effects_for_trigger` lines 387-425
  found: Dispatch filters card_def.effects by trigger, then for each matching effect:
    - TUTOR -> `_enter_pending_tutor`
    - CONJURE -> `_resolve_conjure`
    - RALLY_FORWARD -> `_apply_rally_forward`
    - everything else -> `resolve_effect(..., target_pos=None)` (note: no target_pos plumbed through, defaults to None)
  implication: For the death path, effects fall into the catch-all branch with `target_pos=None`.

- checked: `src/grid_tactics/effect_resolver.py::resolve_effect` + `_resolve_single_target` lines 200-213 and 375-384
  found: For `TargetType.SINGLE_TARGET`, `_resolve_single_target` bails if `target_pos is None`: "No valid target — skip effect (e.g., minion deployed with no enemies)". Silent no-op.
  implication: **DEFECT #1** — Lasercannon's Death effect is `destroy/single_target`. It's handed target_pos=None. It silently returns. The user never sees the destroy happen.

- checked: `src/grid_tactics/effect_resolver.py::_apply_effect_to_minion` lines 123-172
  found: The dispatch handles DAMAGE, HEAL, BUFF_ATTACK, BUFF_HEALTH, DESTROY, BURN, PASSIVE_HEAL, APPLY_BURNING, GRANT_DARK_MATTER. Docstring at 128-131 explicitly says: "Effect types that don't apply to a minion (CONJURE, TUTOR, RALLY, **PROMOTE**, NEGATE, DEPLOY_SELF, LEAP, DARK_MATTER_BUFF) are silently skipped here — they're handled by other code paths".
  found: But grepping `PROMOTE|promote` across `src/grid_tactics/` (excluding tensor_engine) shows only the enum definition and this docstring. No "other code path" exists.
  implication: **DEFECT #2** — Python engine has zero PROMOTE handler. Giant Rat's on_death effect is silently skipped. The comment is a lie.

- checked: `src/grid_tactics/tensor_engine/effects.py` lines 22-75, 249-319, 468-487
  found: Tensor engine's `apply_effects_batch` DOES dispatch PROMOTE (etype==7 at line 60) to `_apply_promote`, which correctly finds a friendly minion of `promote_target_id`, respects the unique constraint, and transforms its card_id/health/atk_bonus. DESTROY (etype==9) also dispatched at line 62 to `_apply_destroy`, which also no-ops for single_target when target_flat_pos points to no minion.
  implication: **Parity gap.** Tensor engine handles Giant Rat correctly but Python engine doesn't. Tensor engine has the same Lasercannon bug (single_target DESTROY on death has no target). RL training has been using a different rules model than UI play for Giant Rat.

- checked: `src/grid_tactics/tensor_engine/engine.py::cleanup_dead_minions_batch` lines 572-667
  found: Two-pass cleanup (comment at 583: "Two passes per Python engine convention") — so a chain-reaction (Giant Rat's promotion triggers another death, or Lasercannon's destroy kills another minion whose on_death triggers) would get a second pass. BUT the Python engine does NOT do a second pass — `_cleanup_dead_minions` runs once per call site. Another parity gap.
  implication: **DEFECT #3** — if an on_death effect kills another minion, Python engine leaks a corpse until the next action-level cleanup. Tensor engine already handles this.

- checked: ordering in both engines
  found: Python sorts by `instance_id` ascending (line 928). Tensor iterates slot index 0..MAX_MINIONS ascending (line 653). Neither prioritizes active player.
  implication: **DEFECT #4** — ordering spec is "active player first, then instance_id". Neither engine implements it. Today: opponent's death triggers can fire before yours after a mutual-kill or AoE. Needs fixing in both engines.

- checked: `tests/test_action_resolver.py::test_on_death_effects_trigger_in_instance_id_order` lines 667-697
  found: Only covers `DAMAGE ALL_ENEMIES on_death` (a synthetic test card). No coverage for DESTROY or PROMOTE on_death.
  implication: Existing test coverage is lucky — the narrowest possible shape happens to work because `ALL_ENEMIES` doesn't need `target_pos`. The two real-card shapes have never been tested.

- checked: modal / interactive targeting for death effects
  found: Pending-modal infra exists for tutor (`pending_tutor_player_idx` in game_state.py, gated in action_resolver lines 1093+) and conjure-deploy (`pending_conjure_deploy_card`). Neither is currently reachable from a death trigger (since the loop is synchronous at line 929-932). If death effects later open modals, they'd need a new pending state analogous to these — the sequential-per-death loop already exists, but would need to be rewritten as a resumable state machine.
  implication: **Future-proofing note, not a current defect.** Current live cards (lasercannon, giant_rat) don't need modals — destroy/single_target is random-pick-semantics per card text "destroy 1 target" with no UI picker, and promote is fully deterministic. Both fixes can land without touching the pending-state machine. But the ORDERING fix should be written in a way that a future modal-death can slot in cleanly (e.g. compute the sorted death queue once, then resolve sequentially — same shape).

## Resolution

root_cause:
  Four distinct defects conspire to make "Death:" look completely broken on the two cards that use it today:

  1. **Lasercannon (`destroy/single_target/on_death`) silently no-ops in both engines** because `resolve_effects_for_trigger` (Python) and `apply_effects_batch` (tensor) pass `target_pos=None`/`EMPTY` to the death trigger. `_resolve_single_target` bails early. Root issue: the card's effect semantically means "on death, destroy an enemy" but it's encoded as `single_target` without any target-picker logic. Either (a) the effect needs a random-enemy target-resolution path for death-trigger `single_target`, or (b) the card should be re-encoded as `all_enemies` or a new `random_enemy` target type. Path (a) preserves the data and matches likely intent ("destroy 1"). Path (b) is a data migration. **Recommend (a)** — add a `random_enemy` sub-path for `single_target` when triggered by on_death with no explicit target, OR better, introduce `TargetType.RANDOM_ENEMY` and migrate the card.

  2. **Giant Rat (`promote/self_owner/on_death`) silently no-ops in the Python engine only.** Tensor engine already has a correct `_apply_promote`. Python engine `_apply_effect_to_minion` lists PROMOTE in its "silently skipped" comment but has no "other code path". This is a pure parity gap — port the tensor implementation into `effect_resolver.py`, add a PROMOTE branch in `resolve_effects_for_trigger` (analogous to how RALLY_FORWARD is special-cased).

  3. **Chain-reaction death cleanup is one-pass in Python, two-pass in tensor.** If DEFECT #1 is fixed, Lasercannon's death could kill a second minion whose own on_death should also fire. Python's `_cleanup_dead_minions` needs to loop (call itself, or loop until no more dead) before returning. Tensor engine already does this.

  4. **Ordering is instance_id-only, not active-player-first.** Both engines sort/iterate by instance_id/slot. Spec requires: "active player's deaths first, then within each player by instance_id ascending". Fix: in Python, change sort key at line 928 from `lambda m: m.instance_id` to `lambda m: (m.owner != active_side, m.instance_id)` where `active_side = state.players[state.active_player_idx].side`. In tensor engine, iterate slots twice — once filtering to `minion_owner == active_player`, once filtering to the other side.

fix:
  Proposed plan (awaiting user approval before implementing):

  **A. Python engine parity: implement PROMOTE**
  - File: `src/grid_tactics/effect_resolver.py`
  - Add `_apply_promote(state, dying_minion, library) -> GameState` mirroring `tensor_engine/effects.py::_apply_promote` (deterministic "most advanced friendly target" pick, unique constraint).
  - In `resolve_effects_for_trigger` dispatch, add `elif effect.effect_type == EffectType.PROMOTE: state = _apply_promote(state, minion, library)` alongside RALLY_FORWARD.
  - Update the docstring at `_apply_effect_to_minion` line 128-131 to remove the PROMOTE lie.

  **B. Make `destroy/single_target` on_death target a random enemy**
  - Two sub-options:
    - **B1 (data change):** Repoint `minion_rgb_lasercannon.json` to `target: all_enemies` + `amount: 1` semantic change (but `all_enemies` currently destroys ALL, not one — would need a new `amount_cap` field). Rejected — too invasive.
    - **B2 (engine change):** Add `TargetType.RANDOM_ENEMY` (new enum, append to end per convention), implement resolver for it in both engines using RNG from `state.rng` (Python) / `state.rng_state` (tensor). Migrate lasercannon to use it. **Recommend B2.**
  - Alternative C: implement `random_target` inline for death-trigger SINGLE_TARGET when target_pos is None — feels hacky, rejected.
  - Need user confirmation: is the card's intent "destroy 1 random enemy" or "destroy 1 chosen enemy (modal)"? If modal, this is a bigger fix touching the pending-state machine. **Question for user.**

  **C. Loop Python `_cleanup_dead_minions` for chain reactions**
  - File: `src/grid_tactics/action_resolver.py`
  - Wrap the body in `while True: dead_minions = [...]; if not dead_minions: break; ...`. Cap at e.g. 10 iterations to defend against pathological infinite promote loops.

  **D. Active-player-first ordering in both engines**
  - File: `src/grid_tactics/action_resolver.py::_cleanup_dead_minions`
  - Change sort key from `lambda m: m.instance_id` to `lambda m: (0 if m.owner == state.players[state.active_player_idx].side else 1, m.instance_id)`.
  - File: `src/grid_tactics/tensor_engine/engine.py::cleanup_dead_minions_batch`
  - Instead of one inner slot loop for ON_DEATH, do two passes: first pass applies effects where `dead_owner == active_player`, second pass applies effects where `dead_owner != active_player`. Preserves batched semantics.

  **E. Tests**
  - `tests/test_action_resolver.py`: add test_lasercannon_death_destroys_random_enemy (after fix B), test_giant_rat_death_promotes_friendly_rat, test_simultaneous_deaths_active_player_first, test_chain_death_reaction_resolves.
  - Tensor engine parity tests in whatever directory covers tensor engine (none found at `tests/tensor_engine/` — may need a new file).

verification: (empty — fix not yet applied)
files_changed: []

## Fix Applied (2026-04-11)

Scope decided with user: one combined fix landing all 4 defects plus the
modal pending-state machinery. Lasercannon becomes the first real consumer
of the new click-target death-modal pattern.

### Engine changes

- `src/grid_tactics/enums.py`
  - Added `ActionType.DEATH_TARGET_PICK = 14` (append-only, per convention).
- `src/grid_tactics/actions.py`
  - Added `death_target_pick_action()` constructor. Server-only; not
    wired into the RL 1262-slot action space because the tensor engine
    auto-resolves death modals deterministically.
- `src/grid_tactics/game_state.py`
  - Added `PendingDeathWork` frozen dataclass: snapshot of a dead minion
    whose on_death effects haven't been fully resolved (card_numeric_id,
    owner, position, instance_id, next_effect_idx).
  - Added `PendingDeathTarget` frozen dataclass: a death-triggered
    modal waiting for a click-target pick (card_numeric_id, owner_idx,
    dying_instance_id, effect_idx, filter).
  - New GameState fields `pending_death_queue` and `pending_death_target`.
    Transient (not serialized to/from dict); view_filter enrichment
    exposes them to the client per-viewer.
- `src/grid_tactics/effect_resolver.py`
  - Ported PROMOTE from the tensor engine: new `_apply_promote_on_death`
    — finds the most advanced friendly target, respects unique
    constraint, transforms card_numeric_id / health / bonuses. Wired
    into `resolve_effects_for_trigger` alongside RALLY_FORWARD.
  - New `resolve_death_effects_or_enter_modal`: iterates a dying
    minion's on_death effects sequentially. If one needs a modal (e.g.
    `DESTROY / SINGLE_TARGET`), sets `pending_death_target` and returns
    early with the effect index so the caller can resume after the
    pick. Synchronous effects resolve inline.
  - New `apply_death_target_pick`: validates the click target against
    the pending modal's filter, applies the effect (currently handles
    `DESTROY` — picked minion's health is zeroed so the next cleanup
    pass cycles it through chain-reaction handling), advances the head
    of the pending queue, clears `pending_death_target`.
  - New `_death_effect_needs_modal` helper.
  - Updated `_apply_effect_to_minion` docstring to remove the PROMOTE lie.
- `src/grid_tactics/action_resolver.py`
  - Rewrote `_cleanup_dead_minions` as three cooperating functions:
    - `_enqueue_dead_minions_and_cleanup_zones`: collects deaths,
      removes from board + populates grave, appends to
      `pending_death_queue` sorted **active-player first, then
      instance_id ascending** (DEFECT #4 fix).
    - `_drain_pending_death_queue`: loops through the queue,
      calling `resolve_death_effects_or_enter_modal` for each head.
      Handles modal pauses (returns early), handles chain reactions
      (re-scans for newly-dead minions after each drain). Bounded
      by `_CHAIN_DEATH_SAFETY_LIMIT=16` (DEFECT #3 fix).
    - `_cleanup_dead_minions` thin wrapper: enqueue then drain.
  - Added a phase-agnostic `pending_death_target` gate at the very top
    of `resolve_action` — runs before the REACT-phase dispatch. Handles
    `DEATH_TARGET_PICK`, drains any chain-reaction tail, and re-enters
    either the action-phase react transition OR the react-stack turn-
    advance tail depending on which phase the original death happened
    in. Inlined the turn-advance tail (tick status effects / passive
    effects / regen / auto-draw) for the post-react branch.
  - Added `pending_death_target` deferrals to all four cleanup sites in
    `resolve_action` (main action, post-move-attack, pending-tutor,
    pending-conjure-deploy). Each site now records `pending_action`
    BEFORE cleanup so the react banner stays accurate across modal
    pauses.
- `src/grid_tactics/legal_actions.py`
  - Added `_pending_death_target_actions` enumeration and a top-of-
    function gate that routes to it when `pending_death_target` is set.
    Phase-agnostic, runs before every other pending / phase check.
  - Imports `death_target_pick_action`.
- `src/grid_tactics/react_stack.py`
  - `resolve_react_stack` now returns early if cleanup left a
    `pending_death_target` — the driver in action_resolver resumes the
    turn-advance tail after the modal clears.
- `src/grid_tactics/tensor_engine/engine.py`
  - Updated `cleanup_dead_minions_batch` ordering: iterates priority
    passes (active player first, then opponent) within each cleanup
    pass (DEFECT #4 parity fix).
  - Bumped chain-reaction passes from 2 to 8 for parity with the
    Python engine's chain-death loop (DEFECT #3 parity fix).
  - New module-level `_compute_auto_death_target` helper: deterministic
    lowest-slot alive enemy pick. Used to auto-resolve DESTROY/
    SINGLE_TARGET on_death in RL training (no UI to show a modal —
    tensor path bypasses the pending state entirely).

### Data

- `data/cards/minion_rgb_lasercannon.json` — **unchanged**. The existing
  `destroy / single_target / on_death / amount=1` shape is now
  correctly interpreted by the engine as "open a click-target modal;
  dying minion's owner picks an enemy minion to destroy." No JSON
  schema migration needed; the new machinery reads the existing data.
- `data/cards/minion_giant_rat.json` — **unchanged**. The existing
  `promote / self_owner / on_death / amount=10` shape now resolves via
  the new `_apply_promote_on_death` in the Python engine (previously
  silently skipped).

### Server / view plumbing

- `src/grid_tactics/server/view_filter.py`
  - Added `enrich_pending_death_target`: asymmetric per-viewer
    enrichment. The picker (dying minion's owner) receives card
    identity, filter tag, and a list of valid target positions. The
    opponent receives only `pending_death_target_owner_idx` so the
    client can show a "waiting on opponent" toast.
- `src/grid_tactics/server/events.py`
  - `_emit_state_to_players` and `submit_action` now compute
    `decision_idx = pending_death_target.owner_idx` when a modal is
    pending, overriding the phase-based routing. This is what lets P2
    pick a Lasercannon death target on P1's turn.
  - Wired `enrich_pending_death_target` into every state emission
    path: state_update, game_over, game_start (first + rematch),
    spectator fanout.

### Client

- `src/grid_tactics/server/static/game.js`
  - New `syncPendingDeathTargetUI` called from `renderGame`. Mirrors
    the 14.1/14.2/14.6 pending-state sync pattern.
  - Red banner for the picker: "Pick an enemy to destroy (<Card> death)".
  - Red toast for the opponent: "Opponent is choosing a target for a
    Death effect…"
  - `onBoardCellClick` and `onBoardMinionClick` route through a new
    `death_target_pick` interaction mode, submitting `DEATH_TARGET_PICK`
    (action_type=14) with the clicked tile. Valid targets come from
    the server-provided `pending_death_valid_targets` list.
  - Board clicks remain inert during a react window UNLESS the current
    mode is `death_target_pick` — the modal must be able to fire even
    when the death happened mid-react-stack resolution.
  - Highlighting in `highlightBoard`: paints valid target tiles with
    the existing `cell-attack` + `attack-valid-target` classes so the
    modal reuses the established red highlight style.

### Tests

- `tests/test_action_resolver.py` — added 4 new classes (11 tests):
  - `TestDeathKeywordPromote` — promote fires; unique constraint; most-
    advanced pick.
  - `TestDeathKeywordOrdering` — active-player-first across sides;
    instance_id tiebreak within a side.
  - `TestDeathKeywordChainReaction` — chain death from one on_death
    killing another on_death minion in the same cleanup call.
  - `TestDeathKeywordLasercannonModal` — modal opens; no-op when no
    valid target; end-to-end attack→modal→pick→destroy flow with
    proper react-window transition; `legal_actions` returns only
    DEATH_TARGET_PICK entries while pending.
  - New helper `_make_death_test_library` with 5 cards
    (`test_die_destroy`, `test_die_damage_all`, `test_die_promote`,
    `test_melee`, `test_rat`).
- `tests/test_enums.py` — updated `EffectType` member count from 17 to
  18 (stale since REVIVE was added; unrelated to this fix).
- `tests/test_minion.py` — updated `ActionType` member count from 14
  to 15 (DEATH_TARGET_PICK).

### Verification

- 58/58 tests in `tests/test_action_resolver.py` pass (including 11
  new death-keyword tests).
- Targeted suites (test_action_resolver, test_effect_resolver,
  test_legal_actions, test_react_stack, test_enums, test_minion):
  215/215 pass.
- End-to-end check using real card data: Lasercannon death opens a
  modal routed to its owner; Giant Rat death promotes the most-
  advanced friendly rat in the Python engine.
- Pre-existing test failures (test_tensor_engine parity, test_rl_env,
  test_observation, test_fatigue_fix, test_events spectator, e2e
  sandbox smoke) are unrelated — confirmed by running them against
  the stashed pre-change state.

