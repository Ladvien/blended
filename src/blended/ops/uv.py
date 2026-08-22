"""UV unwrapping — with the op verifying its own output.

Unwrapping is the one place bpy.ops is unavoidable: the solvers have no
data-API equivalent. So this module owns the context handling (mode
switching, selection, restore) and keeps it out of every builder — the
agent-computer-interface argument: one purpose-built op instead of
context wrangling at each call site.

METHOD CHOICE IS MEASURED, NOT ASSUMED. Overlap counts from our own
analyzer, same three meshes:

    method          plain box      crate          barrel (lathe)
    ANGLE_BASED     0 overlaps     0 overlaps     0 overlaps
    SMART_PROJECT   0 overlaps     0 overlaps     210 overlaps
    CUBE_PROJECT    48 overlaps    360 overlaps   20,624 overlaps

ANGLE_BASED is therefore the default: it is the only method that stayed
clean on curved lathe geometry. It pays for that with island count
(barrel: 344 islands vs smart_project's 26), so SMART_PROJECT remains
available for boxy props where it is both clean and tidier. CUBE_PROJECT
stacks by design and is offered only for deliberate tiling work.

Every unwrap returns an UnwrapReport including its own overlap count, so
a bad atlas is visible at the call site rather than three stages later.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

ANGLE_LIMIT_RAD = math.radians(66.0)
# A 1/512 margin keeps islands a texel apart at 512px so filtering does
# not bleed across seams (Vaughan: space islands to avoid bleed without
# wasting space).
ISLAND_MARGIN_FRACTION = 1.0 / 512.0

ANGLE_BASED = "ANGLE_BASED"
SMART_PROJECT = "SMART_PROJECT"
CUBE_PROJECT = "CUBE_PROJECT"
UNWRAP_METHODS = (ANGLE_BASED, SMART_PROJECT, CUBE_PROJECT)


@dataclass(frozen=True)
class UnwrapReport:
    method: str
    island_count: int
    overlapping_face_pair_count: int
    coverage_fraction: float

    @property
    def clean(self) -> bool:
        return self.overlapping_face_pair_count == 0

    def summary(self) -> str:
        return (
            f"{self.method}: {self.island_count} islands, "
            f"{self.overlapping_face_pair_count} overlapping pairs, "
            f"{self.coverage_fraction:.1%} area sum"
        )


def unwrap_uvs(
    blender_object,
    method: str = ANGLE_BASED,
    angle_limit_rad: float = ANGLE_LIMIT_RAD,
    island_margin: float = ISLAND_MARGIN_FRACTION,
) -> UnwrapReport:
    """Unwrap the object's UVs and measure the resulting atlas.

    Restores the previous mode and selection so callers see no context
    side effects.
    """
    import bpy

    from blended.analyze.mesh_checks import analyze_object

    if method not in UNWRAP_METHODS:
        raise ValueError(
            f"Unknown unwrap method {method!r}; use one of {UNWRAP_METHODS}."
        )
    if blender_object.type != "MESH":
        raise ValueError(f"{blender_object.name} is not a mesh.")
    if blender_object.name not in bpy.context.scene.objects:
        raise ValueError(
            f"{blender_object.name} is not linked into the scene; "
            f"bpy.ops cannot act on it."
        )

    # Determinism: unwrap solvers REUSE existing seams and island
    # structure, so unwrapping a mesh that already carries UVs gives a
    # different result than unwrapping it fresh (measured: a barrel
    # unwrapped ANGLE_BASED after SMART_PROJECT inherited the latter's
    # 26 overlapping islands instead of producing its own clean 344).
    # Clearing first makes the op a pure function of the geometry.
    while blender_object.data.uv_layers:
        blender_object.data.uv_layers.remove(blender_object.data.uv_layers[0])

    previous_active_object = bpy.context.view_layer.objects.active
    previous_selection = [
        scene_object
        for scene_object in bpy.context.scene.objects
        if scene_object.select_get()
    ]
    try:
        bpy.ops.object.select_all(action="DESELECT")
        blender_object.select_set(True)
        bpy.context.view_layer.objects.active = blender_object
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")

        if method == ANGLE_BASED:
            bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=island_margin)
        elif method == SMART_PROJECT:
            bpy.ops.uv.smart_project(
                angle_limit=angle_limit_rad, island_margin=island_margin
            )
        else:
            bpy.ops.uv.cube_project(cube_size=1.0)

        bpy.ops.object.mode_set(mode="OBJECT")
    finally:
        bpy.ops.object.select_all(action="DESELECT")
        for previously_selected in previous_selection:
            previously_selected.select_set(True)
        bpy.context.view_layer.objects.active = previous_active_object

    report = analyze_object(blender_object)
    return UnwrapReport(
        method=method,
        island_count=report.uv_island_count,
        overlapping_face_pair_count=report.uv_overlapping_face_pair_count,
        coverage_fraction=report.uv_coverage_fraction,
    )
