---
phase: 08-idempotency-drift-reliability
plan: 01
subsystem: testing
tags: [idempotency, dry-run, mock, pytest]
dependency_graph:
  requires: [03, 04, 07]
  provides: [idempotency-regression-tests, dry-run-verification]
  affects: [08-02, 08-03]
tech_stack:
  added: []
  patterns: [mock-site-pattern, page-store-pattern]
key_files:
  created:
    - wiki/tests/test_idempotency.py
    - wiki/tests/test_dry_run.py
  modified: []
decisions:
  - id: "08-01-01"
    description: "Mock site uses page_store dict with __getitem__ override for realistic page lookup simulation"
  - id: "08-01-02"
    description: "MediaWiki rstrip behavior replicated in mocks — stored text has trailing whitespace stripped to match real API"
metrics:
  duration: "2 min"
  completed: "2026-04-09"
---

# Phase 8 Plan 1: Idempotency & Dry-Run Test Coverage Summary

Mock-based pytest suite proving idempotency (zero edits on re-sync) and dry-run safety (no .edit()/.upload() calls) across all sync paths.

## What Was Done

### Task 1: Idempotency test — second upsert produces zero edits
- Created `wiki/tests/test_idempotency.py` with 3 tests
- `test_card_upsert_idempotent`: first call creates card page, second call with same data returns "unchanged" with zero `.edit()` calls
- `test_taxonomy_upsert_idempotent`: first call creates 2 element pages, second call returns all "unchanged"
- `test_homepage_upsert_idempotent`: first call creates Main Page, second call returns "unchanged"
- Commit: `f105871`

### Task 2: Dry-run mock test — no API writes when --dry-run is set
- Created `wiki/tests/test_dry_run.py` with 7 tests
- Covers card create/update/unchanged, art upload, taxonomy, homepage, and showcase paths
- Every test asserts `.edit()` or `.upload()` was NOT called under `dry_run=True`
- Commit: `d2d4c49`

## Verification

- 10 new tests: all pass
- 40 total tests (including existing): all pass
- `cd wiki && python -m pytest tests/ -v` returns 40 passed

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

1. **[08-01-01]** Mock site uses a `page_store` dict with `__getitem__` override pattern. This provides realistic page lookup behavior without complex mock setup.
2. **[08-01-02]** MediaWiki's trailing-whitespace-stripping behavior is replicated in mocks by calling `.rstrip()` on stored text, matching the `page.text().rstrip() == expected.rstrip()` comparison used in production code.

## Next Phase Readiness

Plan 08-01 complete. Ready for 08-02 (drift detection) and 08-03 (reliability/retry).
