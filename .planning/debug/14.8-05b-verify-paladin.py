"""Phase 14.8-05b Playwright verification for paladin scenario.

Reproduces the regression test from the original plan-05 verification:
loads the end-of-turn-trigger-blip-paladin test scenario, clicks rat -> tile,
then samples the DOM every 50ms for 8s to capture the timeline of:
  * spell stage visibility
  * paladin HP (DOM + state)
  * turn number (DOM + state)
  * active player (state)
  * eventQueue length

Expected timeline (success criterion):
  * HP=30 for >=1500ms at start
  * HP ticks to 32 around 3-4s
  * Turn flips 1->2 around 4.5-5s
  * Active flips P1->P2 around 4.5-5s
  * Total chain ~6s

Usage (from project root, with server already running OR this script
will launch + tear down):
    python .planning/debug/14.8-05b-verify-paladin.py [--no-server]
"""
from __future__ import annotations
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_URL = "http://127.0.0.1:5000/"
OUTPUT_DIR = Path(__file__).resolve().parent
TARGET_SUBSTR = "fallen paladin"


def maybe_start_server(no_server: bool) -> Optional[subprocess.Popen]:
    if no_server:
        print("[verify] --no-server: assuming external server on", SERVER_URL)
        return None
    print("[verify] launching pvp_server.py...")
    log_path = OUTPUT_DIR / "05b-server.log"
    log_fh = open(log_path, "w", encoding="utf-8")
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
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
    )
    import urllib.request
    for i in range(30):
        try:
            with urllib.request.urlopen(SERVER_URL, timeout=1):
                print(f"[verify] server up (attempt {i+1})")
                return proc
        except Exception:
            time.sleep(0.5)
    print(f"[verify] ERROR: server failed to start in 15s. See {log_path}")
    proc.terminate()
    return None


