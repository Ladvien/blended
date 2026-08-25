"""Pairwise checks between two parts of an assembly: interpenetration
and surface separation.

The assembly briefs relate parts by position (StackedOnSpec,
SharedCentreSpec); nothing measures whether one part intersects
another. scp built the equivalent check against mesh VERTICES first and
it lied: palm-to-weapon distance read 60 mm against vertices and 6.5 mm
against the mesh SURFACE, because on box geometry the nearest vertex is
a far corner. So separation is measured on the surface, never on
vertices.

Interpenetration is a DEPTH, not a face count. Two parts that rest on
each other (a lid on its crate's rim) legitimately share coplanar
faces and even interpenetrate by the resting tolerance (the golden
crate's lid sits ~1 mm into the rim and was human-signed-off). The
face-pair crossing tests fail to distinguish: on axis-aligned boxes
every penetrating face pair touches the other solid along a
zero-depth line. So the measurement is the object-level penetration —
the minimum translation depth between the two evaluated meshes' world
AABBs — and a pair count is reported only when that depth exceeds the
contact tolerance. The count itself is the BVH AABB-overlap pair list,
the same broad phase `_count_self_intersecting_pairs` uses.

MAIN THREAD ONLY: everything below touches bpy/mathutils.
"""

from __future__ import annotations

from dataclasses import dataclass

# Separation samples are capped so a dense mesh does not make the
# measurement O(vertices) against the other object's BVH.
PAIR_SEPARATION_SAMPLE_LIMIT = 512

# How deep a penetration must be to count as interpenetration rather
# than resting contact. Matches the crate-with-lid stack tolerance
# (GROUNDING_TOLERANCE_M): a lidar sunk up to 2 mm into the rim reads
# as "resting on", anything deeper reads as "sunk into".
CONTACT_DEPTH_TOLERANCE_M = 0.002


@dataclass(frozen=True)
class PairReport:
    first_object_name: str
    second_object_name: str
    intersecting_face_pair_count: int
    minimum_separation_m: float


def _world_bounds(first_mesh, first_to_world, second_mesh, second_to_world):
    """Per-axis world-space min/max for both evaluated meshes."""
    first_minima = [float("inf")] * 3
    first_maxima = [-float("inf")] * 3
    for vertex in first_mesh.vertices:
        world = first_to_world @ vertex.co
        for axis in range(3):
            first_minima[axis] = min(first_minima[axis], world[axis])
            first_maxima[axis] = max(first_maxima[axis], world[axis])
    second_minima = [float("inf")] * 3
    second_maxima = [-float("inf")] * 3
    for vertex in second_mesh.vertices:
        world = second_to_world @ vertex.co
        for axis in range(3):
            second_minima[axis] = min(second_minima[axis], world[axis])
            second_maxima[axis] = max(second_maxima[axis], world[axis])
    return (
        (first_minima, first_maxima),
        (second_minima, second_maxima),
    )


def _penetration_depth_m(first_bounds, second_bounds) -> float:
    """The minimum translation depth of the two AABB solids, or 0.0
    when they do not overlap. For the crate: the lidar's bottom enters
    the body's rim by the vertical sink (0.001 m in the golden, 0.03 m
    when sunk); for two overlapping boxes: the shared x extent.
    """
    (first_minima, first_maxima), (second_minima, second_maxima) = (
        first_bounds,
        second_bounds,
    )
    overlaps = []
    for axis in range(3):
        overlap = min(first_maxima[axis], second_maxima[axis]) - max(
            first_minima[axis], second_minima[axis]
        )
        if overlap <= 0.0:
            return 0.0  # separated on this axis: no interpenetration
        overlaps.append(overlap)
    return min(overlaps)


def analyze_pair(first_object, second_object) -> PairReport:
    """Measure one object against another.

    ``intersecting_face_pair_count``: the BVH broad-phase face pairs of
    the two evaluated meshes' world-space triangles, but only when the
    object-level penetration depth exceeds
    ``CONTACT_DEPTH_TOLERANCE_M``. Resting contact (a lidar on its
    crate, sink within 2 mm) reads zero.

    ``minimum_separation_m``: for the first object's evaluated vertices
    in world space — all of them when under
    ``PAIR_SEPARATION_SAMPLE_LIMIT``, else every
    ``ceil(count / limit)``-th — the closest surface point of the
    second object, in world distance. Surface, never nearest-vertex.
    """
    import bpy
    from mathutils.bvhtree import BVHTree

    dependency_graph = bpy.context.evaluated_depsgraph_get()

    first_evaluated = first_object.evaluated_get(dependency_graph)
    first_mesh = first_evaluated.to_mesh()
    second_evaluated = second_object.evaluated_get(dependency_graph)
    second_mesh = second_evaluated.to_mesh()
    try:
        first_mesh.calc_loop_triangles()
        second_mesh.calc_loop_triangles()
        first_to_world = first_evaluated.matrix_world
        second_to_world = second_evaluated.matrix_world

        first_bounds, second_bounds = _world_bounds(
            first_mesh, first_to_world, second_mesh, second_to_world
        )
        penetration_m = _penetration_depth_m(first_bounds, second_bounds)

        intersecting_pair_count = 0
        if penetration_m > CONTACT_DEPTH_TOLERANCE_M:
            # The solids really overlap: count the face pairs whose
            # bounding volumes overlap — the same broad phase the
            # self-intersection checker uses.
            first_vertex_coordinates = [
                tuple(first_to_world @ vertex.co) for vertex in first_mesh.vertices
            ]
            first_triangles = [
                tuple(loop_triangle.vertices)
                for loop_triangle in first_mesh.loop_triangles
            ]
            second_vertex_coordinates = [
                tuple(second_to_world @ vertex.co) for vertex in second_mesh.vertices
            ]
            second_triangles = [
                tuple(loop_triangle.vertices)
                for loop_triangle in second_mesh.loop_triangles
            ]
            if first_triangles and second_triangles:
                first_tree = BVHTree.FromPolygons(
                    first_vertex_coordinates, first_triangles
                )
                second_tree = BVHTree.FromPolygons(
                    second_vertex_coordinates, second_triangles
                )
                intersecting_pair_count = len(first_tree.overlap(second_tree))

        second_to_local = second_to_world.inverted()
        minimum_world_distance = None
        vertex_count = len(first_mesh.vertices)
        if vertex_count:
            sample_step = (
                1
                if vertex_count <= PAIR_SEPARATION_SAMPLE_LIMIT
                else -(-vertex_count // PAIR_SEPARATION_SAMPLE_LIMIT)
            )
            for vertex_index in range(0, vertex_count, sample_step):
                world_point = first_to_world @ first_mesh.vertices[vertex_index].co
                second_local_point = second_to_local @ world_point
                hit, location, _normal, _index = (
                    second_evaluated.closest_point_on_mesh(second_local_point)
                )
                if not hit:
                    continue
                world_closest = second_to_world @ location
                distance_m = (world_closest - world_point).length
                if (
                    minimum_world_distance is None
                    or distance_m < minimum_world_distance
                ):
                    minimum_world_distance = distance_m
    finally:
        first_evaluated.to_mesh_clear()
        second_evaluated.to_mesh_clear()

    return PairReport(
        first_object_name=first_object.name,
        second_object_name=second_object.name,
        intersecting_face_pair_count=intersecting_pair_count,
        minimum_separation_m=(
            minimum_world_distance
            if minimum_world_distance is not None
            else float("inf")
        ),
    )
