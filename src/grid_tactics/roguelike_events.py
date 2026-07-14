"""Mirrored, synchronized roguelike fortune rounds."""

from __future__ import annotations

import os
from dataclasses import replace

from grid_tactics.card_library import CardLibrary
from grid_tactics.engine_events import (
    EVT_CARD_BURNED,
    EVT_CARD_DRAWN,
    EVT_MANA_CHANGE,
    EVT_MINION_SUMMONED,
    EVT_PENDING_MODAL_OPENED,
    EVT_PENDING_MODAL_RESOLVED,
    EVT_PLAYER_HP_CHANGE,
    EventStream,
)
from grid_tactics.game_state import GameState
from grid_tactics.minion import MinionInstance
from grid_tactics.phase_contracts import assert_phase_contract
from grid_tactics.rng import GameRNG
from grid_tactics.types import MAX_HAND_SIZE, MAX_MANA_CAP

ROGUELIKE_EVENT_INTERVAL = int(
    os.environ.get("GT_ROGUELIKE_EVENT_INTERVAL", "25")
)

CLUMSY_GREED = "clumsy_greed"
WITH_A_SLAP = "with_a_slap"
SHARP_EYED_SCEPTIC = "sharp_eyed_sceptic"
GRAVE_EXPECTATIONS = "grave_expectations"
POCKET_CHANGE = "pocket_change"
SPRING_CLEANING = "spring_cleaning"
SKELETON_CREW = "skeleton_crew"
COMPOUND_INTEREST = "compound_interest"
MARKED_CARDS = "marked_cards"
UNCHARTED_FORTUNE = "uncharted_fortune"

ROGUELIKE_EVENT_CHOICES: tuple[str, ...] = (
    CLUMSY_GREED,
    WITH_A_SLAP,
    SHARP_EYED_SCEPTIC,
    GRAVE_EXPECTATIONS,
    POCKET_CHANGE,
    SPRING_CLEANING,
    SKELETON_CREW,
    COMPOUND_INTEREST,
    MARKED_CARDS,
    UNCHARTED_FORTUNE,
)

ROGUELIKE_EVENT_OPTIONS: tuple[dict[str, str], ...] = (
    {"id": CLUMSY_GREED, "name": "Clumsy Greed", "glyph": "🃏",
     "description": "Draw 4. Exhaust 2 random cards from your hand."},
    {"id": WITH_A_SLAP, "name": "With a Slap", "glyph": "👋",
     "description": "Your Handshakes deal +5 damage. Stackable."},
    {"id": SHARP_EYED_SCEPTIC, "name": "Sharp Eyed Sceptic", "glyph": "👁️",
     "description": "Gain a Prohibition and 1 mana."},
    {"id": GRAVE_EXPECTATIONS, "name": "Grave Expectations", "glyph": "⚰️",
     "description": "Return 2 random Grave cards to hand. Lose 25% current HP."},
    {"id": POCKET_CHANGE, "name": "Pocket Change", "glyph": "🪙",
     "description": "Gain 3 mana. Your opponent draws 1 card."},
    {"id": SPRING_CLEANING, "name": "Spring Cleaning", "glyph": "🧹",
     "description": "Exhaust your hand. Draw that many cards plus 1."},
    {"id": SKELETON_CREW, "name": "Skeleton Crew", "glyph": "🦴",
     "description": "Summon 2 Reanimated Bones on random empty friendly tiles."},
    {"id": COMPOUND_INTEREST, "name": "Compound Interest", "glyph": "📈",
     "description": "Gain 1 additional mana at your next 3 turn starts."},
    {"id": MARKED_CARDS, "name": "Marked Cards", "glyph": "🎴",
     "description": "See your top 3. Keep 1; order the other 2 on top."},
    {"id": UNCHARTED_FORTUNE, "name": "Uncharted Fortune", "glyph": "❓",
     "description": "Gain a random fortune not yet seen or offered this game."},
)

