"""The acceptance gate must be able to FAIL.

Project rule 9: every validator ships with a seeded-defect test that
trips it. The acceptance gate is what decides whether a convergence
iteration passed, so a check here that cannot fail would silently
certify every prompt revision as converged.

Each test builds the defect deliberately, then asserts that exactly the
intended check trips — not merely that something failed.
"""

from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


# Where the blind recess bottoms out, as a fraction of floor thickness.
# It must sit BELOW the parity probe point (floor thickness / 2) or the
# fixture stops reproducing the iteration-1 failure: the probe would land
# in solid material and the old spec would catch the defect by accident.
BLIND_RECESS_FLOOR_FRACTION = 0.25


def _assign_material(blender_object, material_name="TestMaterial"):
    material = bpy.data.materials.new(material_name)
    blender_object.data.materials.append(material)


def _build_planter(
    *,
    hollow: bool = True,
    drain_hole: bool = True,
    with_material: bool = True,
    width_scale: float = 1.0,
    leave_stray_cutter: bool = False,
    drain_is_blind_recess: bool = False,
):
    """Build the planter the brief describes, with optional seeded defects."""
    from blended.evaluate import briefs
    from blended.ops.booleans import boolean_difference
    from blended.ops.primitives import add_box, add_cylinder, link_into_scene
    from blended.ops.transforms import snap_base_to_ground

    wall = briefs.PLANTER_WALL_THICKNESS_M
    body = add_box(
        "PlanterBox",
        width_m=briefs.PLANTER_WIDTH_X_M * width_scale,
        depth_m=briefs.PLANTER_DEPTH_Y_M,
        height_m=briefs.PLANTER_HEIGHT_Z_M,
    )
    link_into_scene(body)
    snap_base_to_ground(body)

    if hollow:
        # Cavity: open at the top, so it rises above the rim.
        cavity_height = briefs.PLANTER_HEIGHT_Z_M
        cavity = add_box(
            "Cavity",
            width_m=briefs.PLANTER_WIDTH_X_M * width_scale - 2 * wall,
            depth_m=briefs.PLANTER_DEPTH_Y_M - 2 * wall,
            height_m=cavity_height,
            location_m=(0.0, 0.0, wall + cavity_height / 2.0),
        )
        link_into_scene(cavity)
        boolean_difference(body, cavity)

    if drain_hole:
        # A cutter spanning well past both faces of the floor: a real
        # through-hole. `drain_is_blind_recess` instead stops the cutter
        # inside the floor, leaving the bottom sealed.
        cutter_base_z_m = (
            wall * BLIND_RECESS_FLOOR_FRACTION
            if drain_is_blind_recess
            else -briefs.PLANTER_HEIGHT_Z_M
        )
        cutter_height_m = (
            briefs.PLANTER_HEIGHT_Z_M
            if drain_is_blind_recess
            else briefs.PLANTER_HEIGHT_Z_M * 2.0
        )
        drain = add_cylinder(
            "Drain",
            radius_m=briefs.PLANTER_DRAIN_HOLE_RADIUS_M,
            height_m=cutter_height_m,
            location_m=(0.0, 0.0, cutter_base_z_m),
        )
        link_into_scene(drain)
        boolean_difference(body, drain)

    if leave_stray_cutter:
        link_into_scene(add_cylinder("LeftoverCutter", radius_m=0.01, height_m=0.01))

    if with_material:
        _assign_material(body)
    bpy.context.view_layer.update()
    return body


def _failure_names(report, brief):
    """The set of spec names that tripped, for exact-cause assertions."""
    tripped = set()
    for measurement in report.dimensions:
        if not measurement.ok:
            tripped.add(measurement.spec.name)
    for measurement in report.probes:
        if not measurement.ok:
            tripped.add(measurement.probe.name)
    for measurement in report.clear_axes:
        if not measurement.ok:
            tripped.add(measurement.probe.name)
    for measurement in report.ground_contacts:
        if not measurement.ok:
            tripped.add(measurement.probe.name)
    return tripped


