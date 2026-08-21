"""Modifier operations, applied through the data API (no bpy.ops)."""

from __future__ import annotations


def add_bevel(
    blender_object,
    width_m: float,
    segment_count: int,
):
    """Add a bevel modifier to every edge of the object."""
    bevel_modifier = blender_object.modifiers.new(name="Bevel", type="BEVEL")
    bevel_modifier.width = width_m
    bevel_modifier.segments = segment_count
    bevel_modifier.limit_method = "NONE"
    return bevel_modifier


def apply_all_modifiers(blender_object) -> None:
    """Bake the evaluated (post-modifier) mesh back into the object.

    Uses the depsgraph rather than bpy.ops.object.modifier_apply, so it
    needs no context override and works identically headless and live.
    The object must already be linked into the scene, or the evaluated
    copy will silently equal the stored mesh (see drift catalog).
    """
    import bpy

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = blender_object.evaluated_get(dependency_graph)
    baked_mesh = bpy.data.meshes.new_from_object(
        evaluated_object, depsgraph=dependency_graph
    )
    previous_mesh = blender_object.data
    blender_object.data = baked_mesh
    blender_object.modifiers.clear()
    if previous_mesh.users == 0:
        bpy.data.meshes.remove(previous_mesh)
