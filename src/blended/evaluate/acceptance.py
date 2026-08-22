"""Executes a brief's acceptance spec against the live scene.

This is the deterministic gate for FORM, sitting beside the analyzer's
deterministic gate for STRUCTURE. Both run before any render is looked
at, because a visual critique of a scene that already failed a
measurement is wasted tokens and an invitation to argue with a number.

Everything here answers with a measurement and a delta, never a bare
boolean — "feedback as deltas" (project rule). A failure report that
says `width_x 0.284 m, expected 0.300 +/- 0.020, delta -0.016` tells the
agent what to change; `width_x: FAIL` does not.

MAIN THREAD ONLY: everything below touches bpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from blended.evaluate.briefs import (
    AssetBrief,
    ClearAxisProbe,
    DimensionSpec,
    GroundContactProbe,
    SolidityProbe,
)

# Parity ray casting. The ray starts at the probe point and marches +Z,
# counting surface crossings; an odd count means the point started
# inside solid material. Each restart is nudged past the hit it just
# found, or the same face is hit forever.
PARITY_RAY_DIRECTION = (0.0, 0.0, 1.0)
PARITY_RESTART_OFFSET_M = 1.0e-6
PARITY_MAXIMUM_CROSSINGS = 128
# How far a probe ray may travel before we call it "out of the object".
# Generous relative to prop scale; a prop that needs more than this is
# not a prop.
PARITY_RAY_LENGTH_M = 100.0


@dataclass(frozen=True)
class DimensionMeasurement:
    spec: DimensionSpec
    measured_m: float

    @property
    def delta_m(self) -> float:
        return self.measured_m - self.spec.expected_m

    @property
    def ok(self) -> bool:
        return abs(self.delta_m) <= self.spec.tolerance_m

    def describe(self) -> str:
        return (
            f"{self.spec.name}: {self.measured_m:.4f} m, expected "
            f"{self.spec.expected_m:.4f} +/- {self.spec.tolerance_m:.4f}, "
            f"delta {self.delta_m:+.4f} m"
        )


@dataclass(frozen=True)
class ProbeMeasurement:
    probe: SolidityProbe
    crossing_count: int

    @property
    def measured_inside(self) -> bool:
        return self.crossing_count % 2 == 1

    @property
    def ok(self) -> bool:
        return self.measured_inside == self.probe.expect_inside

    def describe(self) -> str:
        expected = "solid" if self.probe.expect_inside else "empty"
        measured = "solid" if self.measured_inside else "empty"
        point = ", ".join(f"{value:.3f}" for value in self.probe.point_m)
        line = (
            f"{self.probe.name}: at ({point}) expected {expected}, "
            f"measured {measured} ({self.crossing_count} surface crossings)"
        )
        return line if self.ok else f"{line} -> {self.probe.why}"


@dataclass(frozen=True)
class ClearAxisMeasurement:
    probe: ClearAxisProbe
    blocked_at_m: float | None  # None = clear line of sight

    @property
    def ok(self) -> bool:
        return self.blocked_at_m is None

    def describe(self) -> str:
        point = ", ".join(f"{value:.3f}" for value in self.probe.point_m)
        if self.ok:
            return (
                f"{self.probe.name}: {self.probe.axis}-axis through "
                f"({point}) is clear end to end"
            )
        return (
            f"{self.probe.name}: {self.probe.axis}-axis through ({point}) is "
            f"BLOCKED at {self.probe.axis}={self.blocked_at_m:.4f} m "
            f"-> {self.probe.why}"
        )


@dataclass(frozen=True)
class GroundContactMeasurement:
    """How much flat sole this foot actually puts on the floor."""

    probe: GroundContactProbe
    contact_area_m2: float
    # Faces near the foot that were rejected for NOT lying in the plane,
    # and the worst z-span among them. Zero area with rejected faces
    # means "the leg is there but its sole is angled"; zero area with
    # none means "there is no leg here at all". Different repairs.
    rejected_face_count: int
    worst_rejected_span_m: float
    # Area-weighted centroid of the flat sole: where the foot ACTUALLY
    # landed, as opposed to where the probe went looking for it.
    centroid_xy_m: tuple[float, float] = (0.0, 0.0)

    @property
    def measured_radius_m(self) -> float:
        return math.hypot(*self.centroid_xy_m)

    @property
    def measured_angle_deg(self) -> float:
        y, x = self.centroid_xy_m[1], self.centroid_xy_m[0]
        return math.degrees(math.atan2(y, x)) % 360.0

    @property
    def angle_error_deg(self) -> float:
        """Smallest signed turn from the expected bearing to the measured."""
        raw = (self.measured_angle_deg - self.probe.expected_angle_deg) % 360.0
        return raw - 360.0 if raw > 180.0 else raw

    @property
    def has_contact(self) -> bool:
        return self.contact_area_m2 >= self.probe.minimum_area_m2

    @property
    def radius_ok(self) -> bool:
        return (
            abs(self.measured_radius_m - self.probe.expected_radius_m)
            <= self.probe.radius_tolerance_m
        )

    @property
    def angle_ok(self) -> bool:
        return abs(self.angle_error_deg) <= self.probe.angle_tolerance_deg

    @property
    def ok(self) -> bool:
        # Placement is only meaningful once there is a sole to locate.
        return self.has_contact and self.radius_ok and self.angle_ok

    def describe(self) -> str:
        centre = ", ".join(f"{value:.3f}" for value in self.probe.centre_xy_m)
        line = (
            f"{self.probe.name}: at ({centre}) flat sole area "
            f"{self.contact_area_m2:.6f} m2, required "
            f"{self.probe.minimum_area_m2:.6f} m2"
        )
        if self.has_contact:
            line += (
                f"; sole centre r={self.measured_radius_m:.4f} m (expected "
                f"{self.probe.expected_radius_m:.4f} +/- "
                f"{self.probe.radius_tolerance_m:.4f}), bearing "
                f"{self.measured_angle_deg:.1f} deg (expected "
                f"{self.probe.expected_angle_deg:.1f} +/- "
                f"{self.probe.angle_tolerance_deg:.1f}, off by "
                f"{self.angle_error_deg:+.1f})"
            )
        if self.ok:
            return line
        if self.has_contact and not self.radius_ok:
            line += " — this foot is off the specified circle"
        if self.has_contact and not self.angle_ok:
            line += " — the legs are not evenly spaced"
        if self.rejected_face_count:
            line += (
                f" — {self.rejected_face_count} face(s) near this foot are "
                f"NOT level: worst spans {self.worst_rejected_span_m:.4f} m "
                f"in z against a {self.probe.planarity_tolerance_m:.4f} m "
                f"tolerance"
            )
        else:
            line += " — no face at all lies on z=0 near this foot"
        return f"{line} -> {self.probe.why}"


@dataclass(frozen=True)
class AcceptanceReport:
    """Measured facts about whether the built object matches the brief."""

    brief_name: str
    object_name: str
    object_found: bool
    # An object can exist in bpy.data and still have no depsgraph
    # instance, because construction and linking are separate steps in
    # the ops vocabulary. Unlinked, it has no evaluated mesh: probing it
    # raises instead of measuring. That is a real, common build failure
    # (the user sees an empty viewport), so it is reported as one.
    linked_into_scene: bool = False
    dimensions: tuple[DimensionMeasurement, ...] = field(default_factory=tuple)
    probes: tuple[ProbeMeasurement, ...] = field(default_factory=tuple)
    clear_axes: tuple[ClearAxisMeasurement, ...] = field(default_factory=tuple)
    ground_contacts: tuple[GroundContactMeasurement, ...] = field(
        default_factory=tuple
    )
    base_z_m: float = 0.0
    transform_is_finite: bool = True
    # Two numbers, not one. A boolean modifier leaves an EMPTY slot
    # behind (measured: len(mesh.materials) == 1, contents [None]), so a
    # slot count answers "did a modifier run", not "is this textured".
    material_slot_count: int = 0
    assigned_material_count: int = 0
    stray_object_names: tuple[str, ...] = field(default_factory=tuple)

    def failures(self, brief: AssetBrief) -> list[str]:
        """Human-readable failures (empty list = the form gate passed)."""
        if not self.object_found:
            return [
                f"no object named {self.object_name!r} in the scene "
                f"(the brief names it explicitly)"
            ]
        if not self.linked_into_scene:
            return [
                f"object {self.object_name!r} exists but is not linked into "
                f"the scene collection, so it has no evaluated mesh and does "
                f"not appear in the viewport (call ops.primitives."
                f"link_into_scene after constructing it)"
            ]
        found: list[str] = []
        if not self.transform_is_finite:
            found.append("object transform contains non-finite values")
        found.extend(
            measurement.describe()
            for measurement in self.dimensions
            if not measurement.ok
        )
        if brief.require_base_at_ground and abs(self.base_z_m) > (
            brief.grounding_tolerance_m
        ):
            found.append(
                f"base sits at z={self.base_z_m:+.4f} m, expected 0 +/- "
                f"{brief.grounding_tolerance_m:.4f} (not on the ground)"
            )
        found.extend(
            measurement.describe() for measurement in self.probes if not measurement.ok
        )
        found.extend(
            measurement.describe()
            for measurement in self.clear_axes
            if not measurement.ok
        )
        found.extend(
            measurement.describe()
            for measurement in self.ground_contacts
            if not measurement.ok
        )
        if brief.require_material and self.assigned_material_count == 0:
            found.append(
                f"no material assigned: {self.material_slot_count} slot(s), "
                f"{self.assigned_material_count} filled (an empty slot left "
                f"by a boolean modifier is not a material)"
            )
        if self.stray_object_names:
            found.append(
                f"{len(self.stray_object_names)} stray mesh object(s) left in "
                f"the scene: {', '.join(self.stray_object_names)} "
                f"(cutters and offcuts must be removed)"
            )
        return found

    def passes(self, brief: AssetBrief) -> bool:
        return not self.failures(brief)

    def summary(self, brief: AssetBrief) -> str:
        failures = self.failures(brief)
        head = f"FORM {'PASS' if not failures else 'FAIL'}: {self.brief_name}"
        if not self.object_found or not self.linked_into_scene:
            return f"{head}\n  - {failures[0]}"
        lines = [head]
        lines.extend(f"  {measurement.describe()}" for measurement in self.dimensions)
        lines.append(f"  base_z: {self.base_z_m:+.4f} m")
        lines.extend(f"  {measurement.describe()}" for measurement in self.probes)
        lines.extend(f"  {measurement.describe()}" for measurement in self.clear_axes)
        lines.extend(
            f"  {measurement.describe()}" for measurement in self.ground_contacts
        )
        lines.append(
            f"  materials: {self.assigned_material_count} assigned "
            f"in {self.material_slot_count} slot(s)"
        )
        if self.stray_object_names:
            lines.append(f"  stray objects: {', '.join(self.stray_object_names)}")
        return "\n".join(lines)


def _count_surface_crossings(evaluated_object, world_point) -> int:
    """Count +Z surface crossings above a world point. Odd = inside."""
    from mathutils import Vector

    to_local = evaluated_object.matrix_world.inverted()
    local_origin = to_local @ Vector(world_point)
    local_direction = (to_local.to_3x3() @ Vector(PARITY_RAY_DIRECTION)).normalized()

    crossing_count = 0
    cursor = local_origin.copy()
    for _ in range(PARITY_MAXIMUM_CROSSINGS):
        hit, location, _normal, _index = evaluated_object.ray_cast(
            cursor, local_direction, distance=PARITY_RAY_LENGTH_M
        )
        if not hit:
            return crossing_count
        crossing_count += 1
        cursor = location + local_direction * PARITY_RESTART_OFFSET_M
    raise RuntimeError(
        f"Parity ray from {tuple(world_point)} crossed "
        f"{PARITY_MAXIMUM_CROSSINGS} surfaces without leaving the mesh. "
        f"That is a degenerate or self-overlapping surface, not a probe "
        f"failure — fix the geometry before trusting any probe."
    )


def _find_axis_blockage(evaluated_object, probe: ClearAxisProbe) -> float | None:
    """First surface hit along the whole axis, or None if it is clear."""
    from mathutils import Vector

    axis_index = {"x": 0, "y": 1, "z": 2}[probe.axis]
    direction_world = Vector(
        tuple(1.0 if index == axis_index else 0.0 for index in range(3))
    )
    # Start beyond the far side of the object and sweep the full length,
    # so the answer covers BOTH half-spaces around the point.
    start_world = Vector(probe.point_m) - direction_world * (PARITY_RAY_LENGTH_M / 2.0)

    to_local = evaluated_object.matrix_world.inverted()
    local_origin = to_local @ start_world
    local_direction = (to_local.to_3x3() @ direction_world).normalized()

    hit, location, _normal, _index = evaluated_object.ray_cast(
        local_origin, local_direction, distance=PARITY_RAY_LENGTH_M
    )
    if not hit:
        return None
    world_hit = evaluated_object.matrix_world @ location
    return world_hit[axis_index]


def _doubled_area_vector(world_vertices):
    """Twice the area vector of a planar polygon: |v| = 2 * area, and it
    points along the outward normal.

    One computation answers both questions the sole probe asks — how big
    is this face, and which way does it face. Fan triangulation would
    overestimate a concave boolean offcut; the cross-product sum is
    exact for any simple planar polygon.
    """
    from mathutils import Vector

    total = Vector((0.0, 0.0, 0.0))
    count = len(world_vertices)
    for index in range(count):
        total = total + world_vertices[index].cross(
            world_vertices[(index + 1) % count]
        )
    return total


def _measure_sole_contact(
    evaluated_object, probe: GroundContactProbe
) -> GroundContactMeasurement:
    """Total flat-on-z=0 face area near one foot.

    Rays cannot answer this. A downward ray from above hits the seat,
    an upward ray from below hits any single point of an angled sole
    and reports z=0 just as a flat one would. Contact is an area, so
    the faces are measured directly.
    """
    mesh = evaluated_object.to_mesh()
    try:
        to_world = evaluated_object.matrix_world
        centre_x, centre_y = probe.centre_xy_m
        contact_area_m2 = 0.0
        rejected_face_count = 0
        worst_rejected_span_m = 0.0
        weighted_x = 0.0
        weighted_y = 0.0
        for polygon in mesh.polygons:
            world_vertices = [
                to_world @ mesh.vertices[index].co for index in polygon.vertices
            ]
            centroid_x = sum(vertex.x for vertex in world_vertices) / len(
                world_vertices
            )
            centroid_y = sum(vertex.y for vertex in world_vertices) / len(
                world_vertices
            )
            if (
                math.hypot(centroid_x - centre_x, centroid_y - centre_y)
                > probe.search_radius_m
            ):
                continue
            heights = [vertex.z for vertex in world_vertices]
            area_vector = _doubled_area_vector(world_vertices)
            # A candidate sole reaches the floor and faces down. The
            # leg's shaft reaches the floor too, but its normal is
            # horizontal, so it is not a near-miss sole — reporting it
            # as one would put the leg's whole LENGTH in the tilt
            # report instead of the cap's tilt.
            reaches_the_floor = min(heights) <= probe.planarity_tolerance_m
            faces_down = area_vector.z < 0.0
            if not (reaches_the_floor and faces_down):
                continue
            # One condition covers both remaining questions: every vertex
            # within tolerance of z=0 means the face is level AND lying
            # on the floor rather than tilted up off it.
            if max(abs(height) for height in heights) <= probe.planarity_tolerance_m:
                face_area_m2 = area_vector.length / 2.0
                contact_area_m2 += face_area_m2
                weighted_x += centroid_x * face_area_m2
                weighted_y += centroid_y * face_area_m2
                continue
            rejected_face_count += 1
            worst_rejected_span_m = max(
                worst_rejected_span_m, max(heights) - min(heights)
            )
        centroid_xy_m = (
            (weighted_x / contact_area_m2, weighted_y / contact_area_m2)
            if contact_area_m2 > 0.0
            else (0.0, 0.0)
        )
        return GroundContactMeasurement(
            probe=probe,
            contact_area_m2=contact_area_m2,
            rejected_face_count=rejected_face_count,
            worst_rejected_span_m=worst_rejected_span_m,
            centroid_xy_m=centroid_xy_m,
        )
    finally:
        evaluated_object.to_mesh_clear()


def evaluate_brief(brief: AssetBrief) -> AcceptanceReport:
    """Measure the live scene against one brief's acceptance spec."""
    import bpy
    from mathutils import Vector

    bpy.context.view_layer.update()
    blender_object = bpy.data.objects.get(brief.object_name)
    if blender_object is None or blender_object.type != "MESH":
        return AcceptanceReport(
            brief_name=brief.name,
            object_name=brief.object_name,
            object_found=False,
            stray_object_names=tuple(
                scene_object.name
                for scene_object in bpy.context.scene.objects
                if scene_object.type == "MESH"
            ),
        )

    linked_into_scene = blender_object.name in bpy.context.scene.objects
    if not linked_into_scene:
        return AcceptanceReport(
            brief_name=brief.name,
            object_name=brief.object_name,
            object_found=True,
            linked_into_scene=False,
        )

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = blender_object.evaluated_get(depsgraph)

    matrix_values = [value for row in blender_object.matrix_world for value in row]
    transform_is_finite = all(math.isfinite(value) for value in matrix_values)

    corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    extents = {
        axis: (
            max(corner[index] for corner in corners)
            - min(corner[index] for corner in corners)
        )
        for index, axis in enumerate(("x", "y", "z"))
    }
    base_z_m = min(corner.z for corner in corners)

    dimensions = tuple(
        DimensionMeasurement(spec=spec, measured_m=extents[spec.axis])
        for spec in brief.dimensions
    )
    probes = tuple(
        ProbeMeasurement(
            probe=probe,
            crossing_count=_count_surface_crossings(evaluated_object, probe.point_m),
        )
        for probe in brief.probes
    )
    clear_axes = tuple(
        ClearAxisMeasurement(
            probe=probe,
            blocked_at_m=_find_axis_blockage(evaluated_object, probe),
        )
        for probe in brief.clear_axes
    )
    ground_contacts = tuple(
        _measure_sole_contact(evaluated_object, probe)
        for probe in brief.ground_contacts
    )
    stray_object_names = tuple(
        scene_object.name
        for scene_object in bpy.context.scene.objects
        if scene_object.type == "MESH" and scene_object.name != brief.object_name
    )
    return AcceptanceReport(
        brief_name=brief.name,
        object_name=brief.object_name,
        object_found=True,
        linked_into_scene=True,
        dimensions=dimensions,
        probes=probes,
        clear_axes=clear_axes,
        ground_contacts=ground_contacts,
        base_z_m=base_z_m,
        transform_is_finite=transform_is_finite,
        material_slot_count=len(blender_object.data.materials),
        assigned_material_count=sum(
            1 for material in blender_object.data.materials if material is not None
        ),
        stray_object_names=stray_object_names,
    )