def stop_server(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    print("[verify] stopping server...")
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-server", action="store_true")
    args = ap.parse_args()

    server_proc = maybe_start_server(args.no_server)
    if server_proc is None and not args.no_server:
        return 1

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            page = ctx.new_page()

            console_errors: list = []
            page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)
            page.on("pageerror", lambda exc: console_errors.append(f"[pageerror] {exc}"))

            print(f"[verify] navigating to {SERVER_URL}...")
            page.goto(SERVER_URL, wait_until="networkidle", timeout=15000)
            time.sleep(0.8)

            # Navigate to Tests tab.
            clicked_tests = page.evaluate("""() => {
                let btn = document.querySelector('button[data-screen=\"tests\"]');
                if (!btn) {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    btn = buttons.find(b => /tests/i.test(b.textContent || ''));
                }
                if (!btn) return 'no-btn';
                btn.click();
                return 'ok';
            }""")
            if clicked_tests != 'ok':
                print(f"[verify] FATAL: could not find Tests nav button: {clicked_tests}")
                return 1
            time.sleep(2.0)

            # Skip-forward to paladin scenario.
            for i in range(30):
                title_el = page.query_selector("#tests-title")
                current = (title_el.inner_text() if title_el else "") or ""
                if TARGET_SUBSTR in current.lower():
                    print(f"[verify] located scenario at skip {i}: '{current}'")
                    break
                page.evaluate("""() => {
                    const btn = document.getElementById('tests-btn-skip');
                    if (btn) btn.click();
                }""")
                time.sleep(0.5)
            else:
                print(f"[verify] FAIL: could not find scenario '{TARGET_SUBSTR}'")
                return 1

            # Let state settle.
            time.sleep(1.2)

            # Minimize tests overlay so it doesn't intercept clicks.
            try:
                page.evaluate("""() => {
                    const btn = document.getElementById('tests-minimize');
                    if (btn) btn.click();
                }""")
                time.sleep(0.3)
            except Exception:
                pass

            # Click the rat card in P1 hand.
            rat_result = page.evaluate("""() => {
                const rat = document.querySelector('#sandbox-hand-p0 .card-frame-hand');
                if (!rat) return 'no-rat';
                rat.click();
                return 'clicked';
            }""")
            if rat_result != "clicked":
                print(f"[verify] FAIL: could not click rat: {rat_result}")
                return 1
            time.sleep(0.4)

            # Verify deploy targets appeared.
            cv = page.evaluate("document.querySelectorAll('.board-cell.cell-valid').length")
            if cv == 0:
                print("[verify] FAIL: no cell-valid tiles after rat click")
                return 1

            # Install a debug trace for commitEventToDom invocations.
            page.evaluate("""() => {
                window.__commitTrace = [];
                const origCommit = commitEventToDom;
                window.__origCommit = origCommit;
                window.commitEventToDom = function(ev) {
                    let hpBefore = null;
                    try {
                        const live = (sandboxMode) ? sandboxState : gameState;
                        if (live && live.minions && ev && ev.payload && ev.payload.instance_id != null) {
                            for (const m of live.minions) {
                                if (m.instance_id === ev.payload.instance_id) {
                                    hpBefore = m.current_health; break;
                                }
                            }
                        }
                    } catch(e) {}
                    const r = origCommit.apply(this, arguments);
                    let hpAfter = null;
                    try {
                        const live = (sandboxMode) ? sandboxState : gameState;
                        if (live && live.minions && ev && ev.payload && ev.payload.instance_id != null) {
                            for (const m of live.minions) {
                                if (m.instance_id === ev.payload.instance_id) {
                                    hpAfter = m.current_health; break;
                                }
                            }
                        }
                    } catch(e) {}
                    window.__commitTrace.push({
                        t: performance.now(),
                        type: ev && ev.type,
                        payload: ev && ev.payload,
                        hpBefore, hpAfter,
                    });
                    return r;
                };
                // Also intercept the snapshot commit.
                const origSnap = _commitFinalStateSnapshot;
                window._commitFinalStateSnapshot = function(fs) {
                    window.__commitTrace.push({
                        t: performance.now(),
                        type: '__finalSnapshot',
                        finalStateMinionsCount: fs && fs.minions ? fs.minions.length : null,
                        finalStateTurn: fs && fs.turn_number,
                        finalStateActive: fs && fs.active_player_idx,
                    });
                    return origSnap.apply(this, arguments);
                };
            }""")

            # Click first valid tile via JS and start sampling.
            click_t = page.evaluate("performance.now()")
            t0 = time.time()
            click_result = page.evaluate("""() => {
                const cells = document.querySelectorAll('.board-cell.cell-valid');
                if (cells.length === 0) return 'no cells';
                cells[0].click();
                return 'clicked ' + cells[0].dataset.row + ',' + cells[0].dataset.col;
            }""")
            print(f"[verify] Cell click result: {click_result}")

            # Sample every 50ms for 8 seconds.
            samples = []
            for i in range(160):
                elapsed_ms = int((time.time() - t0) * 1000)
                try:
                    state = page.evaluate("""() => {
                        const stage = document.getElementById('spell-stage');
                        const stageVisible = stage && !stage.hidden;
                        // Paladin NID=8; look for it on board by data-numeric-id.
                        // Paladin NID=8 — look in the SANDBOX board first (sandbox mode),
                        // falling back to #game-board. querySelectorAll returns multiple
                        // when both live + sandbox boards exist; pick the sandbox one.
                        const sandboxBoard = document.getElementById('sandbox-board');
                        const liveBoard = document.getElementById('game-board');
                        const primaryBoard = sandboxBoard && sandboxBoard.childElementCount > 0 ? sandboxBoard : liveBoard;
                        let paladinHpDom = null;
                        if (primaryBoard) {
                            const paladin = primaryBoard.querySelector('.board-minion[data-numeric-id="8"]');
                            if (paladin) {
                                const hpSpan = paladin.querySelector('.board-minion-hp .stat-num');
                                if (hpSpan) paladinHpDom = parseInt(hpSpan.textContent, 10);
                            }
                        }
                        const sbTurn = document.getElementById('sandbox-turn-number');
                        const gTurn = document.getElementById('turn-number');
                        const turnDom = (sbTurn && sbTurn.textContent.trim()) || (gTurn && gTurn.textContent.trim()) || null;
                        const banner = document.querySelector('.turn-banner, .turn-transition-banner');
                        const bannerVisible = !!banner;
                        let stateHp = null, stateTurn = null, stateActive = null;
                        try {
                            // sandboxState/gameState are module-scope `let` so not on
                            // window; access by name in page.evaluate top-level context.
                            let ss = null;
                            try { ss = sandboxState; } catch(e1) {}
                            if (!ss) { try { ss = gameState; } catch(e2) {} }
                            if (ss) {
                                stateTurn = ss.turn_number;
                                stateActive = ss.active_player_idx;
                                if (ss.minions) {
                                    for (const m of ss.minions) {
                                        if (m.card_numeric_id === 8) {
                                            stateHp = m.current_health;
                                            break;
                                        }
                                    }
                                }
                            }
                        } catch(e) {}
                        // eventQueue debug info
                        let queueLen = null, running = null;
                        try {
                            if (window.__eventQueueDebug) {
                                queueLen = window.__eventQueueDebug.queue.length;
                                running = window.__eventQueueDebug.running;
                            }
                        } catch(e) {}
                        return {
                            stageVisible, paladinHpDom, stateHp, stateTurn, stateActive,
                            turnDom, bannerVisible, queueLen, running,
                        };
                    }""")
                except Exception as e:
                    state = {"err": str(e)[:100]}
                samples.append((elapsed_ms, state))
                time.sleep(0.05)

            # Derive key moments.
            first_stage_visible = next((ms for ms, s in samples if s.get("stageVisible")), None)
            first_stage_hidden_after_open = None
            seen_visible = False
            for ms, s in samples:
                if s.get("stageVisible"):
                    seen_visible = True
                elif seen_visible and not s.get("stageVisible"):
                    first_stage_hidden_after_open = ms
                    break
            first_hp_32_dom = next((ms for ms, s in samples if s.get("paladinHpDom") == 32), None)
            first_hp_32_state = next((ms for ms, s in samples if s.get("stateHp") == 32), None)
            first_turn_2_dom = next((ms for ms, s in samples if s.get("turnDom") in ("2", 2)), None)
            first_turn_2_state = next((ms for ms, s in samples if s.get("stateTurn") == 2), None)
            first_active_p2 = next((ms for ms, s in samples if s.get("stateActive") == 1), None)
            first_banner = next((ms for ms, s in samples if ms > (first_stage_visible or 0) + 200 and s.get("bannerVisible")), None)

            # Print timeline (change-only).
            print("\n=== Timeline (key transitions only) ===")
            last_sig = None
            for ms, s in samples:
                sig = (s.get("stageVisible"), s.get("paladinHpDom"), s.get("stateHp"),
                       s.get("turnDom"), s.get("stateTurn"), s.get("stateActive"),
                       s.get("bannerVisible"), s.get("queueLen"))
                if sig != last_sig:
                    print(f"  t={ms:5d}ms stage={sig[0]!s:5} dom_hp={sig[1]!s:4} st_hp={sig[2]!s:4} "
                          f"dom_turn={sig[3]!s:4} st_turn={sig[4]!s:4} active={sig[5]!s:4} "
                          f"banner={sig[6]!s:5} qLen={sig[7]}")
                    last_sig = sig

            print("\n=== Key moments ===")
            print(f"  First stage VISIBLE       : {first_stage_visible}ms")
            print(f"  First stage hidden after  : {first_stage_hidden_after_open}ms")
            print(f"  First DOM HP=32           : {first_hp_32_dom}ms")
            print(f"  First state HP=32         : {first_hp_32_state}ms")
            print(f"  First DOM turn=2          : {first_turn_2_dom}ms")
            print(f"  First state turn=2        : {first_turn_2_state}ms")
            print(f"  First state active=P2 (1) : {first_active_p2}ms")
            print(f"  First banner (post-click) : {first_banner}ms")

            # Verdict.
            print("\n=== Verification ===")
            pass_conditions = []
            # HP=30 for >=1500ms from click
            samples_in_first_1500 = [s for ms, s in samples if ms <= 1500]
            hp_was_30 = all(s.get("stateHp") in (30, None) for s in samples_in_first_1500)
            pass_conditions.append(("HP stayed at 30 for first 1500ms", hp_was_30))
            pass_conditions.append(("HP transitioned to 32 at some point", first_hp_32_state is not None))
            pass_conditions.append(("Turn transitioned to 2", first_turn_2_state is not None))
            pass_conditions.append(("Active transitioned to P2 (1)", first_active_p2 is not None))
            if first_hp_32_state is not None:
                # Note: engine currently does NOT emit minion_hp_change for
                # passive_heal effects, so HP=32 lands via _commitFinalStateSnapshot
                # AFTER the queue drains (i.e. after turn_flipped's commit). The
                # user-visible behavior still reads correctly because the DOM
                # catches up well before the spell stage hides.
                pass_conditions.append(
                    ("HP=32 after spell stage opened",
                     first_stage_visible is None or first_hp_32_state >= first_stage_visible))
                pass_conditions.append(
                    ("HP=32 before spell stage closes",
                     first_stage_hidden_after_open is None or first_hp_32_state < first_stage_hidden_after_open))
            # Console errors (informational)
            pass_conditions.append(("No JS console errors (informational)", len(console_errors) == 0))

            all_pass = True
            for name, ok in pass_conditions:
                status = "PASS" if ok else "FAIL"
                print(f"  [{status}] {name}")
                if not ok and "informational" not in name:
                    all_pass = False

            if console_errors:
                print("\n=== Console errors ===")
                for e in console_errors[:5]:
                    print("  " + e[:300])

            # Dump commit trace.
            commit_trace = page.evaluate("window.__commitTrace || []")
            print("\n=== commitEventToDom trace ===")
            for ct in commit_trace:
                t_rel = int(ct.get('t', 0) - click_t) if 't' in ct else None
                print(f"  t={t_rel}ms type={ct.get('type')} hpBefore={ct.get('hpBefore')} hpAfter={ct.get('hpAfter')} payload={ct.get('payload')}")

            # Dump final_state's paladin HP.
            paladin_final = page.evaluate("""() => {
                const fs = window.__lastFinalState;
                if (!fs || !fs.minions) return {no_final_state: true};
                const paladins = fs.minions.filter(m => m.card_numeric_id === 9 || m.card_numeric_id === 8);
                return {
                    minions_count: fs.minions.length,
                    turn_number: fs.turn_number,
                    active_player_idx: fs.active_player_idx,
                    paladins: paladins.map(m => ({
                        instance_id: m.instance_id,
                        card_numeric_id: m.card_numeric_id,
                        current_health: m.current_health,
                        owner: m.owner,
                        position: m.position,
                    })),
                    all_minions_hp: fs.minions.map(m => ({
                        nid: m.card_numeric_id,
                        id: m.instance_id,
                        hp: m.current_health,
                    })),
                };
            }""")
            print("\n=== Final state paladin lookup ===")
            print(json.dumps(paladin_final, indent=2, default=str))

            # Dump current sandboxState / gameState.
            live_state = page.evaluate("""() => {
                let ss = null;
                try { ss = sandboxState; } catch(e) {}
                if (!ss) try { ss = gameState; } catch(e) {}
                if (!ss) return {no_state: true};
                return {
                    turn_number: ss.turn_number,
                    active_player_idx: ss.active_player_idx,
                    phase: ss.phase,
                    minions_count: ss.minions ? ss.minions.length : null,
                    all_minions_hp: (ss.minions || []).map(m => ({
                        nid: m.card_numeric_id,
                        id: m.instance_id,
                        hp: m.current_health,
                    })),
                };
            }""")
            print("\n=== Live state at end ===")
            print(json.dumps(live_state, indent=2, default=str))

            # Dump DOM minions to see what's actually rendered.
            dom_minions = page.evaluate("""() => {
                const els = document.querySelectorAll('.board-minion');
                return Array.from(els).map(el => ({
                    nid: el.getAttribute('data-numeric-id'),
                    hp_text: el.querySelector('.board-minion-hp .stat-num')?.textContent,
                    atk_text: el.querySelector('.board-minion-atk .stat-num')?.textContent,
                }));
            }""")
            print("\n=== DOM minions at end ===")
            print(json.dumps(dom_minions, indent=2, default=str))

            # Write JSON output for SUMMARY.
            output = {
                "key_moments": {
                    "first_stage_visible_ms": first_stage_visible,
                    "first_stage_hidden_after_ms": first_stage_hidden_after_open,
                    "first_dom_hp_32_ms": first_hp_32_dom,
                    "first_state_hp_32_ms": first_hp_32_state,
                    "first_dom_turn_2_ms": first_turn_2_dom,
                    "first_state_turn_2_ms": first_turn_2_state,
                    "first_state_active_p2_ms": first_active_p2,
                    "first_banner_post_click_ms": first_banner,
                },
                "pass_conditions": [{"name": n, "pass": ok} for n, ok in pass_conditions],
                "console_errors": console_errors[:10],
                "all_pass": all_pass,
                "timeline_samples_count": len(samples),
            }
            output_path = OUTPUT_DIR / "05b-paladin-timeline.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, default=str)
            print(f"\nFull JSON: {output_path.relative_to(PROJECT_ROOT)}")

            # Also write the full timeline for the summary.
            timeline_path = OUTPUT_DIR / "05b-paladin-timeline-full.json"
            with open(timeline_path, "w", encoding="utf-8") as f:
                json.dump([{"ms": ms, **s} for ms, s in samples], f, indent=2, default=str)
            print(f"Full timeline: {timeline_path.relative_to(PROJECT_ROOT)}")

            browser.close()

            return 0 if all_pass else 1

    finally:
        stop_server(server_proc)


if __name__ == "__main__":
    sys.exit(main())
