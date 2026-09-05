"""Scene context collection against a real Blender scene.

The depsgraph guard (``context.view_layer.update()`` inside
``collect_scene_context``) is load-bearing: selection and transform
assignment lag by one update, so without the sync the collector would
read stale state (the same trap recorded in
``harness._synchronise_view_layer``).  These tests assign selection and
read in the same call with no intervening redraw to prove the sync works.
"""

from __future__ import annotations

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

#: Tolerance for dimension comparison after rounding to DIMENSION_DECIMALS.
#: The values are read from obj.dimensions (world bounding box) and rounded
#: to 2 decimals, so any float noise is below this threshold.
DIMENSION_TOLERANCE_M = 1e-6

#: Known box dimensions used across the tests.
CRATE_WIDTH_M = 0.6
CRATE_DEPTH_M = 0.4
CRATE_HEIGHT_M = 0.5
BARREL_WIDTH_M = 0.3
BARREL_DEPTH_M = 0.3
BARREL_HEIGHT_M = 0.8


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _make_box(name, width_m, depth_m, height_m):
    from blended.ops.primitives import add_box, link_into_scene

    box = add_box(name, width_m, depth_m, height_m)
    link_into_scene(box)
    return box


def _select_only(obj) -> None:
    """Deselect everything, select exactly one object, make it active."""
    for o in bpy.context.scene.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _select_also(obj) -> None:
    obj.select_set(True)


def _deselect_all() -> None:
    for o in bpy.context.scene.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = None


# ---------------------------------------------------------------------------
# collect_scene_context
# ---------------------------------------------------------------------------


def test_active_object_reported_with_measured_dimensions(empty_scene):
    from blended.agent.scene_context import collect_scene_context

    crate = _make_box("Crate", CRATE_WIDTH_M, CRATE_DEPTH_M, CRATE_HEIGHT_M)
    _select_only(crate)

    # Read in the SAME call — no redraw between assign and read.
    context = collect_scene_context(bpy.context)

    assert context.active_object_name == "Crate"
    assert len(context.selected) == 1
    assert context.selected[0].name == "Crate"
    assert context.selected[0].object_type == "MESH"
    assert context.selected[0].dimensions_m == pytest.approx(
        (CRATE_WIDTH_M, CRATE_DEPTH_M, CRATE_HEIGHT_M),
        abs=DIMENSION_TOLERANCE_M,
    )
    assert context.mode == "OBJECT"
    assert context.total_object_count == 1
    assert context.frame_current == bpy.context.scene.frame_current


def test_second_selected_reported_active_still_first(empty_scene):
    from blended.agent.scene_context import collect_scene_context

    crate = _make_box("Crate", CRATE_WIDTH_M, CRATE_DEPTH_M, CRATE_HEIGHT_M)
    barrel = _make_box("Barrel", BARREL_WIDTH_M, BARREL_DEPTH_M, BARREL_HEIGHT_M)
    _select_only(crate)
    _select_also(barrel)

    context = collect_scene_context(bpy.context)

    assert context.active_object_name == "Crate"
    assert context.selected_total_count == 2
    assert len(context.selected) == 2
    # Active first, then the rest by name — Barrel < Crate alphabetically,
    # but Crate is active so it heads the list.
    assert context.selected[0].name == "Crate"
    assert context.selected[1].name == "Barrel"
    assert context.total_object_count == 2


def test_deselect_all_reports_blender_real_semantics(empty_scene):
    """Assert what Blender actually does when nothing is selected, not
    what we assume it should do."""
    from blended.agent.scene_context import collect_scene_context

    crate = _make_box("Crate", CRATE_WIDTH_M, CRATE_DEPTH_M, CRATE_HEIGHT_M)
    _select_only(crate)
    _deselect_all()

    context = collect_scene_context(bpy.context)

    # Blender: after deselect-all + active=None, there is no active
    # object and the selection is empty.
    assert context.active_object_name == ""
    assert context.selected == ()
    assert context.selected_total_count == 0
    # The scene still has the object, so the block is NOT empty.
    assert context.total_object_count == 1


def test_depsgraph_guard_sees_freshly_linked_selection(empty_scene):
    """The object is linked, selected, and read in one shot with no
    intervening redraw.  If collect_scene_context skipped the view-layer
    update, it would read stale depsgraph state and miss the selection."""
    from blended.agent.scene_context import collect_scene_context

    crate = _make_box("Crate", CRATE_WIDTH_M, CRATE_DEPTH_M, CRATE_HEIGHT_M)
    # Link + select + collect, no redraw in between.
    _select_only(crate)
    context = collect_scene_context(bpy.context)

    assert context.active_object_name == "Crate"
    assert len(context.selected) == 1
    assert context.selected[0].name == "Crate"


def test_location_read_from_world_translation(empty_scene):
    from blended.agent.scene_context import collect_scene_context

    crate = _make_box("Crate", CRATE_WIDTH_M, CRATE_DEPTH_M, CRATE_HEIGHT_M)
    crate.location = (1.0, 2.0, 3.0)
    _select_only(crate)

    context = collect_scene_context(bpy.context)

    # matrix_world.translation reflects the object's location after the
    # view-layer update inside collect_scene_context.
    assert context.selected[0].location_m == pytest.approx(
        (1.0, 2.0, 3.0), abs=DIMENSION_TOLERANCE_M
    )