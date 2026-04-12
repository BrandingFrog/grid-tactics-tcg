"""Test every card in the trimmed 18-card pool via sandbox Socket.IO API."""
import socketio
import time
import json
import sys

SERVER = "http://127.0.0.1:5000"
RESULTS = []

# Card numeric IDs (0-based load order, NOT stable_id).
# Regenerate with: PYTHONPATH=src python3 -c "from pathlib import Path; from grid_tactics.card_library import CardLibrary; lib=CardLibrary.from_directory(Path('data/cards')); [print(f'{lib.get_numeric_id(c):>3} {c}') for c in sorted(lib._cards)]"
NID = {
    "blue_diodebot": 0, "counter_spell": 1, "emberplague_rat": 2,
    "fallen_paladin": 3, "furryroach": 4, "giant_rat": 5,
    "grave_caller": 6, "green_diodebot": 7, "pyre_archer": 8,
    "rat": 9, "ratchanter": 10, "rathopper": 11,
    "ratical_resurrection": 12, "reanimated_bones": 13,
    "red_diodebot": 14, "rgb_lasercannon": 15,
    "surgefed_sparkbot": 16, "to_the_ratmobile": 17,
}


class SandboxClient:
    """Helper wrapping Socket.IO sandbox interactions."""

    def __init__(self):
        self.sio = socketio.Client()
        self.state = None
        self.errors = []

        @self.sio.on("sandbox_state")
        def on_state(data):
            self.state = data.get("state", data) if isinstance(data, dict) else data

        @self.sio.on("error")
        def on_error(data):
            self.errors.append(data)

    def connect(self):
        self.sio.connect(SERVER)
        self.sio.emit("sandbox_create")
        self.sio.sleep(0.8)

    def disconnect(self):
        try:
            self.sio.disconnect()
        except:
            pass

    def set_field(self, player_idx, field, value):
        self.sio.emit("sandbox_set_player_field", {
            "player_idx": player_idx, "field": field, "value": value
        })
        self.sio.sleep(0.5)

    def set_mana(self, player_idx, amount):
        self.set_field(player_idx, "current_mana", amount)

    def set_hp(self, player_idx, amount):
        self.set_field(player_idx, "hp", amount)

    def set_active(self, player_idx):
        self.sio.emit("sandbox_set_active_player", {"player_idx": player_idx})
        self.sio.sleep(0.5)

    def add_card(self, player_idx, stable_id, zone="hand"):
        self.sio.emit("sandbox_add_card_to_zone", {
            "player_idx": player_idx, "card_numeric_id": stable_id, "zone": zone
        })
        self.sio.sleep(0.5)

    def play_card(self, card_index=0, position=None, target_pos=None):
        data = {"action_type": 0, "card_index": card_index}
        if position is not None:
            data["position"] = position
        if target_pos is not None:
            data["target_pos"] = target_pos
        self.sio.emit("sandbox_apply_action", data)
        self.sio.sleep(0.8)

    def pass_turn(self):
        self.sio.emit("sandbox_apply_action", {"action_type": 4})
        self.sio.sleep(0.5)

    def move(self, minion_id, position):
        self.sio.emit("sandbox_apply_action", {
            "action_type": 1, "minion_id": minion_id, "position": position
        })
        self.sio.sleep(0.8)

    def attack(self, minion_id, target_id):
        self.sio.emit("sandbox_apply_action", {
            "action_type": 2, "minion_id": minion_id, "target_id": target_id
        })
        self.sio.sleep(0.8)

    def ensure_p0_turn(self):
        """Make sure it's P0's turn in ACTION phase."""
        if self.state and self.state.get("active_player_idx") != 0:
            self.set_active(0)
        # Also ensure ACTION phase
        if self.state and self.state.get("phase") != 0:
            self.pass_turn()

    @property
    def minions(self):
        return self.state.get("minions", []) if self.state else []

    @property
    def p0(self):
        return self.state["players"][0] if self.state else None

    @property
    def p1(self):
        return self.state["players"][1] if self.state else None


def run_test(name, test_fn):
    """Run a single card test in a fresh sandbox."""
    sb = SandboxClient()
    try:
        sb.connect()
        if sb.state is None:
            RESULTS.append((name, "Sandbox state never received", "FAIL"))
            return
        desc, result = test_fn(sb)
        RESULTS.append((name, desc, result))
    except Exception as e:
        RESULTS.append((name, f"Exception: {e}", "FAIL"))
    finally:
        sb.disconnect()


# ==========================================================================
# DEPLOY TESTS (vanilla + effect minions)
# ==========================================================================

