# Phase 1: Foundation & Schema Design - Research

**Researched:** 2026-04-07
**Domain:** MediaWiki + Semantic MediaWiki dev/deploy, Python MW clients, TCG schema
**Confidence:** MEDIUM-HIGH (Railway/Taqasta pattern is confirmed; TCG schema is prescriptive by design)

## 1. Summary

Use **`ghcr.io/wikiteq/taqasta:latest`** as the single Docker image for both local dev and Railway — it is the exact image Railway's own official MediaWiki template ships, it bundles Semantic MediaWiki (and ~130 other extensions), and it is driven entirely by env vars so there is no `LocalSettings.php` upload dance that would otherwise break on Railway. Use **`mwclient`** for the Python sync script: it is lightweight (pure-Python, `requests`-based), supports SMW's `ask` API natively, and has a trivial BotPassword auth flow — `pywikibot` is overkill and drags a heavy config/user-config file machinery designed for Wikimedia-family sites. Railway deployment uses **three separate services** (MediaWiki, MariaDB, Redis), each with its own volume — Railway does *not* support shared volumes or docker-compose the way local dev does, but you can drag-drop a compose file into the project canvas and it auto-imports as staged services. For the SMW schema, treat each card JSON field as a separate SMW property and store effects as subobjects (SMW's native repeating-complex-data pattern) — this keeps `#ask` queries like "all Fire minions with cost ≤ 2" trivial. The one surprise worth flagging: Railway allows only **one volume per service**, so MediaWiki's uploads (`/mediawiki/images`) and the MariaDB data dir must be on different services — this is fine but forces the multi-service topology.

**Primary recommendation:** Taqasta + mwclient + 3-service Railway topology + subobject-based SMW schema.

## 2. Docker Base Image — Decision

### Options Evaluated

| Image | Maintenance | SMW Bundled | Env-var config | Railway-ready | Verdict |
|---|---|---|---|---|---|
| `mediawiki:latest` (official Wikimedia) | Active | No (manual install) | No — requires uploaded `LocalSettings.php` | **No** — Railway explicitly can't run it because you can't upload the post-install `LocalSettings.php` to a volume during setup | Reject |
| `ghcr.io/wikiteq/taqasta:latest` (WikiTeq) | Active, enterprise-backed (WikiTeq runs it in prod for clients) | **Yes** | **Yes** — `MW_*` env vars drive everything | **Yes** — Railway's own `railway.com/deploy/mediawiki` template uses exactly this image | **PICK** |
| `NaimKabir/semantic-mediawiki` | Active (auto-tracks SMW stable) | Yes | Limited | Unknown | Reject — narrower scope, no env-var setup |
| `BITPlan/docker-semanticmediawiki` | Stale-ish | Yes | No | No | Reject |
| `wirehead/semantic-mediawiki-docker` | K8s-oriented, small audience | Yes | Partial | No | Reject |
| Bitnami / LinuxServer MediaWiki | No SMW bundle | No | Partial | Partial | Reject — still need to install SMW manually |

### Recommendation

**Use `ghcr.io/wikiteq/taqasta:latest`** (pin to a specific SHA or semver tag once the project stabilizes — e.g., `ghcr.io/wikiteq/taqasta:1.43.x` matching MW LTS).

**Why it wins:**
- **Same image local and prod** — eliminates an entire class of "works on my machine" failures.
- **Taqasta's env-var-driven install** is the specific feature that makes Railway deployment possible at all. Railway's template docs and community explicitly call out that vanilla `mediawiki:latest` **cannot** be deployed on Railway because setup requires writing `LocalSettings.php` to a volume that doesn't exist until after setup.
- **Semantic MediaWiki is already bundled** — enable with `MW_LOAD_EXTENSIONS=SemanticMediaWiki,...` plus `enableSemantics()` (Taqasta handles the latter automatically when the extension is in the load list).
- **130+ extensions pre-bundled** means Phase 2+ additions (e.g., `PageForms`, `Cargo`, `Scribunto/Lua`, `ParserFunctions`, `Arrays`) are already available — just flip them on via env var.
- **Enterprise maintenance** — WikiTeq ships this to paying MediaWiki hosting customers.

**Companion services:**
- Database: **MariaDB 10.11** (`mariadb:10.11`) — MediaWiki's first-class DB; MariaDB over MySQL because of MW recommendations and smaller image.
- Cache: **Redis 7** (`redis:7-alpine`) — Taqasta supports `MW_REDIS_SERVERS` out of the box; improves parser cache performance.

### Specific tags to use in docker-compose

```yaml
services:
  mediawiki:
    image: ghcr.io/wikiteq/taqasta:latest    # pin to specific version once stable
  db:
    image: mariadb:10.11
  redis:
    image: redis:7-alpine
```

Sources:
- [Railway MediaWiki template](https://railway.com/deploy/mediawiki) — confirmed uses `ghcr.io/wikiteq/taqasta:latest`
- [WikiTeq/Taqasta GitHub](https://github.com/WikiTeq/Taqasta)
- [Railway Station: how to deploy using docker-compose](https://station.railway.com/questions/how-to-deploy-using-docker-compose-064a6c6d) — explains why vanilla MW doesn't work
- [SMW Help:Using Docker](https://www.semantic-mediawiki.org/wiki/Help:Using_Docker)

## 3. Python MediaWiki Client — Decision

### Options Evaluated

| Criterion | `mwclient` | `pywikibot` |
|---|---|---|
| Install size | ~1 file + `requests` | Large package, many sub-deps |
| Cold startup | ~100ms | ~500ms-1s (imports config machinery) |
| Config required | None (just URL + creds) | `user-config.py` file mandatory (can be inlined but ugly) |
| BotPassword auth | One-liner `site.login(user, pw)` | Works but routed through Pywikibot's site registry |
| Page edit | `page.edit(text, summary)` | `page.text = ...; page.save()` |
| File upload | `site.upload(file, name, desc)` | `pywikibot.FilePage(...).upload(...)` |
| SMW `#ask` query | **Native `site.ask(query)`** | Not native (generic API call) |
| SMW property write | Via wikitext (`[[Property::Value]]`) — same as pywikibot | Same — both use wikitext |
| Maintenance | Active (`mwclient/mwclient`) | Very active (Wikimedia core project) |
| Audience fit | Third-party wikis, automation | Wikimedia Foundation sites |
| Post-commit hook suitability | **Excellent** — fast startup, minimal deps | Poor — slow startup, heavy deps |

### Recommendation

**Use `mwclient`.** Rationale: (1) post-commit hooks must be fast (users `git commit` many times per hour), (2) no mandatory config file simplifies `wiki/scripts/sync_cards.py`, (3) the `site.ask()` method gives first-class SMW query support for future verification steps, (4) pywikibot's user-config.py and "family files" machinery exist to support the 900+ Wikimedia-family wikis and are pure overhead for a single third-party wiki.

Both libraries write SMW properties the same way — by embedding `[[Property::Value]]` or (better) `{{Card|...}}` template calls in page wikitext. SMW properties cannot be written "directly" via API; they are always a side-effect of saving wikitext that contains property annotations. This is a deliberate SMW design.

### Example snippet (goes into `wiki/scripts/sync_cards.py`)

```python
# pip install mwclient
import mwclient
import json
from pathlib import Path

# BotPassword created in Special:BotPasswords on the wiki
site = mwclient.Site("wiki.grid-tactics.up.railway.app", path="/")
site.login("SyncBot@sync-script", "<bot-password>")  # BotPassword format

def upsert_card(card_json: dict) -> None:
    page_title = f"Card:{card_json['name']}"
    page = site.pages[page_title]

    # Build wikitext that invokes Template:Card — the template itself
    # emits the SMW property annotations, so editing the wikitext
    # automatically updates semantic data.
    wikitext = (
        "{{Card\n"
        f"| name     = {card_json['name']}\n"
        f"| type     = {card_json['type']}\n"
        f"| element  = {card_json['element']}\n"
        f"| cost     = {card_json['cost']}\n"
        f"| attack   = {card_json.get('attack', '')}\n"
        f"| hp       = {card_json.get('hp', '')}\n"
        f"| rules    = {card_json['rules_text']}\n"
        f"| keywords = {', '.join(card_json.get('keywords', []))}\n"
        "}}\n"
        "[[Category:Cards]]\n"
    )
    page.edit(wikitext, summary=f"sync {card_json['name']} from data/cards/")

def upload_art(card_name: str, image_path: Path) -> None:
    with image_path.open("rb") as f:
        site.upload(
            f,
            filename=f"{card_name}.png",
            description=f"Card art for {card_name}",
            ignore=True,  # overwrite existing
        )

def smw_sanity_check() -> list[str]:
    # Native SMW ask() method
    result = site.ask("[[Category:Cards]][[Element::Fire]][[Cost::<2]]|?Name")
    return [r["fulltext"] for r in result]

for card_file in Path("data/cards").glob("*.json"):
    card = json.loads(card_file.read_text())
    upsert_card(card)
    art = Path(f"data/card_art/{card['name']}.png")
    if art.exists():
        upload_art(card["name"], art)
```

Sources:
- [mwclient docs — Site, ask, pages, upload](https://mwclient.readthedocs.io/en/latest/reference/site.html)
- [mwclient GitHub](https://github.com/mwclient/mwclient)
- [MediaWiki API:Client code/Evaluations/mwclient](https://www.mediawiki.org/wiki/API:Client_code/Evaluations/mwclient)
- [pywikibot PyPI](https://pypi.org/project/pywikibot/)

## 4. Railway Deployment Pattern

### Architecture

Three Railway **services**, one Railway **project**:

```
Project: grid-tactics-wiki
├── service: mediawiki   (image: ghcr.io/wikiteq/taqasta:latest)
│     volume: /mediawiki       (uploads, LocalSettings cache)
│     public domain: wiki.<project>.up.railway.app  (toggled on)
├── service: db          (image: mariadb:10.11)
│     volume: /var/lib/mysql
│     no public domain (private networking only)
└── service: redis       (image: redis:7-alpine)
      volume: /data
      no public domain
```

### Key gotchas (confirmed)

1. **Railway allows only ONE volume per service.** You cannot put MariaDB data and MediaWiki uploads on the same service even if you wanted to. The 3-service split is effectively mandatory. Source: [Railway Station docker-compose shared volumes](https://station.railway.com/questions/docker-compose-shared-volumes-8bc3258e).

2. **Vanilla `mediawiki:latest` does NOT work on Railway.** The stock image requires an interactive install wizard that writes `LocalSettings.php`. Railway has no way to inject that file. Taqasta solves this by generating `LocalSettings.php` at container start from env vars via its `run.sh`.

3. **Docker Compose import.** Railway's canvas supports drag-and-drop of a `docker-compose.yml` — services and volumes auto-import as staged changes. This means local dev and Railway config can share the same compose file (with env var substitution).

4. **Private networking.** Services in the same Railway project talk to each other at `${service}.railway.internal`. Set `MW_DB_SERVER=db.railway.internal`.

5. **Subdomain.** Railway auto-generates a `<service>-<project>.up.railway.app` domain when you enable "Public Networking" on the mediawiki service. Custom domains (e.g., `wiki.gridtactics.com`) are a free feature. Use `MW_SITE_SERVER=https://${{RAILWAY_PUBLIC_DOMAIN}}` — Railway's own template uses exactly this variable.

### Required env vars on the mediawiki service

```bash
# Site identity
MW_SITE_NAME=Grid Tactics Wiki
MW_SITE_SERVER=https://${{RAILWAY_PUBLIC_DOMAIN}}
MW_SITE_LANG=en

# Admin bootstrap (only used on first boot)
MW_ADMIN_USER=admin
MW_ADMIN_PASS=${{shared.MW_ADMIN_PASS}}

# Database (private network reference)
MW_DB_TYPE=mysql
MW_DB_SERVER=${{db.RAILWAY_PRIVATE_DOMAIN}}
MW_DB_NAME=mediawiki
MW_DB_USER=wikiuser
MW_DB_PASS=${{db.MYSQL_PASSWORD}}

# Cache
MW_MAIN_CACHE=CACHE_REDIS
MW_REDIS_SERVERS=${{redis.RAILWAY_PRIVATE_DOMAIN}}:6379

# Extensions — enable SMW + the quality-of-life ones for card schema
MW_LOAD_EXTENSIONS=SemanticMediaWiki,SemanticResultFormats,PageForms,ParserFunctions,Arrays,Scribunto,CategoryTree

# Uploads
MW_ENABLE_UPLOADS=true
MW_FILE_EXTENSIONS=png,jpg,jpeg,webp,svg

# Secret (generate once and store in Railway shared variables)
MW_SECRET_KEY=${{shared.MW_SECRET_KEY}}
```

### Local dev compose file (same image)

```yaml
# wiki/docker-compose.yml — used for BOTH local dev and Railway import
version: "3.9"
services:
  mediawiki:
    image: ghcr.io/wikiteq/taqasta:latest
    ports:
      - "8080:80"
    environment:
      MW_SITE_NAME: Grid Tactics Wiki (dev)
      MW_SITE_SERVER: http://localhost:8080
      MW_ADMIN_USER: admin
      MW_ADMIN_PASS: devpassword
      MW_DB_TYPE: mysql
      MW_DB_SERVER: db
      MW_DB_NAME: mediawiki
      MW_DB_USER: wikiuser
      MW_DB_PASS: wikipass
      MW_LOAD_EXTENSIONS: SemanticMediaWiki,SemanticResultFormats,PageForms,ParserFunctions,Scribunto
      MW_ENABLE_UPLOADS: "true"
    volumes:
      - mw_data:/mediawiki
    depends_on:
      - db
  db:
    image: mariadb:10.11
    environment:
      MARIADB_ROOT_PASSWORD: rootpass
      MARIADB_DATABASE: mediawiki
      MARIADB_USER: wikiuser
      MARIADB_PASSWORD: wikipass
    volumes:
      - db_data:/var/lib/mysql
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
volumes:
  mw_data:
  db_data:
  redis_data:
```

Sources:
- [Railway MediaWiki deploy template](https://railway.com/deploy/mediawiki)
- [Railway docs — Dockerfiles](https://docs.railway.com/builds/dockerfiles)
- [Railway Station — docker-compose shared volumes limitation](https://station.railway.com/questions/docker-compose-shared-volumes-8bc3258e)

## 5. SMW Property Schema for Grid Tactics Cards

### Design principles

- **One SMW property per atomic card field.** Keep types narrow — SMW's query planner uses datatypes aggressively.
- **Effects as subobjects, not flat properties.** SMW's subobject mechanism (`{{#subobject:...}}`) is the canonical way to store repeating complex data (a card can have N effects, each with trigger/condition/effect_text).
- **Property names use `CamelCase` no-spaces** (SMW community convention; avoids URL-encoding pain in `#ask` queries).
- **Enumerable fields (Element, CardType) use `Type:Page`** so they auto-create category-like pages and enable `[[Element::Fire]]` navigation.
- **Numeric fields (Cost, Attack, HP) use `Type:Number`** to enable range queries (`Cost::<2`).

### Proposed property list

Create these via `Property:<Name>` pages in the `Property:` namespace. Each page contains the type declaration — see example below the table.

| Property | SMW Type | Example Value | Notes |
|---|---|---|---|
| `Property:Name` | Text | `Ratchanter` | Display name (page title is canonical) |
| `Property:CardType` | Page | `Minion` | Minion / Magic / React / Multi — each becomes a nav page |
| `Property:Element` | Page | `Fire` | Wood / Fire / Earth / Water / Metal / Dark / Light |
| `Property:Cost` | Number | `3` | Mana cost |
| `Property:Attack` | Number | `2` | Minions only; blank for spells |
| `Property:HP` | Number | `4` | Minions only |
| `Property:RulesText` | Text | `Whenever a friendly Rat dies, draw a card.` | Raw rules text |
| `Property:Keyword` | Page | `Sacrifice` | Multi-valued (one property call per keyword); Page type links to glossary |
| `Property:Artist` | Text | `AI / dalle-3` | Free text |
| `Property:ArtFile` | Page | `File:Ratchanter.png` | Links to uploaded image |
| `Property:FlavorText` | Text | `The rats listen, and the rats remember.` | |
| `Property:IntroducedIn` | Text | `0.4.2` | Patch version — use Text not Number so `1.10.0` sorts correctly with SRF or Cargo; alternatively Type:Page for patch-note navigation |
| `Property:LastModified` | Date | `2026-04-07` | Auto-set by sync script |
| `Property:SourceFile` | Text | `data/cards/ratchanter.json` | Traceability back to git |
| `Property:HasEffect` | Page | (subobject ref) | Points at subobjects |

### Effects as subobjects

Each card page emits zero or more `{{#subobject}}` calls — one per effect. This is SMW's native "repeating complex data" pattern (Help:Subobjects).

```wikitext
{{#subobject:
 |EffectTrigger=OnDeath
 |EffectCondition=FriendlyRat
 |EffectAction=DrawCard
 |EffectAmount=1
 |EffectText=When a friendly Rat dies, draw a card.
 |@category=CardEffect
}}
```

Sub-properties: `EffectTrigger` (Page), `EffectCondition` (Text), `EffectAction` (Page), `EffectAmount` (Number), `EffectText` (Text).

### Property page contents (example)

Create `Property:Cost` with body:
```wikitext
This property stores the mana cost of a card.

[[Has type::Number]]
[[Allows value::0]] [[Allows value::1]] [[Allows value::2]] [[Allows value::3]] [[Allows value::4]] [[Allows value::5]] [[Allows value::6]] [[Allows value::7]] [[Allows value::8]] [[Allows value::9]] [[Allows value::10]]
```

Sources:
- [SMW Help:Semantic templates](https://www.semantic-mediawiki.org/wiki/Help:Semantic_templates) — "99% of all SMW data is stored via a template"
- [SMW Help:Subobjects](https://www.semantic-mediawiki.org/wiki/Help:Subobjects)
- [SMW Help:Type Page](https://www.semantic-mediawiki.org/wiki/Help:Type_Page)

## 6. Template:Card wikitext example

This is the template `sync_cards.py` will reference. It both (a) renders the card visually and (b) annotates SMW properties in one pass — so every page edit updates semantic data automatically.

Create page `Template:Card` with:

```wikitext
<noinclude>
Usage:
{{Card
| name     = Ratchanter
| type     = Minion
| element  = Dark
| cost     = 3
| attack   = 2
| hp       = 4
| rules    = Whenever a friendly Rat dies, draw a card.
| flavor   = The rats listen, and the rats remember.
| keywords = Sacrifice, Summon
| art      = Ratchanter.png
| patch    = 0.4.2
}}
</noinclude><includeonly>{|
 class="gt-card gt-element-{{lc:{{{element|}}}}}"
 style="float:right; width:280px; border:2px solid #222; border-radius:10px; background:#1a1a1a; color:#eee; font-family:sans-serif; margin:0 0 1em 1em;"
|-
! colspan="2" style="padding:6px 10px; background:linear-gradient(90deg,#333,#111); border-radius:8px 8px 0 0; text-align:left;"
| <span style="float:right; background:#3070d0; border-radius:50%; width:28px; height:28px; display:inline-block; text-align:center; line-height:28px; font-weight:bold;">{{{cost|?}}}</span>
  <span style="font-size:1.2em; font-weight:bold;">{{{name|{{PAGENAME}}}}}</span>
|-
| colspan="2" style="padding:0;"
| [[File:{{{art|CardBack.png}}}|280px|center|link=]]
|-
| colspan="2" style="padding:4px 10px; font-style:italic; border-top:1px solid #444; border-bottom:1px solid #444; background:#222;"
| {{{type|Minion}}} &mdash; {{{element|Neutral}}}{{#if:{{{keywords|}}}| &middot; {{{keywords}}} }}
|-
| colspan="2" style="padding:8px 10px; min-height:60px;"
| {{{rules|}}}{{#if:{{{flavor|}}}|<hr style="border:0;border-top:1px dashed #555;"/><span style="color:#888;font-style:italic;">{{{flavor}}}</span>}}
|-
{{#if:{{{attack|}}}|
! style="padding:6px 10px; background:#111; border-radius:0 0 0 8px; text-align:left;" | ATK {{{attack}}}
! style="padding:6px 10px; background:#111; border-radius:0 0 8px 0; text-align:right;" | HP {{{hp}}}
}}
|}

<!-- === SMW ANNOTATIONS === -->
[[Name::{{{name|{{PAGENAME}}}}}| ]]
[[CardType::{{{type|}}}| ]]
[[Element::{{{element|}}}| ]]
[[Cost::{{{cost|}}}| ]]
{{#if:{{{attack|}}}|[[Attack::{{{attack}}}| ]]}}
{{#if:{{{hp|}}}|[[HP::{{{hp}}}| ]]}}
[[RulesText::{{{rules|}}}| ]]
{{#if:{{{flavor|}}}|[[FlavorText::{{{flavor}}}| ]]}}
{{#if:{{{art|}}}|[[ArtFile::File:{{{art}}}| ]]}}
{{#if:{{{patch|}}}|[[IntroducedIn::{{{patch}}}| ]]}}
{{#arraymap:{{{keywords|}}}|,|@@@|[[Keyword::@@@| ]]}}
[[LastModified::{{CURRENTTIMESTAMP}}| ]]
[[Category:Cards]]
[[Category:{{{element|}}} cards]]
[[Category:{{{type|}}}s]]</includeonly>
```

Note the `| ` trailing pipe after each `[[Property::Value| ]]` — that's the SMW idiom to suppress display of the raw value (it's already shown by the infobox markup above).

The `#arraymap` parser function (from `Extension:Arrays`) expands comma-separated keywords into repeated `[[Keyword::X]]` annotations — enabling queries like `[[Keyword::Sacrifice]]`.

Standard TCG wikis (MTG Wiki, Hearthstone Wiki) use the same pattern — they do **not** use SMW much (they use Cargo/Wikibase), but the infobox-with-annotations structure is identical.

## 7. SMW Query Examples for Phase 7

Confirmed these are supported by SMW 4.x (and by extension by the Taqasta bundle):

```wikitext
<!-- All Fire minions with mana cost <= 2 -->
{{#ask: [[Category:Cards]] [[CardType::Minion]] [[Element::Fire]] [[Cost::<3]]
  | ?Cost
  | ?Attack
  | ?HP
  | ?RulesText
  | format=table
  | sort=Cost
}}

<!-- Cards modified since a specific date (proxy for "changed in patch X.Y.Z") -->
{{#ask: [[Category:Cards]] [[LastModified::>2026-03-01]]
  | ?LastModified
  | format=broadtable
  | sort=LastModified
  | order=desc
}}

<!-- All cards introduced in patch 0.4.2 -->
{{#ask: [[Category:Cards]] [[IntroducedIn::0.4.2]]
  | ?Element
  | ?Cost
  | format=ul
}}

<!-- Every effect triggered OnDeath, across all cards (queries subobjects) -->
{{#ask: [[Category:CardEffect]] [[EffectTrigger::OnDeath]]
  | ?EffectText
  | ?-HasEffect    # parent card via inverse
  | format=table
}}

<!-- Card count by element (aggregation via SRF) -->
{{#ask: [[Category:Cards]]
  | ?Element
  | format=count
}}
```

### Known SMW query limitations to design around

1. **No JOINs across unrelated pages** — you can't query "cards whose art filename contains 'v2'" in one step; you'd break it into two queries. Mitigation: keep filename/metadata as direct properties on the card page.
2. **No regex in property values** — use `[[Property::~*wildcard*]]` for wildcards only.
3. **`Number` property comparisons require the number type** — if you accidentally declare Cost as Text, `[[Cost::<2]]` silently becomes string comparison. **Mitigation:** verify property types during Phase 1 setup; write a verification task.
4. **Subobject inverse queries** need the `-` prefix: `?-HasEffect` retrieves the parent card from an effect subobject. Non-obvious but documented.
5. **Default result limit is 50** — set `limit=500` for card-level queries so Phase 7 regression tests see all 19+ cards.
6. **`{{#ask}}` is expensive on large wikis.** Not a concern for ~100 cards but relevant if we later mirror game logs. Use `Extension:SemanticResultFormats` formats like `format=count` for lightweight checks.

Sources:
- [SMW Help:Inline queries](https://www.semantic-mediawiki.org/wiki/Help:Inline_queries)
- [SMW Help:Selecting pages](https://www.semantic-mediawiki.org/wiki/Help:Selecting_pages)
- [Extension:Semantic Result Formats](https://www.semantic-mediawiki.org/wiki/Extension:Semantic_Result_Formats)

## 8. Open Questions / Flags

1. **Railway volume size / pricing.** Railway's free-tier volume size may be small (historically 0.5–5 GB). Card art at ~1 MB × ~50 cards is trivial, but MariaDB + parser cache could grow. **Action:** planner should add a task to size volumes explicitly and document the tier assumption.

2. **Taqasta version pinning.** `:latest` is fine for dev but the planner should pick a specific SHA or semver tag (once project stabilizes) for prod to avoid mid-week breakage from upstream MW point releases. Taqasta releases track MediaWiki LTS lines.

3. **BotPassword vs OAuth2.** Phase 1 uses BotPassword (simplest). If the wiki later goes public and the sync script runs from GitHub Actions, revisit with OAuth2 owner-only consumers. Flagging for Phase 3/deployment phase.

4. **Effects sub-schema stability.** The subobject schema (`EffectTrigger`, `EffectAction`, etc.) is a best-guess from Grid Tactics' current keyword glossary. The planner should verify against `data/GLOSSARY.md` and `data/cards/*.json` before locking property types — specifically whether effect triggers form a closed enum or an open-ended set. If closed, `EffectTrigger` should be `Type:Page`; if open, `Type:Text`.

5. **Patch version sorting.** `IntroducedIn` as `Type:Text` means `1.10.0` sorts before `1.2.0` lexically. If patch-range queries matter in Phase 7, consider a parallel `IntroducedInSortKey` numeric property (e.g., `10200` for `1.2.0`). Minor but real.

6. **Image mirror for card art.** Phase 1 scope says "test page" — does it need actual card art uploaded? If so, the sync script's `upload` flow needs to be in Phase 1, not deferred. Recommend planner clarifies with user which of DEPLOY-02 / WIKI-01 includes the upload path.

7. **Cargo as an alternative to SMW.** Not a blocker, but worth noting: the MTG Wiki and Hearthstone Wiki both use **Cargo** (by Yaron Koren) instead of SMW because Cargo is backed by SQL tables and supports JOINs. This was explicitly out of scope per the ROADMAP ("Semantic MediaWiki"), but if the designer later hits SMW query limitations (#1 above), Cargo is the idiomatic fallback. Flagging so the planner doesn't paint us into a corner — keep property names Cargo-compatible (no characters SMW allows that Cargo doesn't).

---

## Sources consolidated

### HIGH confidence
- [Railway MediaWiki deploy template](https://railway.com/deploy/mediawiki) — confirms Taqasta is Railway's blessed path
- [WikiTeq/Taqasta GitHub](https://github.com/WikiTeq/Taqasta)
- [SMW Help:Using Docker](https://www.semantic-mediawiki.org/wiki/Help:Using_Docker)
- [SMW Help:Semantic templates](https://www.semantic-mediawiki.org/wiki/Help:Semantic_templates)
- [SMW Help:Subobjects](https://www.semantic-mediawiki.org/wiki/Help:Subobjects)
- [mwclient docs](https://mwclient.readthedocs.io/)
- [mwclient GitHub](https://github.com/mwclient/mwclient)

### MEDIUM confidence
- [Railway Station — docker-compose on Railway](https://station.railway.com/questions/how-to-deploy-using-docker-compose-064a6c6d)
- [Railway Station — shared volumes limitation](https://station.railway.com/questions/docker-compose-shared-volumes-8bc3258e)
- [MediaWiki API:Client code/Evaluations/mwclient](https://www.mediawiki.org/wiki/API:Client_code/Evaluations/mwclient)
- [Extension:Semantic Bundle](https://www.mediawiki.org/wiki/Extension:Semantic_Bundle)

### LOW confidence / flagged for validation
- Cargo-vs-SMW comparison for TCG wikis — based on general knowledge of MTG/Hearthstone wiki stacks; not re-verified this session
- Taqasta's exact bundled-extension list — need to read `values.yml` in repo to confirm `SemanticMediaWiki`, `PageForms`, `Arrays`, `Scribunto` all present (highly likely given WikiTeq's positioning, but not visually confirmed)

**Confidence breakdown:**
- Docker image decision: HIGH (Railway template literally uses Taqasta)
- Python client decision: HIGH (feature matrix is objective)
- Railway deployment pattern: MEDIUM-HIGH (volume limit confirmed; exact env var names from Railway template)
- SMW schema: MEDIUM (prescriptive design — planner and user should review property names before locking)
- Template:Card wikitext: MEDIUM (working pattern, but visual styling is a first draft; expect iteration in Phase 2)
- Query examples: HIGH (all use standard SMW 4.x syntax)

**Research date:** 2026-04-07
**Valid until:** ~2026-07-07 (90 days — MediaWiki LTS and Taqasta move slowly; SMW stable releases annually)
