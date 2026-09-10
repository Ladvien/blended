"""Paired render thumbnails for the chat panel — D4.

The agent renders a contact sheet on every ``render_views`` / ``run_python``
turn and sends it to the vision model, but never shows it to the user
(``UiMap`` §5 of the gap list).  Showing this turn's render beside the
previous one is the measured way to make drift visible to the human eye:
supplying a reference frame beside the candidate is worth +0.32 F1 and
lifts recall from 0.28 to 0.76 for visual defect detection
(DOI 10.48550/arXiv.2604.11082, RESP).

Two pieces live here:

``RenderPreviews`` — wraps ONE ``bpy.utils.previews`` collection for the
addon's lifetime.  ``load()`` is called from ``register()``, ``unload()``
from ``unregister()``; both are safe to call twice (a hot-reload calls
them in sequence).  ``icon_for(path)`` returns the ``icon_id`` for a PNG
on disk, caching by path string so a redraw at 6 Hz does not reload the
file.  A file whose mtime changed produces a fresh icon, because the
harness re-renders to the SAME path within a session (contact sheets are
named ``{object_name}_sheet.png`` — see ``capture.contact_sheet``) and a
stale thumbnail would hide the very drift the pairing is meant to reveal.

``paired_render_paths(events)`` — PURE.  Given the panel's transcript — a
sequence of ``(kind, text)`` pairs on the shared event channel — it
returns ``(previous, latest)`` from the ``render`` events: the newest
render path and the one before it, as ``Path`` objects, ``None`` where
absent.  Every other kind is ignored.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

# The event kind that carries a render contact-sheet path on the shared
# ``(kind, text)`` channel.  See the plan's "New transcript event kinds"
# section: ``render`` carries the absolute path of a contact sheet that
# was just produced.
RENDER_EVENT_KIND = "render"

# The value ``icon_for`` returns when it cannot produce an icon.  Blender
# draws ``0`` as "no icon", so a panel ``draw()`` that calls this never
# needs to branch — and never raises, which is the property that keeps
# the panel alive (an exception inside ``draw()`` makes Blender silently
# abandon the rest of the panel).
NO_ICON_ID = 0


class RenderPreviews:
    """One ``bpy.utils.previews`` collection for the addon's lifetime.

    A single collection is created on ``load()`` and destroyed on
    ``unload()``.  ``icon_for`` caches by path string AND mtime so a
    re-render to the same path (the harness's naming convention) produces
    a fresh icon rather than a stale thumbnail.
    """

    def __init__(self) -> None:
        self._collection = None
        # path_str -> (mtime_float, icon_id_int)
        self._cache: dict[str, tuple[float, int]] = {}

    def load(self) -> None:
        """Create the preview collection.  Idempotent.

        Safe to call twice (a hot-reload calls ``unload`` then ``load``
        in sequence): a second call is a no-op rather than leaking a
        second collection into ``bpy.utils.previews``.
        """
        if self._collection is not None:
            return
        import bpy
        import bpy.utils.previews

        self._collection = bpy.utils.previews.new()

    def unload(self) -> None:
        """Destroy the preview collection.  Idempotent.

        Safe to call twice and safe to call before ``load``: both are
        no-ops.  After ``unload`` the collection is gone from
        ``bpy.utils.previews`` and the cache is cleared.
        """
        if self._collection is not None:
            import bpy
            import bpy.utils.previews

            bpy.utils.previews.remove(self._collection)
            self._collection = None
        self._cache.clear()

    def icon_for(self, path: Path) -> int:
        """Return the ``icon_id`` for a PNG on disk, ``0`` when unavailable.

        Returns ``NO_ICON_ID`` (0) — which Blender draws as "no icon" —
        when the file does not exist or when the collection is not loaded,
        because a panel ``draw()`` MUST NOT raise: an exception inside
        draw makes Blender silently abandon the rest of the panel (see
        ``blender_addon/__init__.py::_wrap_for_region`` for the same
        discipline).  In headless Blender (``bpy.app.background``) the
        collection's load returns 0 (no GPU context — measured by
        ``outputs/ui_capability_probe.py``); that 0 is cached so a
        redraw at 6 Hz does not re-load the file, yet a re-render to the
        same path (mtime changed) produces a fresh load.
        """
        if self._collection is None:
            return NO_ICON_ID
        path_str = str(path)
        if not Path(path_str).is_file():
            return NO_ICON_ID
        mtime = Path(path_str).stat().st_mtime
        cached = self._cache.get(path_str)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        # The collection is a dict subclass: load() raises KeyError if
        # the name is already a key, even with force_reload.  A re-render
        # to the same path (the harness names contact sheets
        # ``{object_name}_sheet.png`` and overwrites) must delete the old
        # entry first, then reload with force_reload=True so the C-level
        # preview is regenerated from the new file bytes — a stale
        # thumbnail would hide the drift the pairing is meant to reveal.
        if path_str in self._collection:
            del self._collection[path_str]
        # `load()` returns an ImagePreview STRUCT, not the id. Passing
        # the struct to `template_icon(icon_value=…)` raises, and the
        # panel swallows that to keep drawing — so the picture silently
        # never appeared. Measured in a live GUI session, 2026-09-05;
        # invisible headless, where every icon id is 0 anyway.
        preview = self._collection.load(
            path_str, path_str, "IMAGE", force_reload=True
        )
        icon_id = int(preview.icon_id)
        self._cache[path_str] = (mtime, icon_id)
        return icon_id


def paired_render_paths(
    events: Sequence[tuple[str, str]],
) -> tuple[Path | None, Path | None]:
    """Return ``(previous, latest)`` from the transcript's ``render`` events.

    PURE — no ``bpy``.  Given the panel's transcript — a sequence of
    ``(kind, text)`` pairs — it collects every ``render`` event's path
    and returns the two newest as ``(previous, latest)``: the one before
    the latest, and the latest.  ``None`` where a slot is absent (no
    renders, or only one render).  Every other kind is ignored, and the
    count of non-render events between renders does not matter.

    Raises ``ValueError`` when a ``render`` event carries an empty path,
    because an empty path is a contract violation in the agent loop, not
    a missing render.
    """
    render_paths: list[Path] = []
    for kind, text in events:
        if kind != RENDER_EVENT_KIND:
            continue
        path_text = text.strip()
        if not path_text:
            raise ValueError(
                f"render event carried an empty path — the agent loop must "
                f"emit the contact-sheet path on every render event, not "
                f"an empty string (event index {len(render_paths)})"
            )
        render_paths.append(Path(path_text))
    if not render_paths:
        return (None, None)
    if len(render_paths) == 1:
        return (None, render_paths[0])
    return (render_paths[-2], render_paths[-1])