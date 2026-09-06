"""The GPU transcript inside a real Blender: metrics, handler, scoping.

`tests/pure/test_transcript_layout.py` proves the arithmetic against a
monospace stub. This file proves the two things a stub cannot:

* the wrap fits when the widths come from the REAL proportional UI font
  at both UI scales — the property the native panel's
  `(width - 34) / (7 * ui_scale)` character estimate could only
  approximate, and the reason this overlay exists;
* the draw handler's lifetime and the theme translation work against
  live `bpy`.

Both run in `--background`. `blf` reports real metrics with no window,
and `SpaceView3D.draw_handler_add/remove` both succeed headless — only
`gpu.shader.from_builtin` needs a GL context, which is why the shader
is built on first draw and never at import.
"""

from __future__ import annotations

import importlib
import types
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender")

pytestmark = pytest.mark.blender

import blf
from test_addon_draw import _load_addon

from blended.ui import transcript_overlay as overlay
from blended.ui.transcript_layout import (
    TranscriptMessage,
    column_rect,
    layout_transcript,
)
from blended.ui.transcript_style import CODE_BAND_CONTRAST

PROSE = (
    "The crate is 0.8 m on a side. Eight slats, mitred at the corners and "
    "bevelled 2 mm so the edges catch a highlight, and the lid is a "
    "separate object so it can be opened without editing the body."
)
# Region sizes in DEVICE pixels: a HiDPI display reports twice the
# logical size, which is exactly why the style has to scale itself.
REGION_SIZES = {1.0: (1600, 900), 2.0: (3200, 1800)}
SIDEBAR_WIDTH_PX = 561  # a real chat sidebar, measured 2026-09-05
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class _StubRegion:
    def __init__(self, region_type, width, height=0, category=""):
        self.type = region_type
        self.width = width
        self.height = height
        self.active_panel_category = category


def _stub_context(
    region_width_px=1600,
    region_height_px=900,
    sidebar_width_px=SIDEBAR_WIDTH_PX,
    category=overlay.CHAT_PANEL_CATEGORY,
    area_type=overlay.VIEWPORT_AREA_TYPE,
):
    """A VIEW_3D area with a sidebar, without needing a window.

    The overlay reads only `type`, `width`, `height` and
    `active_panel_category` off regions, so a stub exercises the real
    geometry — the inset, the hit test and the scoping rule — in
    `--background`.
    """
    sidebar = _StubRegion("UI", sidebar_width_px, region_height_px, category)
    window = _StubRegion("WINDOW", region_width_px, region_height_px)
    area = types.SimpleNamespace(type=area_type, regions=[sidebar, window])
    return types.SimpleNamespace(area=area, region=window)


@pytest.fixture
def addon():
    """The addon registered for real, so `blended_chat` exists.

    No flag to set: the overlay ships on, so this fixture exercises the
    shipped configuration. That is the point of the flip — a fixture
    that had to switch something on was testing a path no user ran.
    """
    module = _load_addon("blended_overlay_provider")
    module.register()
    try:
        yield module
    finally:
        module.unregister()


def _live_style():
    """The style the overlay itself will use in this Blender."""
    return overlay.style_from_theme(bpy.context.preferences.system.ui_scale)


def _live_overlay():
    """The transcript_overlay module `sys.modules` holds right now.

    Not this file's import: a library purge replaces the object, and
    the draw handler's handle lives in whichever object installed it.
    """
    return importlib.import_module("blended.ui.transcript_overlay")


class _ReloadPreferences:
    """The two fields `_reload_library` reads off preferences.

    The repository path is REAL: with it empty, `_reload_library`
    cannot re-import the purged library at all and returns
    "Reload FAILED", which is a different path from the one under test.
    """

    repository_path = str(REPOSITORY_ROOT)
    developer_mode = False


# --- Real font metrics -----------------------------------------------------


@pytest.mark.parametrize("ui_scale", (1.0, 2.0))
def test_wrapped_prose_fits_the_column_at_every_ui_scale(ui_scale):
    """Measured wrapping, at the scale the pixels are actually drawn.

    Blender's DPI handling does not reach `gpu`/`blf`, so a style that
    did not scale itself would wrap 12 px text into a 2x column and
    leave half the column empty — or wrap 24 px text to a 12 px measure
    and overflow the bubble. Both are caught here.
    """
    style = overlay.style_from_theme(ui_scale)
    region_width_px, region_height_px = REGION_SIZES[ui_scale]
    column = column_rect(
        region_width_px, region_height_px, SIDEBAR_WIDTH_PX, style
    )
    assert column is not None

    frame = layout_transcript(
        [
            _message("user", "You", "Build a crate 0.8 m", 0),
            _message("answer", "Agent", PROSE, 1),
        ],
        column=column,
        style=style,
        measure=overlay._measure,
        scroll_px=0,
    )

    inner_width_px = column.width_px - 2 * style.margin_px - 2 * style.padding_px
    assert frame.texts, "nothing was laid out"
    for run in frame.texts:
        measured_px = overlay._measure(run.text, run.size_px)
        assert measured_px <= inner_width_px, (
            f"{run.text!r} measured {measured_px} px in a {inner_width_px} px column"
        )
    assert any(run.size_px == style.body_font_size_px for run in frame.texts)


