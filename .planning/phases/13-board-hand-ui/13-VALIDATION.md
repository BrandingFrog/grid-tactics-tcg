---
phase: 13
slug: board-hand-ui
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Manual browser verification + pytest for server-side |
| **Config file** | pyproject.toml (existing) |
| **Quick run command** | `pytest tests/test_pvp_server.py tests/test_game_flow.py -q` |
| **Full suite command** | `pytest tests/ -q --ignore=tests/test_action_space.py` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick command (regression check)
- **After every plan wave:** Visual browser check + quick command
- **Before `/gsd:verify-work`:** Full suite must be green + visual verification
- **Max feedback latency:** 5 seconds (automated) + manual visual

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 1 | UI-01, UI-02 | visual + regression | `pytest tests/test_pvp_server.py -q` | ✅ | ⬜ pending |
| 13-02-01 | 02 | 2 | UI-03, UI-04 | visual + regression | `pytest tests/test_game_flow.py -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- Existing test infrastructure covers regression. No new test files needed for this UI phase.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 5x5 grid renders with minions showing name, ATK/HP, owner color, attribute | UI-01 | Visual rendering | Open two browsers, create+join room, ready up, verify grid shows deployed minions correctly |
| Hand cards show name, mana cost, ATK/HP, effects, attribute; unaffordable dimmed | UI-02 | Visual rendering | Verify hand renders with full card details, check dimming when mana insufficient |
| Both players' mana and HP displayed prominently | UI-03 | Visual rendering | Check mana/HP widgets visible for both players |
| Turn indicator shows whose turn + ACTION vs REACT phase | UI-04 | Visual rendering | Play a few turns, verify indicator updates correctly |
| P2 perspective is flipped (own side at bottom) | UI-01 | Visual rendering | Check P2's browser shows grid flipped vs P1 |

---

## Validation Sign-Off

- [ ] All tasks have automated regression checks
- [ ] Manual visual verification plan documented
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s (automated)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
