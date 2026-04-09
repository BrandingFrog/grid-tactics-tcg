---
phase: 07-semantic-query-showcase
plan: 02
subsystem: wiki-sync
tags: [smw, semantic-queries, showcase, wikitext]
dependency_graph:
  requires: [phase-04, phase-06]
  provides: [semantic-showcase-page, showcase-cli-flag]
  affects: [phase-09]
tech_stack:
  added: []
  patterns: [pure-function-wikitext-gen, rstrip-idempotency]
key_files:
  created:
    - wiki/sync/sync_showcase.py
  modified:
    - wiki/sync/sync_wiki.py
decisions:
  - id: "07-02-01"
    decision: "Showcase page uses Semantic:Showcase title (colon namespace) for consistency with SMW conventions"
    context: "Page lives outside Card:/Patch: namespace hierarchy but under Rules category"
metrics:
  duration: ~3 min
  completed: 2026-04-09
---

# Phase 7 Plan 2: Semantic:Showcase Page Summary

Showcase page with 7 live SMW queries demonstrating card-database exploration, pushed to Railway wiki via --showcase CLI flag.

## What Was Done

### Task 1: Create sync_showcase.py with 7 semantic queries
- Created `wiki/sync/sync_showcase.py` with two exports:
  - `showcase_page_wikitext()` -- pure function returning wikitext with 7 `#ask` queries
  - `sync_showcase_page(site, dry_run)` -- upsert with rstrip() idempotency
- Queries cover: fire minions under 3 mana, high-attack by tribe, recent patches, tanky minions (HP >= 30), react cards, dark element cards, metal robots
- Includes "Writing Your Own Queries" section with property reference and template skeleton

### Task 2: Wire --showcase flag and push to live wiki
- Added `--showcase` to mutually exclusive CLI group in `sync_wiki.py`
- Pushed Semantic:Showcase to live Railway wiki (created successfully)
- Dry-run confirms idempotency (reports "unchanged")

## Commits

| Commit | Description |
|--------|-------------|
| 3efd019 | feat(wiki-07-02): create sync_showcase.py with 7 semantic queries |
| 0d23a71 | feat(wiki-07-02): wire --showcase flag and push Semantic:Showcase live |

## Deviations from Plan

**Note:** The --showcase CLI flag addition to sync_wiki.py was captured in the 07-01 commit (4c1fcfc) due to parallel wave execution. Both plans modified sync_wiki.py concurrently, and 07-01's commit included the --showcase changes that were already in the working tree. The 0d23a71 commit captured only the VERSION.json bump. All code is correctly committed and live.

## Verification

- `python -m sync.sync_wiki --showcase --dry-run` reports "unchanged"
- Semantic:Showcase page live at https://mediawiki-production-7169.up.railway.app/wiki/Semantic:Showcase
- All 7 queries present in wikitext (verified via assertion)
