"""
Verify that Semantic MediaWiki is installed and bot auth works end-to-end.

Run from ``wiki/``::

    python -m sync.verify_smw

Exits 0 on success, non-zero with a clear message on any failure. This is the
smoke test that plan 01-02 declares as its success criterion, and it is
intended to be re-run at the start of every downstream sync plan as a
"am I pointed at a real, working wiki?" check.
"""

from __future__ import annotations

import sys

from .client import MissingCredentialsError, get_site


def main() -> int:
    try:
        site = get_site()
    except MissingCredentialsError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — we want a clean CLI error
        print(f"[FAIL] Could not connect / authenticate: {exc}", file=sys.stderr)
        return 3

    # 1. SMW present in extension list
    try:
        info = site.api("query", meta="siteinfo", siprop="extensions")
        extensions = info["query"]["extensions"]
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] siteinfo query failed: {exc}", file=sys.stderr)
        return 4

    smw = next((e for e in extensions if e.get("name") == "SemanticMediaWiki"), None)
    if smw is None:
        names = sorted(e.get("name", "?") for e in extensions)
        print(
            "[FAIL] SemanticMediaWiki not in installed extensions. Found: "
            + ", ".join(names),
            file=sys.stderr,
        )
        return 5

    print(f"SMW version: {smw.get('version', '?')}")
    print(f"Bot authenticated as: {site.username}")

    # 2. ask() API sanity — proves SMW query endpoint is wired up.
    try:
        result = site.ask("[[Modification date::+]]|limit=1")
        count = sum(1 for _ in result)
        print(f"ask() returned {count} result(s) (OK — SMW query endpoint live)")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] SMW ask() endpoint failed: {exc}", file=sys.stderr)
        return 6

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
