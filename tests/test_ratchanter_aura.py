"""Ratchanter rework v2: stacking flat buff + tutor-from-deck.

The old continuous +5/+5 aura model is GONE. New semantics:

  - Activated ability "Conjure Common Rat" costs 2 mana.
  - Each cast applies a FLAT stacking buff of (1 + caster.dark_matter_stacks)
    to every living friendly Rat on the board EXCEPT the caster:
    +attack_bonus, +max_health_bonus, +current_health (immediately usable).
  - Each cast also conjures a Common Rat from the caster's deck via the
    Phase 14.2 tutor machinery. If the deck has zero common rats, the
    conjure is skipped silently; the buff still applies.
  - Recasting stacks additively. Buffs persist until the minion dies.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from grid_tactics.action_resolver import resolve_action
from grid_tactics.actions import Action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.types import STARTING_HP


def _lib() -> CardLibrary:
    return CardLibrary.from_directory(Path("data/cards"))


def _empty_state(lib: CardLibrary, mana: int = 10, deck: tuple = ()) -> GameState:
    p1 = Player(side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=mana,
                max_mana=10, hand=(), deck=deck, grave=())
    p2 = Player(side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=10,
                max_mana=10, hand=(), deck=(), grave=())
    return GameState(
        board=Board.empty(),
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=0,
        minions=(),
        next_minion_id=1,
    )


def _put(state: GameState, m: MinionInstance) -> GameState:
    return replace(
        state,
        minions=state.minions + (m,),
        board=state.board.place(m.position[0], m.position[1], m.instance_id),
        next_minion_id=max(state.next_minion_id, m.instance_id + 1),
    )


def _activate(minion_id: int) -> Action:
    return Action(
        action_type=ActionType.ACTIVATE_ABILITY,
        minion_id=minion_id,
        target_pos=None,
    )


def _resolve_react_pass(state: GameState, lib: CardLibrary) -> GameState:
    """Pass through both react windows to get back to the active player."""
    from grid_tactics.actions import pass_action
    # P2 passes
    if state.phase == TurnPhase.REACT:
        state = resolve_action(state, pass_action(), lib)
    return state


# ---------------------------------------------------------------------------
# On-play no longer conjures
# ---------------------------------------------------------------------------


def test_ratchanter_on_play_does_not_conjure_to_hand():
    """Deploying Ratchanter must NOT add a rat card to the owner's hand.
    The on_play conjure was replaced by an activated ability."""
    lib = _lib()
    from grid_tactics.effect_resolver import resolve_effects_for_trigger
    from grid_tactics.enums import TriggerType

    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")

    state = _empty_state(lib)
    rc = MinionInstance(
        instance_id=1, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    )
    state = _put(state, rc)

    state = resolve_effects_for_trigger(
        state, TriggerType.ON_PLAY, rc, lib, target_pos=None,
    )
    assert rat_id not in state.players[0].hand
    assert state.players[0].hand == ()


# ---------------------------------------------------------------------------
# Ability cost
# ---------------------------------------------------------------------------


def test_ability_cost_is_two():
    lib = _lib()
    rc = lib.get_by_card_id("ratchanter")
    assert rc.activated_ability.mana_cost == 2
    assert rc.activated_ability.effect_type == "conjure_rat_and_buff"
    assert rc.activated_ability.target == "none"


def test_cannot_activate_with_one_mana():
    lib = _lib()
    rc_id = lib.get_numeric_id("ratchanter")
    state = _empty_state(lib, mana=1)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    try:
        resolve_action(state, _activate(1), lib)
    except ValueError:
        return
    raise AssertionError("Expected ValueError for insufficient mana")


def test_activation_deducts_two_mana():
    lib = _lib()
    rc_id = lib.get_numeric_id("ratchanter")
    state = _empty_state(lib, mana=5)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    new_state = resolve_action(state, _activate(1), lib)
    assert new_state.players[0].current_mana == 3


# ---------------------------------------------------------------------------
# Flat stacking buff on friendly rats
# ---------------------------------------------------------------------------


def test_buff_applies_plus_one_plus_one_to_friendly_rat():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib, mana=5)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=rat_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = resolve_action(state, _activate(2), lib)
    rat = state.get_minion(1)
    assert rat.attack_bonus == 1
    assert rat.max_health_bonus == 1
    assert rat.current_health == rat_def.health + 1


def test_buff_stacks_on_repeated_cast():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib, mana=10)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=rat_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    # Cast once, pass react, then we'd need a new turn — but for engine-
    # level stacking we just bypass turn flow and re-call _apply directly
    # via a fresh ACTION-phase state.
    from grid_tactics.action_resolver import _apply_activate_ability
    state = _apply_activate_ability(state, _activate(2), lib)
    state = _apply_activate_ability(state, _activate(2), lib)
    state = _apply_activate_ability(state, _activate(2), lib)
    rat = state.get_minion(1)
    assert rat.attack_bonus == 3
    assert rat.max_health_bonus == 3
    assert rat.current_health == rat_def.health + 3


def test_buff_scales_with_dark_matter_stacks():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib, mana=5)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=rat_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
        dark_matter_stacks=4,
    ))
    state = resolve_action(state, _activate(2), lib)
    rat = state.get_minion(1)
    # 1 + 4 = 5
    assert rat.attack_bonus == 5
    assert rat.max_health_bonus == 5
    assert rat.current_health == rat_def.health + 5


def test_buff_applies_to_all_rat_tribe_members():
    """Any tribe containing 'Rat' should be buffed (Giant Rat, Rathopper, etc)."""
    lib = _lib()
    rc_id = lib.get_numeric_id("ratchanter")

    try:
        gr_id = lib.get_numeric_id("giant_rat")
        gr_def = lib.get_by_card_id("giant_rat")
    except KeyError:
        return  # card not in library; skip

    state = _empty_state(lib, mana=5)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=gr_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=gr_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = resolve_action(state, _activate(2), lib)
    gr = state.get_minion(1)
    assert gr.attack_bonus == 1
    assert gr.max_health_bonus == 1


def test_buff_does_not_affect_caster_ratchanter():
    lib = _lib()
    rc_id = lib.get_numeric_id("ratchanter")
    state = _empty_state(lib, mana=5)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = resolve_action(state, _activate(1), lib)
    rc = state.get_minion(1)
    assert rc.attack_bonus == 0
    assert rc.max_health_bonus == 0


def test_buff_does_not_affect_enemy_rats():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib, mana=5)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_2, position=(0, 0), current_health=rat_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = resolve_action(state, _activate(2), lib)
    enemy = state.get_minion(1)
    assert enemy.attack_bonus == 0
    assert enemy.max_health_bonus == 0
    assert enemy.current_health == rat_def.health


def test_buff_does_not_affect_non_rat_allies():
    lib = _lib()
    rc_id = lib.get_numeric_id("ratchanter")
    # Pick any non-rat minion card in the library
    non_rat_id = None
    non_rat_def = None
    for nid in range(lib.card_count):
        cd = lib.get_by_id(nid)
        if cd.card_id == "ratchanter":
            continue
        if cd.health is None:
            continue
        tribe = (cd.tribe or "").lower()
        if cd.card_id == "rat" or "rat" in tribe.split():
            continue
        non_rat_id = nid
        non_rat_def = cd
        break
    assert non_rat_id is not None

    state = _empty_state(lib, mana=5)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=non_rat_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=non_rat_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = resolve_action(state, _activate(2), lib)
    m = state.get_minion(1)
    assert m.attack_bonus == 0
    assert m.max_health_bonus == 0


# ---------------------------------------------------------------------------
# Conjure from deck (tutor flow)
# ---------------------------------------------------------------------------


def test_conjure_enters_pending_tutor_when_deck_has_rat():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")

    state = _empty_state(lib, mana=5, deck=(rat_id, rat_id))
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = resolve_action(state, _activate(1), lib)
    assert state.pending_tutor_player_idx == 0
    assert len(state.pending_tutor_matches) == 2
    # Still in ACTION phase until tutor resolves
    assert state.phase == TurnPhase.ACTION


def test_conjure_skipped_when_deck_empty():
    lib = _lib()
    rc_id = lib.get_numeric_id("ratchanter")

    state = _empty_state(lib, mana=5, deck=())
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = resolve_action(state, _activate(1), lib)
    assert state.pending_tutor_player_idx is None
    # Went straight to react window
    assert state.phase == TurnPhase.REACT


def test_conjure_skipped_when_deck_has_no_rats():
    lib = _lib()
    rc_id = lib.get_numeric_id("ratchanter")
    # Fill deck with Ratchanter copies (no common rat)
    state = _empty_state(lib, mana=5, deck=(rc_id, rc_id, rc_id))
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = resolve_action(state, _activate(1), lib)
    assert state.pending_tutor_player_idx is None
    assert state.phase == TurnPhase.REACT


def test_tutor_select_enters_conjure_deploy_then_deploys():
    """After TUTOR_SELECT during conjure, card enters pending_conjure_deploy.
    Then CONJURE_DEPLOY places it on the board (not hand)."""
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")

    state = _empty_state(lib, mana=5, deck=(rat_id,))
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = resolve_action(state, _activate(1), lib)
    assert state.pending_tutor_player_idx == 0
    assert state.pending_tutor_is_conjure is True

    # Step 1: Select the rat from deck -> enters pending_conjure_deploy
    select = Action(action_type=ActionType.TUTOR_SELECT, card_index=0)
    state = resolve_action(state, select, lib)
    assert rat_id not in state.players[0].hand  # NOT in hand
    assert state.players[0].deck == ()
    assert state.pending_tutor_player_idx is None
    assert state.pending_conjure_deploy_card == rat_id
    assert state.pending_conjure_deploy_player_idx == 0
    assert state.phase == TurnPhase.ACTION  # still in action phase, waiting for deploy

    # Step 2: Deploy the rat to an empty tile on PLAYER_1's side (rows 0-1)
    deploy = Action(action_type=ActionType.CONJURE_DEPLOY, position=(1, 0))
    state = resolve_action(state, deploy, lib)
    assert state.pending_conjure_deploy_card is None
    assert state.phase == TurnPhase.REACT  # now react window opens
    # Rat should be on the board at (1, 0)
    deployed_rat = None
    for m in state.minions:
        if m.card_numeric_id == rat_id and m.position == (1, 0):
            deployed_rat = m
    assert deployed_rat is not None, "Conjured rat should be on the board"
    assert deployed_rat.owner == PlayerSide.PLAYER_1
    assert deployed_rat.from_deck is True


def test_decline_conjure_sends_to_hand():
    """DECLINE_CONJURE sends the conjured card to hand instead of field."""
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")

    state = _empty_state(lib, mana=5, deck=(rat_id,))
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = resolve_action(state, _activate(1), lib)
    select = Action(action_type=ActionType.TUTOR_SELECT, card_index=0)
    state = resolve_action(state, select, lib)
    assert state.pending_conjure_deploy_card == rat_id

    # Decline deploy -> card goes to hand
    decline = Action(action_type=ActionType.DECLINE_CONJURE)
    state = resolve_action(state, decline, lib)
    assert rat_id in state.players[0].hand
    assert state.pending_conjure_deploy_card is None
    assert state.phase == TurnPhase.REACT


def test_buff_applies_even_if_conjure_skipped():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib, mana=5, deck=())
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=rat_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = resolve_action(state, _activate(2), lib)
    rat = state.get_minion(1)
    assert rat.attack_bonus == 1
    assert rat.max_health_bonus == 1


# ---------------------------------------------------------------------------
# Buff persists until death (no recompute)
# ---------------------------------------------------------------------------


def test_buff_persists_if_ratchanter_dies():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib, mana=5)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=rat_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    from grid_tactics.action_resolver import _apply_activate_ability
    state = _apply_activate_ability(state, _activate(2), lib)

    # Simulate Ratchanter death: remove it from minions.
    state = replace(
        state,
        minions=tuple(m for m in state.minions if m.instance_id != 2),
    )
    rat = state.get_minion(1)
    # Buff stays — it's a flat stat add, not an aura.
    assert rat.attack_bonus == 1
    assert rat.max_health_bonus == 1
