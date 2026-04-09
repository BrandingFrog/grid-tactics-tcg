---
phase: 03-card-page-generator
plan: 03
subsystem: wiki-sync
tags: [sync-cli, card-upsert, art-upload, verification, idempotent]
completed: 2026-04-09
duration: ~10 min
requires: [03-01, 03-02]
provides: [sync_wiki.py CLI for full card sync pipeline]
affects: [04, 05, 08]
tech-stack:
  added: []
  patterns: [idempotent-upsert, rstrip-normalization, fileexists-no-change-handling]
key-files:
  created: [wiki/sync/sync_wiki.py]
  modified: []
decisions:
  - id: cross-link-common-rat
    summary: "Card:Rat cross-link target is actually Card:Common Rat (JSON name field)"
  - id: art-duplicate-unchanged
    summary: "MediaWiki fileexists-no-change on duplicate upload treated as 'unchanged' for idempotency"
metrics:
  tasks: 2
  commits: 1
---

# Phase 3 Plan 03: sync_wiki.py CLI Summary

CLI entry point that orchestrates card page upsert, art upload, and verification -- `python -m sync.sync_wiki --all-cards` syncs all 34 cards with art to the live Railway wiki in one command.

## What Was Built

### sync_wiki.py CLI (wiki/sync/sync_wiki.py)

Full-featured CLI with 6 modes:
- `--all-cards` — Upsert all 34 card pages + upload 15 art PNGs
- `--card CARD_ID` — Upsert a single card by card_id
- `--dry-run` — Show what would change without making edits (works with any mode)
- `--verify` — Check Category:Card count matches JSON count
- `--upload-art` — Upload art PNGs only (no page edits)
- `--verify-deep` — Full verification suite (category count, cross-links, SMW properties, art files)

### Core Functions
- `load_all_cards()` — Load and sort all card JSONs
- `upsert_card_page()` — Generate wikitext via `card_to_wikitext()`, rstrip-compare, create/update/skip
- `upload_card_art()` — Upload PNG with `ignore=True`, handle fileexists-no-change as unchanged
- `verify_card_count()` — Count Category:Card members vs expected
- `verify_deep()` — Cross-links (7 targets), SMW spot-checks (3 cards), art files (15 PNGs)

## Execution Results

### First Sync
- 33 cards created, 1 updated (Ratchanter from Phase 1)
- 15 art PNGs uploaded, 19 cards use CardBack.png fallback
- Category:Card count: 34 (matches JSON count)

### Idempotency Re-run
- 34 unchanged, 0 created, 0 updated
- Art: 15 unchanged (fileexists-no-change handled gracefully), 19 no-art

### Deep Verification
- Category:Card: 34 pages (expected 34) -- PASS
- Cross-links: 7/7 OK (Common Rat, 3 Diodebots, Pyre Archer, Grave Caller, Fallen Paladin)
- SMW properties: 3/3 spot-checks pass (Ratchanter Cost=4/Attack=15/HP=30, Counter Spell Cost=2, Fireball Cost=3)
- Art files: 15/15 present on wiki

## Decisions Made

1. **Card:Common Rat not Card:Rat** — The rat minion's JSON `name` field is "Common Rat", so cross-link targets resolve to `Card:Common Rat`. Updated verification targets accordingly.
2. **Art duplicate = unchanged** — MediaWiki raises `fileexists-no-change` on duplicate art uploads even with `ignore=True`. Treated as "unchanged" status for clean idempotency reporting.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Cross-link verification target Card:Rat -> Card:Common Rat**
- **Found during:** Task 2 preparation
- **Issue:** Plan listed "Card:Rat" as cross-link target but the card's actual name is "Common Rat"
- **Fix:** Updated `_verify_cross_links()` to check "Card:Common Rat"
- **Files modified:** wiki/sync/sync_wiki.py

**2. [Rule 1 - Bug] Art upload duplicate handling**
- **Found during:** Task 1 idempotency test
- **Issue:** Second sync run showed 15 art "errors" (fileexists-no-change exceptions)
- **Fix:** Detect fileexists-no-change in exception string, return "unchanged" status
- **Files modified:** wiki/sync/sync_wiki.py

## Commits

| Hash | Message |
|------|---------|
| 55839b1 | feat(wiki-03-03): build sync_wiki.py CLI with card upsert + art upload |

## Next Phase Readiness

Phase 3 is complete. All success criteria met:
- 34 card pages live on wiki with correct wikitext
- 15 art PNGs displayed, 19 show CardBack.png fallback
- Cross-links work (no red-links for synced cards)
- SMW properties populated and queryable
- Idempotent re-runs produce 0 edits

Phase 4 (Taxonomy Pages) can proceed -- element, tribe, and keyword pages can now use `#ask` queries against the 34 populated card pages.
