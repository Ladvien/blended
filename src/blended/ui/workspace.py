"""A shipped ``blended`` workspace: viewport + Image Editor + wide chat sidebar (D2).

Heuristic H-LAN from Fukaya & Daylamani-Zad (DOI 10.1080/10447318.2026.2632170)
says an AI-driven tool inside a host should match the host's design language "through
appropriate use of front-end UI APIs within the host software". A Blender workspace
is the front-end API for screen layout: it is what the user switches to with the tabs
along the top bar, and it is what makes renders and a long conversation coexist
without fighting for the same area. This module ships one named ``blended`` that
holds a 3D viewport (its ``UI`` sidebar open on the ``blended`` tab) beside an Image
Editor sized to show a render contact sheet.

API notes verified against Blender 5.2.0 (``--background --factory-startup``):

- Workspaces are created by ``bpy.ops.workspace.add()`` — it duplicates the active
  workspace. In ``--background`` it returns ``{'PASS_THROUGH'}`` and creates nothing,
  because the screen-redraw path that clones the layout needs a real window.
- ``bpy.data.workspaces`` has no ``.new()``; ``workspace.copy()`` is the data-level
  duplicate and DOES work in background, carrying its screen along. The tests use
  it to plant a workspace so the idempotency path can be asserted headlessly.
- Areas are split with ``bpy.ops.screen.area_split`` under a
  ``context.temp_override(area=…, region=…, screen=…, window=…)``; an area's editor
  is changed via ``area.type``; the sidebar is opened with
  ``space.show_region_ui = True``.
- ``region.active_panel_category`` is **read-only** outside an active window — the
  recorded in-repo precedent (memory note, session 2026-09-04) is that
  ``active_panel_category = "blended"`` works only OUTSIDE a ``temp_override``, in
  the window's own context. So the sidebar-tab assignment is done last, in the
  natural window context, never inside a ``temp_override``.

``ensure_workspace()`` RAISES when ``bpy.app.background`` is true AND no
workspace of that name exists: the screen operators will not work, and a
half-built workspace is worse than none. It raises BEFORE mutating anything —
build it, or raise. The idempotent early-return (workspace already present)
works even in background, because no operators are needed.
"""

from __future__ import annotations

import bpy

__all__ = [
    "BLENDED_WORKSPACE_NAME",
    "ensure_workspace",
    "activate_chat_tab",
    "arrange_workspace",
    "workspace_exists",
]

# --- named constants (no literals in construction) -------------------------

BLENDED_WORKSPACE_NAME = "blended"

# The Image Editor is split off below the viewport so a render contact sheet
# has a wide, short home — the proportions a contact sheet needs.
IMAGE_EDITOR_HEIGHT_FRACTION = 0.4


class _BackgroundWorkspaceError(RuntimeError):
    """Screen operators need a real window; ``--background`` has none."""


def workspace_exists() -> bool:
    """True when a workspace named ``BLENDED_WORKSPACE_NAME`` is in ``bpy.data``."""
    return BLENDED_WORKSPACE_NAME in bpy.data.workspaces


def ensure_workspace() -> str:
    """Idempotently create and activate the ``blended`` workspace.

    If a workspace of that name already exists, returns immediately without
    touching the user's layout. Otherwise copies the active workspace, names
    the copy ``blended`` and switches the window to it. The LAYOUT is a
    separate, deferred step — see ``arrange_workspace``.

    Built from a DATA-LEVEL copy (``WorkSpace.copy()``), not
    ``bpy.ops.workspace.add()``: that operator returned ``PASS_THROUGH`` and
    created nothing when called from a timer callback in a real GUI session
    (measured 2026-09-05), because it needs the window's own operator
    context. ``copy()`` carries the screen with it and works from any
    context, including ``--background``.

    Returns the workspace name.
    """
    if workspace_exists():
        return BLENDED_WORKSPACE_NAME

    if bpy.app.background:
        raise _BackgroundWorkspaceError(
            f"ensure_workspace() cannot build the {BLENDED_WORKSPACE_NAME!r} "
            f"workspace in --background mode: the screen operators that "
            f"arrange it (bpy.ops.screen.area_join / area_split) need a real "
            f"window. Run it from a GUI Blender session, or call "
            f"workspace_exists() to check for an already-created one."
        )

    source = bpy.context.workspace or bpy.data.workspaces[0]
    workspace = source.copy()
    workspace.name = BLENDED_WORKSPACE_NAME
    bpy.context.window.workspace = workspace
    return BLENDED_WORKSPACE_NAME


