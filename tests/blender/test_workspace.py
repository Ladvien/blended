"""The ``blended`` workspace contract (D2).

``workspace_exists()`` is a pure ``bpy.data`` check and is fully assertable in
``--background``. ``ensure_workspace()`` builds a layout via screen operators
that need a real window, so it must RAISE in background with a message that
names the window requirement, and must be idempotent when the workspace is
already present. The idempotency path is exercised by planting a workspace
through ``bpy.data.workspaces[0].copy()`` (the data-level duplicate that works
headlessly) and asserting ``ensure_workspace()`` returns without mutating.
"""

from __future__ import annotations

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

from blended.ui.workspace import (  # noqa: E402
    BLENDED_WORKSPACE_NAME,
    ensure_workspace,
    workspace_exists,
)


@pytest.fixture()
def factory_startup():
    """Reset to factory settings so no stale workspace leaks between tests."""
    bpy.ops.wm.read_factory_settings(use_empty=False)
    yield


def test_workspace_exists_is_false_on_factory_startup(factory_startup):
    """Factory startup ships 11 workspaces, none named ``blended``."""
    assert BLENDED_WORKSPACE_NAME not in [
        ws.name for ws in bpy.data.workspaces
    ], "factory startup unexpectedly already has a 'blended' workspace"
    assert workspace_exists() is False


def test_workspace_exists_is_true_when_one_is_present(factory_startup):
    """Plant a workspace via bpy.data and confirm the check sees it."""
    assert workspace_exists() is False
    _plant_workspace(BLENDED_WORKSPACE_NAME)
    assert workspace_exists() is True
    _cleanup_workspace(BLENDED_WORKSPACE_NAME)


def test_ensure_workspace_raises_in_background_with_window_reason(factory_startup):
    """Background mode has no window redraw loop — raise, don't silently no-op."""
    if not bpy.app.background:
        pytest.skip("this test asserts the background-only error path")
    with pytest.raises(RuntimeError) as exc_info:
        ensure_workspace()
    message = str(exc_info.value)
    assert "background" in message.lower() or "window" in message.lower(), (
        f"error message does not name the window/background requirement: {message!r}"
    )
    # And it must not have left a half-built workspace behind.
    assert not workspace_exists(), (
        "ensure_workspace() raised but left a workspace behind — it must "
        "raise BEFORE mutating anything"
    )


def test_ensure_workspace_is_idempotent_when_name_already_present(factory_startup):
    """With the workspace already present, ensure_workspace returns the name
    and does not change the number of workspaces or screens."""
    _plant_workspace(BLENDED_WORKSPACE_NAME)
    workspace_count_before = len(bpy.data.workspaces)
    screen_count_before = len(bpy.data.screens)

    result = ensure_workspace()

    assert result == BLENDED_WORKSPACE_NAME
    assert len(bpy.data.workspaces) == workspace_count_before, (
        "ensure_workspace() added a workspace when one already existed"
    )
    assert len(bpy.data.screens) == screen_count_before, (
        "ensure_workspace() added a screen when the workspace already existed"
    )
    _cleanup_workspace(BLENDED_WORKSPACE_NAME)


# --- helpers ---------------------------------------------------------------


def _plant_workspace(name: str) -> None:
    """Create a workspace via the data-level copy that works in background."""
    source = bpy.data.workspaces[0]
    copy = source.copy()
    copy.name = name
def _cleanup_workspace(name: str) -> None:
    """Remove a planted workspace if it exists.

    ``bpy.data.workspaces`` has no ``.remove()`` method (verified in Blender
    5.2); ``bpy.data.batch_remove`` is the data-level path that works in
    ``--background``.
    """
    if name in bpy.data.workspaces:
        bpy.data.batch_remove([bpy.data.workspaces[name]])