def test_the_measure_closure_reads_the_proportional_font():
    """The whole justification for injecting `measure`: a character
    count cannot distinguish these two strings, and the real font
    does. An estimate wraps one of them wrongly by construction."""
    narrow = overlay._measure("iiiiiiiiii", 12)
    wide = overlay._measure("MMMMMMMMMM", 12)

    assert narrow < wide, (narrow, wide)
    assert overlay._measure("abc", 24) > overlay._measure("abc", 12)
    assert overlay._measure("", 12) == 0.0


def test_blf_metrics_are_available_headless():
    """The environment fact the whole design rests on: real metrics with
    no window. If this ever fails, the overlay cannot be laid out in
    `--background` and this suite is testing nothing."""
    blf.size(overlay.FONT_IDENTIFIER, 12)
    width_px, height_px = blf.dimensions(overlay.FONT_IDENTIFIER, "Hello world")

    assert width_px > 0
    assert height_px > 0


# --- Handler lifetime ------------------------------------------------------


def test_the_handler_is_installed_and_removed():
    overlay.register_overlay(lambda: (), lambda: 0)
    assert overlay._HANDLER is not None
    overlay.unregister_overlay()
    assert overlay._HANDLER is None


def test_registering_twice_leaves_exactly_one_handler():
    """A hot reload re-runs `register()`. Two stacked handlers would
    paint the transcript twice at two scroll offsets."""
    overlay.register_overlay(lambda: (), lambda: 0)
    first = overlay._HANDLER
    overlay.register_overlay(lambda: (), lambda: 0)
    try:
        assert overlay._HANDLER is not first, "the old handler was kept"
    finally:
        overlay.unregister_overlay()
    assert overlay._HANDLER is None


def test_unregistering_twice_is_harmless():
    overlay.register_overlay(lambda: (), lambda: 0)
    overlay.unregister_overlay()
    overlay.unregister_overlay()
    assert overlay._HANDLER is None


def test_the_wheel_is_not_captured_before_the_first_message():
    """The hazard that kept the keymap unbound, now fixed instead.

    `cursor_is_over_transcript` used to answer True for the column's
    GEOMETRY whether or not anything was painted there, so binding the
    wheel would swallow viewport zoom over a measured 353 x 868 px strip
    of empty viewport on every fresh session — before the user had sent
    a single message. The hit test now shares `_draw`'s emptiness
    condition, so the wheel is bound unconditionally and still only
    consumes events where there is something to scroll.
    """
    context = _stub_context()
    column = overlay._chat_column(context, _live_style())
    centre_x = column.x_px + column.width_px // 2
    centre_y = column.y_px + column.height_px // 2

    overlay.register_overlay(lambda: (), lambda: 0)
    try:
        assert not overlay.cursor_is_over_transcript(context, centre_x, centre_y), (
            "the wheel would swallow viewport zoom with nothing drawn"
        )
    finally:
        overlay.unregister_overlay()

    painted = (
        TranscriptMessage(
            kind="answer",
            label="blended",
            body="one reply, so there is something to scroll",
            index=0,
        ),
    )
    overlay.register_overlay(lambda: painted, lambda: 0)
    try:
        assert overlay.cursor_is_over_transcript(context, centre_x, centre_y), (
            "the same point must be inside the column once it is painted"
        )
    finally:
        overlay.unregister_overlay()


def test_the_overlay_ships_installed_and_the_wheel_is_bound(addon):
    """The flip: `register()` installs the handler and binds the wheel.

    The flag this replaces (`TRANSCRIPT_OVERLAY_ENABLED = False`) is
    deleted rather than re-pointed — a test re-pinned to the new value
    would pin the same one-path-with-a-switch mistake.
    """
    assert _live_overlay()._HANDLER is not None, "the overlay did not install"
    assert addon._OVERLAY_ERROR == ""
    assert [
        item
        for _, item in addon._KEYMAP_ENTRIES
        if item.idname == addon.BLENDED_OT_scroll_transcript.bl_idname
    ], "the wheel is not bound, so the transcript cannot be scrolled"


