"""
Verify that the live Grid Tactics Wiki matches :mod:`sync.schema`.

For every property declared in :data:`sync.schema.PROPERTIES` +
:data:`sync.schema.EFFECT_SUBPROPERTIES`, this script:

1. Fetches ``Property:<Name>`` via mwclient and asserts the page exists and
   contains the expected ``[[Has type::<Type>]]`` annotation.
2. Runs an SMW ``ask`` query (``[[Property:+]]|?Has type|limit=500``) as a
   cross-check against what SMW itself believes is defined.
3. Prints a mismatch table and exits non-zero if anything disagrees.

Usage:
    cd wiki
    python -m sync.verify_schema
"""

from __future__ import annotations

import sys
from typing import Iterable

from sync.client import MissingCredentialsError, get_site
from sync.schema import EFFECT_SUBPROPERTIES, PROPERTIES, PropertySpec


def _all_specs() -> Iterable[PropertySpec]:
    yield from PROPERTIES
    yield from EFFECT_SUBPROPERTIES


def main() -> int:
    try:
        site = get_site()
    except MissingCredentialsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    specs = list(_all_specs())
    expected_types = {spec["name"]: spec["type"] for spec in specs}

    mismatches: list[tuple[str, str, str]] = []  # (name, expected, actual)
    missing: list[str] = []

    # 1) Page-level check
    for name, expected_type in expected_types.items():
        page = site.pages[f"Property:{name}"]
        if not page.exists:
            missing.append(name)
            continue
        body = page.text()
        marker = f"[[Has type::{expected_type}]]"
        if marker not in body:
            mismatches.append((name, expected_type, body.strip()[:80]))

    # 2) SMW ask cross-check (best-effort; don't fail hard if the query shape
    #    changes between SMW versions — the page-level check is authoritative).
    try:
        ask_query = "[[Property:+]]|?Has type|limit=500"
        seen: set[str] = set()
        for result in site.ask(ask_query):
            for full_name, _payload in result.items():
                # Full name looks like "Property:Cost"
                if full_name.startswith("Property:"):
                    seen.add(full_name[len("Property:") :])
        for name in expected_types:
            if name not in seen:
                # Soft signal — the page check above is the real gate.
                print(f"note: ask() did not list Property:{name}", file=sys.stderr)
    except Exception as exc:  # pragma: no cover
        print(f"note: ask() cross-check skipped ({exc})", file=sys.stderr)

    if missing or mismatches:
        if missing:
            print("MISSING properties:")
            for name in missing:
                print(f"  - Property:{name}  (expected type {expected_types[name]})")
        if mismatches:
            print("TYPE MISMATCHES:")
            print(f"  {'Name':<22} {'Expected':<10} Actual (truncated)")
            for name, expected, actual in mismatches:
                print(f"  {name:<22} {expected:<10} {actual}")
        print(
            f"\nFAIL: {len(missing)} missing, {len(mismatches)} wrong type "
            f"(of {len(specs)} expected)"
        )
        return 1

    print(f"Schema OK: {len(specs)}/{len(specs)} properties defined correctly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
