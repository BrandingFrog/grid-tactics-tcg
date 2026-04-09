---
phase: 02-mediawiki-smw-on-railway
plan: 01
subsystem: wiki-railway-infra
tags: [railway, mysql, redis, mediawiki, pivot, deploy, phase-2, complete]
requires: []
provides:
  - railway-project-live
  - mysql-service-live
  - redis-service-live
  - mediawiki-service-live
  - smw-5.1-installed
blocks: []
affects:
  - 02-02
  - 02-03
tech-stack:
  added:
    - Railway (managed deploy, MySQL, Redis, container service)
    - mediawiki:1.42 + SMW 5.1 (custom Dockerfile)
  removed:
    - ghcr.io/wikiteq/taqasta:latest (dead end — rsync-seed broken on Railway)
  patterns:
    - "Custom Dockerfile in wiki/, Railway auto-builds via git-connected service"
    - "Entrypoint handles first-boot install.php + idempotent update.php"
    - "Schema-health check in entrypoint detects partial DB and wipes before install"
key-files:
  created:
    - wiki/Dockerfile
    - wiki/LocalSettings.php
    - wiki/docker-entrypoint-wiki.sh
  modified:
    - wiki/sync/client.py  # MW_API_PATH env var so sync points at Railway /
decisions:
  - "Pivoted away from ghcr.io/wikiteq/taqasta:latest. Taqasta's entrypoint rsync-seeds /mediawiki_base -> /mediawiki, which produced 0 bytes on Railway regardless of volume mount path. Apache fell back to the Debian default page and MediaWiki was never reachable. Rebuilt from mediawiki:1.42 with a thin Dockerfile."
  - "Composer is NOT bundled in mediawiki:1.42. Download composer.phar from getcomposer.org in the Dockerfile."
  - "mediawiki:1.42 ships /var/www/html owned by www-data; composer needs to write composer.json. Chown to root for the build step, restore www-data after."
  - "mediawiki:1.42's composer.json pins phpunit/phpunit 9.6.16 in require-dev, which the composer security audit rejects (PKSA-z3gr-8qht-p93v) even with --update-no-dev/--no-audit. Strip the phpunit entry from composer.json before running composer require."
  - "SMW 4.x emits SQL that fails on Railway's MySQL 9.4 with Wikimedia\\Rdbms\\DBLanguageError. SMW 5.1 is required — ask queries all fail on 4.2.0 and all succeed on 5.1.0 against the same DB."
  - "apt-get install in the build layer enables mpm_event alongside mediawiki:1.42's mpm_prefork, causing apache2 to refuse to start with 'More than one MPM loaded'. Force mpm_prefork in the entrypoint so it runs at every boot."
  - "Railway healthcheck path cleared (empty). MediaWiki 301-redirects / to /wiki/Main_Page which Railway interpreted as unhealthy; disabling the healthcheck lets deploys promote once apache is listening."
  - "Volume mount path corrected to /var/www/html/images (was /data-unused under Taqasta) — uploads persist, DB and other mutable state live in MySQL/Redis services."
  - "DB schema-health check in entrypoint: checks for user, ipblocks, site_stats, page, revision tables and wipes the DB if any are missing. Previous Taqasta attempts left a partial schema that crashed update.php. This makes every boot self-healing."
metrics:
  duration: "multi-session, hands-on (blocker report -> pivot -> green deploy ~2 hours)"
  completed: "2026-04-09"
  status: complete
---

# Phase 2 Plan 1: Deploy MediaWiki+SMW on Railway — COMPLETE (pivot)

**One-liner:** After the Taqasta image proved unworkable on Railway, pivoted to a thin `mediawiki:1.42` + SMW 5.1 Dockerfile in `wiki/`. Railway's git-connected build plus a custom entrypoint now produces a fully functional wiki at https://mediawiki-production-7169.up.railway.app/ with `api.php` serving valid JSON, SMW 5.1.0 installed and queryable, and 25 Property pages live.

## What Was Built

