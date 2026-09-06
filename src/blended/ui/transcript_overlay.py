"""The GPU transcript: a draw handler that paints replies in the viewport.

Not pure — this is the only module that touches `gpu` and `blf`. It
owns three things and nothing else: the draw handler's lifetime, the
theme→style translation, and turning a `TranscriptFrame` into GPU
batches and glyphs. All of the arithmetic lives in
`transcript_layout`, which is why that part is testable.

Why an overlay at all: `UILayout` has no pixel vocabulary. A reply
drawn with `label()` is a stack of fixed-height rows with no padding,
no corner radius, no measured wrapping, and no way to scroll — and a
Blender region cannot be scrolled from Python at all (View2D is
read-only through RNA and 5.2 exposes no scroll operator), so a
conversation drawn in the sidebar eventually pushes its own prompt box
off the bottom. Painting the replies in the viewport instead makes
them rich text with real metrics, and leaves the sidebar holding only
fixed-height controls.

Two measured environment facts shape this file:

* `gpu.shader.from_builtin` raises `SystemError` with no GL context, so
  the shader is built on FIRST DRAW and cached — never at import. The
  module therefore imports cleanly in `--background`, which is what
  lets `tests/blender` exercise registration headless.
* `blf` works headless: `blf.size(0, 12)` then `blf.dimensions(0, "…")`
  returns real metrics with no window. Wrapping is measured, not
  estimated, in every environment.
"""

from __future__ import annotations

from collections.abc import Callable

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from blended.ui.transcript_layout import (
    RectRun,
    TranscriptFrame,
    TranscriptMessage,
    column_rect,
    layout_transcript,
    rounded_rect_vertices,
)
from blended.ui.transcript_style import (
    SCRIM_RGBA,
    Rgba,
    TranscriptStyle,
    shifted_for_contrast,
)

# Blender's default UI font. `blf.load()` would return a second id for a
# real monospace face; nothing here needs one yet.
FONT_IDENTIFIER = 0
SIDEBAR_REGION_TYPE = "UI"
VIEWPORT_REGION_TYPE = "WINDOW"
VIEWPORT_AREA_TYPE = "VIEW_3D"
# The sidebar tab this overlay belongs to — the same string
# `workspace.activate_chat_tab` writes to `region.active_panel_category`.
# This is what SCOPES the overlay: it paints only in viewports whose
# sidebar is showing the chat, so other workspaces and other viewports
# are untouched and no preference toggle is needed.
CHAT_PANEL_CATEGORY = "blended"
BUILTIN_SHADER_NAME = "UNIFORM_COLOR"
SHADER_COLOR_UNIFORM = "color"
SHADER_POSITION_ATTRIBUTE = "pos"
PRIMITIVE_TYPE = "TRIS"

_HANDLER = None
_SHADER = None
_MESSAGES_PROVIDER: Callable[[], tuple[TranscriptMessage, ...]] | None = None
_REVISION_PROVIDER: Callable[[], int] | None = None
_SCROLL_PX = 0
_MAX_SCROLL_PX = 0
_LAST_REVISION = -1

# What the panel reports instead of the user staring at an empty
# viewport. A draw handler that raises spams the console on every frame
# and can wedge the viewport, so `_draw` swallows the exception here —
# and the panel draws it, so nothing is actually swallowed.
LAST_DRAW_ERROR = ""
COLUMN_TOO_NARROW = False


def register_overlay(
    messages_provider: Callable[[], tuple[TranscriptMessage, ...]],
    revision_provider: Callable[[], int],
) -> None:
    """Install the draw handler, replacing any previous one.

    Replacing rather than adding is what makes a hot reload safe: the
    addon's reload path re-runs `register()`, and two stacked handlers
    would paint the transcript twice with different scroll offsets.
    """
    global _HANDLER, _MESSAGES_PROVIDER, _REVISION_PROVIDER
    unregister_overlay()
    _MESSAGES_PROVIDER = messages_provider
    _REVISION_PROVIDER = revision_provider
    _HANDLER = bpy.types.SpaceView3D.draw_handler_add(
        _draw, (), VIEWPORT_REGION_TYPE, "POST_PIXEL"
    )


def unregister_overlay() -> None:
    """Remove the draw handler. Idempotent — safe to call unregistered."""
    global _HANDLER, _MESSAGES_PROVIDER, _REVISION_PROVIDER, _SHADER
    if _HANDLER is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_HANDLER, VIEWPORT_REGION_TYPE)
        except (ValueError, ReferenceError):
            pass
        _HANDLER = None
    _MESSAGES_PROVIDER = None
    _REVISION_PROVIDER = None
    # The shader belongs to the GL context, not to this module: a
    # reload must not hand a stale handle to the next draw.
    _SHADER = None


