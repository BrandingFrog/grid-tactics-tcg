"""Patch sync orchestrator: diff, upsert patch page, update index.

Wires the patch diff engine and wikitext generator to the live wiki.
Manages persistent state (.sync_state.json) to track the last synced commit
and only process new commits on subsequent runs.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sync.client import MissingCredentialsError, get_site
from sync.patch_diff import build_patch_diff
from sync.patch_page import (
    PATCH_TEMPLATE_WIKITEXT,
    patch_index_wikitext,
    patch_to_wikitext,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SYNC_STATE_PATH = Path(__file__).resolve().parent.parent / ".sync_state.json"

# Paths that trigger patch note generation when changed
_WATCHED_PATTERNS = [
    "data/cards/",
    "data/GLOSSARY.md",
    "src/grid_tactics/enums.py",
]


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def load_sync_state() -> dict:
    """Read .sync_state.json if it exists.

    Returns dict with key ``last_synced_sha`` (str or None).
    """
    if _SYNC_STATE_PATH.exists():
        try:
            return json.loads(_SYNC_STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_synced_sha": None}


def save_sync_state(sha: str) -> None:
    """Write sync state with the given SHA and current timestamp."""
    state = {
        "last_synced_sha": sha,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }
    _SYNC_STATE_PATH.write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Template bootstrap
# ---------------------------------------------------------------------------


def bootstrap_patch_template(site) -> str:
    """Upsert Template:Patch on the wiki (idempotent).

    Returns ``"created"``, ``"updated"``, or ``"unchanged"``.
    """
    page = site.pages["Template:Patch"]
    if page.exists:
        current = page.text()
        if current.rstrip() == PATCH_TEMPLATE_WIKITEXT.rstrip():
            return "unchanged"
        page.edit(PATCH_TEMPLATE_WIKITEXT, summary="update Template:Patch")
        return "updated"
    page.edit(PATCH_TEMPLATE_WIKITEXT, summary="bootstrap Template:Patch")
    return "created"


# ---------------------------------------------------------------------------
# Core sync
# ---------------------------------------------------------------------------


def sync_patch(
    site,
    repo_root: Path,
    old_sha: str,
    new_sha: str,
    dry_run: bool = False,
) -> dict:
    """Sync a single patch (diff between old_sha and new_sha) to the wiki.

    Returns dict with keys: status, version, page (if applicable).
    """
    diff = build_patch_diff(old_sha, new_sha, repo_root)

    # No changes at all -- nothing to publish
    if not diff.cards and not diff.keywords and not diff.enums:
        return {"status": "no-changes", "version": diff.version}

    wikitext = patch_to_wikitext(diff)
    page_title = f"Patch:{diff.version}"

    if dry_run:
        return {
            "status": "dry-run",
            "version": diff.version,
            "page": page_title,
        }

    page = site.pages[page_title]
    summary = f"sync patch {diff.version} ({new_sha[:7]})"

    if not page.exists:
        page.edit(wikitext, summary=summary)
        return {"status": "created", "version": diff.version, "page": page_title}

    current = page.text()
    if current.rstrip() == wikitext.rstrip():
        return {"status": "unchanged", "version": diff.version, "page": page_title}

    page.edit(wikitext, summary=summary)
    return {"status": "updated", "version": diff.version, "page": page_title}


def sync_patch_index(
    site, repo_root: Path, dry_run: bool = False
) -> str:
    """Rebuild Patch:Index from all Patch pages in Category:Patch.

    Returns status: ``"created"``, ``"updated"``, ``"unchanged"``, or ``"dry-run"``.
    """
    # Collect all patch pages from Category:Patch
    patches: list[dict] = []
    try:
        cat = site.categories["Patch"]
        for page in cat:
            title = page.name
            # Only process pages whose title starts with "Patch:"
            if not title.startswith("Patch:"):
                continue
            # Skip Patch:Index itself
            if title == "Patch:Index":
                continue
            version = title[len("Patch:"):]
            text = page.text()
            # Extract date and commit from Template:Patch invocation
            date_match = re.search(r"\|date=(\S+)", text)
            commit_match = re.search(r"\|commit=(\w+)", text)
            patches.append({
                "version": version,
                "date": date_match.group(1) if date_match else "unknown",
                "commit_sha": commit_match.group(1) if commit_match else "unknown",
            })
    except Exception as exc:
        print(f"  warning: error reading Category:Patch: {exc}")

    wikitext = patch_index_wikitext(patches)
    page_title = "Patch:Index"

    if dry_run:
        return "dry-run"

    page = site.pages[page_title]
    summary = f"update Patch:Index ({len(patches)} patches)"

    if not page.exists:
        page.edit(wikitext, summary=summary)
        return "created"

    current = page.text()
    if current.rstrip() == wikitext.rstrip():
        return "unchanged"

    page.edit(wikitext, summary=summary)
    return "updated"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], repo_root: Path) -> str:
    """Run a git command and return stdout. Raises on failure."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def _commit_touches_watched(sha: str, repo_root: Path) -> bool:
    """Check if a commit modifies any of the watched file paths."""
    try:
        files = _git(["diff-tree", "--no-commit-id", "-r", "--name-only", sha], repo_root)
    except RuntimeError:
        return False
    for line in files.splitlines():
        for pattern in _WATCHED_PATTERNS:
            if line.strip().startswith(pattern):
                return True
    return False