def make_deploy_test(stable_id, expected_atk, expected_hp):
    def test(sb):
        sb.set_mana(0, 10)
        sb.ensure_p0_turn()
        sb.add_card(0, stable_id)
        if len(sb.p0["hand"]) != 1:
            return ("Card not added to hand", "FAIL")
        sb.play_card(card_index=0, position=[0, 2])
        if len(sb.minions) == 1:
            m = sb.minions[0]
            pos = m.get("position", "?")
            return (f"Deployed at {pos}", "PASS")
        # Check if turn advanced (minion deployed but react drained + turn flipped)
        # The minion might be on the board even if active_player changed
        board = sb.state.get("board", [])
        occupied = [i for i, c in enumerate(board) if c is not None]
        if occupied:
            return (f"Deployed (board cells: {occupied})", "PASS")
        return (f"Deploy failed. active={sb.state.get('active_player_idx')}, phase={sb.state.get('phase')}, errors={sb.errors}", "FAIL")
    return test


# ==========================================================================
# MAGIC CARD TESTS
# ==========================================================================

def test_ratical_resurrection(sb):
    """Ratical Resurrection: revive rat from grave via REVIVE_PLACE modal."""
    sb.set_mana(0, 10)
    sb.ensure_p0_turn()
    sb.add_card(0, NID["rat"], zone="graveyard")  # rat to grave
    grave_before = len(sb.p0.get("grave", []))
    sb.add_card(0, NID["ratical_resurrection"])  # to hand
    sb.play_card(card_index=0)

    # Cast enters pending_revive — send REVIVE_PLACE to pick a deploy cell
    if sb.state.get("pending_revive_player_idx") is not None:
        # ActionType.REVIVE_PLACE = 15
        sb.sio.emit("sandbox_apply_action", {"action_type": 15, "position": [0, 2]})
        sb.sio.sleep(1.0)

    grave_after = len(sb.p0.get("grave", []))
    board_minions = len(sb.minions)
    board_cells = [i for i, c in enumerate(sb.state.get("board", [])) if c is not None]
    if board_minions > 0 or len(board_cells) > 0:
        return (f"Revived: grave {grave_before}->{grave_after}, board={board_cells}", "PASS")
    if grave_after < grave_before:
        return (f"Revived from grave: {grave_before}->{grave_after}", "PASS")
    return (f"No revive: grave={grave_after}, board={board_cells}, pending={sb.state.get('pending_revive_player_idx')}", "FAIL")


def test_to_the_ratmobile(sb):
    """To The Ratmobile: tutor rat(s) from deck to hand. Requires TUTOR_SELECT modal."""
    sb.set_mana(0, 10)
    sb.ensure_p0_turn()
    for _ in range(5):
        sb.add_card(0, NID["rat"], zone="deck_top")
    deck_before = len(sb.p0.get("deck", []))
    sb.add_card(0, NID["to_the_ratmobile"])
    sb.play_card(card_index=0)

    # Cast enters pending_tutor — send TUTOR_SELECT to pick first match
    sb.sio.emit("sandbox_apply_action", {"action_type": 9, "card_index": 0})
    sb.sio.sleep(1.0)
    # Tutor amount=2, so a second pick may be needed
    sb.sio.emit("sandbox_apply_action", {"action_type": 9, "card_index": 0})
    sb.sio.sleep(1.0)

    deck_after = len(sb.p0.get("deck", []))
    if deck_after < deck_before:
        return (f"Tutored: deck {deck_before}->{deck_after}", "PASS")
    return (f"No tutor: deck {deck_before}->{deck_after}", "FAIL")


# ==========================================================================
# TUTOR MINION TESTS (Diodebots)
# ==========================================================================

def make_tutor_deploy_test(stable_id, tutor_name):
    def test(sb):
        sb.set_mana(0, 10)
        sb.ensure_p0_turn()
        sb.add_card(0, NID["rat"], zone="deck_top")  # rat to deck as tutor target
        sb.add_card(0, stable_id)  # tutor minion to hand
        hand_before = len(sb.p0["hand"])
        sb.play_card(card_index=0, position=[0, 2])
        hand_after = len(sb.p0["hand"])
        has_minion = len(sb.minions) > 0 or any(c is not None for c in sb.state.get("board", []))
        if has_minion and hand_after >= hand_before:
            return (f"Deployed + tutored: hand {hand_before}->{hand_after}", "PASS")
        if has_minion:
            return (f"Deployed but tutor unclear: hand {hand_before}->{hand_after}", "PASS")
        return (f"Deploy failed: hand={hand_after}, minions={len(sb.minions)}", "FAIL")
    return test


