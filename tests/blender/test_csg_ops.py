"""CSG ops: every boolean result must survive the analyzer gate."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

BOX_SIZE_M = 1.0
HOLE_RADIUS_M = 0.2
# Cutter must overshoot both faces or the difference leaves coplanar caps.
CUTTER_OVERSHOOT_FACTOR = 1.5


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _bored_box():
    from blended.ops import add_box, add_cylinder, boolean_difference, link_into_scene

    box_object = add_box("BoredBox", BOX_SIZE_M, BOX_SIZE_M, BOX_SIZE_M)
    link_into_scene(box_object)
    cutter_height_m = BOX_SIZE_M * CUTTER_OVERSHOOT_FACTOR
    cutter_object = add_cylinder(
        "HoleCutter",
        radius_m=HOLE_RADIUS_M,
        height_m=cutter_height_m,
        location_m=(0.0, 0.0, -(cutter_height_m - BOX_SIZE_M) / 2.0),
    )
    link_into_scene(cutter_object)
    return boolean_difference(box_object, cutter_object)


def test_difference_bores_a_clean_hole(empty_scene):
    from blended.analyze import MeshBudget, analyze_object

    bored_box = _bored_box()
    report = analyze_object(bored_box)
    failures = report.failures(MeshBudget())
    assert failures == [], f"analyzer failures: {failures}; report={report}"
    # The hole is real geometry: more triangles than the plain box.
    assert report.triangle_count > 12


def test_difference_consumes_the_cutter(empty_scene):
    _bored_box()
    assert "HoleCutter" not in bpy.data.objects


def test_union_produces_single_manifold_solid(empty_scene):
    from blended.analyze import MeshBudget, analyze_object
    from blended.ops import add_box, boolean_union, link_into_scene

    base_object = add_box("UnionBase", 1.0, 1.0, 1.0)
    link_into_scene(base_object)
    overlapping_object = add_box(
        "UnionAddend", 1.0, 1.0, 1.0, location_m=(0.5, 0.0, 0.3)
    )
    link_into_scene(overlapping_object)
    unioned = boolean_union(base_object, overlapping_object)

    report = analyze_object(unioned)
    assert report.connected_component_count == 1
    assert report.failures(MeshBudget()) == [], report.failures(MeshBudget())


def test_snap_base_to_ground(empty_scene):
    from blended.ops import add_box, link_into_scene, snap_base_to_ground

    GROUND_TOLERANCE_M = 1.0e-6
    floating_box = add_box("Floater", 1.0, 1.0, 1.0, location_m=(0.0, 0.0, 3.0))
    link_into_scene(floating_box)
    snap_base_to_ground(floating_box)
    bpy.context.view_layer.update()
    from mathutils import Vector

    lowest_z_m = min(
        (floating_box.matrix_world @ Vector(corner)).z
        for corner in floating_box.bound_box
    )
    assert abs(lowest_z_m) < GROUND_TOLERANCE_M
