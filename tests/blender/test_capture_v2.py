"""Inspection v2: contact sheets and X-ray capture."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")
PIL_Image = pytest.importorskip("PIL.Image", reason="contact sheets require Pillow")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_contact_sheet_contains_all_views_and_verdict(empty_scene, tmp_path):
    from blended.analyze import analyze_object
    from blended.builders import CrateBuilder, CrateParameters
    from blended.capture import capture_contact_sheet

    crate_object = CrateBuilder(CrateParameters()).build()
    report = analyze_object(crate_object)
    sheet_path = capture_contact_sheet(crate_object, tmp_path, report=report)

    assert sheet_path.exists()
    sheet_image = PIL_Image.open(sheet_path)
    single_view_size = PIL_Image.open(tmp_path / "front.png").size
    # 2x2 grid: the sheet is materially larger than any single view.
    assert sheet_image.size[0] > single_view_size[0] * 1.5
    assert sheet_image.size[1] > single_view_size[1] * 1.5


def test_xray_reveals_hidden_geometry(empty_scene, tmp_path):
    """A fully enclosed inner box must change the rendered pixels only
    when X-ray is on."""
    import numpy

    from blended.capture import CaptureSettings, capture_views
    from blended.ops import add_box, link_into_scene

    outer_box = add_box("OuterShell", 1.0, 1.0, 1.0)
    link_into_scene(outer_box)
    inner_box = add_box("HiddenInner", 0.4, 0.4, 0.4, location_m=(0.0, 0.0, 0.3))
    link_into_scene(inner_box)

    plain_paths = capture_views(outer_box, tmp_path / "plain")
    xray_paths = capture_views(
        outer_box, tmp_path / "xray", CaptureSettings(xray=True)
    )

    plain_pixels = numpy.asarray(
        PIL_Image.open(plain_paths["three_quarter"]).convert("L"), dtype=int
    )
    xray_pixels = numpy.asarray(
        PIL_Image.open(xray_paths["three_quarter"]).convert("L"), dtype=int
    )
    CHANGED_PIXEL_THRESHOLD = 8
    MINIMUM_CHANGED_PIXELS = 500
    changed_pixel_count = (
        numpy.abs(plain_pixels - xray_pixels) > CHANGED_PIXEL_THRESHOLD
    ).sum()
    assert changed_pixel_count > MINIMUM_CHANGED_PIXELS