def arrange_workspace() -> bool:
    """Give the CURRENT window a 3D viewport with an Image Editor under it.

    Must run a frame AFTER `ensure_workspace()` switched to the copy.
    Mutating the copied workspace's `screens[0]` directly produced a
    screen with two Timeline editors in a live GUI session (2026-09-05):
    an area that has never been drawn has no realised regions, so
    `area.type` and `area_split` do not land there. The screen the
    window is showing is the only one these operators can arrange.

    It splits the LARGEST area exactly once and never joins. An earlier
    version joined areas in a `while len(screen.areas) > 1` loop to
    collapse the layout first; when a join made no progress the loop
    spun forever on the main thread and froze Blender outright
    (measured 2026-09-05). The user's other editors are left alone,
    which is also the better outcome — a copied workspace keeps the
    tools they already had.

    Returns True when the screen now holds both a viewport and an Image
    Editor.
    """
    window = bpy.context.window
    if window is None:
        return False
    screen = window.screen
    if _has_chat_layout(screen):
        _open_sidebar(screen, window)
        return True

    largest = max(screen.areas, key=lambda area: area.width * area.height)
    largest.type = "VIEW_3D"
    # Identity, not position: the column may already hold other areas
    # (the source layout's timeline strip is 91 px tall). Choosing "the
    # lowest area sharing this x" made that strip the Image Editor and
    # left a stray viewport behind — measured from area geometry in a
    # live GUI session, 2026-09-05.
    before = {area.as_pointer() for area in screen.areas}
    largest_pointer = largest.as_pointer()
    with bpy.context.temp_override(
        window=window, screen=screen, area=largest, region=_window_region(largest)
    ):
        bpy.ops.screen.area_split(
            direction="HORIZONTAL", factor=IMAGE_EDITOR_HEIGHT_FRACTION
        )
    created = [area for area in screen.areas if area.as_pointer() not in before]
    # Re-fetch the split area by pointer: the operator rebuilds the
    # screen's area list, and the pre-split reference may no longer be
    # the struct that survived.
    kept = next(
        (area for area in screen.areas if area.as_pointer() == largest_pointer), None
    )
    if not created or kept is None:
        # The split refused. Say so rather than leaving the caller to
        # believe in a layout that does not exist.
        return False

    # The split's two products are `kept` and the new area: the lower of
    # the pair becomes the render's home, the upper stays the viewport.
    pair = sorted([kept, created[0]], key=lambda area: area.y)
    pair[0].type = "IMAGE_EDITOR"
    pair[1].type = "VIEW_3D"
    _open_sidebar(screen, window)
    return _has_chat_layout(screen)


def _has_chat_layout(screen) -> bool:
    """True when the screen already holds a viewport and an Image Editor."""
    types = {area.type for area in screen.areas}
    return {"VIEW_3D", "IMAGE_EDITOR"} <= types


def _open_sidebar(screen, window) -> None:
    """Open the UI sidebar of the workspace's viewport.

    `Region.width` is READ-ONLY in the RNA — the sidebar's width is the
    user's to drag, and the panel is built to fit the 27-row sidebar a
    default window gives it (see `_answer_row_budget` in the addon).

    Selecting the `blended` TAB is a separate call: a freshly copied
    screen's regions are not realised until Blender has drawn them once,
    and `active_panel_category` is read-only until then (measured in a
    live GUI session, 2026-09-05 — it raised AttributeError immediately
    after the copy and succeeded a frame later). See
    `activate_chat_tab`.
    """
    viewport = None
    for area in screen.areas:
        if area.type == "VIEW_3D":
            viewport = area
            break
    assert viewport is not None, "no VIEW_3D area after layout build"
    viewport.spaces[0].show_region_ui = True


def activate_chat_tab() -> bool:
    """Select the `blended` tab in every open 3D-viewport sidebar.

    Returns True when at least one region took it. Call this a frame
    AFTER the workspace is built — the addon's operator defers it
    through `bpy.app.timers` for exactly that reason.
    """
    activated = False
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type != "UI":
                    continue
                try:
                    region.active_panel_category = BLENDED_WORKSPACE_NAME
                    activated = True
                except AttributeError:
                    # Not realised yet, or headless: the sidebar is open
                    # either way and the user can click the tab.
                    pass
    return activated


def _window_region(area) -> object:
    """Return the WINDOW region of ``area`` (the one operators run in)."""
    for region in area.regions:
        if region.type == "WINDOW":
            return region
    raise RuntimeError(
        f"area {area.type!r} has no WINDOW region; cannot run screen operators"
    )