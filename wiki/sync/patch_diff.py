"""Git-based diff engine for detecting card, glossary, and enum changes between commits.

Pure functions -- no wiki connection needed. All data retrieved via subprocess git commands.
"""

from __future__ import annotations

import json
import re
import subprocess

from sync.sync_cards import build_rules_text
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CardChange:
    """A single card that was added, changed, or removed between two commits."""

    card_id: str
    card_name: str
    change_type: Literal["added", "changed", "removed"]
    changed_fields: list[str] = field(default_factory=list)
    old_values: dict[str, object] = field(default_factory=dict)
    new_values: dict[str, object] = field(default_factory=dict)
    old_rules: str = ""
    new_rules: str = ""


@dataclass
class KeywordChange:
    """A glossary keyword that was added, changed, or removed."""

    keyword: str
    change_type: Literal["added", "changed", "removed"]
    old_description: str | None = None
    new_description: str | None = None


@dataclass
class EnumChange:
    """An enum member that was added or removed."""

    enum_name: str
    value_name: str
    change_type: Literal["added", "removed"]


@dataclass
class PatchDiff:
    """Aggregated diff between two commits."""

    version: str
    cards: list[CardChange]
    keywords: list[KeywordChange]
    enums: list[EnumChange]
    commit_sha: str
    commit_date: str


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git_show(sha: str, path: str, repo_root: Path) -> str | None:
    """Read file contents at a specific commit. Returns None if file didn't exist."""
    result = subprocess.run(
        ["git", "show", f"{sha}:{path}"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        return result.stdout
    return None


def _git_ls_tree(sha: str, dir_path: str, repo_root: Path) -> list[str]:
    """List filenames in a directory at a specific commit."""
    result = subprocess.run(
        ["git", "ls-tree", "--name-only", f"{sha}:{dir_path}"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Diff functions
# ---------------------------------------------------------------------------


def diff_cards(old_sha: str, new_sha: str, repo_root: Path) -> list[CardChange]:
    """Compare card JSON files between two commits."""
    old_files = set(_git_ls_tree(old_sha, "data/cards", repo_root))
    new_files = set(_git_ls_tree(new_sha, "data/cards", repo_root))

    changes: list[CardChange] = []

    # Added cards
    for fname in sorted(new_files - old_files):
        raw = _git_show(new_sha, f"data/cards/{fname}", repo_root)
        if raw is None:
            continue
        card = json.loads(raw)
        changes.append(CardChange(
            card_id=card.get("card_id", fname),
            card_name=card.get("name", fname),
            change_type="added",
        ))

    # Removed cards
    for fname in sorted(old_files - new_files):
        raw = _git_show(old_sha, f"data/cards/{fname}", repo_root)
        if raw is None:
            continue
        card = json.loads(raw)
        changes.append(CardChange(
            card_id=card.get("card_id", fname),
            card_name=card.get("name", fname),
            change_type="removed",
        ))

    # Documentation-only fields — changes to these alone do NOT produce a
    # patch-note entry (wiki-only content, not gameplay). Gameplay changes
    # alongside them still surface the card.
    _DOC_ONLY_FIELDS = {"tips", "rulings", "trivia"}

    # Possibly changed cards
    for fname in sorted(old_files & new_files):
        old_raw = _git_show(old_sha, f"data/cards/{fname}", repo_root)
        new_raw = _git_show(new_sha, f"data/cards/{fname}", repo_root)
        if old_raw is None or new_raw is None:
            continue
        old_card = json.loads(old_raw)
        new_card = json.loads(new_raw)
        if old_card == new_card:
            continue
        # Find which fields changed
        all_keys = set(old_card.keys()) | set(new_card.keys())
        changed_fields = sorted(
            k for k in all_keys if old_card.get(k) != new_card.get(k)
        )
        # Drop documentation-only changes from patch notes entirely.
        gameplay_changes = [f for f in changed_fields if f not in _DOC_ONLY_FIELDS]
        if not gameplay_changes:
            continue
        if changed_fields:
            changes.append(CardChange(
                card_id=new_card.get("card_id", fname),
                card_name=new_card.get("name", fname),
                change_type="changed",
                changed_fields=gameplay_changes,
                old_values={k: old_card.get(k) for k in gameplay_changes},
                new_values={k: new_card.get(k) for k in gameplay_changes},
                old_rules=build_rules_text(old_card),
                new_rules=build_rules_text(new_card),
            ))

    # Sort by card_name
    changes.sort(key=lambda c: c.card_name)
    return changes


def _parse_glossary(text: str) -> dict[str, str]:
    """Parse GLOSSARY.md into {keyword: description} dict."""
    keywords: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")]
        # Filter header/separator rows
        if len(parts) < 4:
            continue
        keyword = parts[1]
        description = parts[2]
        if keyword in ("Keyword", "---", "") or keyword.startswith("-"):
            continue
        if description in ("Description", "---", ""):
            continue
        keywords[keyword] = description
    return keywords


def diff_glossary(old_sha: str, new_sha: str, repo_root: Path) -> list[KeywordChange]:
    """Compare GLOSSARY.md between two commits."""
    old_raw = _git_show(old_sha, "data/GLOSSARY.md", repo_root)
    new_raw = _git_show(new_sha, "data/GLOSSARY.md", repo_root)

    old_kw = _parse_glossary(old_raw) if old_raw else {}
    new_kw = _parse_glossary(new_raw) if new_raw else {}

    changes: list[KeywordChange] = []

    for kw in sorted(set(old_kw.keys()) | set(new_kw.keys())):
        if kw in new_kw and kw not in old_kw:
            changes.append(KeywordChange(kw, "added", None, new_kw[kw]))
        elif kw in old_kw and kw not in new_kw:
            changes.append(KeywordChange(kw, "removed", old_kw[kw], None))
        elif old_kw[kw] != new_kw[kw]:
            changes.append(KeywordChange(kw, "changed", old_kw[kw], new_kw[kw]))

    return changes


def _parse_enum_members(text: str, enum_name: str) -> set[str]:
    """Extract member names from a specific IntEnum class in Python source."""
    members: set[str] = set()
    in_enum = False
    for line in text.splitlines():
        # Detect class declaration
        if re.match(rf"^class\s+{re.escape(enum_name)}\s*\(", line):
            in_enum = True
            continue
        if in_enum:
            # End of class: non-indented non-empty line
            if line and not line[0].isspace() and not line.startswith("#"):
                break
            m = re.match(r"^\s+([A-Z_]+)\s*=\s*\d+", line)
            if m:
                members.add(m.group(1))
    return members


def diff_enums(old_sha: str, new_sha: str, repo_root: Path) -> list[EnumChange]:
    """Compare EffectType enum between two commits."""
    old_raw = _git_show(old_sha, "src/grid_tactics/enums.py", repo_root)
    new_raw = _git_show(new_sha, "src/grid_tactics/enums.py", repo_root)

    old_members = _parse_enum_members(old_raw, "EffectType") if old_raw else set()
    new_members = _parse_enum_members(new_raw, "EffectType") if new_raw else set()

    changes: list[EnumChange] = []

    for name in sorted(new_members - old_members):
        changes.append(EnumChange("EffectType", name, "added"))
    for name in sorted(old_members - new_members):
        changes.append(EnumChange("EffectType", name, "removed"))

    return changes


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------


def build_patch_diff(old_sha: str, new_sha: str, repo_root: Path) -> PatchDiff:
    """Build a complete PatchDiff between two commits."""
    # Get version from VERSION.json at new_sha
    version_raw = _git_show(new_sha, "src/grid_tactics/server/static/VERSION.json", repo_root)
    version = "unknown"
    if version_raw:
        version = json.loads(version_raw).get("version", "unknown")

    # Get commit date
    result = subprocess.run(
        ["git", "log", "-1", "--format=%cs", new_sha],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        encoding="utf-8",
        errors="replace",
    )
    commit_date = result.stdout.strip() if result.returncode == 0 else "unknown"

    return PatchDiff(
        version=version,
        cards=diff_cards(old_sha, new_sha, repo_root),
        keywords=diff_glossary(old_sha, new_sha, repo_root),
        enums=diff_enums(old_sha, new_sha, repo_root),
        commit_sha=new_sha,
        commit_date=commit_date,
    )
