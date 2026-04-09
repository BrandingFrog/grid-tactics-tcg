---
phase: 04-taxonomy-pages
plan: 02
subsystem: wiki-sync
tags: [mediawiki, smw, taxonomy, keywords, glossary, rules]
dependency_graph:
  requires: [04-01]
  provides: [keyword pages, rules pages, verify_taxonomy, --verify-taxonomy CLI]
  affects: [07-01]
tech_stack:
  added: []
  patterns: [glossary markdown parsing, rules page content dict]
key_files:
  created: []
  modified:
    - wiki/sync/sync_taxonomy.py
    - wiki/sync/sync_wiki.py
decisions:
  - id: 04-02-01
    description: "27 keywords parsed from GLOSSARY.md (7 trigger + 20 mechanic), not 28 as estimated"
  - id: 04-02-02
    description: "Keyword pages use bare names (Summon, Range X) matching SMW property values"
  - id: 04-02-03
    description: "Rules pages use descriptive titles (Grid Tactics TCG, 5x5 Board, Mana, React Window, Win Conditions, Turn Structure)"
metrics:
  duration: ~6 min
  completed: 2026-04-09
---

# Phase 4 Plan 02: Keyword & Rules Pages Summary

**One-liner:** 27 keyword pages from GLOSSARY.md + 6 conceptual rules pages with ManuallyMaintained markers, full 5-group verification suite passing on live wiki.

## What Was Done

### Task 1: Add keyword and rules page generators
Extended `wiki/sync/sync_taxonomy.py` with:
- `parse_glossary()` -- parses data/GLOSSARY.md markdown table rows into keyword/description/category dicts
- `keyword_page_wikitext()` -- generates wikitext with SMW `{{#ask:}}` query listing cards with each keyword
- `RULES_PAGES` dict -- 6 substantive conceptual pages with real multi-paragraph content
- `sync_keywords()` / `sync_rules_pages()` -- orchestration functions using existing `upsert_taxonomy_pages()`
- `verify_taxonomy()` -- comprehensive 5-group verification function

Updated `wiki/sync/sync_wiki.py`:
- `--taxonomy` now syncs all 4 types: elements (7), tribes (14), keywords (27), rules (6)
- Added `--verify-taxonomy` flag for standalone verification

Synced 33 new pages to live wiki (27 keywords + 6 rules). All 54 taxonomy pages confirmed.

### Task 2: Full verification
Ran `--verify-taxonomy` with all 5 check groups passing:
1. Category counts: Element(7), Tribe(14), Keyword(27), Rules(6)
2. Fire element spot check: expected 6, got 6
3. Rat tribe spot check: expected 4, got 4
4. Keyword content check: Summon, React, Burn descriptions match glossary
5. Rules pages check: 6/6 pages with ManuallyMaintained marker

Idempotency confirmed: `--taxonomy --dry-run` reports all 54 pages unchanged.

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

| ID | Decision | Rationale |
|---|---|---|
| 04-02-01 | 27 keywords (not ~28 estimated) | Glossary has exactly 7 triggers + 20 mechanics = 27 |
| 04-02-02 | Keyword page titles are bare names | Consistent with element/tribe naming from 04-01 |
| 04-02-03 | Rules page titles are descriptive | "Grid Tactics TCG", "5x5 Board" etc. for natural linking |

## Commits

| Hash | Message |
|---|---|
| c44857c | feat(wiki-04-02): add keyword and rules page generators to sync_taxonomy.py |

## Next Phase Readiness

- All Phase 4 taxonomy pages complete: 7 elements + 14 tribes + 27 keywords + 6 rules = 54 pages
- `verify_taxonomy()` provides a comprehensive gate for future regressions
- Rules pages marked ManuallyMaintained -- won't be overwritten by automated sync
- Phase 7 (Semantic Query Showcase) can build on keyword/element SMW queries
