"""Rebuild patch pages whose 'Changed' sections dumped raw list syntax.

Symptom: ``** Rulings: none → ["...", "..."]`` in the Changed section
(from a docs-only card change before patch_diff.py learned to skip
those).

For each broken page, reads the commit SHA from its infobox, asks
sync_patches to rebuild that single patch using the updated filters.
Pages whose only change was docs become empty diffs and are deleted.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from sync.client import get_site
from sync.sync_patches import sync_patch


_COMMIT_RE = re.compile(r"\|\s*commit\s*=\s*(\w+)", re.IGNORECASE)
_BROKEN_MARKER = re.compile(r"\*\*\s*(?:Rulings|Tips|Trivia):.*\['", re.DOTALL)


def main() -> int:
    site = get_site()
    repo_root = Path(__file__).resolve().parent.parent.parent

    # Find broken pages
    cat = site.categories["Patch"]
    broken_commits: list[tuple[str, str]] = []  # (title, short_sha)
    for p in cat:
        if not p.name.startswith("Patch:") or p.name == "Patch:Index":
            continue
        text = p.text()
        if not _BROKEN_MARKER.search(text):
            continue
        m = _COMMIT_RE.search(text)
        if not m:
            print(f"  skip {p.name}: no commit in infobox")
            continue
        broken_commits.append((p.name, m.group(1)))

    print(f"rebuilding {len(broken_commits)} patches")

    for title, short_sha in broken_commits:
        # Resolve short SHA to full SHA to satisfy git rev-parse
        try:
            full_sha = subprocess.check_output(
                ["git", "rev-parse", short_sha],
                cwd=str(repo_root),
                encoding="utf-8",
            ).strip()
        except subprocess.CalledProcessError:
            print(f"  {title}: cannot resolve sha {short_sha} — leaving stale")
            continue

        # Get the parent SHA
        try:
            parent = subprocess.check_output(
                ["git", "rev-parse", f"{full_sha}^"],
                cwd=str(repo_root),
                encoding="utf-8",
            ).strip()
        except subprocess.CalledProcessError:
            print(f"  {title}: no parent commit — leaving stale")
            continue

        result = sync_patch(site, repo_root, parent, full_sha, dry_run=False)
        status = result.get("status", "?")

        # If the rebuilt diff is empty (docs-only commit), remove the page
        # since it no longer represents a real patch.
        if status == "no-changes":
            page = site.pages[title]
            if page.exists:
                page.edit(
                    "#REDIRECT [[Patch:Index]]\n",
                    summary="docs-only patch redirects to Patch:Index",
                )
                print(f"  {title}: was docs-only, redirected to Patch:Index")
            else:
                print(f"  {title}: already gone")
        else:
            print(f"  {title}: rebuilt ({status})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
