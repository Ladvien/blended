"""The mesh analyzer: the hard acceptance gate.

The agentic-3D literature is unanimous that once a script executes, the
remaining failures are structural (disconnected components, bad
geometry) and are NOT fixed by more agent autonomy (3DCodeBench) and
NOT reliably caught by VLM screenshot critique (TikZ study: verifiers
are biased toward accepting). So the gate is this analyzer, and the
render critique is advisory.

Check list follows the Attene/Campen/Kobbelt repair taxonomy for
*designed* meshes: non-manifoldness, gaps (boundary edges),
degeneracies, disconnected components.
"""

from __future__ import annotations

from dataclasses import dataclass

# A face smaller than this is degenerate: it breaks normal, circumcenter
# and barycentric computation downstream (Attene et al. 2013).
ZERO_AREA_EPSILON_M2 = 1.0e-9

# Vertices closer than this are treated as accidental doubles.
DUPLICATE_VERTEX_DISTANCE_M = 1.0e-5

# Vaughan, "Digital Modeling" p.340: 1,500-2,000 polys for a real-time
# weapon prop. Default budget for simple props sits at the top of that.
DEFAULT_PROP_TRIANGLE_BUDGET = 2_000


@dataclass(frozen=True)
class MeshBudget:
    """What a mesh must satisfy to pass the gate."""

    maximum_triangle_count: int = DEFAULT_PROP_TRIANGLE_BUDGET
    require_manifold: bool = True
    allow_boundary_edges: bool = False
    maximum_component_count: int = 1
    allow_self_intersections: bool = False
    allow_flipped_normals: bool = False


@dataclass(frozen=True)
class MeshReport:
    """Measured facts about one mesh object. Numbers, not opinions."""

    object_name: str
    triangle_count: int
    non_manifold_edge_count: int
    boundary_edge_count: int
    zero_area_face_count: int
    non_finite_coordinate_count: int
    connected_component_count: int
    duplicate_vertex_pair_count: int
    self_intersecting_face_pair_count: int
    flipped_normal_triangle_count: int

    def failures(self, budget: MeshBudget) -> list[str]:
        """Return human-readable failures against a budget (empty = pass)."""
        found_failures: list[str] = []
        if self.triangle_count > budget.maximum_triangle_count:
            found_failures.append(
                f"triangle count {self.triangle_count} exceeds budget "
                f"{budget.maximum_triangle_count}"
            )
        if budget.require_manifold and self.non_manifold_edge_count > 0:
            found_failures.append(
                f"{self.non_manifold_edge_count} non-manifold edges"
            )
        if not budget.allow_boundary_edges and self.boundary_edge_count > 0:
            found_failures.append(
                f"{self.boundary_edge_count} boundary edges (open mesh)"
            )
        if self.zero_area_face_count > 0:
            found_failures.append(
                f"{self.zero_area_face_count} zero-area faces"
            )
        if self.non_finite_coordinate_count > 0:
            found_failures.append(
                f"{self.non_finite_coordinate_count} non-finite coordinates"
            )
        if self.connected_component_count > budget.maximum_component_count:
            found_failures.append(
                f"{self.connected_component_count} disconnected components "
                f"(budget {budget.maximum_component_count})"
            )
        if self.duplicate_vertex_pair_count > 0:
            found_failures.append(
                f"{self.duplicate_vertex_pair_count} duplicate vertex pairs "
                f"within {DUPLICATE_VERTEX_DISTANCE_M} m"
            )
        if (
            not budget.allow_self_intersections
            and self.self_intersecting_face_pair_count > 0
        ):
            found_failures.append(
                f"{self.self_intersecting_face_pair_count} self-intersecting "
                f"face pairs (join-without-union is the usual cause)"
            )
        if (
            not budget.allow_flipped_normals
            and self.flipped_normal_triangle_count > 0
        ):
            found_failures.append(
                f"{self.flipped_normal_triangle_count} triangles face inward "
                f"(flipped normals)"
            )
        return found_failures

    def passes(self, budget: MeshBudget) -> bool:
        return not self.failures(budget)


def _count_connected_components(working_mesh) -> int:
    """Count edge-connected vertex components with an iterative flood fill."""
    unvisited_vertices = set(working_mesh.verts)
    component_count = 0
    while unvisited_vertices:
        component_count += 1
        frontier = [unvisited_vertices.pop()]
        while frontier:
            current_vertex = frontier.pop()
            for connected_edge in current_vertex.link_edges:
                neighbor_vertex = connected_edge.other_vert(current_vertex)
                if neighbor_vertex in unvisited_vertices:
                    unvisited_vertices.remove(neighbor_vertex)
                    frontier.append(neighbor_vertex)
    return component_count


