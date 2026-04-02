---
phase: 2
slug: card-system-types
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/ -x -q` |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/ -v --tb=short` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/Scripts/python.exe -m pytest tests/ -x -q`
- **After every plan wave:** Run `.venv/Scripts/python.exe -m pytest tests/ -v --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | ENG-04 | unit | `pytest tests/test_cards.py -k card_type` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ENG-05 | unit | `pytest tests/test_cards.py -k minion_stats` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ENG-12 | unit | `pytest tests/test_cards.py -k multi_purpose` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | CARD-01 | unit | `pytest tests/test_cards.py -k json_load` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | CARD-02 | unit | `pytest tests/test_cards.py -k starter_pool` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_cards.py` — stubs for ENG-04, ENG-05, ENG-12, CARD-01, CARD-02
- [ ] `tests/test_effects.py` — stubs for effect system validation
- [ ] `tests/test_card_loader.py` — stubs for JSON loading and validation

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
