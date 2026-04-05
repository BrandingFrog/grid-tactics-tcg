---
phase: 12
slug: state-serialization-game-flow
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml (existing) |
| **Quick run command** | `pytest tests/test_game_flow.py -q` |
| **Full suite command** | `pytest tests/test_game_flow.py tests/test_pvp_server.py tests/test_fatigue_fix.py -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_game_flow.py -q`
- **After every plan wave:** Run full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 1 | VIEW-01 | unit | `pytest tests/test_game_flow.py::test_view_filter_hides_opponent_hand -q` | ❌ W0 | ⬜ pending |
| 12-01-02 | 01 | 1 | VIEW-02 | integration | `pytest tests/test_game_flow.py::test_illegal_action_rejected -q` | ❌ W0 | ⬜ pending |
| 12-02-01 | 02 | 2 | VIEW-03 | integration | `pytest tests/test_game_flow.py::test_legal_actions_in_state_update -q` | ❌ W0 | ⬜ pending |
| 12-02-02 | 02 | 2 | SERVER-03 | integration | `pytest tests/test_game_flow.py::test_full_game_to_completion -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_game_flow.py` — stubs for VIEW-01, VIEW-02, VIEW-03, SERVER-03

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Two terminals playing full game via WebSocket | SERVER-03 | Multi-process real WebSocket | Start server, run two python-socketio clients, alternate actions through full game |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
