---
phase: 08-idempotency-drift-reliability
plan: 02
subsystem: sync-reliability
tags: [drift-detection, resume-manifest, cli, difflib]
dependency_graph:
  requires: []
  provides: [check_drift.py, resume-manifest]
  affects: [09-ci-automation]
tech_stack:
  added: []
  patterns: [resume-manifest-on-failure, unified-diff-reporting]
key_files:
  created:
    - wiki/sync/check_drift.py
  modified:
    - wiki/sync/sync_wiki.py
    - wiki/.gitignore
decisions:
  - id: "08-02-01"
    description: "DriftReport dataclass uses drift_type enum strings (content_mismatch, missing_page, extra_page) rather than booleans"
  - id: "08-02-02"
    description: "Resume manifest uses .sync_resume.json in wiki/ root, gitignored, deleted on successful completion"
  - id: "08-02-03"
    description: "Batch-level try/except catches Exception but not KeyboardInterrupt; per-card try/except stays as-is"
metrics:
  duration: "3 min"
  completed: "2026-04-09"
---

# Phase 8 Plan 02: Drift Detection & Resume Manifest Summary

**One-liner:** check_drift.py CLI compares live wiki pages against JSON source with unified diffs; sync_wiki.py writes .sync_resume.json on batch failure for automatic resume

## What Was Done

### Task 1: check_drift.py — drift detection CLI
Created `wiki/sync/check_drift.py` as a standalone module that compares live wiki content against expected wikitext computed from JSON source files.

- `DriftReport` dataclass with `page_title`, `drift_type`, and `details` fields
- `check_drift()` function checks card pages, taxonomy (elements/tribes/keywords/rules), Main Page, and Semantic:Showcase
- CLI with `--cards-only` flag for fast CI checks and `--verbose` flag for unified diff output
- Exit codes: 0 (clean), 1 (drift found), 2 (connection error)
- Uses `difflib.unified_diff` for details, capped at 20 lines per page

### Task 2: Resume manifest in sync_wiki.py
Added resume-on-failure logic to the `--all-cards` path.

- On batch-level exception: writes `.sync_resume.json` with completed/remaining card IDs and timestamps
- On restart: reads manifest, filters card list to remaining only, prints resume status
- On success: deletes manifest automatically
- `--no-resume` flag to ignore manifest and force full sync
- `.sync_resume.json` added to `wiki/.gitignore`

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | `2f78f49` | create check_drift.py drift detection CLI |
| 2 | `6321882` | add resume manifest to sync_wiki.py --all-cards |

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

1. `from sync.check_drift import check_drift, DriftReport` -- OK
2. `python -m sync.check_drift --help` -- shows usage with --cards-only and --verbose
3. `python -m sync.sync_wiki --all-cards --help` -- shows --no-resume flag
4. `pytest tests/ -v` -- 40 passed, 0 failed