def test_correct_planter_passes_every_check(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter()
    report = evaluate_brief(brief)
    assert report.passes(brief), report.summary(brief)


def test_sealed_drain_hole_trips_the_drain_checks_and_nothing_else(empty_scene):
    """The canonical wrong-object failure: hollow, but no drainage.

    A hole that was never cut fails BOTH drain checks — there is no
    material missing at the probe point and no line of sight through
    the floor. Nothing else may trip: the box is otherwise correct.
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(drain_hole=False)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert _failure_names(report, brief) == {
        "drain_hole_is_open",
        "drain_hole_goes_all_the_way_through",
    }


def test_solid_block_trips_the_hollow_probe(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(hollow=False, drain_hole=False)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert "interior_is_hollow" in _failure_names(report, brief)
    assert "drain_hole_is_open" in _failure_names(report, brief)


def test_wrong_width_trips_the_dimension_spec(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(width_scale=1.5)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert "width_x" in _failure_names(report, brief)
    width = next(m for m in report.dimensions if m.spec.name == "width_x")
    assert width.delta_m > 0, width.describe()


def test_missing_material_trips_the_material_check(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(with_material=False)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert any("no material" in failure for failure in report.failures(brief))


def test_stray_cutter_trips_the_stray_check(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(leave_stray_cutter=True)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert report.stray_object_names == ("LeftoverCutter",)


def test_missing_object_reports_not_found(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    report = evaluate_brief(brief)

    assert not report.object_found
    assert not report.passes(brief)
    assert "PlanterBox" in report.failures(brief)[0]


def test_ungrounded_object_trips_the_grounding_check(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    body = _build_planter()
    body.location.z += 0.5
    bpy.context.view_layer.update()
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert any("not on the ground" in failure for failure in report.failures(brief))


def test_unlinked_object_reports_a_measurement_not_a_crash(empty_scene):
    """Construction and linking are separate ops; forgetting the second
    one leaves an object that exists, has no evaluated mesh, and shows
    nothing in the viewport. Probing it used to raise."""
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief
    from blended.ops.primitives import add_box

    brief = get_brief("planter_box")
    add_box("PlanterBox", width_m=0.3, depth_m=0.2, height_m=0.25)
    report = evaluate_brief(brief)

    assert report.object_found
    assert not report.linked_into_scene
    assert not report.passes(brief)
    assert "not linked into the scene" in report.failures(brief)[0]


# --- The stool brief must be SATISFIABLE ------------------------------
# A convergence loop against an impossible acceptance spec burns its
# whole iteration budget and blames the prompt. So the spec is proven
# reachable by a reference build before any agent is asked to hit it.
# This build is also the assembly-level regression fixture.


# How far below the floor the sole-flattening cutter reaches. Only its
# TOP face matters (it sits on z=0); the depth just has to clear the
# lowest point any tilted leg end can reach.
SOLE_CUTTER_DEPTH_M = 0.1
# Extra drop beyond the geometric minimum, so the whole tilted end cap
# clears the cut plane rather than grazing it.
SOLE_OVERHANG_MARGIN_M = 0.005


def _build_reference_stool(*, angled_feet: bool = False, leg_angles_deg=None):
    """A stool that satisfies THREE_LEG_STOOL_BRIEF, built from the
    whitelisted ops only.

    `angled_feet=True` seeds the iteration-4 defect: the legs are tilted
    cylinders, so their end caps are tilted too, and the stool is then
    dropped onto z=0 by its lowest POINT. Grounding passes; the stool
    rocks on three edges.
    """
    import math

    from mathutils import Euler

    from blended.evaluate import briefs
    from blended.ops.booleans import boolean_difference, boolean_union
    from blended.ops.primitives import add_box, add_cylinder, link_into_scene
    from blended.ops.transforms import apply_object_transform, snap_base_to_ground

    seat_radius_m = briefs.STOOL_SEAT_DIAMETER_M / 2.0
    leg_radius_m = 0.022
    # Legs run from under the seat out to the foot circle. Length is the
    # hypotenuse of that rise and that outward run.
    leg_top_radius_m = seat_radius_m * 0.45
    rise_m = briefs.STOOL_TOTAL_HEIGHT_Z_M - briefs.STOOL_SEAT_THICKNESS_M
    run_m = briefs.STOOL_FOOT_CIRCLE_RADIUS_M - leg_top_radius_m
    splay_rad = math.atan2(run_m, rise_m)
    # The naive construction stands the leg base on the floor and never
    # cuts, which is exactly how iteration 4 built it. The correct one
    # drops the leg until its whole tilted end cap clears the cut plane;
    # otherwise the cap crosses z=0 — high on the outer side, low on the
    # inner — and the cut leaves a crescent whose centroid sits inboard.
    # Measured: that lands the sole at r=0.1281 against a specified
    # 0.1400, which the placement probe correctly rejects.
    overhang_m = (
        0.0
        if angled_feet
        else leg_radius_m / math.cos(splay_rad) + SOLE_OVERHANG_MARGIN_M
    )
    # Exactly the drop, no more: the leg has to regain the length it
    # loses going below the floor, or it no longer meets the seat.
    leg_length_m = math.hypot(rise_m, run_m) + overhang_m

    seat = add_cylinder(
        "Stool",
        radius_m=seat_radius_m,
        height_m=briefs.STOOL_SEAT_THICKNESS_M,
        segment_count=24,
        location_m=(0.0, 0.0, rise_m),
    )
    link_into_scene(seat)

    placements_deg = leg_angles_deg or [
        360.0 / briefs.STOOL_LEG_COUNT * index
        for index in range(briefs.STOOL_LEG_COUNT)
    ]
    for leg_index, placement_deg in enumerate(placements_deg):
        angle_rad = math.radians(placement_deg)
        leg = add_cylinder(
            f"Leg{leg_index}",
            radius_m=leg_radius_m,
            height_m=leg_length_m,
            segment_count=12,
        )
        link_into_scene(leg)
        # Tilt outward in the leg's own radial direction, then stand it
        # up at the foot. Rotation happens about the cylinder base.
        leg.rotation_euler = Euler(
            (splay_rad * math.sin(angle_rad), -splay_rad * math.cos(angle_rad), 0.0),
            "XYZ",
        )
        # Going DOWN, the axis leans outward, so the base must start
        # further out for the axis to cross z=0 exactly on the circle.
        base_radius_m = (
            briefs.STOOL_FOOT_CIRCLE_RADIUS_M + overhang_m * math.tan(splay_rad)
        )
        leg.location = (
            base_radius_m * math.cos(angle_rad),
            base_radius_m * math.sin(angle_rad),
            -overhang_m,
        )
        apply_object_transform(leg)
        boolean_union(seat, leg)

    if not angled_feet:
        # Cut the tilted end caps off flush with the floor, so each foot
        # presents a face to stand on rather than an edge to rock on.
        # BEFORE snapping, not after: snapping lifts the stool until its
        # lowest POINT is at z=0, which leaves nothing below the plane
        # for the cutter to remove.
        cutter = add_box(
            "SoleCutter",
            width_m=briefs.STOOL_SEAT_DIAMETER_M * 2.0,
            depth_m=briefs.STOOL_SEAT_DIAMETER_M * 2.0,
            height_m=SOLE_CUTTER_DEPTH_M,
            location_m=(0.0, 0.0, -SOLE_CUTTER_DEPTH_M),
        )
        link_into_scene(cutter)
        boolean_difference(seat, cutter)
    snap_base_to_ground(seat)
    apply_object_transform(seat)
    _assign_material(seat, "Wood")
    bpy.context.view_layer.update()
    return seat


def test_stool_brief_is_satisfiable(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool()
    report = evaluate_brief(brief)
    assert report.passes(brief), report.summary(brief)


def test_stool_reference_passes_the_structural_gate(empty_scene):
    from blended.analyze import analyze_object
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    stool = _build_reference_stool()
    report = analyze_object(stool)
    assert report.passes(brief.budget), report.failures(brief.budget)


def test_legs_collapsed_to_the_axis_trips_no_central_post(empty_scene):
    """The measured historical failure (stale matrix_world): every leg
    ends up at the origin as one central post."""
    import math

    from blended.evaluate import briefs
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief
    from blended.ops.booleans import boolean_union
    from blended.ops.primitives import add_cylinder, link_into_scene
    from blended.ops.transforms import snap_base_to_ground

    brief = get_brief("three_leg_stool")
    rise_m = briefs.STOOL_TOTAL_HEIGHT_Z_M - briefs.STOOL_SEAT_THICKNESS_M
    seat = add_cylinder(
        "Stool",
        radius_m=briefs.STOOL_SEAT_DIAMETER_M / 2.0,
        height_m=briefs.STOOL_SEAT_THICKNESS_M,
        segment_count=24,
        location_m=(0.0, 0.0, rise_m),
    )
    link_into_scene(seat)
    post = add_cylinder("Post", radius_m=0.022, height_m=rise_m)
    link_into_scene(post)
    boolean_union(seat, post)
    snap_base_to_ground(seat)
    _assign_material(seat, "Wood")
    bpy.context.view_layer.update()

    report = evaluate_brief(brief)
    tripped = _failure_names(report, brief)
    assert "no_central_post" in tripped
    assert {f"leg_{index}_foot_is_solid" for index in range(math.floor(3))} <= tripped


def test_blind_recess_trips_the_clear_axis_probe(empty_scene):
    """The failure that slipped through iteration 1.

    A drain cut from the cavity DOWN into the floor but not out the
    bottom is sealed, yet every parity probe reads exactly as it does on
    a correct planter: the point inside the recess still has open air
    above it all the way out of the open top. Only a full-axis line of
    sight distinguishes the two.
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(drain_is_blind_recess=True)
    report = evaluate_brief(brief)

    # The old spec is fooled — this is the point of the test.
    assert all(measurement.ok for measurement in report.probes), (
        "parity probes should NOT be able to see this defect; if they can, "
        "the fixture no longer reproduces the iteration-1 failure"
    )
    # The new spec is not.
    assert not report.passes(brief)
    blocked = [m for m in report.clear_axes if not m.ok]
    assert [m.probe.name for m in blocked] == [
        "drain_hole_goes_all_the_way_through"
    ]
    assert blocked[0].blocked_at_m is not None


def test_correct_planter_has_a_clear_drain_axis(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter()
    report = evaluate_brief(brief)
    assert all(measurement.ok for measurement in report.clear_axes), (
        report.summary(brief)
    )


def test_angled_sole_trips_the_ground_contact_probe(empty_scene):
    """The failure that slipped through iteration 4.

    Legs splayed 11.3 deg from vertical end in tilted caps. Dropped onto
    the floor by their lowest point, `base_z` reads exactly 0.0000 and
    every parity probe reads exactly as it does on a flat-footed stool —
    the stool touches along three edges and rocks. Contact is an area,
    and only measuring it as one tells the two apart.
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool(angled_feet=True)
    report = evaluate_brief(brief)

    # Everything the gate measured BEFORE this probe existed is fooled —
    # if any of it trips, the fixture has stopped reproducing iteration 4.
    assert abs(report.base_z_m) <= brief.grounding_tolerance_m, (
        f"base_z {report.base_z_m:+.4f} should still pass grounding; the "
        f"fixture no longer reproduces the iteration-4 failure"
    )
    assert all(measurement.ok for measurement in report.probes), (
        "parity probes should NOT be able to see an angled sole"
    )
    assert all(measurement.ok for measurement in report.dimensions), (
        "dimensions should NOT be able to see an angled sole"
    )

    # The new probe is not fooled, and it names every foot.
    assert not report.passes(brief)
    tripped = _failure_names(report, brief)
    assert tripped == {
        f"leg_{index}_sole_is_flat_on_the_ground" for index in range(3)
    }, tripped


def test_angled_sole_is_reported_as_a_tilt_not_a_missing_leg(empty_scene):
    """Zero contact area has two causes and they need different repairs.

    An angled sole must say so — naming the faces it rejected and how
    far out of plane they were — rather than reading as "no leg here".
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool(angled_feet=True)
    report = evaluate_brief(brief)

    failed = [m for m in report.ground_contacts if not m.ok]
    assert len(failed) == 3
    for measurement in failed:
        assert measurement.rejected_face_count > 0, measurement.describe()
        assert (
            measurement.worst_rejected_span_m
            > measurement.probe.planarity_tolerance_m
        ), measurement.describe()
        assert "NOT level" in measurement.describe()


def test_flat_soles_measure_real_contact_area(empty_scene):
    """The correct build does not merely pass — it puts a measurable
    face on the floor at each foot."""
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool()
    report = evaluate_brief(brief)

    assert len(report.ground_contacts) == 3
    for measurement in report.ground_contacts:
        assert measurement.ok, measurement.describe()
        assert measurement.contact_area_m2 >= measurement.probe.minimum_area_m2


# Gaps of 105, 120 and 135 degrees instead of three of 120: plainly
# uneven, while every foot stays inside the probe's search radius. A leg
# more than about 29 degrees off is simply not found there, and the
# CONTACT check reports that — a different failure. This fixture targets
# the placement check specifically, so both misplaced legs must still be
# located.
UNEVENLY_SPACED_LEG_ANGLES_DEG = (0.0, 105.0, 225.0)


def test_uneven_leg_spacing_trips_the_placement_check(empty_scene):
    """The question the render cannot answer.

    Measured 2026-08-22 (iteration 10): the contact sheet's front
    orthographic view projects the 120 and 240 degree legs to the SAME
    world x, so they overlap into what reads as one leg. The human
    answered "Unclear" to whether the legs were evenly spaced and was
    right to — the view does not contain the information. It is a
    measurement, so it is measured.
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool(leg_angles_deg=UNEVENLY_SPACED_LEG_ANGLES_DEG)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    off = [m for m in report.ground_contacts if not m.angle_ok]
    assert off, [m.describe() for m in report.ground_contacts]
    for measurement in off:
        # Real contact, in the wrong place — not a missing foot.
        assert measurement.has_contact, measurement.describe()
        assert abs(measurement.angle_error_deg) > (
            measurement.probe.angle_tolerance_deg
        )
        assert "not evenly spaced" in measurement.describe()


def test_correct_spacing_measures_the_specified_bearings(empty_scene):
    """The correct build reports the brief's own angles back."""
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool()
    report = evaluate_brief(brief)

    bearings = sorted(
        round(m.measured_angle_deg) for m in report.ground_contacts
    )
    assert bearings == [0, 120, 240], [m.describe() for m in report.ground_contacts]
    for measurement in report.ground_contacts:
        assert measurement.radius_ok, measurement.describe()
        assert measurement.angle_ok, measurement.describe()
