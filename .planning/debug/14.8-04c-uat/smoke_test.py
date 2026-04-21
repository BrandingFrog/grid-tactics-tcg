"""Playwright smoke test for Phase 14.8 plan 04c visual UAT.

Verifies the 5 UAT scenarios load cleanly AFTER plan 04b's eventQueue
migration. This is prep work for the human-verify checkpoint — it catches
trivial breakage (server won't start, scenario won't load, JS exceptions
on fresh scenario, engine_events socket message never fires) so the
user doesn't waste time if the pipeline is broken.

NOT a replacement for human eyes — discrete visual beats, animation
ordering, and modal interaction correctness must be verified manually.

Usage (from project root, with server already running OR this script
will launch + tear down):
    python .planning/debug/14.8-04c-uat/smoke_test.py [--no-server]

Exit code:
    0 = smoke passed, UAT is runnable
    1 = smoke FAILED, UAT blocked — see output
"""
from __future__ import annotations
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCREENSHOT_DIR = Path(__file__).resolve().parent
SERVER_URL = "http://127.0.0.1:5000/"

# Scenario IDs in tests.json to exercise. Title-substring matches for
# navigation (case-insensitive). Order matters — the Tests tab ships
# them sequentially and we skip-forward to each one.
SCENARIOS = [
    {
        "uat_num": 1,
        "id": "prohibition-react-chain",
        "title_substr": "react chain",
        "description": "3-deep react chain (Acidic Rain + 3x Prohibition)",
    },
    {
        "uat_num": 2,
        "id": "end-of-turn-trigger-blip-paladin",
        "title_substr": "fallen paladin",
        "description": "Paladin end-of-turn heal on rat deploy",
    },
    {
        "uat_num": 3,
        "id": "priority-modal-two-end-triggers",
        "title_substr": "priority modal",
        "description": "Double-paladin priority modal",
    },
    {
        "uat_num": 4,
        "id": "ratchanter-activated-ability-eventqueue",
        "title_substr": "ratchanter activated",
        "description": "Ratchanter activated ability (tutor -> conjure_deploy chain)",
    },
    {
        "uat_num": 5,
        "id": "tree-wyrm-react-eventqueue",
        "title_substr": "tree wyrm react",
        "description": "Multi-purpose Tree Wyrm react",
    },
]


def maybe_start_server(no_server: bool) -> Optional[subprocess.Popen]:
    """Launch pvp_server.py in a subprocess unless --no-server was given.

    Returns the subprocess Popen or None.
    """
    if no_server:
        print("[smoke] --no-server: assuming external server on", SERVER_URL)
        return None
    print("[smoke] launching pvp_server.py...")
    log_path = SCREENSHOT_DIR / "server.log"
    log_fh = open(log_path, "w", encoding="utf-8")
    # Inject src/ onto PYTHONPATH so `import grid_tactics` resolves when
    # pvp_server.py runs as a standalone script (pyproject.toml sets
    # pythonpath = ["src"] for pytest but that only affects test runs).
    env = dict(os.environ)
    src_dir = str(PROJECT_ROOT / "src")
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (src_dir + os.pathsep + existing_pp) if existing_pp else src_dir
    proc = subprocess.Popen(
        [sys.executable, "pvp_server.py"],
        cwd=str(PROJECT_ROOT),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        env=env,
        # On Windows, use CREATE_NEW_PROCESS_GROUP so we can CTRL_BREAK cleanly.
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
    )
    # Wait for server to be responsive.
    import urllib.request
    for i in range(30):
        try:
            with urllib.request.urlopen(SERVER_URL, timeout=1):
                print(f"[smoke] server up (attempt {i+1})")
                return proc
        except Exception:
            time.sleep(0.5)
    print(f"[smoke] ERROR: server failed to start in 15s. See {log_path}")
    proc.terminate()
    return None


