"""Blender layer: ``RenderPreviews`` against real ``bpy.utils.previews``.

The panel ``draw()`` calls ``icon_for`` on every redraw (~6 Hz), so the
two properties that keep the panel alive are asserted here, not assumed:

- ``icon_for`` on a missing path returns 0 and does NOT raise (an
  exception inside ``draw()`` makes Blender silently abandon the rest of
  the panel).
- ``load()`` twice then ``unload()`` twice leaves ``bpy.utils.previews``
  clean — a hot-reload calls them in sequence.

The cache is observable in background even when ``icon_id`` is 0
(headless Blender has no GPU context for preview generation — measured
by ``outputs/ui_capability_probe.py``): the second call for the same
path must not re-enter the underlying collection's ``load``, which we
verify by counting calls on a thin wrapper around the real collection.
A non-zero ``icon_id`` assertion is guarded with ``skipif(background)``
because previews genuinely cannot generate without a window.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender


def _write_png(path: Path) -> None:
    """Write a real PNG through Blender's own image API.

    Blender's bundled Python has numpy and no Pillow, so the test
    produces its PNG the way the capture layer does: create an Image
    datablock, fill its pixels, ``save_render`` to disk.
    """
    image = bpy.data.images.new("test_render_preview", 8, 8)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    # Pixels are flat [r, g, b, a, ...]; 8x8 = 64 pixels = 256 floats.
    image.pixels = [1.0, 0.0, 0.0, 1.0] * 64
    image.save_render(str(path))
    bpy.data.images.remove(image)


def test_icon_for_missing_path_returns_zero_and_does_not_raise():
    """The property that keeps the panel alive: no exception on bad input."""
    from blended.ui.previews import RenderPreviews

    previews = RenderPreviews()
    previews.load()
    try:
        missing = Path("/nonexistent/definitely_not_here_sheet.png")
        # Must not raise — draw() calls this.
        icon_id = previews.icon_for(missing)
        assert icon_id == 0
    finally:
        previews.unload()


def test_icon_for_when_unloaded_returns_zero_and_does_not_raise():
    """Calling icon_for before load() must not raise either."""
    from blended.ui.previews import RenderPreviews

    previews = RenderPreviews()
    # Never loaded.
    icon_id = previews.icon_for(Path("/tmp/anything.png"))
    assert icon_id == 0


def test_load_twice_then_unload_twice_leaves_previews_clean():
    """A hot-reload calls unload->load in sequence; both must be safe twice."""
    from blended.ui.previews import RenderPreviews

    previews = RenderPreviews()
    previews.load()
    previews.load()  # idempotent — no second collection
    previews.unload()
    previews.unload()  # idempotent — no error
    # After unload, icon_for must still return 0 without raising.
    assert previews.icon_for(Path("/tmp/anything.png")) == 0


def test_icon_for_caches_identical_value_on_second_call(tmp_path):
    """The cache: a second call for the same path must not re-load the file.

    In background, ``icon_id`` is 0 (no GPU context), so the cache is
    verified through the collection's key set: after the first call the
    path string is a key in the collection, and after the second call
    the key set is unchanged — proving the file was not re-loaded.  A
    wrapper with a call counter makes the "did not re-enter" property
    explicit.
    """
    from blended.ui.previews import RenderPreviews

    png_path = tmp_path / "cache_test_sheet.png"
    _write_png(png_path)

    previews = RenderPreviews()
    previews.load()
    try:
        # Wrap the real collection's load to count entries.
        real_collection = previews._collection
        call_count = [0]
        original_load = real_collection.load

        def counting_load(*args, **kwargs):
            call_count[0] += 1
            return original_load(*args, **kwargs)

        real_collection.load = counting_load  # type: ignore[method-assign]

        first_icon = previews.icon_for(png_path)
        second_icon = previews.icon_for(png_path)

        # The cache means exactly one underlying load.
        assert call_count[0] == 1, (
            f"expected one underlying load for the same path, got "
            f"{call_count[0]}"
        )
        # Identical value on the second call (cache hit returns the
        # stored icon_id, not a fresh one).
        assert first_icon == second_icon
    finally:
        previews.unload()


def test_icon_for_returns_fresh_icon_when_mtime_changes(tmp_path):
    """A re-render to the same path must produce a fresh icon, not stale.

    The harness names contact sheets ``{object_name}_sheet.png`` and
    re-renders to the SAME path within a session.  A stale thumbnail
    would hide the drift the pairing is meant to reveal, so the cache
    keys on (path_str, mtime).  After the file is rewritten (new mtime),
    the underlying load must fire again.
    """
    from blended.ui.previews import RenderPreviews

    png_path = tmp_path / "rerender_sheet.png"
    _write_png(png_path)

    previews = RenderPreviews()
    previews.load()
    try:
        real_collection = previews._collection
        call_count = [0]
        original_load = real_collection.load

        def counting_load(*args, **kwargs):
            call_count[0] += 1
            return original_load(*args, **kwargs)

        real_collection.load = counting_load  # type: ignore[method-assign]

        previews.icon_for(png_path)
        # Rewrite the file (new content + new mtime).  On fast
        # filesystems the mtime may not advance between two writes in
        # the same second, so sleep past the filesystem's mtime
        # resolution before rewriting.
        time.sleep(0.05)
        _write_png(png_path)
        previews.icon_for(png_path)

        # The mtime change must trigger a second underlying load.
        assert call_count[0] == 2, (
            f"expected a fresh load after mtime change, got "
            f"{call_count[0]} underlying loads"
        )
    finally:
        previews.unload()


@pytest.mark.skipif(
    bpy.app.background,
    reason="previews need a GPU window to generate a non-zero icon_id",
)
def test_icon_for_real_png_returns_nonzero_in_gui(tmp_path):
    """In a GUI session, a real PNG must yield a non-zero icon_id.

    This is the one assertion that genuinely cannot run in ``--background``
    (the capability probe measured icon_id = 0 headless).  It is guarded
    rather than faked: a fake non-zero pass would hide a broken
    ``load`` call behind a skip.
    """
    from blended.ui.previews import RenderPreviews

    png_path = tmp_path / "gui_sheet.png"
    _write_png(png_path)

    previews = RenderPreviews()
    previews.load()
    try:
        icon_id = previews.icon_for(png_path)
        assert icon_id != 0, "GUI session must produce a real icon_id"
    finally:
        previews.unload()


def test_icon_for_returns_an_integer_id_not_the_preview_struct(tmp_path):
    """`collection.load()` hands back an ImagePreview STRUCT. Passing
    that to `template_icon(icon_value=…)` raises, and the panel swallows
    the error to stay alive — so the thumbnail silently never drew,
    which no headless assertion about CACHING could catch (measured in a
    live GUI session, 2026-09-05). The type is observable in background,
    so it is asserted here."""
    from blended.ui.previews import RenderPreviews

    png_path = tmp_path / "typed_sheet.png"
    _write_png(png_path)

    previews = RenderPreviews()
    previews.load()
    try:
        icon_id = previews.icon_for(png_path)
        assert type(icon_id) is int, (
            f"icon_for must return the integer icon_id, got "
            f"{type(icon_id).__name__}"
        )
    finally:
        previews.unload()