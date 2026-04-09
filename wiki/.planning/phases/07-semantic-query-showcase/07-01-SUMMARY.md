---
phase: 07-semantic-query-showcase
plan: 01
subsystem: wiki-navigation
tags: [mediawiki, main-page, navigation, homepage]
dependency_graph:
  requires: [phase-03, phase-04, phase-05, phase-06]
  provides: [main-page, homepage-sync]
  affects: [phase-07-02]
tech_stack:
  added: []
  patterns: [direct-page-upsert, rstrip-idempotency]
key_files:
  created:
    - wiki/sync/sync_homepage.py
  modified:
    - wiki/sync/sync_wiki.py
decisions:
  - id: "07-01-01"
    description: "Main Page uses direct upsert (not upsert_taxonomy_pages) since it's a single special page"
  - id: "07-01-02"
    description: "Main Page placed in Category:Rules to keep it discoverable via existing taxonomy"
metrics:
  duration: "2 min"
  completed: "2026-04-09"
---

# Phase 7 Plan 1: Main Page & Navigation Hub Summary

**One-liner:** Wiki Main Page with navigation links to all 7 elements, 14 tribes, 27 keywords, 6 rules pages, patch index, and card database -- live on Railway.

## What Was Done

### Task 1: Create sync_homepage.py with Main Page wikitext
- Created `wiki/sync/sync_homepage.py` with two functions:
  - `main_page_wikitext()` -- returns wikitext for Main Page with sections for Card Database, Elements, Tribes, Keywords, Rules, and Patch Notes
  - `sync_main_page(site, dry_run)` -- upserts Main Page with rstrip() idempotency pattern
- All 7 element links inline (Wood, Fire, Earth, Water, Metal, Dark, Light)
- All 6 rules pages linked (Grid Tactics TCG, 5x5 Board, Mana, React Window, Win Conditions, Turn Structure)
- Category links: Card, Element, Tribe, Keyword, Trigger Keyword, Mechanic Keyword
- Forward-link to Semantic:Showcase (Phase 7 Plan 2)
- Commit: `8c45f5a`

### Task 2: Wire --homepage flag into sync_wiki.py CLI and push to live wiki
- Added `--homepage` to the mutually exclusive CLI group in sync_wiki.py
- Pushed Main Page to live Railway wiki (status: "updated")
- Verified idempotency: dry-run reports "unchanged"
- Verified page content on live wiki: all expected links present (1034 chars)
- Commit: `4c1fcfc`

## Decisions Made

1. **Direct upsert for Main Page** -- Used direct `site.pages["Main Page"]` instead of `upsert_taxonomy_pages()` since Main Page is a single special page, not a batch of taxonomy pages.
2. **Category:Rules membership** -- Main Page is tagged with `[[Category:Rules]]` to keep it discoverable through existing taxonomy structure.

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

- `python -m sync.sync_wiki --homepage --dry-run` reports "unchanged" (idempotent)
- Live Main Page at Railway wiki contains all required links
- All 7 elements, 6 rules pages, category links, Patch:Index, and Semantic:Showcase verified

## Next Phase Readiness

Phase 7 Plan 2 (Semantic Query Showcase page) can proceed. The Main Page already links to `[[Semantic:Showcase]]` which Plan 2 will create.
