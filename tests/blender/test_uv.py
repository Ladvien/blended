"""UV unwrapping, UV analysis, and the layout render."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")
pytest.importorskip("PIL.Image", reason="UV layout render requires Pillow")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_unwrapped_mesh_reports_uvs(empty_scene):
    from blended.analyze import analyze_object
    from blended.builders import CrateBuilder, CrateParameters
    from blended.ops import smart_unwrap

    crate_object = CrateBuilder(CrateParameters()).build()
    assert analyze_object(crate_object).uv_layer_count == 0

    island_count = smart_unwrap(crate_object)
    report = analyze_object(crate_object)
    assert report.uv_layer_count == 1
    assert report.uv_island_count == island_count >= 1
    assert 0.0 < report.uv_coverage_fraction <= 1.0
    assert report.uv_out_of_bounds_face_count == 0


def test_require_uv_budget_fails_without_unwrap(empty_scene):
    from blended.analyze import MeshBudget, analyze_object
    from blended.builders import CrateBuilder, CrateParameters
    from blended.ops import smart_unwrap

    textured_budget = MeshBudget(require_uv_layer=True)
    crate_object = CrateBuilder(CrateParameters()).build()

    failures_before = analyze_object(crate_object).failures(textured_budget)
    assert any("no UV layer" in failure for failure in failures_before)

    smart_unwrap(crate_object)
    assert analyze_object(crate_object).failures(textured_budget) == []


def test_geometry_budget_ignores_missing_uvs(empty_scene):
    """UV requirements are opt-in: blockout stages must not be forced to
    carry a layout."""
    from blended.analyze import MeshBudget, analyze_object
    from blended.builders import CrateBuilder, CrateParameters

    crate_object = CrateBuilder(CrateParameters()).build()
    assert analyze_object(crate_object).failures(MeshBudget()) == []


def test_stacked_uvs_are_detected_as_overlaps(empty_scene):
    """Two islands occupying the same UV space share texels — detected,
    and gated when the budget forbids it."""
    from blended.analyze import MeshBudget, analyze_object
    from blended.ops import add_box, link_into_scene, smart_unwrap

    box_object = add_box("StackedUVs", 1.0, 1.0, 1.0)
    link_into_scene(box_object)
    smart_unwrap(box_object)

    # Collapse every island onto the same square: guaranteed overlaps.
    uv_layer = box_object.data.uv_layers.active
    for polygon in box_object.data.polygons:
        for loop_index, corner_index in enumerate(polygon.loop_indices):
            unit_square_corner = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))[
                loop_index % 4
            ]
            uv_layer.data[corner_index].uv = unit_square_corner

    report = analyze_object(box_object)
    assert report.uv_overlapping_face_pair_count > 0
    strict_budget = MeshBudget(require_uv_layer=True, allow_uv_overlaps=False)
    assert any(
        "overlapping UV" in failure for failure in report.failures(strict_budget)
    )


def test_out_of_bounds_uvs_are_detected(empty_scene):
    from blended.analyze import MeshBudget, analyze_object
    from blended.ops import add_box, link_into_scene, smart_unwrap

    box_object = add_box("OutOfBoundsUVs", 1.0, 1.0, 1.0)
    link_into_scene(box_object)
    smart_unwrap(box_object)
    uv_layer = box_object.data.uv_layers.active
    for uv_datum in uv_layer.data:
        uv_datum.uv[0] += 2.0  # shove the whole atlas out of the 0-1 square

    report = analyze_object(box_object)
    assert report.uv_out_of_bounds_face_count > 0
    strict_budget = MeshBudget(
        require_uv_layer=True, allow_uv_out_of_bounds=False
    )
    assert any(
        "outside the 0-1 UV" in failure
        for failure in report.failures(strict_budget)
    )


def test_island_budget_catches_seam_heavy_layouts(empty_scene):
    from blended.analyze import MeshBudget, analyze_object
    from blended.builders import BarrelBuilder, BarrelParameters
    from blended.ops import smart_unwrap

    barrel_object = BarrelBuilder(BarrelParameters()).build()
    smart_unwrap(barrel_object)
    report = analyze_object(barrel_object)

    tight_budget = MeshBudget(
        require_uv_layer=True, maximum_uv_island_count=1
    )
    assert any(
        "UV islands exceeds budget" in failure
        for failure in report.failures(tight_budget)
    )


def test_uv_layout_render_produces_an_image(empty_scene, tmp_path):
    from blended.builders import BarrelBuilder, BarrelParameters
    from blended.capture import render_uv_layout
    from blended.ops import smart_unwrap

    barrel_object = BarrelBuilder(BarrelParameters()).build()
    smart_unwrap(barrel_object)
    layout_path = render_uv_layout(barrel_object, tmp_path / "uv.png")

    assert layout_path.exists()
    from PIL import Image

    layout_image = Image.open(layout_path)
    assert layout_image.size == (512, 512)
    # Islands were actually drawn: more than the background + border colors.
    assert len(layout_image.convert("RGB").getcolors(maxcolors=100000)) > 3


def test_default_unwrap_is_clean_on_curved_geometry(empty_scene):
    """The measured reason ANGLE_BASED is the default: smart_project
    overlaps badly on a lathe, angle-based does not."""
    from blended.builders import BarrelBuilder, BarrelParameters
    from blended.ops.uv import SMART_PROJECT, unwrap_uvs

    barrel_object = BarrelBuilder(BarrelParameters()).build()

    default_report = unwrap_uvs(barrel_object)
    assert default_report.clean, default_report.summary()

    smart_report = unwrap_uvs(barrel_object, method=SMART_PROJECT)
    assert smart_report.overlapping_face_pair_count > 0, (
        "smart_project unexpectedly clean on curved geometry — "
        "re-verify the default choice"
    )


def test_unwrap_report_surfaces_overlaps_at_the_call_site(empty_scene):
    from blended.builders import CrateBuilder, CrateParameters
    from blended.ops.uv import CUBE_PROJECT, unwrap_uvs

    crate_object = CrateBuilder(CrateParameters()).build()
    cube_report = unwrap_uvs(crate_object, method=CUBE_PROJECT)
    assert not cube_report.clean  # cube projection stacks by design
    assert "overlapping pairs" in cube_report.summary()


def test_unknown_method_is_rejected(empty_scene):
    import pytest as pytest_module

    from blended.builders import CrateBuilder, CrateParameters
    from blended.ops.uv import unwrap_uvs

    crate_object = CrateBuilder(CrateParameters()).build()
    with pytest_module.raises(ValueError):
        unwrap_uvs(crate_object, method="MAGIC")


def test_unwrap_is_deterministic_regardless_of_prior_uvs(empty_scene):
    """Unwrapping must be a pure function of the geometry: a prior
    layout must not leak into the next one."""
    from blended.builders import BarrelBuilder, BarrelParameters
    from blended.ops.uv import SMART_PROJECT, unwrap_uvs

    barrel_object = BarrelBuilder(BarrelParameters()).build()

    from_fresh = unwrap_uvs(barrel_object)
    unwrap_uvs(barrel_object, method=SMART_PROJECT)
    after_other_method = unwrap_uvs(barrel_object)

    assert after_other_method.island_count == from_fresh.island_count
    assert (
        after_other_method.overlapping_face_pair_count
        == from_fresh.overlapping_face_pair_count
        == 0
    )
