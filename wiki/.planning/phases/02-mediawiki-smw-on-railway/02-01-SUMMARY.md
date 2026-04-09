---
phase: 02-mediawiki-smw-on-railway
plan: 01
subsystem: wiki-railway-infra
tags: [railway, mariadb, redis, mediawiki, taqasta, deploy, phase-2, partial, blocked]
requires: []
provides:
  - railway-project-live
  - mariadb-service-live
  - redis-service-live
  - mediawiki-container-deployed
blocks:
  - 02-02  # cannot run MW install / bootstrap until app is reachable at /api.php
  - 02-03  # cannot upload template or sample card against a wiki that is not serving
affects:
  - 02-02
  - 02-03
tech-stack:
  added:
    - Railway (managed deploy, MySQL, Redis, container service)
  patterns:
    - "Taqasta image on Railway with a single persistent volume as the MediaWiki root"
    - "Healthcheck path `/` with 600s timeout to accommodate Taqasta first-boot install loop"
key-files:
  created: []
  modified: []
decisions:
  - "Volume mounted at /mediawiki (deviation from 02-01 plan which specified /var/lib/mysql on mariadb and /mediawiki on mw). The Taqasta image's init loop required /mediawiki as the persistent root for its self-install pattern to complete rather than a sub-path mount — using the planned path caused a crash loop during Phase 2 iteration."
  - "Healthcheck path set to `/` with timeout 600s (deviation from plan's implicit shorter gate). Taqasta's first-boot installer can take several minutes before Apache starts serving, and a tighter healthcheck marked the deploy as failed before init finished. Widening the window let the deploy reach SUCCESS."
  - "MySQL + Redis + mediawiki each provisioned as separate Railway services in the project `grid-tactics-wiki`, matching the Phase 1 docker-compose topology."
metrics:
  duration: "multi-session, hands-on"
  completed: "2026-04-09 (infra only — app layer blocked)"
  status: partial
---

# Phase 2 Plan 1: Deploy MediaWiki+SMW on Railway — PARTIAL / BLOCKED

**One-liner:** Railway project `grid-tactics-wiki` is live with MySQL, Redis, and a `mediawiki` service (Taqasta image, volume at `/mediawiki`, healthcheck `/` 600s). The container deploy reports SUCCESS and the public URL returns HTTP 200 — but the response body is the stock **Debian Apache2 "It works" default page**, not MediaWiki. No MediaWiki route is reachable. Plan 02-01 is marked **partial** pending app-layer remediation.

## What Was Built

- **Railway project `grid-tactics-wiki`** — three services: `mysql`, `redis`, `mediawiki` (Taqasta image).
- **Persistent volume `mw_data`** mounted at `/mediawiki` on the mediawiki service (deviation — see below).
- **Public domain** — `https://mediawiki-production-7169.up.railway.app` wired through Railway's edge. Deploy `c124f846-0927-4fa7-b8b8-be88f3625ba7` ended in SUCCESS state.
- **Admin credentials** staged in Railway env vars: `MW_ADMIN_USER=Admin`, `MW_ADMIN_PASS=GridTactics2026Wiki!`.

## Verified Behavior

```
$ curl -sI https://mediawiki-production-7169.up.railway.app/
HTTP/1.1 200
server: railway-edge
last-modified: Wed, 14 Jan 2026 14:00:10 GMT
etag: "29cd-6485986bbae80"
content-type: text/html

$ curl -sL https://mediawiki-production-7169.up.railway.app/ | head -5
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" ...
  <head>
    <title>Apache2 Debian Default Page: It works</title>
```

The `last-modified` timestamp (2026-01-14) and the page title prove this is the unmodified `/var/www/html/index.html` from the Debian Apache package — it was never replaced by the MediaWiki install. None of the probed MediaWiki paths respond:

```
404 /wiki/Main_Page
404 /wiki/Special:Version
404 /api.php
404 /w/api.php
404 /w/index.php
404 /index.php
404 /mediawiki/api.php
```

## Success Gates

