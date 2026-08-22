"""assign_material must produce a material the RENDER can show.

Measured 2026-08-22 (iteration 1): the agent set the Principled BSDF
base colour to terracotta, the Workbench render came back grey, the
vision model reported the discrepancy as a deviation, and the agent
spent tool calls chasing a defect that did not exist. Workbench reads
`material.diffuse_color`, never the shader graph.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

TERRACOTTA_RGB = (0.72, 0.35, 0.22)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _box():
    from blended.ops.primitives import add_box, link_into_scene

    box = add_box("Subject", 0.2, 0.2, 0.2)
    link_into_scene(box)
    return box


def test_assign_material_fills_one_slot(empty_scene):
    from blended.ops.materials import assign_material

    box = _box()
    assign_material(box, "Terracotta", TERRACOTTA_RGB)

    assert len(box.data.materials) == 1
    assert box.data.materials[0] is not None
    assert box.data.materials[0].name == "Terracotta"


def test_assign_material_sets_both_colour_fields(empty_scene):
    """The shader colour and the Workbench colour must not disagree."""
    from blended.ops.materials import assign_material

    box = _box()
    material = assign_material(box, "Terracotta", TERRACOTTA_RGB)

    principled = material.node_tree.nodes["Principled BSDF"]
    shader_rgb = tuple(principled.inputs["Base Color"].default_value)[:3]
    viewport_rgb = tuple(material.diffuse_color)[:3]

    assert shader_rgb == pytest.approx(TERRACOTTA_RGB)
    assert viewport_rgb == pytest.approx(TERRACOTTA_RGB)


def test_assign_material_is_idempotent_by_name(empty_scene):
    """Re-running a chunk must not stack a second slot."""
    from blended.ops.materials import assign_material

    box = _box()
    assign_material(box, "Terracotta", TERRACOTTA_RGB)
    assign_material(box, "Terracotta", TERRACOTTA_RGB)

    assert len(box.data.materials) == 1
    assert len([m for m in bpy.data.materials if m.name == "Terracotta"]) == 1


def test_the_render_actually_shows_the_colour(empty_scene, tmp_path):
    """The assertion that closes the loop: pixels, not properties."""
    from blended.capture.views import capture_views
    from blended.ops.materials import assign_material

    box = _box()
    assign_material(box, "Terracotta", TERRACOTTA_RGB)
    paths = capture_views(box, tmp_path)

    image = bpy.data.images.load(str(paths["front"]))
    width, height = image.size
    pixels = list(image.pixels)
    centre_index = ((height // 2) * width + (width // 2)) * 4
    red, green, blue, alpha = pixels[centre_index : centre_index + 4]

    assert alpha == pytest.approx(1.0), "centre pixel is background, not the box"
    # Workbench applies studio lighting, so absolute values shift — but a
    # terracotta box must still be unmistakably redder than it is blue.
    assert red > blue, f"render is not showing the material colour: {(red, green, blue)}"
    assert red > green > blue
