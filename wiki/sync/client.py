"""
mwclient Site factory for the Grid Tactics Wiki.

Reads credentials from environment variables (loaded from ``wiki/.env`` via
python-dotenv). All downstream sync scripts should call :func:`get_site` rather
than constructing ``mwclient.Site`` directly so that auth, URL parsing, and
Taqasta-specific path handling stay in one place.

Required env vars:
    MW_API_URL   Base URL of the wiki (e.g. ``http://localhost:8080/``).
    MW_BOT_USER  Full bot username in ``<user>@<appid>`` form (e.g. ``admin@phase1``).
    MW_BOT_PASS  Generated BotPassword secret.

Taqasta note: the bundled MediaWiki serves ``api.php`` at ``/w/api.php`` with
short-URL rewrites pointing ``/wiki/X`` at ``index.php?title=X``. The API path
passed to ``mwclient.Site`` MUST be ``/w/`` (confirmed by curling
``/w/api.php?action=query&meta=siteinfo`` during plan 01-02).
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import mwclient
from dotenv import load_dotenv

# Load .env from wiki/ (one directory up from this file).
_WIKI_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_WIKI_DIR / ".env")


class MissingCredentialsError(RuntimeError):
    """Raised when MW_BOT_USER / MW_BOT_PASS are not set in the environment."""


def get_site() -> mwclient.Site:
    """Return an authenticated ``mwclient.Site`` for the configured wiki.

    Raises :class:`MissingCredentialsError` if required env vars are not set.
    """
    api_url = os.environ.get("MW_API_URL", "http://localhost:8080/").strip()
    bot_user = os.environ.get("MW_BOT_USER", "").strip()
    bot_pass = os.environ.get("MW_BOT_PASS", "").strip()

    if not bot_user or not bot_pass:
        raise MissingCredentialsError(
            "MW_BOT_USER and MW_BOT_PASS must be set (see wiki/.env). "
            "Run plan 01-02 Task 2 to create the BotPassword."
        )

    parsed = urlparse(api_url if "://" in api_url else f"http://{api_url}")
    scheme = parsed.scheme or "http"
    host = parsed.netloc or parsed.path  # handles "localhost:8080" with no scheme

    # Path where api.php lives on the wiki. Local Taqasta dev used /w/;
    # Railway mediawiki:1.42 deploy (Phase 2) serves api.php at /. Override
    # via MW_API_PATH env var; default to / for the live wiki.
    path = os.environ.get("MW_API_PATH", "/").strip() or "/"
    if not path.endswith("/"):
        path += "/"

    site = mwclient.Site(host, path=path, scheme=scheme)
    site.login(bot_user, bot_pass)
    return site