def scroll_by(delta_px: int) -> None:
    """Move the transcript by `delta_px`, clamped to what exists.

    Zero is the newest reply at the top of the column; `_MAX_SCROLL_PX`
    puts the oldest kept bubble on the bottom margin. Both bounds come
    from the last frame the overlay laid out, so scrolling can never
    walk the stack off the screen.
    """
    global _SCROLL_PX
    _SCROLL_PX = max(0, min(_MAX_SCROLL_PX, _SCROLL_PX + delta_px))


def _rgba(theme_colour, alpha: float) -> Rgba:
    """A theme colour as RGBA, with the overlay's own alpha.

    Theme colours are sometimes 3-component (`wcol_box.text`) and
    sometimes 4 (`wcol_box.inner`), and the 4-component ones carry an
    alpha meant for an opaque panel. The overlay floats over a 3D
    scene, so translucency is its own design parameter and the theme
    supplies only the hue.
    """
    red, green, blue = (float(channel) for channel in tuple(theme_colour)[:3])
    return (red, green, blue, alpha)


def style_from_theme(ui_scale: float) -> TranscriptStyle:
    """The overlay's style, coloured by the active theme, scaled to DPI.

    Following the theme is H-LAN's first rule — match the design
    language of the host environment (DOI 10.1080/10447318.2026.2632170)
    — so a light-theme user does not get a dark slab over their
    viewport.

    One colour is not a theme read and one is not read at all: the code
    band is DERIVED from the agent bubble so it always contrasts with
    it (Blender's own dark theme put `wcol_box.inner` within 0.004 of
    the old pinned band and it vanished — measured in a live GUI
    session, 2026-09-06), and the error bubble stays a constant because
    the theme exposes no error-widget colour to read.
    """
    default = TranscriptStyle()
    try:
        theme = bpy.context.preferences.themes[0]
        interface = theme.user_interface
        agent_bubble_rgba = _rgba(
            interface.wcol_box.inner, default.agent_bubble_rgba[3]
        )
        return TranscriptStyle(
            agent_bubble_rgba=agent_bubble_rgba,
            user_bubble_rgba=_rgba(
                interface.wcol_regular.inner, default.user_bubble_rgba[3]
            ),
            code_band_rgba=shifted_for_contrast(agent_bubble_rgba),
            body_text_rgba=_rgba(interface.wcol_box.text, default.body_text_rgba[3]),
            label_text_rgba=_rgba(interface.wcol_box.text, default.label_text_rgba[3]),
            scrim_rgba=_rgba(
                theme.view_3d.space.gradients.high_gradient, SCRIM_RGBA[3]
            ),
        ).scaled(ui_scale)
    except (AttributeError, IndexError, KeyError):
        # A theme without those widgets is not a reason to stop drawing.
        return default.scaled(ui_scale)


def _sidebar_region(area):
    for region in area.regions:
        if region.type == SIDEBAR_REGION_TYPE:
            return region
    return None


def _sidebar_shows_chat(area) -> bool:
    """True when this viewport's sidebar is open on the chat tab.

    The overlay's whole scoping rule: paint the transcript over the
    viewport the chat belongs to and nowhere else. No preference
    toggle, because "which viewport" is already answered by which
    sidebar the user put the chat in.
    """
    sidebar = _sidebar_region(area)
    return (
        sidebar is not None
        and sidebar.width > 1
        and sidebar.active_panel_category == CHAT_PANEL_CATEGORY
    )


def _sidebar_inset_px(area) -> int:
    """How far the column must sit from the region's right edge.

    With `use_region_overlap` on — Blender's default — the sidebar is
    painted OVER the `WINDOW` region, so the window's width includes
    the pixels the sidebar covers and the column has to be inset by the
    sidebar's width to sit beside it. With overlap off the window
    region is already inset and the answer is zero.
    """
    if not bpy.context.preferences.system.use_region_overlap:
        return 0
    sidebar = _sidebar_region(area)
    return 0 if sidebar is None else sidebar.width


def _chat_column(context, style: TranscriptStyle):
    """The transcript column for `context`, or None.

    None means "do not paint here": not a 3D viewport, no sidebar, the
    sidebar is not showing the chat tab, or the viewport is too narrow
    for a readable column.
    """
    area = getattr(context, "area", None)
    region = getattr(context, "region", None)
    if area is None or area.type != VIEWPORT_AREA_TYPE:
        return None
    if region is None or region.type != VIEWPORT_REGION_TYPE:
        return None
    if not _sidebar_shows_chat(area):
        return None
    return column_rect(region.width, region.height, _sidebar_inset_px(area), style)


