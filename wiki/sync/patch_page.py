"""Wikitext generation for Patch:X.Y.Z and Patch:Index pages.

Pure functions -- no wiki connection needed. Produces wikitext strings from PatchDiff data.
"""

from __future__ import annotations

from sync.card_history import _FIELD_LABELS, _format_value
from sync.patch_diff import PatchDiff


# ---------------------------------------------------------------------------
# Template:Patch wikitext (module-level constant)
# ---------------------------------------------------------------------------

PATCH_TEMPLATE_WIKITEXT = """\
<includeonly><div class="patch-infobox" style="float:right; border:1px solid #aaa; padding:8px; margin:0 0 8px 8px; width:250px; background:#f9f9f9;">
'''Patch {{{version|}}}'''
* '''Date:''' {{{date|}}}
* '''Commit:''' <code>{{{commit|}}}</code>
</div></includeonly><noinclude>
Infobox template for patch notes pages.
[[Category:Template]]
</noinclude>"""


# ---------------------------------------------------------------------------
# Patch page wikitext
# ---------------------------------------------------------------------------


def patch_to_wikitext(diff: PatchDiff) -> str:
    """Generate wikitext for a Patch:X.Y.Z page from a PatchDiff."""
    lines: list[str] = []

    # Infobox template
    short_sha = diff.commit_sha[:7]
    lines.append("{{Patch")
    lines.append(f"|version={diff.version}")
    lines.append(f"|date={diff.commit_date}")
    lines.append(f"|commit={short_sha}")
    lines.append("}}")
    lines.append("")
    lines.append(f"Patch '''{diff.version}''' was released on {diff.commit_date}.")

    # -- Cards section --
    if diff.cards:
        lines.append("")
        lines.append("== Cards ==")

        added = [c for c in diff.cards if c.change_type == "added"]
        changed = [c for c in diff.cards if c.change_type == "changed"]
        removed = [c for c in diff.cards if c.change_type == "removed"]

        if added:
            lines.append("")
            lines.append("=== Added ===")
            for c in added:
                lines.append(f"* [[Card:{c.card_name}|{c.card_name}]] — new card")

        if changed:
            lines.append("")
            lines.append("=== Changed ===")
            for c in changed:
                lines.append(f"* [[Card:{c.card_name}|{c.card_name}]]")
                if c.old_values and c.new_values:
                    for f in c.changed_fields:
                        label = _FIELD_LABELS.get(f, f.replace("_", " ").capitalize())
                        old_v = _format_value(f, c.old_values.get(f))
                        new_v = _format_value(f, c.new_values.get(f))
                        lines.append(f"** {label}: {old_v} → {new_v}")
                else:
                    fields = ", ".join(
                        _FIELD_LABELS.get(f, f.replace("_", " ").capitalize())
                        for f in c.changed_fields
                    )
                    lines.append(f"** Updated: {fields}")

        if removed:
            lines.append("")
            lines.append("=== Removed ===")
            for c in removed:
                lines.append(f"* [[Card:{c.card_name}|{c.card_name}]] — removed")

    # -- Mechanics section --
    has_mechanics = bool(diff.keywords or diff.enums)
    if has_mechanics:
        lines.append("")
        lines.append("== Mechanics ==")

        if diff.keywords:
            lines.append("")
            lines.append("=== Keywords ===")
            for kw in diff.keywords:
                if kw.change_type == "added":
                    lines.append(f"* '''{kw.keyword}''' — added")
                elif kw.change_type == "removed":
                    lines.append(f"* '''{kw.keyword}''' — removed")
                elif kw.change_type == "changed":
                    lines.append(f"* '''{kw.keyword}''' — changed: {kw.new_description}")

        if diff.enums:
            lines.append("")
            lines.append("=== Effect Types ===")
            for ec in diff.enums:
                if ec.change_type == "added":
                    lines.append(f"* '''{ec.value_name}''' — added to {ec.enum_name}")
                else:
                    lines.append(f"* '''{ec.value_name}''' — removed from {ec.enum_name}")

    lines.append("")
    lines.append("[[Category:Patch]]")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Patch index wikitext
# ---------------------------------------------------------------------------


def patch_index_wikitext(patches: list[dict]) -> str:
    """Generate wikitext for Patch:Index page.

    Each entry in patches should have keys: version, date, commit_sha.
    Sorted newest-first by version string (lexicographic, works for 0.x.y).
    """
    sorted_patches = sorted(patches, key=lambda p: p["version"], reverse=True)

    lines: list[str] = []
    lines.append("This page lists all patches for Grid Tactics, newest first.")
    lines.append("")
    lines.append('{| class="wikitable sortable"')
    lines.append("|-")
    lines.append("! Version !! Date !! Commit")

    for p in sorted_patches:
        short_sha = p["commit_sha"][:7]
        lines.append("|-")
        lines.append(
            f"| [[Patch:{p['version']}|{p['version']}]] "
            f"|| {p['date']} "
            f"|| <code>{short_sha}</code>"
        )

    lines.append("|}")
    lines.append("")
    lines.append("[[Category:Patch]]")

    return "\n".join(lines)
