---
phase: 03-card-page-generator
plan: 02
subsystem: wiki-sync
tags: [mediawiki, template, category, file-upload, placeholder]
dependency_graph:
  requires: [02-03]
  provides: [singular-category-card, cardback-placeholder, upload-capability]
  affects: [03-03]
tech_stack:
  added: []
  patterns: [null-edit-for-template-recategorization]
key_files:
  created: []
  modified:
    - wiki/sync/templates/Card.wiki
    - wiki/sync/create_sample_card.py
decisions:
  - id: 03-02-01
    description: "CardBack.png is a solid #1a1a1a (280x400) dark gray PNG matching the card template background color"
  - id: 03-02-02
    description: "SMW ask results on Railway mediawiki:1.42 return OrderedDict values (not plain numbers) -- normalized with _smw_val() helper"
metrics:
  duration: 2m
  completed: 2026-04-09
---

# Phase 3 Plan 02: Template Category Fix + Placeholder Art Summary

JWT auth with refresh rotation using jose library -- Fixed Template:Card category from plural to singular, uploaded CardBack.png placeholder, confirmed file upload capability on Railway wiki.

## One-liner

Template:Card category fixed to singular `[[Category:Card]]`, CardBack.png (280x400 dark gray) uploaded as art fallback, file upload confirmed working with Admin credentials on Railway.

## What Was Done

### Task 1: Fix Template:Card category + upload placeholder art

1. **Category fix**: Changed `[[Category:Cards]]` to `[[Category:Card]]` in `wiki/sync/templates/Card.wiki` (line 66). Pushed to live wiki via `bootstrap_template.py`.

2. **Upload capability verified**: Tested `site.upload()` with a 1x1 test PNG -- succeeded, then cleaned up the test file. Admin account has full upload permissions on Railway wiki.

3. **CardBack.png uploaded**: Generated a 280x400 dark gray (#1a1a1a) PNG using Pillow and uploaded as `File:CardBack.png`. Accessible at `https://mediawiki-production-7169.up.railway.app/images/f/fa/CardBack.png`.

4. **Card:Ratchanter validated**: After template update, performed purge + null edit to force re-categorization. Card:Ratchanter now appears in `Category:Card` (singular). SMW ask query returns correct Cost=4, HP=30.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SMW ask result format changed between Taqasta and Railway mediawiki:1.42**

- **Found during:** Task 1, Step 4 (verification)
- **Issue:** `create_sample_card.py` called `float(cost_vals[0])` but SMW on Railway returns `OrderedDict({'fulltext': '4', ...})` instead of plain `4`.
- **Fix:** Added `_smw_val()` helper that extracts `fulltext` from OrderedDict values before comparison.
- **Files modified:** `wiki/sync/create_sample_card.py`
- **Commit:** 656af86

**2. [Rule 3 - Blocking] Template change did not auto-recategorize existing pages**

- **Found during:** Task 1, Step 4 (verification)
- **Issue:** After updating Template:Card, Card:Ratchanter still appeared only in `Category:Cards` (plural). MediaWiki's job queue for template-dependent page refreshes was not processing fast enough.
- **Fix:** Performed API purge + null edit on Card:Ratchanter to force immediate re-render with updated template. Card now correctly appears in `Category:Card`.
- **Not committed as separate change** -- this was a runtime wiki action, not a code change.

## Commits

| Hash | Message |
|------|---------|
| 656af86 | feat(wiki-03-02): fix Template:Card category + upload CardBack.png placeholder |

## Verification Results

| Check | Result |
|-------|--------|
| Template:Card contains `[[Category:Card]]` (singular) | PASS |
| `File:CardBack.png` exists on wiki | PASS |
| `site.upload()` works with Admin credentials | PASS |
| Card:Ratchanter in Category:Card after re-sync | PASS |
| SMW ask returns correct Cost/HP values | PASS |

## Next Phase Readiness

- **Plan 03 unblocked**: File upload capability confirmed. Art PNGs can be uploaded in Plan 03.
- **Null edit pattern**: Plan 03's card sync should include a purge/null-edit step after template changes to ensure categories update immediately.
- **SMW value format**: Any code reading SMW ask results must handle OrderedDict values (use `_smw_val()` pattern or equivalent).
