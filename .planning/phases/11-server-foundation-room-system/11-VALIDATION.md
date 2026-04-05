---
phase: 11
slug: server-foundation-room-system
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml (existing) |
| **Quick run command** | `pytest tests/test_pvp_server.py -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_pvp_server.py -q`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | SERVER-01 | integration | `pytest tests/test_pvp_server.py::test_create_room -q` | ❌ W0 | ⬜ pending |
| 11-01-02 | 01 | 1 | SERVER-02 | integration | `pytest tests/test_pvp_server.py::test_join_room -q` | ❌ W0 | ⬜ pending |
| 11-02-01 | 02 | 2 | SERVER-01 | integration | `pytest tests/test_pvp_server.py::test_ready_and_game_start -q` | ❌ W0 | ⬜ pending |
| 11-02-02 | 02 | 2 | SERVER-02 | integration | `pytest tests/test_pvp_server.py::test_full_create_join_ready_flow -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_pvp_server.py` — stubs for SERVER-01, SERVER-02 (create/join/ready/game_start)
- [ ] `tests/conftest.py` — update with Flask-SocketIO test client fixtures

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Two separate terminals can connect and join same room | SERVER-02 | Multi-process WebSocket test | Start server, open two terminals with python-socketio client, create + join room, verify game_start received |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
