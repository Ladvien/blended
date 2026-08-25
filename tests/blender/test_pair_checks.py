"""Pair separation is measured on the SURFACE, never on vertices.

scp's measured trap: palm-to-weapon distance read 60 mm against mesh
vertices and 6.5 mm against the mesh surface, because on box geometry
the nearest vertex is a far corner. Two wrong root causes were
announced off that artifact.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _unit_cube(name, center_xy_m, z_min_m=0.0):
    """A 1 m cube with its base at z_min_m, centred on center_xy_m."""
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(
        [
            (center_xy_m[0] - 0.5, center_xy_m[1] - 0.5, z_min_m),
            (center_xy_m[0] + 0.5, center_xy_m[1] - 0.5, z_min_m),
            (center_xy_m[0] + 0.5, center_xy_m[1] + 0.5, z_min_m),
            (center_xy_m[0] - 0.5, center_xy_m[1] + 0.5, z_min_m),
            (center_xy_m[0] - 0.5, center_xy_m[1] - 0.5, z_min_m + 1.0),
            (center_xy_m[0] + 0.5, center_xy_m[1] - 0.5, z_min_m + 1.0),
            (center_xy_m[0] + 0.5, center_xy_m[1] + 0.5, z_min_m + 1.0),
            (center_xy_m[0] - 0.5, center_xy_m[1] + 0.5, z_min_m + 1.0),
        ],
        [],
        [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)],
    )
    mesh_data.update()
    cube_object = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(cube_object)
    return cube_object


def test_separation_is_measured_on_the_surface(empty_scene):
    """Two 1 m cubes whose faces sit 0.01 m apart must report a
    minimum separation within 1e-3 of 0.01 — a nearest-vertex
    implementation reads roughly the cube diagonal instead."""
    from blended.analyze.pair_checks import analyze_pair

    first = _unit_cube("First", (-1.005, 0.0))
    second = _unit_cube("Second", (0.005, 0.0))
    pair_report = analyze_pair(first, second)

    assert pair_report.intersecting_face_pair_count == 0
    assert abs(pair_report.minimum_separation_m - 0.01) <= 1.0e-3, (
        f"surface separation {pair_report.minimum_separation_m}, "
        f"expected ~0.01; a nearest-vertex implementation reads the "
        f"diagonal instead"
    )


def test_overlapping_cubes_report_intersecting_pairs(empty_scene):
    from blended.analyze.pair_checks import analyze_pair

    first = _unit_cube("OverlapA", (-0.25, 0.0))
    second = _unit_cube("OverlapB", (0.25, 0.0))
    pair_report = analyze_pair(first, second)

    assert pair_report.intersecting_face_pair_count > 0
