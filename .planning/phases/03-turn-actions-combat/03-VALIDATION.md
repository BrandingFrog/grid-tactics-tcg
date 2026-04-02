---
phase: 3
slug: turn-actions-combat
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/ -x -q` |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -v --tb=short` |
| **Estimated runtime** | ~8 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/Scripts/python.exe -m pytest tests/ -x -q`
- **After every plan wave:** Run `.venv/Scripts/python.exe -m pytest tests/ -v --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 8 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | ENG-03 | unit | `pytest tests/test_actions.py -k turn_structure` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ENG-06 | unit | `pytest tests/test_actions.py -k movement_combat` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ENG-08 | unit | `pytest tests/test_actions.py -k draw_action` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ENG-10 | unit | `pytest tests/test_actions.py -k legal_actions` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_minion.py` — stubs for MinionInstance
- [ ] `tests/test_actions.py` — stubs for action types, turn structure, legal actions
- [ ] `tests/test_combat.py` — stubs for combat resolution, simultaneous damage
- [ ] `tests/test_react.py` — stubs for react window, stack chaining
- [ ] `tests/test_effects.py` — stubs for effect resolution

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 8s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