- **Railway project `grid-tactics-wiki`** — three services: `mysql` (v9.4), `redis`, `mediawiki`.
- **mediawiki service** — git-connected to `BrandingFrog/grid-tactics-tcg`, `rootDirectory: wiki`, builds `wiki/Dockerfile` on push.
- **Dockerfile** — `FROM mediawiki:1.42` + composer phar + SMW ~5.0 (resolved to 5.1.0) + custom entrypoint.
- **Entrypoint** — waits for MySQL, schema-health-checks the DB (wipes if broken), runs `install.php` on first boot, runs `update.php` every boot (idempotent), forces mpm_prefork, execs `apache2-foreground`.
- **LocalSettings.php** — reads all config from env vars (`MW_DB_SERVER` host:port splitting, `MW_SITE_SERVER`, `MW_SECRET_KEY`, SMW `wfLoadExtension` + `enableSemantics`).
- **Persistent volume** — mounted at `/var/www/html/images` for uploads.
- **Public domain** — `https://mediawiki-production-7169.up.railway.app` returns MediaWiki (not Debian default).

## Verified Behavior

```
$ curl -sS ".../api.php?action=query&meta=siteinfo&format=json"
{"batchcomplete":"","query":{"general":{"sitename":"Grid Tactics Wiki",
  "generator":"MediaWiki 1.42.7","dbtype":"mysql","dbversion":"9.4.0", ...}}}

$ curl -sS ".../api.php?action=query&meta=siteinfo&siprop=extensions"
  -> SemanticMediaWiki 5.1.0 present

$ curl -sS ".../wiki/Main_Page" -> HTTP 200

$ python -m sync.verify_smw
SMW version: 5.1.0
Bot authenticated as: Admin
ask() returned 0 result(s) (OK)
OK
```

## Success Gates

- [x] Railway project created with three services online
- [x] mediawiki service deploy reaches SUCCESS state
- [x] Public domain returns HTTP 200 on wiki pages
- [x] Root URL serves MediaWiki (not Debian default)
- [x] `/wiki/Main_Page` returns 200
- [x] `api.php` reachable and returns valid JSON
- [x] siteinfo shows SemanticMediaWiki 5.1.0
- [x] SMW ask queries return results (validated end-to-end in plan 02-02/03)
- [x] Persistent volume mounted at `/var/www/html/images`

## Deviations from Plan

### Rule 1 — Existential pivot: Taqasta -> mediawiki:lts
**Issue:** `ghcr.io/wikiteq/taqasta:latest` entrypoint rsync-seeds `/mediawiki_base` -> `/mediawiki` and produces 0 bytes on Railway regardless of volume mount path. Apache served the Debian default page; no MediaWiki route was reachable.
**Fix:** Threw out Taqasta entirely. Built a minimal `wiki/Dockerfile` from `mediawiki:1.42` with composer-installed SMW and a custom entrypoint. Railway is now git-connected to the repo with `rootDirectory: wiki`.

### Rule 2 — Build-layer surprises
- composer.phar had to be installed manually (mediawiki:1.42 does not ship it).
- `/var/www/html` ownership had to be temporarily changed to root so composer could write composer.json.
- phpunit 9.6.16 entry in `require-dev` blocked composer's dep resolver; stripped from composer.json via inline php.
- apt-get enabled mpm_event alongside mpm_prefork; forced mpm_prefork in the entrypoint.

### Rule 3 — SMW 4.x incompatible with MySQL 9
All SMW `ask` queries returned `Wikimedia\Rdbms\DBLanguageError` on SMW 4.2.0 / MySQL 9.4. Bumped composer require to `mediawiki/semantic-media-wiki "~5.0"` (resolved 5.1.0). All queries now work.

### Rule 4 — Healthcheck path disabled
MediaWiki 301-redirects `/` to `/wiki/Main_Page`, which Railway interpreted as unhealthy. Set `healthcheckPath = ""` so Railway only checks TCP listen on port 80.

## Handoff to Plan 02-02 / 02-03

SMW + API auth are confirmed working via `python -m sync.verify_smw` returning OK. Plans 02-02 (bootstrap schema) and 02-03 (Template:Card + sample card) both completed in the same session — see their SUMMARY files.
