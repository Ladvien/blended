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

from blended.ops._contract import op
from blended.ops._objects import ObjectName


def _refresh_dependency_graph() -> None:
    """Force matrix_world to reflect pending location/rotation changes."""
    import bpy

    bpy.context.view_layer.update()


@op(reads_only=True)
def world_bounds(object_name: str) -> dict[str, list[float]]:
    """Read the named object's world-space bounding box: min_m, max_m, extents_m corners of its evaluated bounds.

    Measured demand (OT-12): five escape-hatch chunks in the v12 runs
    existed only to print world extents of a target and a cutter when a
    boolean reported no overlap. The depsgraph is refreshed first
    (OPS-14) so the box is this frame's, not the previous one's.
    """
    import bpy
    from mathutils import Vector

    from blended.ops._objects import object_by_name

    blender_object = object_by_name(object_name)
    bpy.context.view_layer.update()
    corners = [blender_object.matrix_world @ Vector(corner) for corner in blender_object.bound_box]
    minimum = [min(corner[axis] for corner in corners) for axis in range(3)]
    maximum = [max(corner[axis] for corner in corners) for axis in range(3)]
    return {
        "min_m": minimum,
        "max_m": maximum,
        "extents_m": [maximum[axis] - minimum[axis] for axis in range(3)],
    }


def apply_object_transform(object_name: str) -> ObjectName:
    """Bake the named object's matrix into its mesh and reset it to identity.

    Do this before export or measurement whenever the object transform
    is not identity — analyzers and exporters that read mesh-local
    coordinates otherwise measure something the viewport does not show.
    """
    from mathutils import Matrix

    from blended.ops._objects import object_by_name

    blender_object = object_by_name(object_name, "MESH")
    _refresh_dependency_graph()
    blender_object.data.transform(blender_object.matrix_world)
    blender_object.matrix_world = Matrix.Identity(4)
    return object_name


def rotate_object_euler(
    object_name: str,
    x_rad: float = 0.0,
    y_rad: float = 0.0,
    z_rad: float = 0.0,
    order: str = "XYZ",
) -> ObjectName:
    """Set the named object's Euler rotation, in radians, about its own origin.

    Exists because the whitelisted vocabulary had no way to rotate
    anything — measured 2026-08-22: an agent asked for a stool with
    splayed legs spent three search_ops calls and a dir() probe before
    concluding "There's no rotate op", then improvised with raw
    attribute writes. Rotation is not an exotic operation; a facade that
    omits it is not a facade.

    The rotation is SET, not accumulated, so re-running a chunk is
    idempotent. The depsgraph is refreshed afterwards so the very next
    read of matrix_world is truthful — the trap that once collapsed
    three splayed legs into a central post.
    """
    from mathutils import Euler

    from blended.ops._objects import object_by_name

    blender_object = object_by_name(object_name)
    blender_object.rotation_mode = order
    blender_object.rotation_euler = Euler((x_rad, y_rad, z_rad), order)
    _refresh_dependency_graph()
    return object_name


def move_object_to(object_name: str, location_m: tuple[float, float, float]) -> ObjectName:
    """Set the named object's world location in metres, then refresh.

    Same reason as rotate_object_euler: placement is half of assembly,
    and it shares the stale-matrix_world trap.
    """
    from blended.ops._objects import object_by_name

    blender_object = object_by_name(object_name)
    blender_object.location = location_m
    _refresh_dependency_graph()
    return object_name


def snap_base_to_ground(object_name: str) -> float:
    """Move the named object so its lowest point sits exactly at z=0.

    Returns the applied z offset in meters.
    """
    from mathutils import Vector

    from blended.ops._objects import object_by_name

    blender_object = object_by_name(object_name)
    _refresh_dependency_graph()
    world_corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    lowest_z_m = min(corner.z for corner in world_corners)
    offset_z_m = -lowest_z_m
    blender_object.location.z += offset_z_m
    _refresh_dependency_graph()
    return offset_z_m


def center_on_origin_xy(object_name: str) -> ObjectName:
    """Center the named object's world-space bounds on the X/Y origin."""
    from mathutils import Vector

    from blended.ops._objects import object_by_name

    blender_object = object_by_name(object_name)
    _refresh_dependency_graph()
    world_corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    bounds_center = sum(world_corners, Vector()) / len(world_corners)
    blender_object.location.x -= bounds_center.x
    blender_object.location.y -= bounds_center.y
    _refresh_dependency_graph()
    return object_name
