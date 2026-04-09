---
phase: 04-taxonomy-pages
plan: 01
subsystem: wiki-sync
tags: [mediawiki, smw, taxonomy, elements, tribes]
dependency_graph:
  requires: [03-03]
  provides: [sync_taxonomy.py, taxonomy CLI flag, 21 wiki pages]
  affects: [04-02]
tech_stack:
  added: []
  patterns: [taxonomy page generator, reusable upsert_taxonomy_pages]
key_files:
  created:
    - wiki/sync/sync_taxonomy.py
  modified:
    - wiki/sync/sync_wiki.py
decisions:
  - id: 04-01-01
    description: "Element page titles are bare names (Fire, Wood) not namespaced (Element:Fire)"
  - id: 04-01-02
    description: "Tribe page titles are bare names (Rat, Knight) matching SMW property values"
  - id: 04-01-03
    description: "Mage/Rat tribe page created with slash in title (valid MediaWiki page name)"
metrics:
  duration: ~3 min
  completed: 2026-04-09
---

# Phase 4 Plan 01: Element & Tribe Taxonomy Pages Summary

**One-liner:** 21 taxonomy pages (7 elements + 14 tribes) with SMW broadtable ask queries, idempotent sync via reusable sync_taxonomy.py module.

## What Was Done

### Task 1: Create sync_taxonomy.py
Created `wiki/sync/sync_taxonomy.py` with:
- `scan_elements()` / `scan_tribes()` - extract unique values from card JSONs
- `element_page_wikitext()` / `tribe_page_wikitext()` - pure-function wikitext generators with `{{#ask:}}` broadtable queries
- `upsert_taxonomy_pages()` - generic page upsert with `rstrip()` idempotency
- `sync_elements()` / `sync_tribes()` - orchestration functions combining scan + generate + upsert

### Task 2: CLI flag + live wiki sync
Extended `sync_wiki.py` with `--taxonomy` flag. Synced 21 pages to live wiki:
- 7 element pages: Dark, Earth, Fire, Light, Metal, Water, Wood
- 14 tribe pages: Archer, Assassin, Cleric, Dark Mage, Dragon, Golem, Imp, Insect, Knight, Mage/Rat, Paladin, Rat, Robot, Undead

Inline verification confirmed:
- Category:Element: 7 members
- Category:Tribe: 14 members
- Fire element ask query: 6 cards (Emberplague Rat, Fire Imp, Fireball, Flame Wyrm, Inferno, Pyre Archer)
- Rat tribe ask query: 4 cards (Common Rat, Emberplague Rat, Giant Rat, Rathopper)
- Idempotent re-run: all 21 pages unchanged

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

| ID | Decision | Rationale |
|---|---|---|
| 04-01-01 | Element pages use bare names (Fire, not Element:Fire) | Matches plan spec; keeps titles clean for cross-linking |
| 04-01-02 | Tribe pages use bare names matching SMW property values | Consistent with element naming; SMW property values resolve correctly |
| 04-01-03 | Mage/Rat tribe page works with slash in title | MediaWiki treats slashes as subpages but page created successfully |

## Commits

| Hash | Message |
|---|---|
| 1b88e12 | feat(wiki-04-01): create sync_taxonomy.py with element and tribe page generators |
| c9cbe26 | feat(wiki-04-01): add --taxonomy CLI flag and upsert 21 taxonomy pages |

## Next Phase Readiness

- `sync_taxonomy.py` is designed for reuse by Plan 02 (keywords and rules pages)
- `upsert_taxonomy_pages()` is a generic page upsert function that any future taxonomy generator can use
- No blockers for Plan 02