def test_drawing_without_a_viewport_is_a_silent_no_op():
    """A draw handler that raises spams the console every frame and can
    wedge the viewport. Headless there is no area at all, which is the
    same shape as every other "not our viewport" case."""
    overlay.register_overlay(lambda: (), lambda: 0)
    try:
        overlay._draw()
    finally:
        overlay.unregister_overlay()
    assert overlay.LAST_DRAW_ERROR == ""


def test_scroll_is_clamped_to_what_the_last_frame_laid_out():
    overlay._MAX_SCROLL_PX = 100
    overlay._SCROLL_PX = 0

    overlay.scroll_by(60)
    assert overlay._SCROLL_PX == 60
    overlay.scroll_by(60)
    assert overlay._SCROLL_PX == 100, "scrolled past the end of the stack"
    overlay.scroll_by(-500)
    assert overlay._SCROLL_PX == 0, "scrolled above the newest reply"


# --- Theme translation -----------------------------------------------------


def test_theme_colours_arrive_as_four_components():
    """`wcol_box.text` is a 3-component theme colour and `gpu` needs
    four. A 3-tuple reaching `uniform_float` is a draw-time exception,
    i.e. an empty viewport with the error only in the console."""
    style = overlay.style_from_theme(1.0)

    for name in (
        "scrim_rgba",
        "agent_bubble_rgba",
        "user_bubble_rgba",
        "error_bubble_rgba",
        "code_band_rgba",
        "body_text_rgba",
        "label_text_rgba",
    ):
        colour = getattr(style, name)
        assert len(colour) == 4, f"{name} is {colour}"
        assert all(0.0 <= channel <= 1.0 for channel in colour), f"{name} is {colour}"


def test_the_code_band_contrasts_with_the_themed_bubble():
    """The measured GUI defect, 2026-09-06. With the band pinned to
    (0.11, 0.11, 0.11), Blender's own dark theme reported
    `wcol_box.inner` at 0.114 — a 0.004 step — and the code block was
    indistinguishable from the bubble in the live screenshot. Asserted
    against the REAL theme, because that is the value that was wrong."""
    style = overlay.style_from_theme(1.0)

    bubble = style.agent_bubble_rgba
    band = style.code_band_rgba
    step = max(abs(band[channel] - bubble[channel]) for channel in range(3))
    assert step >= CODE_BAND_CONTRAST, (
        f"band {band} is only {step} from bubble {bubble}"
    )
    assert band[3] == bubble[3], "the band must keep the bubble's alpha"


def test_every_pixel_field_doubles_at_twice_the_ui_scale():
    one = overlay.style_from_theme(1.0)
    two = overlay.style_from_theme(2.0)

    pixel_fields = [
        name for name in one.__dataclass_fields__ if name.endswith("_px")
    ]
    assert pixel_fields, "no pixel fields to scale"
    for name in pixel_fields:
        assert getattr(two, name) == 2 * getattr(one, name), name
    assert two.line_spacing_factor == one.line_spacing_factor
    assert two.maximum_lines_newest == one.maximum_lines_newest
    assert two.scrim_rgba == one.scrim_rgba


# --- Scoping and the wheel -------------------------------------------------


def test_the_column_is_inset_by_the_sidebar_when_regions_overlap():
    """With `use_region_overlap` on — Blender's default — the sidebar is
    painted OVER the window region, so the window's width includes the
    pixels it covers and the column must be inset or it lands under the
    chat."""
    context = _stub_context()
    expected_px = (
        SIDEBAR_WIDTH_PX
        if bpy.context.preferences.system.use_region_overlap
        else 0
    )

    assert overlay._sidebar_inset_px(context.area) == expected_px

    column = overlay._chat_column(context, overlay.style_from_theme(1.0))
    assert column is not None
    assert column.x_px + column.width_px <= 1600 - expected_px


def test_no_column_where_the_sidebar_is_not_showing_the_chat():
    """The overlay's whole scoping rule, and why it needs no preference
    toggle: it paints over the viewport the user put the chat in, and
    nowhere else."""
    style = overlay.style_from_theme(1.0)

    assert overlay._chat_column(_stub_context(category="Item"), style) is None
    assert overlay._chat_column(_stub_context(sidebar_width_px=1), style) is None
    assert overlay._chat_column(_stub_context(area_type="IMAGE_EDITOR"), style) is None