def cursor_is_over_transcript(
    context, mouse_region_x: int, mouse_region_y: int
) -> bool:
    """True when the pointer is inside the PAINTED transcript column.

    The scroll operator asks this before consuming a wheel event, so
    the wheel keeps zooming the viewport everywhere else.

    The emptiness test is the same one `_draw` uses, and it is load
    bearing: with nothing painted, the geometry alone answers True over
    a measured 353 x 868 px strip of empty viewport, so the wheel keymap
    would swallow viewport zoom there on every fresh session before the
    user has sent a single message. That hazard is the reason the
    shelving comment gave for not binding the keymap at all; the fix is
    to make the hit test agree with the paint, not to leave the keymap
    unbound.
    """
    try:
        if _MESSAGES_PROVIDER is None or not _MESSAGES_PROVIDER():
            return False
        style = style_from_theme(bpy.context.preferences.system.ui_scale)
        column = _chat_column(context, style)
    except Exception:  # noqa: BLE001 — an operator must never raise on a wheel
        return False
    if column is None:
        return False
    return (
        column.x_px <= mouse_region_x <= column.x_px + column.width_px
        and column.y_px <= mouse_region_y <= column.y_px + column.height_px
    )


def _measure(text: str, size_px: int) -> float:
    """Real font metrics — the reason this overlay exists."""
    blf.size(FONT_IDENTIFIER, size_px)
    return blf.dimensions(FONT_IDENTIFIER, text)[0]


def _fan_indices(vertex_count: int) -> tuple[tuple[int, int, int], ...]:
    """Triangle-fan indices for a convex ring of `vertex_count` points."""
    return tuple((0, index, index + 1) for index in range(1, vertex_count - 1))


def _draw_rect(rect: RectRun, style: TranscriptStyle) -> None:
    vertices = rounded_rect_vertices(rect, style.corner_segments)
    batch = batch_for_shader(
        _SHADER,
        PRIMITIVE_TYPE,
        {SHADER_POSITION_ATTRIBUTE: vertices},
        indices=_fan_indices(len(vertices)),
    )
    _SHADER.uniform_float(SHADER_COLOR_UNIFORM, rect.rgba)
    batch.draw(_SHADER)


def _rasterise(frame: TranscriptFrame, style: TranscriptStyle) -> None:
    """Paint one laid-out frame: rectangles first, then every glyph."""
    global _SHADER
    if _SHADER is None:
        # First draw, not import: `from_builtin` raises SystemError with
        # no GL context, and this module must import headless.
        _SHADER = gpu.shader.from_builtin(BUILTIN_SHADER_NAME)
    gpu.state.blend_set("ALPHA")
    _SHADER.bind()
    try:
        for rect in frame.rects:
            _draw_rect(rect, style)
    finally:
        gpu.state.blend_set("NONE")

    blf.enable(FONT_IDENTIFIER, blf.CLIPPING)
    blf.clipping(FONT_IDENTIFIER, *frame.clip)
    try:
        for run in frame.texts:
            blf.size(FONT_IDENTIFIER, run.size_px)
            blf.color(FONT_IDENTIFIER, *run.rgba)
            blf.position(FONT_IDENTIFIER, run.x_px, run.y_px, 0)
            blf.draw(FONT_IDENTIFIER, run.text)
    finally:
        blf.disable(FONT_IDENTIFIER, blf.CLIPPING)


def _draw() -> None:
    """The draw handler. Guards first, then one frame of arithmetic."""
    global _LAST_REVISION, _MAX_SCROLL_PX, _SCROLL_PX, COLUMN_TOO_NARROW
    global LAST_DRAW_ERROR
    context = bpy.context
    area = getattr(context, "area", None)
    if area is None or area.type != VIEWPORT_AREA_TYPE:
        return
    try:
        if _MESSAGES_PROVIDER is None:
            return
        style = style_from_theme(context.preferences.system.ui_scale)
        messages = _MESSAGES_PROVIDER()
        if not messages:
            COLUMN_TOO_NARROW = False
            return
        column = _chat_column(context, style)
        if column is None:
            # Distinguish "not our viewport" from "our viewport, too
            # narrow": only the latter is worth telling the user about.
            COLUMN_TOO_NARROW = _sidebar_shows_chat(area)
            return
        COLUMN_TOO_NARROW = False

        # A new message returns the stack to the top, where the newest
        # bubble is: the user asked for THIS reply, not the scroll
        # position they left behind.
        if _REVISION_PROVIDER is not None:
            revision = _REVISION_PROVIDER()
            if revision != _LAST_REVISION:
                _LAST_REVISION = revision
                _SCROLL_PX = 0

        frame = layout_transcript(
            messages,
            column=column,
            style=style,
            measure=_measure,
            scroll_px=_SCROLL_PX,
        )
        _MAX_SCROLL_PX = frame.max_scroll_px
        _SCROLL_PX = min(_SCROLL_PX, _MAX_SCROLL_PX)
        _rasterise(frame, style)
        LAST_DRAW_ERROR = ""
    except Exception as draw_error:  # noqa: BLE001 — surfaced in the panel
        LAST_DRAW_ERROR = f"{type(draw_error).__name__}: {draw_error}"

