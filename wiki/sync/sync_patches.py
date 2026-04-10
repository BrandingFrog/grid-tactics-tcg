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

from sync.card_history import (
    build_deprecated_wikitext,

    extract_history_section,
)
from sync.client import MissingCredentialsError, get_site
from sync.patch_diff import PatchDiff, _git_ls_tree, _git_show, build_patch_diff
from sync.patch_page import (
    PATCH_TEMPLATE_WIKITEXT,
    patch_index_wikitext,
    patch_to_wikitext,
)
from sync.sync_cards import build_rules_text, card_to_wikitext, derive_keywords

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
# Card history updates
# ---------------------------------------------------------------------------


def _load_name_map_at_sha(sha: str, repo_root: Path) -> dict[str, str]:
    """Build {card_id: display_name} from all card JSONs at a specific commit."""
    name_map: dict[str, str] = {}
    filenames = _git_ls_tree(sha, "data/cards", repo_root)
    for fname in filenames:
        if not fname.endswith(".json"):
            continue
        raw = _git_show(sha, f"data/cards/{fname}", repo_root)
        if raw is None:
            continue
        try:
            card = json.loads(raw)
            name_map[card["card_id"]] = card["name"]
        except (json.JSONDecodeError, KeyError):
            continue
    return name_map


def _load_card_at_sha(sha: str, card_id: str, repo_root: Path) -> dict | None:
    """Load a single card JSON by card_id at a specific commit.

    Scans all files in data/cards/ to find the one matching card_id.
    """
    filenames = _git_ls_tree(sha, "data/cards", repo_root)
    for fname in filenames:
        if not fname.endswith(".json"):
            continue
        raw = _git_show(sha, f"data/cards/{fname}", repo_root)
        if raw is None:
            continue
        try:
            card = json.loads(raw)
            if card.get("card_id") == card_id:
                return card
        except (json.JSONDecodeError, KeyError):
            continue
    return None


def update_card_histories(
    site,
    diff: PatchDiff,
    repo_root: Path,
    dry_run: bool = False,
) -> list[dict]:
    """Update card pages with history sections based on patch diff.

    For each CardChange in the diff:
    - Added cards: append "added" history entry, re-render with last_changed_patch.
    - Changed cards: append "changed" history entry, re-render from new JSON.
    - Removed cards: wrap with DeprecatedCard template.

    Returns list of result dicts {card_name, page, status}.
    """
    results: list[dict] = []

    if not diff.cards:
        return results

    # Pre-load name_map at new commit for rendering changed/added cards
    name_map = _load_name_map_at_sha(diff.commit_sha, repo_root)

    for card_change in diff.cards:
        page_title = f"Card:{card_change.card_name}"

        if dry_run:
            results.append({
                "card_name": card_change.card_name,
                "page": page_title,
                "status": f"dry-run ({card_change.change_type})",
            })
            continue

        page = site.pages[page_title]

        if card_change.change_type == "removed":
            # Wrap existing page with DeprecatedCard
            if page.exists:
                existing_text = page.text()
                new_text = build_deprecated_wikitext(
                    card_change.card_name, diff.version, existing_text,
                )
                page.edit(
                    new_text,
                    summary=f"mark {card_change.card_name} as deprecated (removed in {diff.version})",
                )
                results.append({
                    "card_name": card_change.card_name,
                    "page": page_title,
                    "status": "deprecated",
                })
            else:
                results.append({
                    "card_name": card_change.card_name,
                    "page": page_title,
                    "status": "skipped (page not found)",
                })
            continue

        # Added or changed: load card JSON at new commit
        card = _load_card_at_sha(diff.commit_sha, card_change.card_id, repo_root)
        if card is None:
            results.append({
                "card_name": card_change.card_name,
                "page": page_title,
                "status": "error (card JSON not found at commit)",
            })
            continue

        # Extract existing history from current page (if it exists)
        existing_entries: list[dict] = []
        if page.exists:
            _, existing_entries = extract_history_section(page.text())

        # Build new history entry
        new_entry = {
            "version": diff.version,
            "date": diff.commit_date,
            "change_type": card_change.change_type,
            "changed_fields": card_change.changed_fields,
            "old_rules": card_change.old_rules,
            "new_rules": card_change.new_rules,
            "old_values": card_change.old_values,
            "new_values": card_change.new_values,
        }

        # Replace existing entry for this version, or append new
        replaced = False
        for i, e in enumerate(existing_entries):
            if e["version"] == diff.version:
                existing_entries[i] = new_entry
                replaced = True
                break
        if not replaced:
            existing_entries.append(new_entry)

        # Re-render full card page with history entries
        full_text = card_to_wikitext(
            card,
            name_map,
            art_exists=True,
            last_changed_patch=diff.version,
            history_entries=existing_entries,
        )

        summary = f"update {card_change.card_name} history ({card_change.change_type} in {diff.version})"
        page.edit(full_text, summary=summary)

        results.append({
            "card_name": card_change.card_name,
            "page": page_title,
            "status": card_change.change_type,
        })

    return results


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

    Creates/updates the patch page, then updates card history sections for
    any cards that were added, changed, or removed.

    Returns dict with keys: status, version, page (if applicable),
    card_results (list of card history update results).
    """
    diff = build_patch_diff(old_sha, new_sha, repo_root)

    # No changes at all -- nothing to publish
    if not diff.cards and not diff.keywords and not diff.enums:
        return {"status": "no-changes", "version": diff.version}

    wikitext = patch_to_wikitext(diff)
    page_title = f"Patch:{diff.version}"

    if dry_run:
        # Still run card history in dry-run mode for reporting
        card_results = update_card_histories(site, diff, repo_root, dry_run=True)
        return {
            "status": "dry-run",
            "version": diff.version,
            "page": page_title,
            "card_results": card_results,
        }

    page = site.pages[page_title]
    summary = f"sync patch {diff.version} ({new_sha[:7]})"

    if not page.exists:
        page.edit(wikitext, summary=summary)
        patch_status = "created"
    else:
        current = page.text()
        if current.rstrip() == wikitext.rstrip():
            patch_status = "unchanged"
        else:
            page.edit(wikitext, summary=summary)
            patch_status = "updated"

    # Update card history sections for affected cards
    card_results = update_card_histories(site, diff, repo_root, dry_run=False)
    if card_results:
        for cr in card_results:
            print(f"    card history: {cr['page']}: {cr['status']}")

    return {
        "status": patch_status,
        "version": diff.version,
        "page": page_title,
        "card_results": card_results,
    }


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
