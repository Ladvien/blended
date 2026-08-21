"""API drift catalog: known Blender API changes and their fixes.

This file is a first-class artifact, not a comment. Every time a
traceback teaches us that an API moved, the lesson lands here in the
same commit as the fix, so the agent (and the humans) stop paying for
it twice. 3DCodeBench's curation pipeline kept exactly this artifact
("Blender 5.0 API module" of their Experience Library) and found API
drift to be the dominant failure family.

Entry sources are tagged: [measured] = hit in one of our own sessions;
[3DCodeBench] = reported error fingerprint from arXiv:2606.01057.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DriftEntry:
    """One known API change: how it fails, and what to do instead."""

    symbol: str                # the API the old code reaches for
    changed_in: str            # Blender series where behavior changed
    error_signature: str       # distinctive substring of the traceback
    fix: str                   # what current code should do
    source: str                # provenance tag


DRIFT_ENTRIES: tuple[DriftEntry, ...] = (
    DriftEntry(
        symbol="bpy.types.Action.fcurves",
        changed_in="5.0",
        error_signature="fcurves",
        fix=(
            "Actions are slotted/layered in 5.x: walk "
            "action.layers -> strips -> channelbags -> fcurves. "
            "Reading action.fcurves returns empty and silently does nothing."
        ),
        source="[measured] scp_characters session",
    ),
    DriftEntry(
        symbol="bpy.types.Mesh.use_auto_smooth",
        changed_in="4.1",
        error_signature="'Mesh' object has no attribute 'use_auto_smooth'",
        fix=(
            "use_auto_smooth was removed. Use the smooth-by-angle modifier "
            "or per-face smooth shading; do not set the attribute."
        ),
        source="[3DCodeBench] excluded-model failure fingerprint",
    ),
    DriftEntry(
        symbol="Principled BSDF input 'Specular'",
        changed_in="4.0",
        error_signature='bpy_prop_collection[key]: key "Specular" not found',
        fix=(
            "The Principled BSDF 'Specular' socket was renamed; use "
            "'Specular IOR Level' (and check socket names against the "
            "running version before indexing node.inputs by string)."
        ),
        source="[3DCodeBench] excluded-model failure fingerprint",
    ),
    DriftEntry(
        symbol="bpy.ops.mesh.primitive_cone_add(diameter1=...)",
        changed_in="2.8+",
        error_signature='keyword "diameter1" is invalid',
        fix=(
            "Cone/cylinder primitive operators take radius1/radius2, not "
            "diameter1/diameter2. Prefer bmesh construction over bpy.ops "
            "primitives so argument drift cannot bite at all."
        ),
        source="[3DCodeBench] excluded-model failure fingerprint",
    ),
    DriftEntry(
        symbol="empty scene / evaluated_get on unlinked object",
        changed_in="all",
        error_signature="evaluated_get",
        fix=(
            "If bpy.context.scene.objects is empty the depsgraph has no "
            "instances: evaluated_get returns STORED values and every pose "
            "measures identical, with no error raised. Link the object into "
            "scene.collection and check len(scene.objects) before measuring."
        ),
        source="[measured] scp_characters session",
    ),
    DriftEntry(
        symbol="duplicate object names on retry (silent .001 suffix)",
        changed_in="all",
        error_signature=".001",
        fix=(
            "A failed attempt leaves its partial objects in the scene, so "
            "re-running a builder with the same name silently creates "
            "'Name.001' while name lookups still find the stale 'Name' - "
            "no error raised, wrong object measured. Ops are idempotent by "
            "name (constructors remove a same-name object first); builders "
            "must reuse deterministic names, never rely on Blender's "
            "auto-suffix."
        ),
        source="[measured] blended stage-1 retry test, 2026-08-21",
    ),
)



def validate_catalog() -> list[str]:
    """Return a list of schema problems (empty list = healthy catalog)."""
    problems: list[str] = []
    seen_symbols: set[str] = set()
    for entry in DRIFT_ENTRIES:
        if not entry.error_signature.strip():
            problems.append(f"{entry.symbol}: empty error_signature")
        if not entry.fix.strip():
            problems.append(f"{entry.symbol}: empty fix")
        if not (entry.source.startswith("[measured]") or entry.source.startswith("[3DCodeBench]")):
            problems.append(f"{entry.symbol}: untagged source {entry.source!r}")
        if entry.symbol in seen_symbols:
            problems.append(f"duplicate symbol: {entry.symbol}")
        seen_symbols.add(entry.symbol)
    return problems


def match_traceback(traceback_text: str) -> list[DriftEntry]:
    """Return catalog entries whose signature appears in a traceback.

    This is the seam where the retry loop plugs in: on failure, matched
    entries are appended to the retry prompt so known drift is fixed on
    the first retry instead of rediscovered.
    """
    return [
        entry
        for entry in DRIFT_ENTRIES
        if entry.error_signature in traceback_text
    ]
