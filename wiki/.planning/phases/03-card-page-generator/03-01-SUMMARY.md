---
phase: 03-card-page-generator
plan: 01
subsystem: wiki-sync
tags: [wikitext, card-generation, template-invocation, cross-links]
completed: 2026-04-09
duration: ~3 min
requires: [01-04]
provides: [sync_cards.py pure-function wikitext conversion]
affects: [03-02, 03-03]
tech-stack:
  added: []
  patterns: [pure-function data transformation, cross-link resolution via name_map]
key-files:
  created:
    - wiki/sync/sync_cards.py
    - wiki/tests/__init__.py
    - wiki/tests/test_sync_cards.py
  modified: []
decisions:
  - id: 03-01-D1
    description: "Keywords derived from JSON structure, never hard-coded per card"
  - id: 03-01-D2
    description: "Cross-links use [[Card:Display Name|Display Name]] format via name_map lookup"
  - id: 03-01-D3
    description: "React effects (react_effect field separate from effects array) are included in both keyword derivation and rules text"
  - id: 03-01-D4
    description: "VERSION.json read for patch field with fallback to 0.4.2"
metrics:
  tasks: 2/2
  tests: 30
  cards-covered: 34/34
---

# Phase 3 Plan 1: Card-to-Wikitext Conversion Summary

Pure-function card JSON to wikitext conversion with derived keywords, synthesized rules text, and cross-link wikilinks for all 34 cards.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create sync_cards.py with pure-function wikitext generation | 58b30d0 | wiki/sync/sync_cards.py |
| 2 | Unit tests for wikitext generation | 322b48f | wiki/tests/test_sync_cards.py, wiki/tests/__init__.py |

## What Was Built

### sync_cards.py (5 exported functions)

- **`build_card_name_map(cards_dir)`** - Reads all 34 card JSONs, returns `{card_id: display_name}` mapping for cross-link resolution
- **`derive_keywords(card)`** - Derives keywords from card JSON structure: React, Unique, Melee/Ranged, Tutor, Transform, Promote, Active, Conjure, Sacrifice, Summon, Death, Passive, Burn, Heal, Deal, Destroy, Negate, Leap, Rally, Deploy, Dark Matter
- **`build_rules_text(card, name_map)`** - Synthesizes human-readable rules from effects, activated abilities, transform options, tutor/promote targets, and react conditions with `[[Card:Name|Name]]` cross-links
- **`card_to_wikitext(card, name_map, art_exists)`** - Generates complete `{{Card ... }}` template invocation with correct field mapping, field omission for magic/react, and deckable handling
- **`get_version()`** - Reads VERSION.json for patch field

### Test Coverage (30 tests)

- 12 keyword derivation tests covering all card mechanics
- 9 rules text tests covering activated abilities, transforms, tutors, multi-effect, promote, react conditions, deploy, no-name-map fallback, empty effects
- 7 card_to_wikitext tests covering minion/magic/react types, art toggle, deckable, no-categories
- 2 build_card_name_map tests

## Decisions Made

1. **Keywords derived, not hard-coded** - Every keyword comes from inspecting JSON fields (card_type, range, effects, activated_ability, etc.)
2. **react_effect handled separately** - Cards like Dark Sentinel and Surgefed Sparkbot have a `react_effect` field separate from `effects[]` array; both are processed for keywords and rules
3. **Cross-links via name_map** - `_wikilink()` helper resolves card_id to `[[Card:Display Name|Display Name]]` via the name_map, with title-case fallback when name_map is unavailable

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

All prerequisites for 03-02 (CLI push) and 03-03 (verification) are satisfied:
- `card_to_wikitext()` is importable and produces valid Template:Card invocations
- All 34 cards convert without errors
- Cross-link cards produce wikilinks
- Magic/react cards correctly omit attack/hp/range
