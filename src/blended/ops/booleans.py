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


def _apply_boolean(
    target_object,
    operand_object,
    operation: str,
    solver: str = BOOLEAN_SOLVER_DEFAULT,
) -> None:
    from blended.ops.modifiers import apply_all_modifiers
    from blended.ops.primitives import remove_object_and_mesh

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