_OPTION_BY_ID = {option["id"]: option for option in ROGUELIKE_EVENT_OPTIONS}


def _public_option(choice_id: str) -> dict[str, str]:
    """Return reveal-safe fortune copy for the shared result screen."""
    if choice_id == "uncharted_fallback":
        return {
            "id": choice_id,
            "name": "Uncharted Fortune",
            "glyph": "?",
            "description": "No unseen fortune remained. Gain 1 mana.",
        }
    option = _OPTION_BY_ID.get(choice_id)
    if option is None:
        return {
            "id": choice_id,
            "name": choice_id.replace("_", " ").title(),
            "glyph": "?",
            "description": "Fortune resolved.",
        }
    return dict(option)


def is_roguelike_event_boundary(completed_turn: int) -> bool:
    return completed_turn > 0 and completed_turn % ROGUELIKE_EVENT_INTERVAL == 0


def open_roguelike_event(
    state: GameState,
    *,
    event_collector: EventStream | None = None,
) -> GameState:
    """Deal one seeded-random three-card offer, mirrored to both seats."""
    assert_phase_contract(state, "system:roguelike_event")
    if state.pending_roguelike_event_turn is not None:
        raise ValueError("A roguelike event is already pending")
    rng = GameRNG(state.seed + state.turn_number * 2081)
    order = rng.shuffle(tuple(range(len(ROGUELIKE_EVENT_CHOICES))))
    options = tuple(ROGUELIKE_EVENT_CHOICES[idx] for idx in order[:3])
    seen = list(state.roguelike_seen_fortunes)
    for option in options:
        if option not in seen:
            seen.append(option)
    state = replace(
        state,
        pending_roguelike_event_turn=state.turn_number,
        pending_roguelike_event_choices=(None, None),
        pending_roguelike_event_options=options,
        roguelike_seen_fortunes=tuple(seen),
    )
    if event_collector is not None:
        event_collector.collect(
            EVT_PENDING_MODAL_OPENED,
            "system:roguelike_event",
            {
                "modal_kind": "roguelike_event",
                "owner_idx": None,
                "options_count": 3,
                "turn": state.turn_number,
            },
            requires_decision=True,
        )
    return state


