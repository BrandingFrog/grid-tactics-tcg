---
phase: 06-card-history-tracking
plan: 02
subsystem: wiki-sync
tags: [card-history, patch-sync, deprecated-cards, template-bootstrap]
dependency_graph:
  requires: [06-01, 05-02]
  provides: [card-history-in-sync-pipeline, deprecated-card-handling, template-bootstrap]
  affects: [07-01]
tech_stack:
  added: []
  patterns: [card-history-integration, template-bootstrap-in-patch-flow]
key_files:
  created: []
  modified:
    - wiki/sync/sync_patches.py
    - wiki/sync/sync_wiki.py
decisions:
  - id: 06-02-01
    summary: "Template bootstraps (Patch, DeprecatedCard, Card) run unconditionally before patch sync, not gated by dry-run"
  - id: 06-02-02
    summary: "Card history deduplication by version string prevents double-entries on re-run"
metrics:
  duration: 7m
  completed: 2026-04-09
---

# Phase 6 Plan 2: Wire Card History into Sync Pipeline Summary

Card history tracking and deprecated card handling integrated into patch sync pipeline with live template bootstrap on Railway wiki.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Integrate card history into patch sync pipeline | 3f29998 | sync_patches.py, sync_wiki.py |
| 2 | End-to-end verification against live wiki | (verification only) | - |

## What Was Built

### sync_patches.py (3 new functions)
- **update_card_histories(site, diff, repo_root, dry_run)**: Processes each CardChange in a PatchDiff -- adds history entries for added/changed cards, wraps removed cards with DeprecatedCard template.
- **_load_name_map_at_sha**: Builds card_id-to-name mapping from all card JSONs at a specific git commit.
- **_load_card_at_sha**: Loads a single card JSON by card_id at a specific commit for re-rendering.
- **sync_patch()** updated to call `update_card_histories()` after creating/updating the patch page.

### sync_wiki.py (2 new helpers)
- **_bootstrap_deprecated_template(site)**: Idempotent upsert of Template:DeprecatedCard from disk.
- **_bootstrap_card_template(site)**: Idempotent upsert of Template:Card from disk (ensures LastChangedPatch annotation is live).
- **--patch handler** updated to bootstrap all three templates (Patch, DeprecatedCard, Card) before syncing.

### Live Wiki State
- Template:DeprecatedCard created on Railway wiki.
- Template:Card updated with LastChangedPatch annotation on Railway wiki.
- All 34 card pages verified unchanged (backward compatible).
- Deep verification: 34 cards, 7 cross-links, 3 SMW spot-checks, 15 art files -- all passing.

## Deviations from Plan

None -- plan executed exactly as written.

## Decisions Made

1. **[06-02-01]** Template bootstraps run unconditionally before patch sync (not gated by --dry-run). Templates need to exist for sync to work.
2. **[06-02-02]** Card history entries are deduplicated by version string -- if a version already appears in the history, a new entry is not added. Prevents double-entries on re-run.

## Next Phase Readiness

Phase 6 is complete. The patch sync pipeline now:
1. Bootstraps all templates (Patch, DeprecatedCard, Card)
2. Creates/updates patch pages
3. Updates card history sections for affected cards
4. Handles card removal via DeprecatedCard wrapping

Phase 7 (Semantic Query Showcase & Homepage) can proceed -- all card pages have SMW properties, taxonomy pages exist, and patch infrastructure is complete.
