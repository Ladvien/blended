"""The bounded cleanup pass for generated geometry.

Order matters and every action is logged with its numbers. Two rules
from the mesh-repair literature (Attene et al.) are load-bearing:

* Hole filling is THRESHOLD-BOUNDED and reported. Blind-filling large
  holes produces "arbitrarily implausible" geometry — a hole bigger
  than the threshold is left open and reported as a remaining failure,
  never papered over.
* Cleanup is measured by the analyzer before and after. The
  CleanupReport carries both MeshReports; the claim "cleanup worked" is
  the analyzer's to make, not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from blended.analyze.mesh_checks import (
    DUPLICATE_VERTEX_DISTANCE_M,
    MeshBudget,
    MeshReport,
    analyze_object,
)

DEGENERATE_DISSOLVE_DISTANCE_M = 1.0e-6
MAXIMUM_DECIMATE_PASSES = 3
DECIMATE_UNDERSHOOT_FACTOR = 0.98


@dataclass(frozen=True)
class CleanupSettings:
    weld_distance_m: float = DUPLICATE_VERTEX_DISTANCE_M
    maximum_hole_perimeter_m: float = 0.15
    triangle_budget: int = MeshBudget().maximum_triangle_count
    decimate_to_budget: bool = True


@dataclass(frozen=True)
class CleanupReport:
    before: MeshReport
    after: MeshReport
    actions: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        return (
            f"tris {self.before.triangle_count} -> {self.after.triangle_count}"
            f" | boundary {self.before.boundary_edge_count} -> "
            f"{self.after.boundary_edge_count}"
            f" | doubles {self.before.duplicate_vertex_pair_count} -> "
            f"{self.after.duplicate_vertex_pair_count}"
        )


def _boundary_hole_groups(working_mesh):
    """Group boundary edges into connected components ('holes'), each
    with its total perimeter in meters."""
    boundary_edges = [edge for edge in working_mesh.edges if len(edge.link_faces) == 1]
    unvisited_edges = set(boundary_edges)
    hole_groups = []
    while unvisited_edges:
        seed_edge = unvisited_edges.pop()
        group_edges = [seed_edge]
        frontier = [seed_edge]
        while frontier:
            current_edge = frontier.pop()
            for edge_vertex in current_edge.verts:
                for neighbor_edge in edge_vertex.link_edges:
                    if neighbor_edge in unvisited_edges:
                        unvisited_edges.remove(neighbor_edge)
                        group_edges.append(neighbor_edge)
                        frontier.append(neighbor_edge)
        perimeter_m = sum(edge.calc_length() for edge in group_edges)
        hole_groups.append((group_edges, perimeter_m))
    return hole_groups


def cleanup_mesh(
    blender_object, settings: CleanupSettings = CleanupSettings()
) -> CleanupReport:
    """Run the bounded cleanup pass; return before/after reports."""
    import bmesh

    before_report = analyze_object(blender_object)
    actions: list[str] = []

    working_mesh = bmesh.new()
    working_mesh.from_mesh(blender_object.data)
    try:
        vertex_count_before_weld = len(working_mesh.verts)
        bmesh.ops.remove_doubles(
            working_mesh,
            verts=list(working_mesh.verts),
            dist=settings.weld_distance_m,
        )
        welded_vertex_count = vertex_count_before_weld - len(working_mesh.verts)
        if welded_vertex_count:
            actions.append(
                f"welded {welded_vertex_count} vertices within "
                f"{settings.weld_distance_m} m"
            )

        face_count_before_dissolve = len(working_mesh.faces)
        bmesh.ops.dissolve_degenerate(
            working_mesh,
            dist=DEGENERATE_DISSOLVE_DISTANCE_M,
            edges=list(working_mesh.edges),
        )
        dissolved_face_count = face_count_before_dissolve - len(working_mesh.faces)
        if dissolved_face_count:
            actions.append(f"dissolved {dissolved_face_count} degenerate faces")

        loose_vertices = [
            vertex for vertex in working_mesh.verts if not vertex.link_faces
        ]
        if loose_vertices:
            bmesh.ops.delete(working_mesh, geom=loose_vertices, context="VERTS")
            actions.append(f"deleted {len(loose_vertices)} loose vertices")

        for hole_edges, perimeter_m in _boundary_hole_groups(working_mesh):
            if perimeter_m <= settings.maximum_hole_perimeter_m:
                bmesh.ops.holes_fill(working_mesh, edges=hole_edges, sides=0)
                actions.append(
                    f"filled hole of perimeter {perimeter_m:.4f} m "
                    f"({len(hole_edges)} edges)"
                )
            else:
                actions.append(
                    f"LEFT OPEN: hole of perimeter {perimeter_m:.4f} m exceeds "
                    f"threshold {settings.maximum_hole_perimeter_m} m"
                )

        bmesh.ops.recalc_face_normals(working_mesh, faces=list(working_mesh.faces))
        actions.append("recalculated face normals outward")
        working_mesh.to_mesh(blender_object.data)
    finally:
        working_mesh.free()

    if settings.decimate_to_budget:
        for _ in range(MAXIMUM_DECIMATE_PASSES):
            interim_report = analyze_object(blender_object)
            if interim_report.triangle_count <= settings.triangle_budget:
                break
            decimate_ratio = (
                settings.triangle_budget
                / interim_report.triangle_count
                * DECIMATE_UNDERSHOOT_FACTOR
            )
            decimate_modifier = blender_object.modifiers.new(
                name="DecimateToBudget", type="DECIMATE"
            )
            decimate_modifier.decimate_type = "COLLAPSE"
            decimate_modifier.ratio = decimate_ratio
            from blended.ops.modifiers import apply_all_modifiers

            apply_all_modifiers(blender_object)
            actions.append(
                f"decimated {interim_report.triangle_count} -> target "
                f"{settings.triangle_budget} (ratio {decimate_ratio:.4f})"
            )

    after_report = analyze_object(blender_object)
    return CleanupReport(
        before=before_report, after=after_report, actions=tuple(actions)
    )