def resolve_roguelike_event_choice(
    state: GameState,
    player_idx: int,
    choice_id: str,
    library: CardLibrary,
    *,
    event_collector: EventStream | None = None,
) -> GameState:
    """Lock one private choice; apply both once the second seat locks."""
    assert_phase_contract(state, "system:roguelike_event")
    if state.pending_roguelike_event_turn is None:
        raise ValueError("No roguelike event is pending")
    if player_idx not in (0, 1):
        raise ValueError(f"Invalid player_idx: {player_idx}")
    if choice_id not in state.pending_roguelike_event_options:
        raise ValueError(f"Fortune is not in the current offer: {choice_id!r}")
    if state.pending_roguelike_event_choices[player_idx] is not None:
        raise ValueError("This player already chose a fortune")

    choices = list(state.pending_roguelike_event_choices)
    choices[player_idx] = choice_id
    state = replace(state, pending_roguelike_event_choices=tuple(choices))
    if any(choice is None for choice in choices):
        return state

    event_turn = int(state.pending_roguelike_event_turn)
    current_offer = tuple(state.pending_roguelike_event_options)
    resolved_choices: list[str] = []
    history_entries: list[str] = []
    seen = list(state.roguelike_seen_fortunes)
    for idx, choice in enumerate(choices):
        actual = choice
        if choice == UNCHARTED_FORTUNE:
            eligible = tuple(
                fortune for fortune in ROGUELIKE_EVENT_CHOICES
                if fortune not in seen and fortune not in current_offer
                and fortune != UNCHARTED_FORTUNE
            )
            if eligible:
                actual = GameRNG(
                    state.seed + event_turn * 6151 + idx * 1229
                ).choice(eligible)
                seen.append(actual)
                history_entries.append(f"{UNCHARTED_FORTUNE}:{actual}")
            else:
                actual = "uncharted_fallback"
                history_entries.append(f"{UNCHARTED_FORTUNE}:fallback")
        else:
            history_entries.append(choice)
        resolved_choices.append(actual)

    if event_collector is not None:
        event_collector.collect(
            EVT_PENDING_MODAL_RESOLVED,
            "system:roguelike_event",
            {
                "modal_kind": "roguelike_event",
                "turn": event_turn,
                "choices": [
                    {
                        "player_idx": idx,
                        "choice": choice,
                        "resolved_as": resolved_choices[idx],
                        "option": _public_option(choice),
                        "resolved_option": _public_option(
                            resolved_choices[idx]
                        ),
                    }
                    for idx, choice in enumerate(choices)
                ],
                "resolution": "simultaneous_no_react",
            },
        )

    history = [list(entries) for entries in state.roguelike_event_history]
    for idx, entry in enumerate(history_entries):
        history[idx].append(entry)
    state = replace(
        state,
        pending_roguelike_event_turn=None,
        pending_roguelike_event_choices=(None, None),
        pending_roguelike_event_options=(),
        roguelike_seen_fortunes=tuple(seen),
        roguelike_event_history=tuple(tuple(entries) for entries in history),
    )

    # Fortunes form one sealed, non-reactable batch.  Owner-local effects
    # settle first; cross-player writes settle only after both local effects.
    # This makes outcomes independent of seat iteration order.  In particular,
    # Pocket Change's opponent draw cannot change Spring Cleaning's snapshot of
    # that player's pre-resolution hand.
    marked_players: list[int] = []
    deferred_opponent_draws: list[int] = []
    for idx, actual in enumerate(resolved_choices):
        if actual == MARKED_CARDS:
            marked_players.append(idx)
        else:
            state = _apply_choice(
                state, idx, actual, event_turn, library,
                event_collector=event_collector,
                deferred_opponent_draws=deferred_opponent_draws,
            )
    for opponent_idx in deferred_opponent_draws:
        state = _apply_pocket_change_draw(
            state, opponent_idx, event_collector,
        )
    from grid_tactics.action_resolver import _check_game_over
    state = _check_game_over(state, event_collector=event_collector)
    if state.is_game_over:
        return replace(
            state,
            pending_marked_cards_player_idx=None,
            pending_marked_cards_cards=(),
            pending_marked_cards_queue=(),
        )
    return _open_next_marked_cards(
        state, tuple(marked_players), event_collector=event_collector,
    )


def resolve_marked_cards_choice(
    state: GameState,
    player_idx: int,
    keep_index: int,
    top_order: tuple[int, ...],
    *,
    event_collector: EventStream | None = None,
) -> GameState:
    """Keep one revealed card and place the others on top in chosen order."""
    assert_phase_contract(state, "system:marked_cards")
    if state.pending_marked_cards_player_idx != player_idx:
        raise ValueError("Marked Cards is not pending for this player")
    cards = tuple(state.pending_marked_cards_cards)
    if not cards or keep_index not in range(len(cards)):
        raise ValueError("Invalid Marked Cards keep index")
    remaining = tuple(idx for idx in range(len(cards)) if idx != keep_index)
    if tuple(sorted(top_order)) != tuple(sorted(remaining)):
        raise ValueError("Top order must contain every non-kept card once")
    player = state.players[player_idx]
    if tuple(player.deck[:len(cards)]) != cards:
        raise ValueError("Deck changed during Marked Cards decision")

    keep_card = cards[keep_index]
    ordered_cards = tuple(cards[idx] for idx in top_order)
    player = replace(player, deck=ordered_cards + player.deck[len(cards):])
    player, burned = player.add_to_hand_with_overdraw(keep_card)
    state = replace(
        state,
        players=_replace_player(state.players, player_idx, player),
        pending_marked_cards_player_idx=None,
        pending_marked_cards_cards=(),
    )
    if event_collector is not None:
        event_collector.collect(
            EVT_PENDING_MODAL_RESOLVED,
            "system:marked_cards",
            {"modal_kind": "marked_cards", "owner_idx": player_idx},
        )
        event_collector.collect(
            EVT_CARD_BURNED if burned else EVT_CARD_DRAWN,
            "system:marked_cards",
            {
                "player_idx": player_idx,
                "source": "marked_cards",
                "card_numeric_id": keep_card,
            },
        )
    queue = tuple(state.pending_marked_cards_queue)
    state = replace(state, pending_marked_cards_queue=())
    return _open_next_marked_cards(
        state, queue, event_collector=event_collector,
    )