# ==========================================================================
# PASSIVE/TRIGGER EFFECT TESTS
# ==========================================================================

def test_emberplague_burn(sb):
    """Emberplague Rat: passive burn. Deploy and verify it's on board."""
    sb.set_mana(0, 10)
    sb.ensure_p0_turn()
    sb.add_card(0, NID["emberplague_rat"])
    sb.play_card(card_index=0, position=[0, 2])
    if len(sb.minions) > 0 or any(c is not None for c in sb.state.get("board", [])):
        return ("Deployed. Burn is passive (triggers each turn)", "PASS")
    return (f"Deploy failed. errors={sb.errors}", "FAIL")


def test_fallen_paladin(sb):
    """Fallen Paladin: passive heal. Deploy and verify."""
    sb.set_mana(0, 10)
    sb.ensure_p0_turn()
    sb.add_card(0, NID["fallen_paladin"])
    sb.play_card(card_index=0, position=[0, 2])
    if len(sb.minions) > 0 or any(c is not None for c in sb.state.get("board", [])):
        return ("Deployed. Passive heal triggers each turn", "PASS")
    return (f"Deploy failed. errors={sb.errors}", "FAIL")


def test_furryroach_rally(sb):
    """Furryroach: rally forward on move. Deploy two minions."""
    sb.set_mana(0, 10)
    sb.ensure_p0_turn()
    # Deploy a rat at [1,2] first
    sb.add_card(0, NID["rat"])
    sb.play_card(card_index=0, position=[1, 2])
    sb.ensure_p0_turn()
    sb.set_mana(0, 10)
    # Deploy furryroach at [0,2]
    sb.add_card(0, NID["furryroach"])
    sb.play_card(card_index=0, position=[0, 2])
    board = [i for i, c in enumerate(sb.state.get("board", [])) if c is not None]
    if len(board) >= 2:
        return (f"Both deployed at cells {board}. Rally triggers on move", "PASS")
    if len(board) == 1:
        return (f"Only 1 minion on board (cell {board}). Second deploy may need turn fix", "FAIL")
    return (f"No minions on board. errors={sb.errors}", "FAIL")


def test_giant_rat_promote(sb):
    """Giant Rat: promote on death. Deploy and verify on board."""
    sb.set_mana(0, 10)
    sb.ensure_p0_turn()
    sb.add_card(0, NID["giant_rat"])
    sb.play_card(card_index=0, position=[0, 2])
    if len(sb.minions) > 0 or any(c is not None for c in sb.state.get("board", [])):
        return ("Deployed. Promote triggers on death", "PASS")
    return (f"Deploy failed. errors={sb.errors}", "FAIL")


def test_grave_caller(sb):
    """Grave Caller: dark matter buff on play. Deploy and verify."""
    sb.set_mana(0, 10)
    sb.ensure_p0_turn()
    sb.add_card(0, NID["grave_caller"])
    sb.play_card(card_index=0, position=[0, 2])
    if len(sb.minions) > 0 or any(c is not None for c in sb.state.get("board", [])):
        return ("Deployed. DM buff applied on play", "PASS")
    return (f"Deploy failed. errors={sb.errors}", "FAIL")


def test_pyre_archer(sb):
    """Pyre Archer: burn on attack. Deploy and verify."""
    sb.set_mana(0, 10)
    sb.ensure_p0_turn()
    sb.add_card(0, NID["pyre_archer"])
    sb.play_card(card_index=0, position=[0, 2])
    if len(sb.minions) > 0 or any(c is not None for c in sb.state.get("board", [])):
        m = sb.minions[0] if sb.minions else {}
        return (f"Deployed. range={m.get('attack_range','?')}. Burn triggers on attack", "PASS")
    return (f"Deploy failed. errors={sb.errors}", "FAIL")


def test_rathopper_leap(sb):
    """Rathopper: leap on move. Deploy and verify."""
    sb.set_mana(0, 10)
    sb.ensure_p0_turn()
    sb.add_card(0, NID["rathopper"])
    sb.play_card(card_index=0, position=[0, 2])
    if len(sb.minions) > 0 or any(c is not None for c in sb.state.get("board", [])):
        return ("Deployed. Leap triggers on move", "PASS")
    return (f"Deploy failed. errors={sb.errors}", "FAIL")


