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

    symbol: str  # the API the old code reaches for
    changed_in: str  # Blender series where behavior changed
    error_signature: str  # distinctive substring of the traceback
    fix: str  # what current code should do
    source: str  # provenance tag


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
    DriftEntry(
        symbol="scene.display.shading.show_backface_culling in renders",
        changed_in="all",
        error_signature="show_backface_culling",
        fix=(
            "Backface culling is a VIEWPORT display setting: Workbench "
            "renders ignore it entirely (measured: 0 changed pixels), so a "
            "flipped normal cannot be visualized that way headless. Use the "
            "analyzer's ray-parity flipped_normal_triangle_count, or show "
            "it via shading contrast. show_xray DOES affect Workbench "
            "renders and is the supported transparency debug path."
        ),
        source="[measured] blended stage-4 pretest, 2026-08-21",
    ),
    DriftEntry(
        symbol="glTF export splits vertices at flat-shading seams",
        changed_in="all",
        error_signature="io_scene_gltf2",
        fix=(
            "glTF stores per-vertex normals, so exporting a flat-shaded "
            "watertight solid ships a file whose vertices are split along "
            "every sharp edge: re-imported it reads as dozens of "
            "disconnected components and boundary edges everywhere, with "
            "no error raised. Engines render it fine. Judge shipped GLBs "
            "on POSITION-WELDED topology (weld_and_dissolve first), never "
            "on the raw re-import - the same reason TRELLIS metadata "
            "reports as_shipped and position_welded topology separately."
        ),
        source="[measured] blended stage-8 export round-trip, 2026-08-21",
    ),
    DriftEntry(
        symbol="BVHTree.overlap on coplanar triangles",
        changed_in="all",
        error_signature="BVHTree",
        fix=(
            "BVHTree.overlap() silently returns an EMPTY list for "
            "exactly-coplanar triangle pairs - measured: two obviously "
            "overlapping triangles at z=0 report no pairs, the same two "
            "report a pair once one is nudged off-plane. No error, no "
            "warning, just a clean-looking zero. So BVHTree is unusable "
            "for any 2D/flattened work (UV overlap above all); use a "
            "uniform-grid or sweep broadphase plus an explicit 2D "
            "predicate. It remains correct for genuine 3D self-"
            "intersection, where the triangles are not coplanar."
        ),
        source="[measured] blended stage-3.2 UV overlap, 2026-08-21",
    ),
    DriftEntry(
        symbol="bpy.ops.uv.smart_project on curved geometry",
        changed_in="all",
        error_signature="smart_project",
        fix=(
            "smart_project silently produces a heavily OVERLAPPING atlas "
            "on curved/lathe geometry - measured on a barrel: 210 "
            "overlapping face pairs, 38% of covered texels multiply "
            "covered, max stack depth 40, while reporting a healthy "
            "looking 94% coverage (area sum double-counts overlap). It is "
            "clean on boxy meshes. bpy.ops.uv.unwrap(method='ANGLE_BASED') "
            "stayed at 0 overlaps on every mesh tested and is the default. "
            "cube_project stacks by design. Never trust an unwrap without "
            "measuring its overlap count."
        ),
        source="[measured] blended stage-3.2 unwrap comparison, 2026-08-21",
    ),
    DriftEntry(
        symbol="UV unwrap inherits pre-existing seams",
        changed_in="all",
        error_signature="uv_layers",
        fix=(
            "Unwrap solvers reuse the existing UV layout's seams and "
            "island structure, so unwrapping a mesh that already has UVs "
            "silently yields a different result than unwrapping it fresh "
            "- measured: a barrel unwrapped ANGLE_BASED right after "
            "SMART_PROJECT inherited that method's 26 overlapping islands "
            "instead of its own clean 344, with no warning. Clear "
            "mesh.uv_layers before unwrapping so the op is a pure "
            "function of the geometry."
        ),
        source="[measured] blended stage-3.2 unwrap determinism, 2026-08-21",
    ),
    DriftEntry(
        symbol="matrix_world is stale until view_layer.update()",
        changed_in="all",
        error_signature="matrix_world",
        fix=(
            "Setting object.location / .rotation_euler does NOT update "
            "matrix_world - the depsgraph evaluates it lazily. Reading it "
            "first returns the stale matrix (identity on a fresh object), "
            "so any op that bakes matrix_world into mesh data silently "
            "does NOTHING: no error, no warning, vertices untouched. "
            "Measured: an agent positioned three splayed stool legs via "
            "rotation_euler + location, called apply_object_transform, and "
            "all three stayed at the origin and unioned into a single "
            "central post. Call bpy.context.view_layer.update() before "
            "reading matrix_world."
        ),
        source="[measured] blended agent stool run, 2026-08-21",
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
        if not (
            entry.source.startswith("[measured]")
            or entry.source.startswith("[3DCodeBench]")
        ):
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
    return [entry for entry in DRIFT_ENTRIES if entry.error_signature in traceback_text]
