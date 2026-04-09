---
phase: 09-launch-polish
plan: 01
subsystem: wiki-polish
tags: [mobile-css, logo, favicon, search, mediawiki]
depends_on: []
provides: [mobile-responsive-css, site-logo, site-favicon, search-verification]
affects: []
tech_stack:
  added: [Pillow]
  patterns: [idempotent-css-append, marker-comment-guard]
key_files:
  created:
    - wiki/sync/sync_polish.py
  modified:
    - wiki/sync/sync_wiki.py
decisions:
  - id: 09-01-favicon-png
    description: "Use PNG instead of ICO for favicon upload (MediaWiki bans ICO filetype)"
  - id: 09-01-search-text
    description: "Use srwhat=text for keyword search (default search mode misses template params)"
metrics:
  duration: 6min
  completed: 2026-04-09
---

# Phase 9 Plan 1: Launch Polish Summary

Mobile CSS, logo/favicon branding, and search verification pushed to live Railway wiki.

## What Was Done

### Task 1: Create sync_polish.py (7 functions)

Created `wiki/sync/sync_polish.py` with:

1. **push_mobile_css()** -- Appends responsive CSS block to MediaWiki:Common.css with marker comment guard (`/* --- Grid Tactics Mobile --- */`) for idempotency. Media query at 480px handles card infobox full-width, SMW table horizontal scroll, sidebar hide, responsive images.

2. **generate_logo_png()** -- Pillow-based 135x135 dark background with "GT" white text and border. Falls back to minimal PNG if Pillow unavailable.

3. **generate_favicon_ico()** -- 32x32 ICO generation (kept for API compatibility).

4. **generate_favicon_png()** -- 32x32 PNG favicon (added after discovering MediaWiki bans ICO uploads).

5. **upload_logo()** -- Generates to temp file, uploads as File:Wiki.png via mwclient.

6. **upload_favicon()** -- Generates PNG to temp file, uploads as File:Favicon.png.

7. **configure_logo_and_favicon()** -- Pushes CSS logo override to Common.css and JS favicon injection to Common.js (both with marker guards).

8. **verify_search()** -- Uses MediaWiki API `action=query&list=search` for "Rat" and "Ranged" keyword searches.

### Task 2: CLI Integration and Live Execution

- Added `--polish` CLI flag to `sync_wiki.py` (runs all polish operations in sequence)
- Added `--verify-search` CLI flag (exits 0/1 based on search results)
- Executed against live Railway wiki -- all assets pushed successfully
- Verified idempotency: third run shows "unchanged" for all operations
- Search verification passes: Rat returns 5 results, Ranged returns 6 card pages

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Favicon ICO upload banned by MediaWiki**

- **Found during:** Task 2 (live execution)
- **Issue:** MediaWiki returned `filetype-banned` for `.ico` uploads. Permitted types: png, jpg, jpeg, gif, webp, svg.
- **Fix:** Added `generate_favicon_png()` function, changed `upload_favicon()` to upload PNG instead of ICO, updated JS injection to reference `Favicon.png`.
- **Files modified:** `wiki/sync/sync_polish.py`

**2. [Rule 3 - Blocking] Ranged keyword search returned 0 results**

- **Found during:** Task 2 (verify-search)
- **Issue:** Default MediaWiki search mode (title-based) did not find "Ranged" which appears in template params in page body text.
- **Fix:** Added `srwhat="text"` parameter to the Ranged search API call for full-text content search.
- **Files modified:** `wiki/sync/sync_polish.py`

## Commits

| Commit | Description |
|--------|------------|
| 24d7b8e | feat(wiki-09-01): create sync_polish.py with mobile CSS, logo/favicon, search verification |
| 37cd0a1 | feat(wiki-09-01): wire --polish and --verify-search CLI flags, execute against live wiki |

## Verification Results

- `--polish` succeeds with status output for each operation
- `--polish` second run shows "unchanged" for all operations (idempotent)
- `--verify-search` exits 0 (Rat: 5 results, Ranged: 6 results)
- MediaWiki:Common.css contains mobile responsive rules + logo CSS
- MediaWiki:Common.js contains favicon injection JS
- File:Wiki.png and File:Favicon.png uploaded to wiki
