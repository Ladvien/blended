"""Primitive construction operations.

Convention: build with bmesh / the data API, not bpy.ops primitives.
Operators depend on context (active object, mode, area) and their
keyword arguments drift across versions; bmesh construction is
context-free, deterministic, and headless-safe. This is the base
vocabulary the reusable-component library grows from — executable code
as the action space (CodeAct, DOI 10.48550/arXiv.2402.01030) over a
surface that survives Blender's API drift (BlenderLLM,
DOI 10.48550/arXiv.2412.14203).

Convention: construction is IDEMPOTENT BY NAME. A failed attempt leaves
its partial objects in the scene; re-creating under the same name would
silently become "Name.001" while lookups still find the stale "Name"
(measured in the stage-1 retry test — see drift catalog). So every
constructor first removes any existing object with its target name.
"""

from __future__ import annotations

from blended.ops._contract import op
from blended.ops._objects import ObjectName


@op(gated=False)
def add_box(
    name: str,
    width_m: float,
    depth_m: float,
    height_m: float,
    location_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> ObjectName:
    """Create a closed box mesh object of the given outer dimensions.

    The box is centered on X/Y and sits with its base at location_m[2],
    which matches the game-asset convention of feet/base at z=0.
    """
    import bmesh
    import bpy

    remove_object_and_mesh(name)
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

    return box_object.name


def link_into_scene(object_name: str) -> ObjectName:
    """Link the named object into the active scene collection.

    Never skip this: an unlinked object has no depsgraph instance, so
    evaluated_get() silently returns stored values (see drift catalog).
    """
    import bpy

    from blended.ops._objects import object_by_name

    blender_object = object_by_name(object_name)
    collection = bpy.context.scene.collection
    # Idempotent by name like every constructor: the gate (OT-5) makes
    # linking the first measured step, and a second link must not fail.
    if blender_object.name not in collection.objects:
        collection.objects.link(blender_object)
    return ObjectName(object_name)


def remove_object_and_mesh(object_name: str) -> None:
    """Remove an object (and its now-orphaned mesh) by exact name.

    The idempotency primitive: constructors call this first so a rerun
    after a failed attempt replaces the stale object instead of silently
    creating a .001-suffixed sibling on top of it.
    """
    import bpy

    existing_object = bpy.data.objects.get(object_name)
    if existing_object is None:
        return
    existing_mesh = existing_object.data
    bpy.data.objects.remove(existing_object)
    if existing_mesh is not None and existing_mesh.users == 0:
        bpy.data.meshes.remove(existing_mesh)


@op(gated=False)
def add_cylinder(
    name: str,
    radius_m: float,
    height_m: float,
    segment_count: int = 24,
    location_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> ObjectName:
    """Create a closed cylinder mesh object, base at location_m[2], idempotent by name."""
    import bmesh
    import bpy

    remove_object_and_mesh(name)
    mesh_data = bpy.data.meshes.new(name)
    cylinder_object = bpy.data.objects.new(name, mesh_data)

    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_cone(
            working_mesh,
            cap_ends=True,
            cap_tris=False,
            segments=segment_count,
            radius1=radius_m,
            radius2=radius_m,
            depth=height_m,
        )
        half_height_offset_m = height_m / 2.0
        for vertex in working_mesh.verts:
            vertex.co.x += location_m[0]
            vertex.co.y += location_m[1]
            vertex.co.z += location_m[2] + half_height_offset_m
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()

    return cylinder_object.name