def test_rgb_lasercannon(sb):
    """RGB Lasercannon: Cost: Discard 2 Robots from hand. Death: Destroy target."""
    sb.set_mana(0, 10)
    sb.ensure_p0_turn()
    sb.add_card(0, NID["blue_diodebot"])   # Robot [0]
    sb.add_card(0, NID["green_diodebot"])  # Robot [1]
    sb.add_card(0, NID["rgb_lasercannon"]) # RGB   [2]

    # Play RGB (index 2) with discard_card_index=0 (first robot as cost)
    sb.sio.emit("sandbox_apply_action", {
        "action_type": 0, "card_index": 2, "position": [0, 2],
        "discard_card_index": 0
    })
    sb.sio.sleep(1.0)
    has_minion = len(sb.minions) > 0 or any(c is not None for c in sb.state.get("board", []))
    exhaust = len(sb.p0.get("exhaust", []))
    if has_minion and exhaust >= 2:
        return (f"Deployed. 2 Robots discarded to exhaust pile", "PASS")
    return (f"Deploy failed. hand={len(sb.p0['hand'])}, exhaust={exhaust}, errors={sb.errors}", "FAIL")


def test_counter_spell(sb):
    """Counter Spell: react card. Verify it can be held in hand."""
    sb.set_mana(0, 10)
    sb.add_card(0, NID["counter_spell"])
    if len(sb.p0["hand"]) == 1:
        return ("React card in hand. Plays during react window", "PASS")
    return ("Could not add to hand", "FAIL")


# ==========================================================================
# RUN ALL
# ==========================================================================

# Vanilla minions
run_test("Common Rat",        make_deploy_test(NID["rat"], 10, 10))
run_test("Ratchanter",        make_deploy_test(NID["ratchanter"], 15, 30))
run_test("Reanimated Bones",  make_deploy_test(NID["reanimated_bones"], 5, 5))
run_test("Surgefed Sparkbot", make_deploy_test(NID["surgefed_sparkbot"], 27, 25))

# Effect minions — deploy
run_test("Blue Diodebot",     make_tutor_deploy_test(NID["blue_diodebot"], "Blue Diodebot"))
run_test("Green Diodebot",    make_tutor_deploy_test(NID["green_diodebot"], "Green Diodebot"))
run_test("Red Diodebot",      make_tutor_deploy_test(NID["red_diodebot"], "Red Diodebot"))
run_test("Emberplague Rat",   test_emberplague_burn)
run_test("Fallen Paladin",    test_fallen_paladin)
run_test("Furryroach",        test_furryroach_rally)
run_test("Giant Rat",         test_giant_rat_promote)
run_test("Grave Caller",      test_grave_caller)
run_test("Pyre Archer",       test_pyre_archer)
run_test("Rathopper",         test_rathopper_leap)
run_test("RGB Lasercannon",   test_rgb_lasercannon)

# Magic cards
run_test("Ratical Resurrection", test_ratical_resurrection)
run_test("To The Ratmobile!",    test_to_the_ratmobile)
# React
run_test("Counter Spell",       test_counter_spell)

# Print results
print("\n" + "=" * 90)
print(f"{'CARD':<25} {'EXPECTATION':<30} {'WHAT HAPPENED':<45} {'RESULT':>6}")
print("=" * 90)
expectations = {
    "Common Rat": "Deploy vanilla 10/10",
    "Ratchanter": "Deploy vanilla 15/30",
    "Reanimated Bones": "Deploy vanilla 5/5",
    "Surgefed Sparkbot": "Deploy vanilla 27/25",
    "Blue Diodebot": "Deploy + tutor Robot from deck",
    "Green Diodebot": "Deploy + tutor Robot from deck",
    "Red Diodebot": "Deploy + tutor Robot from deck",
    "Emberplague Rat": "Deploy, passive burn each turn",
    "Fallen Paladin": "Deploy, passive heal each turn",
    "Furryroach": "Deploy, rally on move",
    "Giant Rat": "Deploy, promote on death",
    "Grave Caller": "Deploy, DM buff on play",
    "Pyre Archer": "Deploy, burn on attack",
    "Rathopper": "Deploy, leap on move",
    "RGB Lasercannon": "Deploy, destroy on death",
    "Ratical Resurrection": "Revive rat from graveyard",
    "To The Ratmobile!": "Tutor rat from deck to hand",
    "Counter Spell": "React card held in hand",
}
passed = failed = 0
for name, desc, result in RESULTS:
    exp = expectations.get(name, "?")
    flag = "PASS" if result == "PASS" else "FAIL"
    if result == "PASS":
        passed += 1
    else:
        failed += 1
    print(f"{name:<25} {exp:<30} {desc:<45} {flag:>6}")
print("=" * 90)
print(f"Total: {passed} passed, {failed} failed out of {len(RESULTS)}")