def test_the_wheel_is_captured_only_over_the_transcript_column():
    """Outside the column the operator returns PASS_THROUGH, so the
    wheel keeps zooming the scene. Getting this wrong takes the
    viewport's own navigation away from the user.

    The column is built from the LIVE `ui_scale` because that is what
    `cursor_is_over_transcript` reads — a test that assumed 1.0 while
    the preference said something else compared two different columns.

    A painted transcript is registered first because the hit test now
    requires one: this test is about the column's BOUNDARY, and without
    a provider every answer would be False for the emptiness reason
    instead, which would make the boundary assertions vacuous.
    """
    context = _stub_context()
    column = overlay._chat_column(context, _live_style())
    overlay.register_overlay(
        lambda: (
            TranscriptMessage(
                kind="answer", label="blended", body="painted", index=0
            ),
        ),
        lambda: 0,
    )
    try:
        assert overlay.cursor_is_over_transcript(
            context, column.x_px + 5, column.y_px + 5
        )
        assert overlay.cursor_is_over_transcript(
            context,
            column.x_px + column.width_px - 1,
            column.y_px + column.height_px - 1,
        )
        assert not overlay.cursor_is_over_transcript(
            context, column.x_px - 5, column.y_px + 5
        )
        assert not overlay.cursor_is_over_transcript(
            context, column.x_px + 5, column.y_px + column.height_px + 5
        )
        assert not overlay.cursor_is_over_transcript(
            _stub_context(category="Item"), column.x_px + 5, column.y_px + 5
        )
    finally:
        overlay.unregister_overlay()


# --- The addon's provider --------------------------------------------------


def test_the_overlay_shows_the_conversation_and_not_the_traffic(addon):
    """Conversation, not traffic. The traffic kinds stay in the record
    panel where each is one disclosable row; `step` events never appear
    anywhere — they move the plan card."""
    addon._STATE.transcript = [
        ("user", "Build a crate"),
        ("thinking", "considering the slats"),
        ("tool", 'run_python({"source": "x"})'),
        ("result", "OK: Crate"),
        ("step", "1"),
        ("answer", "Built it."),
    ]
    bpy.context.scene.blended_chat.show_details = False

    bodies = [message.body for message in addon._transcript_messages()]
    assert bodies == ["Build a crate", "Built it."]

    bpy.context.scene.blended_chat.show_details = True
    detailed = [message.kind for message in addon._transcript_messages()]
    assert "tool" in detailed
    assert "result" in detailed
    assert "thinking" in detailed
    assert "step" not in detailed, "progress events are not conversation"


def test_the_streaming_reply_is_appended_last_and_keeps_its_tail(addon):
    """The words being written are at the END of the text and the
    cursor has to stay visible, so the live message asks the layout to
    keep its tail rather than its head."""
    addon._STATE.transcript = [("user", "Build a crate"), ("answer", "Built it.")]
    addon._STATE.live_kind = "content"
    addon._STATE.live_text = "Now bevelling"

    messages = addon._transcript_messages()

    assert messages[-1].kind == "answer", "`content` deltas are answer text"
    assert messages[-1].body.startswith("Now bevelling")
    assert messages[-1].body.endswith(addon._LIVE_CURSOR)
    assert messages[-1].prefer_tail is True
    assert messages[-1].index == len(addon._STATE.transcript)
    assert [message.prefer_tail for message in messages[:-1]] == [False, False]


def test_registering_the_addon_installs_the_overlay(addon):
    """The wiring: `register()` puts the handler in place and reports no
    failure. Read through `sys.modules`, not through this file's own
    import: an earlier hot-reload test purges `blended.*`, so the live
    module is not necessarily the one imported at collection time."""
    live = _live_overlay()

    assert addon._OVERLAY_ERROR == "", addon._OVERLAY_ERROR
    assert live._HANDLER is not None
    assert addon._overlay_status() == ("", False)


def test_a_library_reload_never_orphans_the_overlay(addon):
    """The measured hot-reload hazard, 2026-09-06.

    `devreload.purge_library_modules()` drops every `blended.*` module
    and the draw handler's handle lives in that module's globals, so a
    FRESH `transcript_overlay` cannot remove a handler installed by the
    module it replaced. Without a teardown before the purge, every
    reload leaves another live handler painting the old session's state
    from the old code — and the panel's status rows would then be read
    off a module nothing is drawing through.

    Runs last in this file on purpose: it invalidates every `blended.*`
    module object, including this file's own import.
    """
    stale = _live_overlay()
    assert stale._HANDLER is not None, "nothing was installed to orphan"

    summary = addon._reload_library(_ReloadPreferences())

    fresh = _live_overlay()
    assert fresh is not stale, f"the library was not purged: {summary}"
    assert stale._HANDLER is None, "the old handler was left installed"
    assert fresh._HANDLER is not None, "the reloaded overlay was not installed"
    assert addon._OVERLAY_ERROR == "", addon._OVERLAY_ERROR


def _message(kind, label, body, index, prefer_tail=False):
    from blended.ui.transcript_layout import TranscriptMessage

    return TranscriptMessage(
        kind=kind, label=label, body=body, index=index, prefer_tail=prefer_tail
    )
