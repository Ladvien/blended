"""CSG operations via the boolean modifier, applied through the depsgraph.

The EXACT solver is the reliability default; it is slower than FAST but
does not leave the near-coplanar garbage FAST does. Every operation
consumes its operand (the cutter/addend is removed afterward) so scenes
never accumulate hidden helper objects — an invisible leftover cutter is
exactly the kind of state that made retries lie (see drift catalog).

Every CSG result must go back through the analyzer: booleans are the
single most common way a designed mesh silently goes non-manifold.
"""

from __future__ import annotations

BOOLEAN_SOLVER_DEFAULT = "EXACT"


class UnlinkedOperand(RuntimeError):
    """A boolean operand is not in the scene, so the modifier cannot see it."""


def _require_linked(blender_object, role: str) -> None:
    """Refuse to start a boolean on an object the depsgraph cannot see.

    Construction and linking are separate steps in this vocabulary, so
    `add_box` hands back an object that is not in the scene yet. Measured
    2026-08-22 (iteration 8): boolean_union on two unlinked boxes
    RETURNED NORMALLY, left the target at 8 vertices — no union
    happened — and consumed the addend anyway. The agent read that as a
    broken op, wiped the scene to A/B-test it, destroyed the finished
    stool along with everything else, and ended the run with no object
    at all. A silent wrong answer cost fifteen tool calls; this raise
    costs one.
    """
    import bpy

    if blender_object.name not in bpy.context.scene.objects:
        raise UnlinkedOperand(
            f"boolean {role} {blender_object.name!r} is not linked into the "
            f"scene, so the modifier cannot evaluate it and the result "
            f"would silently be the unchanged target. Call "
            f"ops.primitives.link_into_scene({blender_object.name!r}'s "
            f"object) after creating it, before any boolean."
        )


def _apply_boolean(
    target_object,
    operand_object,
    operation: str,
    solver: str = BOOLEAN_SOLVER_DEFAULT,
) -> None:
    from blended.ops.modifiers import apply_all_modifiers
    from blended.ops.primitives import remove_object_and_mesh

    # Checked BEFORE anything mutates: a boolean that fails halfway has
    # already eaten its operand.
    _require_linked(target_object, "target")
    _require_linked(operand_object, "operand")

    boolean_modifier = target_object.modifiers.new(
        name=f"Boolean_{operation}", type="BOOLEAN"
    )
    boolean_modifier.operation = operation
    boolean_modifier.object = operand_object
    boolean_modifier.solver = solver
    apply_all_modifiers(target_object)
    remove_object_and_mesh(operand_object.name)

    from blended.ops.heal import weld_and_dissolve

    weld_and_dissolve(target_object)


def boolean_difference(target_object, cutter_object, solver=BOOLEAN_SOLVER_DEFAULT):
    """Subtract cutter from target; the cutter is consumed."""
    _apply_boolean(target_object, cutter_object, "DIFFERENCE", solver)
    return target_object


def boolean_union(target_object, addend_object, solver=BOOLEAN_SOLVER_DEFAULT):
    """Merge addend into target as one watertight solid; addend consumed."""
    _apply_boolean(target_object, addend_object, "UNION", solver)
    return target_object


def boolean_intersect(target_object, operand_object, solver=BOOLEAN_SOLVER_DEFAULT):
    """Keep only the overlap of the two solids; operand consumed."""
    _apply_boolean(target_object, operand_object, "INTERSECT", solver)
    return target_object
