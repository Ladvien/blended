"""Transform operations through the data API (no bpy.ops, no context)."""

from __future__ import annotations


def apply_object_transform(blender_object) -> None:
    """Bake the object's matrix into its mesh and reset it to identity.

    Do this before export or measurement whenever the object transform
    is not identity — analyzers and exporters that read mesh-local
    coordinates otherwise measure something the viewport does not show.
    """
    from mathutils import Matrix

    blender_object.data.transform(blender_object.matrix_world)
    blender_object.matrix_world = Matrix.Identity(4)


def snap_base_to_ground(blender_object) -> float:
    """Move the object so its lowest point sits exactly at z=0.

    Returns the applied z offset in meters. Uses world-space bounds, so
    apply transforms first if the object has any.
    """
    from mathutils import Vector

    world_corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    lowest_z_m = min(corner.z for corner in world_corners)
    offset_z_m = -lowest_z_m
    blender_object.location.z += offset_z_m
    return offset_z_m


def center_on_origin_xy(blender_object) -> None:
    """Center the object's world-space bounds on the X/Y origin."""
    from mathutils import Vector

    world_corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    bounds_center = sum(world_corners, Vector()) / len(world_corners)
    blender_object.location.x -= bounds_center.x
    blender_object.location.y -= bounds_center.y
