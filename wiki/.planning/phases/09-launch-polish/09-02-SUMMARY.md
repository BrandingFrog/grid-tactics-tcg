---
phase: 09-launch-polish
plan: 02
subsystem: wiki-sync
tags: [deck-guide, archetypes, mediawiki, wikitext]
dependency_graph:
  requires: [phase-01, phase-03, phase-04]
  provides: [deck-building-guide-page, deckguide-cli-flag]
  affects: []
tech_stack:
  added: []
  patterns: [auto-generated-sections, element-archetype-listing]
key_files:
  created:
    - wiki/sync/sync_deckguide.py
  modified:
    - wiki/sync/sync_wiki.py
    - wiki/sync/sync_homepage.py
decisions:
  - id: "09-02-01"
    description: "Element flavor text derived from element names (Fire=aggressive, Dark=sacrifice/drain, etc.)"
  - id: "09-02-02"
    description: "Tribe synergies section only shows tribes with 3+ cards to avoid noise"
metrics:
  duration: "~2 min"
  completed: "2026-04-09"
---

# Phase 09 Plan 02: Deck Building Guide Summary

Deck Building Guide wiki page with static strategy content and auto-generated element/tribe archetype listings from card JSON data.

## What Was Done

### Task 1: Create sync_deckguide.py
- Created `wiki/sync/sync_deckguide.py` with two public functions:
  - `generate_deckguide_wikitext(cards_dir)` -- pure function generating full page wikitext
  - `sync_deckguide(site, cards_dir, dry_run)` -- idempotent upsert to wiki
- Static sections: Basic Principles (mana curve, element synergy, tribe synergy), Strategy Tips (placement, react cards, sacrifice wins), Key Mechanics (links to rules pages)
- Auto-generated section: 7 element archetypes with card counts and `{{#ask:}}` queries, tribe synergies for tribes with 3+ cards (Rat, Robot, Undead, Golem)
- Commit: `31cbaa6`

### Task 2: Wire CLI, push to wiki, add Main Page link
- Added `--deckguide` flag to `sync_wiki.py` CLI (mutually exclusive group)
- Added "Deck Building Guide -- Archetypes and strategy" link to Main Page Rules section
- Pushed both pages to live Railway wiki
- Verified idempotency: second run returns "unchanged"
- Commit: `67e8ad5`

## Decisions Made

1. **Element flavor text** -- Each element gets a one-line thematic description (Fire=aggressive/damage, Water=control/disruption, Earth=defensive/high-HP, etc.)
2. **Tribe threshold** -- Only tribes with 3+ cards appear in the Tribe Synergies subsection to keep the guide focused

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

- `generate_deckguide_wikitext()` produces 3369 chars with AUTO-ARCHETYPES markers and Category:Rules
- Live wiki page created successfully
- Main Page updated with guide link
- Second sync run returns "unchanged" (idempotent)
- Dry-run mode works correctly
