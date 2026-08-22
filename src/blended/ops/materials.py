"""Material assignment through the data API.

Why this op exists at all: a game asset with no material is not
shippable, so the acceptance gate requires one — but there was no
whitelisted way to make one, which forced agents into raw bpy for a
step every single asset needs.

Why it sets the colour TWICE: Workbench, the engine every inspection
render uses, does not read the Principled BSDF at all. It reads
`material.diffuse_color` — the viewport display colour. An agent that
sets only the BSDF base colour gets a correct-looking material and a
grey render, then burns tool calls investigating a discrepancy that
does not exist (measured, iteration 1). One op, both fields, always in
sync.
"""

from __future__ import annotations

PRINCIPLED_NODE_NAME = "Principled BSDF"
BASE_COLOR_INPUT_NAME = "Base Color"
DEFAULT_BASE_COLOR_RGB = (0.8, 0.8, 0.8)
DEFAULT_ROUGHNESS = 0.7


def assign_material(
    blender_object,
    name: str,
    base_color_rgb: tuple[float, float, float] = DEFAULT_BASE_COLOR_RGB,
    roughness: float = DEFAULT_ROUGHNESS,
):
    """Create a material of `name` and assign it as the object's only slot.

    Idempotent by name, like the primitive constructors: re-running a
    chunk replaces the material instead of stacking a second slot.
    Returns the material.
    """
    import bpy

    existing = bpy.data.materials.get(name)
    if existing is not None:
        bpy.data.materials.remove(existing)

    material = bpy.data.materials.new(name)
    # No `use_nodes = True` here: in 5.2 a new material already has its
    # node tree and the property is deprecated (removal expected in 6.0).
    principled = material.node_tree.nodes.get(PRINCIPLED_NODE_NAME)
    if principled is None:
        raise RuntimeError(
            f"Material {name!r} has no {PRINCIPLED_NODE_NAME!r} node, so its "
            f"base colour cannot be set. The default node tree changed; fix "
            f"this op rather than working around it at the call site."
        )
    red, green, blue = base_color_rgb
    principled.inputs[BASE_COLOR_INPUT_NAME].default_value = (red, green, blue, 1.0)
    principled.inputs["Roughness"].default_value = roughness
    # The half Workbench actually renders.
    material.diffuse_color = (red, green, blue, 1.0)
    material.roughness = roughness

    blender_object.data.materials.clear()
    blender_object.data.materials.append(material)
    return material