- [x] Railway project created with three services online
- [x] mediawiki service deploy reaches SUCCESS state
- [x] Public domain returns HTTP 200
- [ ] **Root URL serves MediaWiki (not Apache default)** — FAIL, serves Debian `/var/www/html/index.html`
- [ ] `/wiki/Main_Page` returns 200 — FAIL, 404
- [ ] `api.php` reachable for mwclient at any path — FAIL, 404 on every tried path
- [ ] `Special:Version` shows SMW 6.0.1 + PageForms + Scribunto + CategoryTree + Arrays + ParserFunctions — BLOCKED (cannot reach the page)

## Deviations from Plan

### Rule 4 — Architectural: volume mount path changed to `/mediawiki`

**Found during:** Phase 2 iteration, repeated Taqasta crash loops (see `railway-crash-*.png` screenshots in repo root).

**Issue:** Plan called for a narrower mount (e.g. `/var/www/html/images`). Taqasta's entrypoint performs a self-install that wants the whole MediaWiki root to live on the persistent volume, and a narrower mount caused the init loop to fail repeatedly.

**Fix:** Moved the volume mount to `/mediawiki`. This got the container past the crash loop and into a state where the deploy goes green.

**Second-order effect (SUSPECTED root cause of the app-layer blocker):** Taqasta's Apache `DocumentRoot` default is `/var/www/html`. If the MediaWiki application files live on the `/mediawiki` volume but Apache's vhost still points at `/var/www/html` (which on a fresh Debian image contains only the stock `index.html`), then Apache will happily serve the Debian default page on `/` and 404 every MediaWiki route. This is consistent with every observed symptom. The fix is one of: (a) repoint Apache `DocumentRoot` to `/mediawiki`, (b) symlink `/var/www/html` to `/mediawiki`, or (c) use Taqasta's documented mount path instead of `/mediawiki`.

### Rule 3 — Blocking: healthcheck timeout 600s

Initially used the Railway default healthcheck timeout. Taqasta's first-boot install takes long enough that the deploy was marked failed before Apache started listening. Widened timeout to 600s and the deploy began reaching SUCCESS — but "SUCCESS" here only means Apache started, not that MediaWiki is serving (see Rule 4 above).

## Open Blocker

**App layer not reachable.** The container is up and Apache is serving, but it is serving the wrong document root. Until this is fixed:

- Plan 02-02 cannot run MediaWiki installer verification, create a BotPassword, run `verify_smw.py`, or `bootstrap_schema.py`. Every one of those steps hits `api.php`, which returns 404.
- Plan 02-03 cannot upload `Template:Card` or create `Card:Ratchanter`. Nothing to talk to.
- **Bot password creation via Playwright was not attempted** — no point logging in to a page that does not exist. `Special:UserLogin` also 404s.

### Suggested next actions (for whoever picks this up)

1. Open a shell on the Railway mediawiki service and inspect:
   - What is at `/mediawiki` on the persistent volume? (expected: MediaWiki tree including `LocalSettings.php`, `api.php`, `index.php`)
   - What is at `/var/www/html`? (expected if broken: just `index.html`)
   - What does `/etc/apache2/sites-enabled/*.conf` have as `DocumentRoot`?
2. If the MediaWiki tree is at `/mediawiki` but Apache points at `/var/www/html`, either:
   - Repoint the vhost `DocumentRoot` to `/mediawiki` (and restart Apache), OR
   - Remove `/var/www/html/index.html` and symlink `/var/www/html -> /mediawiki`, OR
   - Check Taqasta's docs for the expected volume mount path and move the volume there (the image may want `/var/www/html` or `/var/www/mediawiki`, not `/mediawiki`).
3. Re-run `curl https://mediawiki-production-7169.up.railway.app/api.php?action=query&meta=siteinfo&format=json` — expect JSON.
4. Only then resume plans 02-02 and 02-03 against the live wiki.

## Commits

Infra-side commits were made out of session and are listed in the Railway deploy history (`c124f846-0927-4fa7-b8b8-be88f3625ba7` SUCCESS). No code changes were required in this session — the blocker is a container / vhost configuration issue, not a repo change.

## Status

**Plan 02-01: partial.** Infra layer up, app layer not serving MediaWiki. Plans 02-02 and 02-03 remain **not started** (blocked on this plan).  STATE.md and ROADMAP.md are intentionally NOT updated to `phase-2-complete` because the bootstrap scripts never ran successfully against the live wiki.
