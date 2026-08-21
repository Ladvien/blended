"""Array operations via the ARRAY modifier, applied through the depsgraph.

Note the honest intermediate state: an applied array is N disconnected
copies in ONE mesh — deliberately multi-component. It only becomes a
gate-passing solid once something (usually a boolean_union with a
connecting part) bridges the copies. Builders own that step; the gate
verifies it happened.
"""

from __future__ import annotations


def linear_array(
    blender_object,
    count: int,
    offset_m: tuple[float, float, float],
):
    """Repeat the object `count` times at a constant metric offset and
    bake the result into the mesh."""
    from blended.ops.modifiers import apply_all_modifiers

    MINIMUM_ARRAY_COUNT = 2
    if count < MINIMUM_ARRAY_COUNT:
        raise ValueError(f"Array count must be >= {MINIMUM_ARRAY_COUNT}.")

    array_modifier = blender_object.modifiers.new(name="LinearArray", type="ARRAY")
    array_modifier.count = count
    array_modifier.use_relative_offset = False
    array_modifier.use_constant_offset = True
    array_modifier.constant_offset_displace = offset_m
    apply_all_modifiers(blender_object)
    return blender_object
