"""Primitive construction operations.

Convention: build with bmesh / the data API, not bpy.ops primitives.
Operators depend on context (active object, mode, area) and their
keyword arguments drift across versions; bmesh construction is
context-free, deterministic, and headless-safe. This is the base
vocabulary the reusable-component library grows from.
"""

from __future__ import annotations


def add_box(
    name: str,
    width_m: float,
    depth_m: float,
    height_m: float,
    location_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    """Create a closed box mesh object of the given outer dimensions.

    The box is centered on X/Y and sits with its base at location_m[2],
    which matches the game-asset convention of feet/base at z=0.
    """
    import bmesh
    import bpy

    mesh_data = bpy.data.meshes.new(name)
    box_object = bpy.data.objects.new(name, mesh_data)

    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_cube(working_mesh, size=1.0)
        half_height_offset_m = height_m / 2.0
        for vertex in working_mesh.verts:
            vertex.co.x = vertex.co.x * width_m + location_m[0]
            vertex.co.y = vertex.co.y * depth_m + location_m[1]
            vertex.co.z = vertex.co.z * height_m + location_m[2] + half_height_offset_m
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()

    return box_object


def link_into_scene(blender_object) -> None:
    """Link an object into the active scene collection.

    Never skip this: an unlinked object has no depsgraph instance, so
    evaluated_get() silently returns stored values (see drift catalog).
    """
    import bpy

    bpy.context.scene.collection.objects.link(blender_object)
