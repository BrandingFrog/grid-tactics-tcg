---
phase: 06-card-history-tracking
plan: 01
subsystem: wiki-sync
tags: [card-history, deprecated-cards, wikitext, smw-properties]
dependency_graph:
  requires: [05-01, 05-02]
  provides: [card_history.py, DeprecatedCard.wiki, LastChangedPatch property]
  affects: [06-02]
tech_stack:
  added: []
  patterns: [pure-function-wikitext-builders, round-trip-parsing]
key_files:
  created:
    - wiki/sync/card_history.py
    - wiki/sync/templates/DeprecatedCard.wiki
  modified:
    - wiki/sync/templates/Card.wiki
    - wiki/sync/sync_cards.py
decisions:
  - id: 06-01-01
    summary: "History entries sorted newest-first by reverse lexicographic version string"
  - id: 06-01-02
    summary: "DeprecatedCard template keeps page in Category:Card AND adds Category:Deprecated"
  - id: 06-01-03
    summary: "LastChangedPatch is a new SMW property separate from FirstPatch"
metrics:
  duration: 2m
  completed: 2026-04-09
---

# Phase 6 Plan 1: Card History & Deprecated Card Building Blocks Summary

Pure-function card history section builder, deprecated card wikitext wrapper, and LastChangedPatch SMW property annotation for Template:Card.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create card_history.py module | fd44100 | wiki/sync/card_history.py |
| 2 | Update Card template + DeprecatedCard template | 1b95c96 | Card.wiki, DeprecatedCard.wiki, sync_cards.py |

## What Was Built

### card_history.py (3 pure functions)
- **build_history_section**: Converts list of history entry dicts into `== History ==` wikitext with `; [[Patch:X|X]] (date)` / `: description` format, newest-first.
- **build_deprecated_wikitext**: Wraps original card wikitext with `{{DeprecatedCard|patch=...}}` header and `[[Category:Deprecated]]` footer.
- **extract_history_section**: Parses existing card page wikitext to separate body from history entries. Enables round-trip: build -> extract -> build produces identical output.

### Template Updates
- **Card.wiki**: Added `LastChangedPatch` SMW property annotation (conditional on `last_changed_patch` parameter).
- **DeprecatedCard.wiki**: New template with red warning banner linking to removal patch. Keeps page in Category:Card for SMW queries.
- **sync_cards.py**: `card_to_wikitext()` accepts optional `last_changed_patch` parameter, backward-compatible.

## Deviations from Plan

None -- plan executed exactly as written.

## Decisions Made

1. **[06-01-01]** History entries sorted newest-first using reverse lexicographic sort on version string (consistent with Phase 5 convention).
2. **[06-01-02]** DeprecatedCard template adds both Category:Deprecated AND Category:Card so SMW queries still find deprecated cards.
3. **[06-01-03]** LastChangedPatch is a distinct SMW property from FirstPatch (patch parameter). FirstPatch records when card was introduced; LastChangedPatch tracks most recent modification.

## Next Phase Readiness

Plan 06-02 can now import `build_history_section`, `build_deprecated_wikitext`, and `extract_history_section` from `sync.card_history` to wire into the sync pipeline. The `card_to_wikitext` function is ready to accept `last_changed_patch` values from the caller.
