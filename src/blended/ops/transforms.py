"""Transform operations through the data API (no bpy.ops, no context).

Every op here reads `matrix_world`, which Blender evaluates LAZILY:
setting `.location` or `.rotation_euler` does NOT update it until the
dependency graph runs. Reading it before then returns the STALE matrix
(identity on a fresh object) and the transform silently does nothing —
no error, no warning. Measured: an agent set rotation and location,
called apply_object_transform, and its vertices were untouched, so
three splayed stool legs collapsed into a single central post.

So every function here refreshes the depsgraph first. See the drift
catalog.
"""

from __future__ import annotations


def _refresh_dependency_graph() -> None:
    """Force matrix_world to reflect pending location/rotation changes."""
    import bpy

    bpy.context.view_layer.update()


def apply_object_transform(blender_object) -> None:
    """Bake the object's matrix into its mesh and reset it to identity.

    Do this before export or measurement whenever the object transform
    is not identity — analyzers and exporters that read mesh-local
    coordinates otherwise measure something the viewport does not show.
    """
    from mathutils import Matrix

    _refresh_dependency_graph()
    blender_object.data.transform(blender_object.matrix_world)
    blender_object.matrix_world = Matrix.Identity(4)


def snap_base_to_ground(blender_object) -> float:
    """Move the object so its lowest point sits exactly at z=0.

    Returns the applied z offset in meters.
    """
    from mathutils import Vector

    _refresh_dependency_graph()
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

    _refresh_dependency_graph()
    world_corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    bounds_center = sum(world_corners, Vector()) / len(world_corners)
    blender_object.location.x -= bounds_center.x
    blender_object.location.y -= bounds_center.y
