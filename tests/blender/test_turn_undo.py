"""The turn-undo guard's contract (D5).

The guard's preference-suppression and restoration IS assertable in
``--background`` because ``preferences.edit.use_global_undo`` is a plain RNA
property. The live undo stack is NOT: ``bpy.ops.ed.undo()`` in background has
nothing to pop, so the assertion that an object created inside the guard is
gone after ``revert_turn()`` is guarded with ``skipif(bpy.app.background)`` —
the main agent verifies it in the GUI.
"""

from __future__ import annotations

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

from blended.ui.turn_undo import TurnUndoGuard, revert_turn


@pytest.fixture()
def empty_scene():
    """Start from a clean file so prior tests don't leak undo steps."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _global_undo() -> bool:
    return bool(bpy.context.preferences.edit.use_global_undo)


def _set_global_undo(value: bool) -> None:
    bpy.context.preferences.edit.use_global_undo = value


def test_open_suppresses_global_undo_and_reports_open(empty_scene):
    """``open()`` must flip use_global_undo to False and set is_open True."""
    _set_global_undo(True)
    guard = TurnUndoGuard("chat: turn 1")
    assert not guard.is_open
    guard.open()
    assert guard.is_open
    assert _global_undo() is False
    guard.close()


def test_close_restores_a_true_starting_state(empty_scene):
    """When global undo was ON, ``close()`` puts it back ON."""
    _set_global_undo(True)
    guard = TurnUndoGuard("chat: turn 2")
    guard.open()
    assert _global_undo() is False
    guard.close()
    assert _global_undo() is True
    assert not guard.is_open


def test_close_restores_a_false_starting_state(empty_scene):
    """When global undo was OFF, ``close()`` leaves it OFF — not forced on."""
    _set_global_undo(False)
    guard = TurnUndoGuard("chat: turn 3")
    guard.open()
    assert _global_undo() is False
    guard.close()
    assert _global_undo() is False


def test_an_exception_inside_the_guarded_region_still_restores(empty_scene):
    """The guard's guarantee, proved by the object (try/finally), not the test.

    A turn that raises must not leave the user's Blender with global undo
    switched off. The test uses try/finally to exercise the guarantee the
    guard itself provides — the assertion is on the preference AFTER the
    finally, not on the exception.
    """
    _set_global_undo(True)
    guard = TurnUndoGuard("chat: turn that raises")

    class _TurnError(RuntimeError):
        pass

    with pytest.raises(_TurnError):
        guard.open()
        try:
            raise _TurnError("simulated turn failure")
        finally:
            guard.close()

    assert _global_undo() is True
    assert not guard.is_open


def test_close_without_open_is_a_noop(empty_scene):
    """``close()`` with no preceding ``open()`` must not raise or change state."""
    _set_global_undo(True)
    guard = TurnUndoGuard("chat: never opened")
    guard.close()  # not an error
    assert _global_undo() is True
    assert not guard.is_open


def test_close_twice_is_a_noop(empty_scene):
    """A second ``close()`` is the same as the first — idempotent."""
    _set_global_undo(True)
    guard = TurnUndoGuard("chat: turn 4")
    guard.open()
    guard.close()
    assert _global_undo() is True
    guard.close()  # second close: no error, no change
    assert _global_undo() is True
    assert not guard.is_open


def test_revert_turn_returns_a_bool_and_does_not_raise_on_empty_stack(empty_scene):
    """``revert_turn()`` returns False when there is nothing to undo, not an error."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = revert_turn()
    assert isinstance(result, bool)
    assert result is False


@pytest.mark.skipif(
    bpy.app.background,
    reason=(
        "The live undo stack is not available in --background; the main agent "
        "verifies that an object created after open() is gone after "
        "revert_turn() in the GUI."
    ),
)
def test_revert_turn_removes_an_object_created_inside_the_guard(empty_scene):
    """The whole turn collapses to one undo step: revert undoes the object.

    This is the core H-LAN guarantee (DOI 10.1080/10447318.2026.2632170): one
    Ctrl+Z reverses the entire turn. Requires a real window so the undo stack
    actually records the push and can pop it.
    """
    _set_global_undo(True)
    guard = TurnUndoGuard("chat: create a cube")
    guard.open()
    try:
        bpy.ops.mesh.primitive_cube_add()
        cube_name = bpy.context.active_object.name
        assert cube_name in bpy.data.objects, "cube was not created"
    finally:
        guard.close()

    assert _global_undo() is True
    assert revert_turn() is True, "undo reported nothing to pop"
    assert cube_name not in bpy.data.objects, (
        f"object {cube_name!r} survived revert_turn() — the turn did not "
        f"collapse to one undo step"
    )


def test_open_twice_without_close_raises(empty_scene):
    """Re-opening would push a second step and break the one-step invariant."""
    _set_global_undo(True)
    guard = TurnUndoGuard("chat: double open")
    guard.open()
    with pytest.raises(RuntimeError, match="called twice"):
        guard.open()
    guard.close()
    assert _global_undo() is True


def test_empty_message_is_rejected(empty_scene):
    """A guard with no step label cannot name its restore point — refuse it."""
    with pytest.raises(ValueError, match="non-empty"):
        TurnUndoGuard("")