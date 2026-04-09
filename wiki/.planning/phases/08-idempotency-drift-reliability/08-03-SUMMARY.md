---
phase: 08
plan: 03
subsystem: ci-testing
tags: [github-actions, drift-detection, pytest, ci]
dependency_graph:
  requires: ["08-02"]
  provides: ["CI drift check workflow", "check_drift unit tests"]
  affects: ["09"]
tech_stack:
  added: []
  patterns: ["GitHub Actions CI", "mock-based drift testing"]
key_files:
  created:
    - .github/workflows/drift-check.yml
    - wiki/tests/test_check_drift.py
  modified: []
decisions:
  - id: "08-03-01"
    summary: "CLI tests patch check_drift at function level rather than building full mock site, for speed and isolation"
  - id: "08-03-02"
    summary: "Drift tests use tmp_path with 2-3 card JSON copies to keep test execution fast"
metrics:
  duration: ~3 min
  completed: 2026-04-09
---

# Phase 8 Plan 3: CI Drift Check Workflow & Unit Tests Summary

GitHub Actions workflow for automated drift detection on every push to master, plus 6 unit tests proving check_drift.py works correctly with mocked wiki responses.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Unit tests for check_drift.py | e292bfa | wiki/tests/test_check_drift.py |
| 2 | GitHub Actions drift-check workflow | 3bcb2d7 | .github/workflows/drift-check.yml |

## What Was Built

### Unit Tests (wiki/tests/test_check_drift.py)

6 tests in 2 classes:

**TestCheckDrift** (4 tests):
- `test_no_drift_clean` -- mock site returns expected wikitext, empty report
- `test_content_mismatch_detected` -- tampered card page triggers content_mismatch
- `test_missing_page_detected` -- non-existent card page triggers missing_page
- `test_multiple_drifts` -- 2 mismatches + 1 missing = 3 drift reports

**TestCheckDriftCLI** (2 tests):
- `test_cli_exit_zero_no_drift` -- main() returns 0 when clean
- `test_cli_exit_one_on_drift` -- main() returns 1 when drift found

### GitHub Actions Workflow (.github/workflows/drift-check.yml)

- Triggers on push to master with path filters (data/cards/**, data/GLOSSARY.md, wiki/sync/**, VERSION.json)
- Manual trigger via workflow_dispatch
- Steps: checkout, setup Python 3.12, install wiki deps, run pytest, run check_drift --cards-only
- Wiki credentials from GitHub repo secrets (MW_API_URL, MW_BOT_USER, MW_BOT_PASS, MW_API_PATH)

## Decisions Made

1. **CLI tests use function-level patching** -- patch `check_drift` return value rather than building full mock site. Faster, tests CLI logic (exit codes, output) not drift detection logic (covered by TestCheckDrift).
2. **Drift tests copy 2-3 card JSONs to tmp_path** -- keeps test fast (~0.7s for all 6) while using real card data for realistic wikitext generation.

## Deviations from Plan

None -- plan executed exactly as written.

## Verification

- `cd wiki && python -m pytest tests/test_check_drift.py -v` -- 6/6 pass
- `cd wiki && python -m pytest tests/ -v` -- 46/46 pass (no regressions)
- `.github/workflows/drift-check.yml` validated as valid YAML

## Next Phase Readiness

Phase 8 complete. All 5 success criteria met:
1. Idempotency verified by test (08-01)
2. Dry-run verified by mock test (08-01)
3. check_drift.py exits non-zero on drift (08-02 + 08-03 tests)
4. Resume manifest works for mid-batch failures (08-02)
5. GitHub Actions workflow triggers on push to master (08-03)

Ready for Phase 9 (Launch Polish).