def choose_marked_cards_for_ai(
    state: GameState, player_idx: int, library: CardLibrary,
) -> tuple[int, tuple[int, ...]]:
    cards = tuple(state.pending_marked_cards_cards)
    if not cards:
        raise ValueError("No Marked Cards choice pending")

    def value(index: int) -> int:
        card = library.get_by_id(cards[index])
        return (
            int(card.mana_cost) * 10
            + int(card.attack or 0)
            + int(card.health or 0)
            + (8 if getattr(card, "react_condition", None) is not None else 0)
        )

    keep = max(range(len(cards)), key=lambda idx: (value(idx), -idx))
    remaining = tuple(idx for idx in range(len(cards)) if idx != keep)
    order = tuple(sorted(remaining, key=lambda idx: (-value(idx), idx)))
    return keep, order


def apply_handshake_slap_damage(
    state: GameState,
    *,
    event_collector: EventStream | None = None,
) -> GameState:
    for source_idx, stacks in enumerate(state.handshake_slap_stacks):
        if stacks <= 0:
            continue
        damage = stacks * 5
        target_idx = 1 - source_idx
        target = state.players[target_idx]
        prev_hp = target.hp
        target = target.take_damage(damage)
        state = replace(
            state, players=_replace_player(state.players, target_idx, target),
        )
        if event_collector is not None:
            event_collector.collect(
                EVT_PLAYER_HP_CHANGE, "system:turn_flip",
                {"player_idx": target_idx, "prev": prev_hp, "new": target.hp,
                 "delta": -damage, "cause": "handshake_slap",
                 "source_player_idx": source_idx, "stacks": stacks},
            )
    return state


