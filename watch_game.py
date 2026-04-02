"""Watch a game play out turn by turn in the terminal with color."""

import os
import sys
import time

# Enable ANSI colors on Windows
os.system("")

from pathlib import Path
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, Attribute, CardType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.action_resolver import resolve_action
from grid_tactics.legal_actions import legal_actions
from grid_tactics.rng import GameRNG

# --- ANSI colors ---
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Player colors
P1 = "\033[96m"      # cyan
P2 = "\033[91m"      # red
P1_BG = "\033[46m"   # cyan bg
P2_BG = "\033[41m"   # red bg

# Attribute colors
ATTR_COLORS = {
    Attribute.FIRE: "\033[91m",    # red
    Attribute.DARK: "\033[95m",    # magenta
    Attribute.LIGHT: "\033[93m",   # yellow
    Attribute.NEUTRAL: "\033[37m", # white
}

# Action colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"
GRAY = "\033[90m"

# Board
BOARD_LINE = "\033[90m"  # gray

# --- Config ---
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42
DELAY = float(sys.argv[2]) if len(sys.argv) > 2 else 0.4
TURN_LIMIT = 200

# --- Load cards ---
library = CardLibrary.from_directory(Path("data/cards"))

# --- Build decks (3 copies of each card) ---
all_ids = [library.get_numeric_id(c.card_id) for c in library.all_cards]
deck = []
for cid in sorted(all_ids):
    deck.extend([cid] * 3)
deck_tuple = tuple(deck[:45])

# --- Helpers ---
def card_name(numeric_id: int) -> str:
    defn = library.get_by_id(numeric_id)
    return defn.name if defn else f"#{numeric_id}"

def card_color(numeric_id: int) -> str:
    defn = library.get_by_id(numeric_id)
    if not defn or not defn.attribute:
        return WHITE
    return ATTR_COLORS.get(defn.attribute, WHITE)

def colored_card_name(numeric_id: int) -> str:
    return f"{card_color(numeric_id)}{card_name(numeric_id)}{RESET}"

def hp_bar(hp: int, max_hp: int = 20, width: int = 10) -> str:
    filled = max(0, int(hp / max_hp * width))
    empty = width - filled
    if hp > max_hp * 0.6:
        color = GREEN
    elif hp > max_hp * 0.3:
        color = YELLOW
    else:
        color = RED
    return f"{color}{'#' * filled}{GRAY}{'.' * empty}{RESET}"

def render_board(state: GameState) -> str:
    lines = []
    lines.append("")
    lines.append(f"  {BOARD_LINE}+-------+-------+-------+-------+-------+{RESET}")

    minion_map = {}
    for m in state.minions:
        minion_map[m.position] = m

    for row in range(5):
        if row == 2:
            label = f"{GRAY}NML{RESET}"
        elif row <= 1:
            label = f"{P1}P1 {RESET}"
        else:
            label = f"{P2}P2 {RESET}"

        cells = []
        for col in range(5):
            m = minion_map.get((row, col))
            if m is None:
                cells.append(f"  {GRAY}.{RESET}    ")
            else:
                defn = library.get_by_id(m.card_numeric_id)
                owner_color = P1 if m.owner == PlayerSide.PLAYER_1 else P2
                owner_tag = "1" if m.owner == PlayerSide.PLAYER_1 else "2"
                atk = defn.attack + m.attack_bonus if defn and defn.attack else 0
                hp = m.current_health
                max_h = defn.health if defn else hp
                # Color HP based on percentage
                if hp > max_h * 0.5:
                    hp_c = GREEN
                elif hp > max_h * 0.25:
                    hp_c = YELLOW
                else:
                    hp_c = RED
                attr_c = ATTR_COLORS.get(defn.attribute, WHITE) if defn and defn.attribute else WHITE
                cell = f"{owner_color}{owner_tag}{RESET}{attr_c}:{atk}{RESET}/{hp_c}{hp}{RESET}"
                # Pad to 7 visible chars (owner:atk/hp)
                cells.append(f" {cell}  ")

        lines.append(f"  {label}{BOARD_LINE}|{RESET}{'|'.join(cells)}{BOARD_LINE}|{RESET}")

        if row == 1:
            lines.append(f"  {BOARD_LINE}+------- NO MAN'S LAND --------+{RESET}")
        elif row == 2:
            lines.append(f"  {BOARD_LINE}+-------------------------------+{RESET}")
        else:
            lines.append(f"  {BOARD_LINE}+-------+-------+-------+-------+-------+{RESET}")

    return "\n".join(lines)