def _count_self_intersecting_pairs(evaluated_mesh) -> int:
    """Count non-adjacent triangle pairs whose bounding volumes overlap
    and whose triangles actually intersect (BVH self-overlap).

    Pairs sharing any vertex are skipped: mesh adjacency always
    "overlaps" and is not a defect. What remains is real geometry
    passing through other geometry — the signature of a join that
    should have been a boolean union, or of a bad boolean.
    """
    from mathutils.bvhtree import BVHTree

    evaluated_mesh.calc_loop_triangles()
    vertex_coordinates = [vertex.co[:] for vertex in evaluated_mesh.vertices]
    triangles = [
        tuple(loop_triangle.vertices)
        for loop_triangle in evaluated_mesh.loop_triangles
    ]
    if not triangles:
        return 0
    bvh_tree = BVHTree.FromPolygons(vertex_coordinates, triangles)
    intersecting_pair_count = 0
    for first_index, second_index in bvh_tree.overlap(bvh_tree):
        if first_index >= second_index:
            continue  # symmetric duplicate or self-pair
        if set(triangles[first_index]) & set(triangles[second_index]):
            continue  # adjacency, not a defect
        intersecting_pair_count += 1
    return intersecting_pair_count


# Ray-parity constants for flipped-normal detection.
PARITY_RAY_OFFSET_M = 1.0e-5
PARITY_MAXIMUM_CASTS = 64


def _count_flipped_normal_triangles(evaluated_mesh) -> int:
    """Count triangles whose normal points into the solid (ray parity).

    For each triangle, step epsilon along its normal and count surface
    crossings out to infinity: an even count means the step landed
    outside (normal is outward-correct), an odd count means it landed
    inside (the triangle is flipped). Simplified single-ray variant of
    Takayama et al.'s visibility voting; only meaningful for closed
    manifold meshes, so the caller gates on that.
    """
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    evaluated_mesh.calc_loop_triangles()
    vertex_coordinates = [vertex.co[:] for vertex in evaluated_mesh.vertices]
    triangles = [
        tuple(loop_triangle.vertices)
        for loop_triangle in evaluated_mesh.loop_triangles
    ]
    if not triangles:
        return 0
    bvh_tree = BVHTree.FromPolygons(vertex_coordinates, triangles)

    flipped_count = 0
    for loop_triangle in evaluated_mesh.loop_triangles:
        triangle_normal = Vector(loop_triangle.normal)
        centroid = Vector((0.0, 0.0, 0.0))
        for vertex_index in loop_triangle.vertices:
            centroid += Vector(vertex_coordinates[vertex_index])
        centroid /= 3.0

        ray_origin = centroid + triangle_normal * PARITY_RAY_OFFSET_M
        crossing_count = 0
        for _ in range(PARITY_MAXIMUM_CASTS):
            hit_location = bvh_tree.ray_cast(ray_origin, triangle_normal)[0]
            if hit_location is None:
                break
            crossing_count += 1
            ray_origin = hit_location + triangle_normal * PARITY_RAY_OFFSET_M
        if crossing_count % 2 == 1:
            flipped_count += 1
    return flipped_count


def analyze_object(blender_object) -> MeshReport:
    """Measure the object's *evaluated* mesh (modifiers included).

    Measures the mesh itself, never a derivation shared with the builder
    that made it — the analyzer must be able to fail.
    """
    import math

    import bmesh
    import bpy

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = blender_object.evaluated_get(dependency_graph)
    evaluated_mesh = evaluated_object.to_mesh()
    try:
        working_mesh = bmesh.new()
        working_mesh.from_mesh(evaluated_mesh)
        try:
            triangle_count = sum(
                len(face.verts) - 2 for face in working_mesh.faces
            )
            non_manifold_edge_count = sum(
                1 for edge in working_mesh.edges if len(edge.link_faces) > 2
            )
            boundary_edge_count = sum(
                1 for edge in working_mesh.edges if len(edge.link_faces) == 1
            )
            zero_area_face_count = sum(
                1
                for face in working_mesh.faces
                if face.calc_area() < ZERO_AREA_EPSILON_M2
            )
            non_finite_coordinate_count = sum(
                1
                for vertex in working_mesh.verts
                for coordinate in vertex.co
                if not math.isfinite(coordinate)
            )
            connected_component_count = _count_connected_components(
                working_mesh
            )
            duplicate_search = bmesh.ops.find_doubles(
                working_mesh,
                verts=list(working_mesh.verts),
                dist=DUPLICATE_VERTEX_DISTANCE_M,
            )
            duplicate_vertex_pair_count = len(duplicate_search["targetmap"])
            self_intersecting_face_pair_count = (
                _count_self_intersecting_pairs(evaluated_mesh)
            )
            # Parity is only meaningful on closed manifold geometry;
            # open/non-manifold meshes already fail their own checks.
            if boundary_edge_count == 0 and non_manifold_edge_count == 0:
                flipped_normal_triangle_count = (
                    _count_flipped_normal_triangles(evaluated_mesh)
                )
            else:
                flipped_normal_triangle_count = 0
        finally:
            working_mesh.free()
    finally:
        evaluated_object.to_mesh_clear()

    return MeshReport(
        object_name=blender_object.name,
        triangle_count=triangle_count,
        non_manifold_edge_count=non_manifold_edge_count,
        boundary_edge_count=boundary_edge_count,
        zero_area_face_count=zero_area_face_count,
        non_finite_coordinate_count=non_finite_coordinate_count,
        connected_component_count=connected_component_count,
        duplicate_vertex_pair_count=duplicate_vertex_pair_count,
        self_intersecting_face_pair_count=self_intersecting_face_pair_count,
        flipped_normal_triangle_count=flipped_normal_triangle_count,
    )
