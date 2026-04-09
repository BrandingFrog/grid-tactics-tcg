---
phase: 09-launch-polish
plan: 03
subsystem: backup
tags: [mediawiki, backup, github-actions, xml-export]
dependency_graph:
  requires: [08-03]
  provides: [weekly-wiki-backup, xml-export-script]
  affects: []
tech_stack:
  added: []
  patterns: [mediawiki-xml-export, github-actions-artifacts]
key_files:
  created:
    - wiki/sync/backup.py
    - .github/workflows/wiki-backup.yml
  modified: []
decisions:
  - id: "09-03-01"
    summary: "XML export via MediaWiki API instead of mysqldump"
    reason: "Railway doesn't expose MariaDB port externally; API export is portable and importable via importDump.php"
metrics:
  duration: "3 min"
  completed: "2026-04-09"
---

# Phase 9 Plan 03: Weekly Wiki Backup Summary

XML export backup via MediaWiki API with weekly GitHub Actions scheduling and 90-day artifact retention.

## What Was Done

### Task 1: Create backup.py and GitHub Actions workflow

- Created `wiki/sync/backup.py` -- exports all wiki pages via `action=query&export=1` API
- Discovers pages from 7 categories (Card, Element, Tribe, Keyword, Rules, Patch, Deprecated) plus 6 special pages
- Produces timestamped XML file (`wiki_backup_YYYY-MM-DD.xml`) and JSON manifest with page titles and revision IDs
- Batches pages in groups of 25 for API efficiency
- CLI: `python -m sync.backup [--output-dir DIR]`
- Created `.github/workflows/wiki-backup.yml` -- weekly schedule (Sunday 3AM UTC) with manual trigger (`workflow_dispatch`)
- Uses same secrets as drift-check workflow (MW_API_URL, MW_BOT_USER, MW_BOT_PASS, MW_API_PATH)
- Artifacts retained for 90 days

### Task 2: Test backup and verify recoverability

- Ran backup locally against live Railway wiki
- Result: 96 pages exported, 135.6 KB XML file
- XML root element: `<mediawiki>` with export-0.11 namespace
- All 96 pages recoverable via `ET.findall('{ns}page')`
- JSON manifest confirms all 7 categories covered
- Cleaned up test output

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed export API response path**

- **Found during:** Task 2 (first test run)
- **Issue:** Used `exportnowrap=1` parameter which makes the API return raw XML that mwclient cannot parse (expects JSON wrapper)
- **Fix:** Removed `exportnowrap`, read XML from `result['query']['export']['*']` path
- **Files modified:** wiki/sync/backup.py
- **Commit:** 085c349

## Post-Plan Notes

- GitHub secrets (MW_API_URL, MW_BOT_USER, MW_BOT_PASS, MW_API_PATH) need to be configured in the repository for the workflow to run. These are the same secrets used by the drift-check workflow. Currently no secrets are configured.
- Once secrets are set, trigger manually via: `gh workflow run wiki-backup.yml`

## Commits

| Hash | Message |
|------|---------|
| 1fca8c8 | feat(wiki-09-03): backup script and weekly GitHub Actions workflow |
| 085c349 | fix(wiki-09-03): fix export API call to use correct response path |