# ---------------------------------------------------------------------------
# Pending sync
# ---------------------------------------------------------------------------


def sync_all_pending(
    site, repo_root: Path, dry_run: bool = False
) -> list[dict]:
    """Process all pending commits since last sync.

    Walks commits between last_synced_sha and HEAD, filters by watched paths,
    and syncs each relevant commit as a patch page. Updates .sync_state.json
    and rebuilds Patch:Index.

    Returns list of results from sync_patch calls.
    """
    state = load_sync_state()
    last_sha = state.get("last_synced_sha")

    head_sha = _git(["rev-parse", "HEAD"], repo_root)

    # Already synced to HEAD
    if last_sha == head_sha:
        return []

    # Determine commits to process
    if last_sha is None:
        # First-ever sync: just diff HEAD~1..HEAD
        try:
            parent = _git(["rev-parse", "HEAD~1"], repo_root)
            commit_shas = [head_sha]
        except RuntimeError:
            # Repo has only one commit
            commit_shas = [head_sha]
            parent = None
    else:
        # Get commits between last sync and HEAD
        rev_list_output = _git(
            ["rev-list", "--reverse", f"{last_sha}..HEAD"], repo_root
        )
        commit_shas = [s.strip() for s in rev_list_output.splitlines() if s.strip()]

    results: list[dict] = []

    for sha in commit_shas:
        if not _commit_touches_watched(sha, repo_root):
            continue

        # Get parent of this commit
        try:
            parent_sha = _git(["rev-parse", f"{sha}^"], repo_root)
        except RuntimeError:
            # First commit in repo -- skip (no parent to diff against)
            continue

        result = sync_patch(site, repo_root, parent_sha, sha, dry_run=dry_run)
        if result["status"] != "no-changes":
            results.append(result)

    # Update state (even if no patches were generated)
    if not dry_run:
        save_sync_state(head_sha)

    # Rebuild Patch:Index
    if results and not dry_run:
        idx_status = sync_patch_index(site, repo_root, dry_run=dry_run)
        print(f"  Patch:Index: {idx_status}")

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI for patch sync operations."""
    parser = argparse.ArgumentParser(
        description="Sync patch notes to the Grid Tactics Wiki.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--pending",
        action="store_true",
        help="Sync all pending commits (default mode for hook)",
    )
    group.add_argument(
        "--commit",
        type=str,
        metavar="SHA",
        help="Sync a specific commit (diff against its parent)",
    )
    group.add_argument(
        "--bootstrap-template",
        action="store_true",
        help="Just bootstrap Template:Patch on the wiki",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview mode — show what would change without making edits",
    )
    args = parser.parse_args(argv)

    # Determine repo root (two levels up from this file: wiki/sync/ -> repo)
    repo_root = Path(__file__).resolve().parent.parent.parent

    # Connect to wiki
    try:
        site = get_site()
    except MissingCredentialsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.bootstrap_template:
        status = bootstrap_patch_template(site)
        print(f"Template:Patch: {status}")
        return 0

    if args.commit:
        # Diff against parent
        try:
            parent = _git(["rev-parse", f"{args.commit}^"], repo_root)
        except RuntimeError:
            print(f"ERROR: cannot find parent of {args.commit}", file=sys.stderr)
            return 1
        result = sync_patch(site, repo_root, parent, args.commit, dry_run=args.dry_run)
        print(f"  {result.get('page', result.get('version', '?'))}: {result['status']}")
        return 0

    if args.pending:
        # Ensure template exists
        tmpl_status = bootstrap_patch_template(site)
        if tmpl_status != "unchanged":
            print(f"  Template:Patch: {tmpl_status}")
        results = sync_all_pending(site, repo_root, dry_run=args.dry_run)
        if not results:
            print("No pending patch changes.")
        else:
            for r in results:
                print(f"  {r.get('page', r.get('version', '?'))}: {r['status']}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