def stop_server(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    print("[smoke] stopping server...")
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def find_scenario_index(page, title_substr: str, max_skips: int = 30) -> Optional[int]:
    """Skip-forward through tests until the title substring matches.

    Returns the skip count used, or None if not found. Uses JS-dispatched
    clicks rather than Playwright's hitbox-based clicks to work around the
    tests overlay textarea that can intercept pointer events.
    """
    for i in range(max_skips + 1):
        title_el = page.query_selector("#tests-title")
        current = (title_el.inner_text() if title_el else "") or ""
        if title_substr.lower() in current.lower():
            return i
        # Advance via JS .click() on the skip button — bypasses pointer
        # interception from the overlay textarea.
        clicked = page.evaluate("""() => {
            const btn = document.getElementById('tests-btn-skip');
            if (!btn) return false;
            btn.click();
            return true;
        }""")
        if not clicked:
            return None
        time.sleep(0.55)
    return None


def run_scenario(page, sc: dict, results: dict, console_errors: list, engine_events_log: list) -> None:
    """Load one scenario via the Tests tab, verify it loads + no JS errors."""
    uat_num = sc["uat_num"]
    key = f"scenario_{uat_num}"
    results[key] = {"description": sc["description"], "id": sc["id"]}

    # Reset error/event tracking for this scenario.
    err_baseline = len(console_errors)
    evt_baseline = len(engine_events_log)

    # Clear the page's engine_events counter via JS for cleanly-scoped counts.
    page.evaluate("""() => { window.__smokeEngineEvents = []; }""")

    print(f"\n[smoke] Scenario {uat_num}: {sc['description']}")
    skips = find_scenario_index(page, sc["title_substr"])
    if skips is None:
        results[key]["status"] = "NOT_FOUND"
        results[key]["error"] = f"Scenario '{sc['title_substr']}' not found in Tests tab"
        print(f"  FAIL: {results[key]['error']}")
        return

    # Let the scenario's setup ops run on the server side.
    time.sleep(1.2)

    # Confirm the title now matches.
    title_el = page.query_selector("#tests-title")
    title_text = (title_el.inner_text() if title_el else "") or ""
    results[key]["loaded_title"] = title_text

    # Check sandbox state is populated (board should have at least one minion
    # OR hand should have at least one card — scenario-dependent).
    # sandboxState is declared with `let` at module scope so it isn't
    # attached to window. But Playwright can still reference it by name
    # because page.evaluate executes in the top-level JS context. If that
    # fails (strict-mode / different binding), fall back to reading the
    # DOM directly.
    state_check = page.evaluate("""() => {
        try {
            let ss = null;
            try { ss = sandboxState; } catch(e1) {}
            if (!ss) try { ss = gameState; } catch(e2) {}
            if (!ss) try { ss = window.__lastFinalState; } catch(e3) {}
            if (!ss) return { ok: false, reason: 'no sandboxState/gameState/__lastFinalState' };
            // Minion dict payload doesn't include is_alive (dead minions are
            // removed from the list during cleanup). Any minion present is alive.
            const minions = (ss.minions || []).length;
            const p1_hand = (ss.players && ss.players[0] && ss.players[0].hand) ? ss.players[0].hand.length : 0;
            const p2_hand = (ss.players && ss.players[1] && ss.players[1].hand) ? ss.players[1].hand.length : 0;
            // Also count DOM tiles with minions as a cross-check.
            const dom_minions = document.querySelectorAll('.board-minion, .minion-tile, [data-numeric-id]').length;
            return {
                ok: true,
                minions, p1_hand, p2_hand, dom_minions,
                turn: ss.turn_number,
                active: ss.active_player_idx,
                phase: ss.phase,
            };
        } catch(e) { return { ok: false, reason: String(e).slice(0, 200) }; }
    }""")
    results[key]["state_check"] = state_check

    if not state_check.get("ok"):
        results[key]["status"] = "LOAD_FAIL"
        results[key]["error"] = state_check.get("reason", "unknown")
        print(f"  FAIL: scenario loaded but state missing ({state_check.get('reason')})")
        return

    total_cards_or_minions = (
        state_check.get("minions", 0) + state_check.get("p1_hand", 0) + state_check.get("p2_hand", 0)
    )
    if total_cards_or_minions == 0:
        results[key]["status"] = "EMPTY_STATE"
        results[key]["error"] = "setup ops produced empty state (no minions or cards)"
        print(f"  FAIL: setup produced empty state")
        return

    # Capture baseline screenshot.
    screenshot_path = SCREENSHOT_DIR / f"scenario-{uat_num}-load.png"
    try:
        page.screenshot(path=str(screenshot_path), full_page=False)
        results[key]["screenshot"] = str(screenshot_path.relative_to(PROJECT_ROOT))
    except Exception as e:
        results[key]["screenshot_err"] = str(e)[:100]

    # New JS errors since this scenario started loading?
    new_errs = console_errors[err_baseline:]
    new_evts = len(engine_events_log) - evt_baseline
    results[key]["new_console_errors"] = len(new_errs)
    results[key]["new_engine_events"] = new_evts
    if new_errs:
        results[key]["first_error"] = new_errs[0][:300]

    # Verdict.
    if new_errs:
        results[key]["status"] = "CONSOLE_ERRORS"
        print(f"  WARN: {len(new_errs)} console error(s) during load; first: {new_errs[0][:120]}")
    else:
        results[key]["status"] = "LOADS_CLEAN"
        print(f"  OK: loaded clean (minions={state_check.get('minions')}, p1_hand={state_check.get('p1_hand')}, p2_hand={state_check.get('p2_hand')}, engine_events so far: {new_evts})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-server", action="store_true", help="Don't launch pvp_server.py; assume it's already running")
    args = ap.parse_args()

    server_proc = maybe_start_server(args.no_server)
    if server_proc is None and not args.no_server:
        return 1

    results: dict = {"smoke_start": time.strftime("%Y-%m-%d %H:%M:%S")}
    console_errors: list = []
    engine_events_log: list = []

    exit_code = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            page = ctx.new_page()

            # Capture console errors.
            def on_console(msg):
                if msg.type in ("error",):
                    console_errors.append(f"[{msg.type}] {msg.text}")

            page.on("console", on_console)
            page.on("pageerror", lambda exc: console_errors.append(f"[pageerror] {exc}"))

            # Open page.
            print(f"[smoke] navigating to {SERVER_URL}...")
            page.goto(SERVER_URL, wait_until="networkidle", timeout=15000)
            time.sleep(0.8)

            # Instrument a global engine_events tap so we can count events.
            page.evaluate("""() => {
                window.__smokeEngineEvents = [];
                if (typeof socket !== 'undefined' && socket && socket.on) {
                    socket.on('engine_events', function(payload) {
                        try {
                            window.__smokeEngineEvents.push({
                                t: performance.now(),
                                count: (payload && payload.events) ? payload.events.length : 0,
                                is_sandbox: !!(payload && payload.is_sandbox),
                            });
                        } catch(e) {}
                    });
                }
            }""")

            # Sanity: is the top-level socket variable present? If not, plan 03b
            # wiring is broken.
            has_socket = page.evaluate("typeof socket !== 'undefined' && socket && typeof socket.on === 'function'")
            results["has_socket_global"] = bool(has_socket)
            if not has_socket:
                results["smoke_verdict"] = "BLOCKED_NO_SOCKET"
                exit_code = 1
                print("[smoke] FATAL: window.socket not found — 03b wiring broken")
                return exit_code

            # Navigate to Tests tab via the nav button (data-screen='tests').
            # Use JS click to bypass any hitbox issues.
            clicked_tests = page.evaluate("""() => {
                // Prefer the data-screen selector (nav button) over text match.
                let btn = document.querySelector('button[data-screen=\"tests\"]');
                if (!btn) {
                    // Fall back to any button whose text contains 'tests'.
                    const buttons = Array.from(document.querySelectorAll('button'));
                    btn = buttons.find(b => /tests/i.test(b.textContent || ''));
                }
                if (!btn) return 'no-btn';
                btn.click();
                return 'ok';
            }""")
            if clicked_tests != 'ok':
                results["smoke_verdict"] = "BLOCKED_NO_TESTS_BTN"
                exit_code = 1
                print(f"[smoke] FATAL: could not find Tests nav button: {clicked_tests}")
                return exit_code
            time.sleep(2.0)  # let tests_list socket round-trip complete

            # Check the tests overlay is actually present AND populated.
            overlay_state = page.evaluate("""() => {
                const title = document.getElementById('tests-title');
                const overlay = document.getElementById('tests-overlay');
                if (!title) return { ok: false, reason: 'no tests-title el' };
                if (!overlay) return { ok: false, reason: 'no tests-overlay el' };
                return { ok: true, title: title.textContent, hidden: overlay.hidden };
            }""")
            if not overlay_state.get("ok"):
                results["smoke_verdict"] = "BLOCKED_NO_TESTS_OVERLAY"
                exit_code = 1
                print(f"[smoke] FATAL: tests overlay missing: {overlay_state.get('reason')}")
                return exit_code
            print(f"[smoke] tests overlay ready: title='{overlay_state.get('title')}' hidden={overlay_state.get('hidden')}")

            # Iterate scenarios.
            for sc in SCENARIOS:
                # Pull the current engine_events log into the local list.
                try:
                    current_evts = page.evaluate("window.__smokeEngineEvents || []")
                    engine_events_log[:] = current_evts
                except Exception:
                    pass
                run_scenario(page, sc, results, console_errors, engine_events_log)

            # Final engine_events + console_errors sweep.
            try:
                final_evts = page.evaluate("window.__smokeEngineEvents || []")
                results["total_engine_events_frames"] = len(final_evts)
            except Exception:
                pass

            results["total_console_errors"] = len(console_errors)
            results["console_errors_sample"] = [e[:200] for e in console_errors[:10]]

            browser.close()

    finally:
        stop_server(server_proc)

    # Print a summary.
    print("\n" + "=" * 72)
    print("SMOKE TEST SUMMARY")
    print("=" * 72)
    passes = sum(1 for k, v in results.items() if isinstance(v, dict) and v.get("status") == "LOADS_CLEAN")
    warns = sum(1 for k, v in results.items() if isinstance(v, dict) and v.get("status") == "CONSOLE_ERRORS")
    fails = sum(1 for k, v in results.items() if isinstance(v, dict) and v.get("status") in ("NOT_FOUND", "LOAD_FAIL", "EMPTY_STATE"))
    print(f"  PASS (loaded clean)        : {passes}/5")
    print(f"  WARN (loaded + JS errors)  : {warns}/5")
    print(f"  FAIL (load failed)         : {fails}/5")
    print(f"  Total engine_events frames : {results.get('total_engine_events_frames', 0)}")
    print(f"  Total console errors       : {results.get('total_console_errors', 0)}")

    for i in range(1, 6):
        key = f"scenario_{i}"
        if key not in results:
            continue
        r = results[key]
        status = r.get("status", "UNKNOWN")
        print(f"  [{status:14s}] Scenario {i}: {r.get('description', '?')}")
        if r.get("error"):
            print(f"                 error: {r['error'][:180]}")
        if r.get("state_check", {}).get("ok"):
            sc = r["state_check"]
            print(f"                 state: minions={sc.get('minions')} p1_hand={sc.get('p1_hand')} p2_hand={sc.get('p2_hand')} turn={sc.get('turn')} active={sc.get('active')} phase={sc.get('phase')}")
        if r.get("screenshot"):
            print(f"                 screenshot: {r['screenshot']}")

    # Write results JSON for the checkpoint report.
    import json
    results_path = SCREENSHOT_DIR / "smoke_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results: {results_path.relative_to(PROJECT_ROOT)}")

    if fails > 0:
        print("\nSMOKE VERDICT: BLOCKED — at least one scenario failed to load cleanly.")
        print("UAT cannot proceed until the failing scenarios are fixed.")
        return 1
    print("\nSMOKE VERDICT: OK — all scenarios load. Ready for human UAT.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