def describe_action(action, state: GameState) -> str:
    active_idx = state.active_player_idx
    active_color = P1 if active_idx == 0 else P2
    active_tag = f"{active_color}{'P1' if active_idx == 0 else 'P2'}{RESET}"
    t = action.action_type

    if t == ActionType.PASS:
        return f"{active_tag} {GRAY}passes{RESET}"
    elif t == ActionType.DRAW:
        return f"{active_tag} {CYAN}draws a card{RESET}"
    elif t == ActionType.MOVE:
        m = state.get_minion(action.minion_id)
        name = colored_card_name(m.card_numeric_id) if m else "?"
        return f"{active_tag} moves {name} to {action.position}"
    elif t == ActionType.ATTACK:
        attacker = state.get_minion(action.minion_id)
        target = state.get_minion(action.target_id)
        a_name = colored_card_name(attacker.card_numeric_id) if attacker else "?"
        t_name = colored_card_name(target.card_numeric_id) if target else "?"
        return f"{active_tag} {RED}attacks{RESET} {t_name} with {a_name}"
    elif t == ActionType.PLAY_CARD:
        p = state.players[state.active_player_idx]
        if action.card_index is not None and action.card_index < len(p.hand):
            cid = p.hand[action.card_index]
            name = colored_card_name(cid)
            defn = library.get_by_id(cid)
            if defn and defn.card_type == CardType.MAGIC:
                return f"{active_tag} {MAGENTA}casts{RESET} {name}"
        else:
            name = "?"
        if action.position:
            return f"{active_tag} {GREEN}deploys{RESET} {name} at {action.position}"
        return f"{active_tag} {MAGENTA}casts{RESET} {name}"
    elif t == ActionType.PLAY_REACT:
        reactor = "P2" if active_idx == 0 else "P1"
        reactor_color = P2 if active_idx == 0 else P1
        return f"{reactor_color}{reactor}{RESET} {YELLOW}reacts!{RESET}"
    elif t == ActionType.SACRIFICE:
        m = state.get_minion(action.minion_id)
        name = colored_card_name(m.card_numeric_id) if m else "?"
        defn = library.get_by_id(m.card_numeric_id) if m else None
        atk = (defn.attack + m.attack_bonus) if defn and m else 0
        return f"{active_tag} {BOLD}{RED}SACRIFICES{RESET} {name} for {BOLD}{RED}{atk} damage!{RESET}"
    return f"{active_tag} does {t.name}"

# --- Run game ---
print(f"\n{BOLD}{'='*50}")
print(f"  {CYAN}GRID TACTICS TCG{RESET}{BOLD} -- Game Replay (seed={SEED})")
print(f"{'='*50}{RESET}")
print(f"  Deck: {len(deck_tuple)} cards each")
print(f"  Card pool: {library.card_count} unique cards")

state, rng = GameState.new_game(SEED, deck_tuple, deck_tuple)

turn = 0
last_action_turn = state.turn_number

while not state.is_game_over and state.turn_number <= TURN_LIMIT:
    if state.turn_number != last_action_turn or turn == 0:
        last_action_turn = state.turn_number
        p1 = state.players[0]
        p2 = state.players[1]

        print(f"\n{BOLD}{'-'*50}{RESET}")
        print(f"  {BOLD}Turn {state.turn_number}{RESET}  |  "
              f"{P1}P1{RESET}: {hp_bar(p1.hp)} {p1.hp}HP  "
              f"{CYAN}{p1.current_mana}/{p1.max_mana}MP{RESET}  "
              f"hand:{len(p1.hand)} deck:{len(p1.deck)}")
        print(f"            |  "
              f"{P2}P2{RESET}: {hp_bar(p2.hp)} {p2.hp}HP  "
              f"{CYAN}{p2.current_mana}/{p2.max_mana}MP{RESET}  "
              f"hand:{len(p2.hand)} deck:{len(p2.deck)}")
        print(f"  Board: {BOLD}{len(state.minions)}{RESET} minions")
        print(render_board(state))

    actions = legal_actions(state, library)
    action = rng.choice(actions)

    desc = describe_action(action, state)
    phase_tag = f"{YELLOW}[REACT]{RESET} " if state.phase == TurnPhase.REACT else "  "
    print(f"  {phase_tag}{desc}")

    state = resolve_action(state, action, library)
    turn += 1

    time.sleep(DELAY)

# --- Final result ---
p1 = state.players[0]
p2 = state.players[1]
print(f"\n{BOLD}{'='*50}")
print(f"  GAME OVER after {state.turn_number} turns")
print(f"{'='*50}{RESET}")
print(render_board(state))
print(f"\n  {P1}P1{RESET}: {hp_bar(p1.hp)} {p1.hp} HP  |  {P2}P2{RESET}: {hp_bar(p2.hp)} {p2.hp} HP")

if state.winner == PlayerSide.PLAYER_1:
    print(f"\n  {BOLD}{P1}>>> PLAYER 1 WINS! <<<{RESET}")
elif state.winner == PlayerSide.PLAYER_2:
    print(f"\n  {BOLD}{P2}>>> PLAYER 2 WINS! <<<{RESET}")
elif state.is_game_over and state.winner is None:
    print(f"\n  {BOLD}{YELLOW}>>> DRAW <<<{RESET}")
else:
    print(f"\n  {BOLD}{YELLOW}>>> DRAW (turn limit) <<<{RESET}")

print(f"{BOLD}{'='*50}{RESET}\n")