def score_roguelike_event_choices(
    state: GameState, player_idx: int, library: CardLibrary,
) -> dict[str, int]:
    """Heuristic utilities using no opponent hidden-zone information."""
    if player_idx not in (0, 1):
        raise ValueError(f"Invalid player_idx: {player_idx}")
    player = state.players[player_idx]
    opponent = state.players[1 - player_idx]
    draw_count = min(4, len(player.deck))
    to_hand = min(draw_count, MAX_HAND_SIZE - len(player.hand))
    burned = draw_count - to_hand
    discarded = min(2, len(player.hand) + to_hand)
    greed = ((to_hand - discarded) * 10 + to_hand * 2 - burned * 8
             + max(0, 5 - len(player.hand)) * 2)

    next_slap = (state.handshake_slap_stacks[player_idx] + 1) * 5
    slap = 24 + max(0, (76 - state.turn_number) // 25) * 3
    if opponent.hp <= next_slap:
        slap += 30
    elif opponent.hp <= next_slap + 5:
        slap += 14
    elif opponent.hp <= 20:
        slap += 7

    prohibition = library.get_numeric_id("prohibition")
    sceptic = 4
    if len(player.hand) < MAX_HAND_SIZE:
        sceptic += 10 if prohibition in player.hand else 18
    if player.current_mana < MAX_MANA_CAP:
        sceptic += 10 + (6 if player.current_mana == 3 else 0)
    if player.current_mana >= 4:
        sceptic += 4

    grave_damage = (player.hp + 3) // 4
    grave = min(2, len(player.grave)) * 9 - grave_damage
    if grave_damage >= player.hp:
        grave -= 100
    pocket = min(3, MAX_MANA_CAP - player.current_mana) * 5 - 7
    spring_draws = min(len(player.hand) + 1, len(player.deck))
    spring = 10 + spring_draws * 3 - len(player.hand) * 2
    empty_tiles = sum(
        1 for pos in state.board.get_positions_for_side(player.side)
        if state.board.get(*pos) is None
    )
    skeletons = min(2, empty_tiles) * 14
    compound = 22 if state.compound_interest_turns[player_idx] == 0 else 16
    marked = 20 if len(player.deck) >= 3 else len(player.deck) * 5

    scores = {
        CLUMSY_GREED: greed,
        WITH_A_SLAP: slap,
        SHARP_EYED_SCEPTIC: sceptic,
        GRAVE_EXPECTATIONS: grave,
        POCKET_CHANGE: pocket,
        SPRING_CLEANING: spring,
        SKELETON_CREW: skeletons,
        COMPOUND_INTEREST: compound,
        MARKED_CARDS: marked,
    }
    unseen = [
        score for choice, score in scores.items()
        if choice not in state.roguelike_seen_fortunes
        and choice not in state.pending_roguelike_event_options
    ]
    scores[UNCHARTED_FORTUNE] = (
        sum(unseen) // len(unseen) - 2 if unseen else 5
    )
    return scores


def choose_roguelike_event_for_ai(
    state: GameState, player_idx: int, library: CardLibrary,
) -> str:
    scores = score_roguelike_event_choices(state, player_idx, library)
    offered = (
        state.pending_roguelike_event_options or ROGUELIKE_EVENT_CHOICES
    )
    best = max(scores[choice] for choice in offered)
    tied = tuple(choice for choice in offered if scores[choice] == best)
    event_turn = state.pending_roguelike_event_turn or state.turn_number
    return GameRNG(
        state.seed + int(event_turn) * 3571 + player_idx * 7919
    ).choice(tied)


def _apply_choice(
    state: GameState,
    player_idx: int,
    choice_id: str,
    event_turn: int,
    library: CardLibrary,
    *,
    event_collector: EventStream | None,
    deferred_opponent_draws: list[int] | None = None,
) -> GameState:
    if choice_id == CLUMSY_GREED:
        return _apply_clumsy_greed(state, player_idx, event_turn, event_collector)
    if choice_id == WITH_A_SLAP:
        stacks = list(state.handshake_slap_stacks)
        stacks[player_idx] += 1
        return replace(state, handshake_slap_stacks=tuple(stacks))
    if choice_id == SHARP_EYED_SCEPTIC:
        return _apply_sharp(state, player_idx, library, event_collector)
    if choice_id == GRAVE_EXPECTATIONS:
        return _apply_grave_expectations(
            state, player_idx, event_turn, event_collector,
        )
    if choice_id == POCKET_CHANGE:
        state = _gain_mana(
            state, player_idx, 3, "pocket_change", event_collector,
        )
        opponent_idx = 1 - player_idx
        if deferred_opponent_draws is not None:
            deferred_opponent_draws.append(opponent_idx)
            return state
        return _apply_pocket_change_draw(
            state, opponent_idx, event_collector,
        )
    if choice_id == SPRING_CLEANING:
        return _apply_spring_cleaning(state, player_idx, event_collector)
    if choice_id == SKELETON_CREW:
        return _apply_skeleton_crew(
            state, player_idx, event_turn, library, event_collector,
        )
    if choice_id == COMPOUND_INTEREST:
        turns = list(state.compound_interest_turns)
        turns[player_idx] += 3
        return replace(state, compound_interest_turns=tuple(turns))
    if choice_id == "uncharted_fallback":
        return _gain_mana(state, player_idx, 1, "uncharted_fortune", event_collector)
    raise ValueError(f"Unknown fortune effect: {choice_id!r}")


def _apply_clumsy_greed(state, idx, event_turn, events):
    player = state.players[idx]
    for _ in range(4):
        if not player.deck:
            break
        player, card_id, burned = player.draw_card_with_overdraw()
        _collect_card(events, idx, card_id, burned, "roguelike_event")
    order = GameRNG(state.seed + event_turn * 1009 + idx * 9176).shuffle(
        tuple(range(len(player.hand)))
    )
    exhaust_indexes = frozenset(order[:2])
    exhausted = tuple(
        card_id for hand_idx, card_id in enumerate(player.hand)
        if hand_idx in exhaust_indexes
    )
    kept = tuple(
        card_id for hand_idx, card_id in enumerate(player.hand)
        if hand_idx not in exhaust_indexes
    )
    player = replace(
        player,
        hand=kept,
        exhaust=player.exhaust + exhausted,
    )
    if events is not None:
        for card_id in exhausted:
            events.collect(
                EVT_CARD_BURNED,
                "system:roguelike_event",
                {
                    "player_idx": idx,
                    "card_numeric_id": card_id,
                    "source": "clumsy_greed",
                    "destination": "exhaust",
                },
            )
    return replace(state, players=_replace_player(state.players, idx, player))


def _apply_sharp(state, idx, library, events):
    player = state.players[idx]
    card_id = library.get_numeric_id("prohibition")
    player, burned = player.add_to_hand_with_overdraw(card_id)
    _collect_card(events, idx, card_id, burned, "roguelike_event")
    state = replace(state, players=_replace_player(state.players, idx, player))
    return _gain_mana(state, idx, 1, "roguelike_event", events)


def _apply_grave_expectations(state, idx, event_turn, events):
    player = state.players[idx]
    order = GameRNG(state.seed + event_turn * 4243 + idx * 811).shuffle(
        tuple(range(len(player.grave)))
    )
    picked = tuple(order[:2])
    picked_cards = [player.grave[i] for i in picked]
    grave = list(player.grave)
    for grave_idx in sorted(picked, reverse=True):
        del grave[grave_idx]
    player = replace(player, grave=tuple(grave))
    for card_id in picked_cards:
        player, burned = player.add_to_hand_with_overdraw(card_id)
        _collect_card(events, idx, card_id, burned, "grave_expectations")
    damage = max(1, (player.hp + 3) // 4)
    prev_hp = player.hp
    player = player.take_damage(damage)
    if events is not None:
        events.collect(EVT_PLAYER_HP_CHANGE, "system:roguelike_event",
                       {"player_idx": idx, "prev": prev_hp, "new": player.hp,
                        "delta": -damage, "cause": "grave_expectations"})
    return replace(state, players=_replace_player(state.players, idx, player))


def _apply_pocket_change_draw(state, opponent_idx, events):
    opponent = state.players[opponent_idx]
    if opponent.deck:
        opponent, card_id, burned = opponent.draw_card_with_overdraw()
        state = replace(
            state, players=_replace_player(state.players, opponent_idx, opponent),
        )
        _collect_card(events, opponent_idx, card_id, burned, "pocket_change")
    return state


def _apply_spring_cleaning(state, idx, events):
    player = state.players[idx]
    exhausted = tuple(player.hand)
    player = replace(
        player,
        hand=(),
        exhaust=player.exhaust + exhausted,
    )
    for card_id in exhausted:
        if events is not None:
            events.collect(EVT_CARD_BURNED, "system:roguelike_event",
                           {"player_idx": idx, "card_numeric_id": card_id,
                            "source": "spring_cleaning",
                            "destination": "exhaust"})
    for _ in range(len(exhausted) + 1):
        if not player.deck:
            break
        player, card_id, burned = player.draw_card_with_overdraw()
        _collect_card(events, idx, card_id, burned, "spring_cleaning")
    return replace(state, players=_replace_player(state.players, idx, player))


def _apply_skeleton_crew(state, idx, event_turn, library, events):
    player = state.players[idx]
    empty = tuple(
        pos for pos in state.board.get_positions_for_side(player.side)
        if state.board.get(*pos) is None
    )
    positions = GameRNG(
        state.seed + event_turn * 1877 + idx * 413
    ).shuffle(empty)[:2]
    card_id = library.get_numeric_id("reanimated_bones")
    card = library.get_by_id(card_id)
    for pos in positions:
        minion = MinionInstance(
            instance_id=state.next_minion_id,
            card_numeric_id=card_id,
            owner=player.side,
            position=pos,
            current_health=card.health,
            from_deck=False,
        )
        state = replace(
            state,
            board=state.board.place(*pos, minion.instance_id),
            minions=state.minions + (minion,),
            next_minion_id=state.next_minion_id + 1,
        )
        if events is not None:
            events.collect(EVT_MINION_SUMMONED, "system:roguelike_event",
                           {"instance_id": minion.instance_id,
                            "card_numeric_id": card_id, "owner_idx": idx,
                            "position": list(pos), "source": "skeleton_crew"})
    return state


def _open_next_marked_cards(state, queue, *, event_collector):
    remaining = list(queue)
    while remaining:
        idx = remaining.pop(0)
        cards = tuple(state.players[idx].deck[:3])
        if not cards:
            continue
        state = replace(
            state,
            pending_marked_cards_player_idx=idx,
            pending_marked_cards_cards=cards,
            pending_marked_cards_queue=tuple(remaining),
        )
        if event_collector is not None:
            event_collector.collect(
                EVT_PENDING_MODAL_OPENED, "system:marked_cards",
                {"modal_kind": "marked_cards", "owner_idx": idx,
                 "options_count": len(cards)}, requires_decision=True,
            )
        return state
    return replace(
        state,
        pending_marked_cards_player_idx=None,
        pending_marked_cards_cards=(),
        pending_marked_cards_queue=(),
    )


def _gain_mana(state, idx, amount, cause, events):
    player = state.players[idx]
    prev = player.current_mana
    new = min(MAX_MANA_CAP, prev + amount)
    player = replace(player, current_mana=new)
    if events is not None and new != prev:
        events.collect(EVT_MANA_CHANGE, "system:roguelike_event",
                       {"player_idx": idx, "prev": prev, "new": new,
                        "delta": new - prev, "cause": cause})
    return replace(state, players=_replace_player(state.players, idx, player))


def _collect_card(events, idx, card_id, burned, source):
    if events is not None:
        events.collect(EVT_CARD_BURNED if burned else EVT_CARD_DRAWN,
                       "system:roguelike_event",
                       {"player_idx": idx, "source": source,
                        "card_numeric_id": card_id})


def _replace_player(players: tuple, idx: int, player) -> tuple:
    values = list(players)
    values[idx] = player
    return tuple(values)


__all__ = [
    "CLUMSY_GREED", "WITH_A_SLAP", "SHARP_EYED_SCEPTIC",
    "GRAVE_EXPECTATIONS", "POCKET_CHANGE", "SPRING_CLEANING",
    "SKELETON_CREW", "COMPOUND_INTEREST", "MARKED_CARDS",
    "UNCHARTED_FORTUNE", "ROGUELIKE_EVENT_CHOICES",
    "ROGUELIKE_EVENT_OPTIONS", "ROGUELIKE_EVENT_INTERVAL",
    "apply_handshake_slap_damage", "choose_marked_cards_for_ai",
    "choose_roguelike_event_for_ai", "is_roguelike_event_boundary",
    "open_roguelike_event", "resolve_marked_cards_choice",
    "resolve_roguelike_event_choice", "score_roguelike_event_choices",
]
