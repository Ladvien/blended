"""Every dimension and colour the GPU transcript overlay draws with.

Pure: no `bpy`, no `gpu`, no `blf`. One of the two modules in this
package the pure test layer may import (see the package docstring).

The overlay exists because `UILayout` has no pixel vocabulary — a
`label()` is one row of a fixed height and there is no padding, no
corner radius and no way to ask how wide a string will be. Drawing the
replies with `gpu` + `blf` instead buys all three, and the price is
that every number Blender used to supply now has to be named here.

Two facts make this file load-bearing rather than decorative:

* Blender's DPI handling does not reach `gpu`/`blf` drawing. A panel
  written in rows scales itself; a `blf.size(0, 12)` is twelve device
  pixels at every `ui_scale`. So `TranscriptStyle.scaled` is the whole
  of the overlay's DPI story, and a real sidebar measures 561 x 1104 px
  at `ui_scale` 2.0 (live GUI session, 2026-09-05).
* Named tolerances, no magic numbers: construction code reads these
  constants and never defines a value of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

# --- Geometry --------------------------------------------------------------

# The column is a fraction of the viewport, clamped: narrow enough that
# the model it describes stays visible, wide enough that prose wraps at
# a readable measure. 34% of a 1600 px viewport is 544 px.
COLUMN_WIDTH_FRACTION = 0.34
COLUMN_MINIMUM_WIDTH_PX = 320
COLUMN_MAXIMUM_WIDTH_PX = 560
COLUMN_MARGIN_PX = 16
BUBBLE_CORNER_RADIUS_PX = 10
BUBBLE_PADDING_PX = 12
BUBBLE_GAP_PX = 10
PARAGRAPH_GAP_PX = 6
# Prose, not code: 1.45 is the line height typography uses for body
# text at these sizes. The native panel had to fake this with
# `scale_y = 0.8` on a fixed row.
LINE_SPACING_FACTOR = 1.45
BODY_FONT_SIZE_PX = 12
LABEL_FONT_SIZE_PX = 11
CODE_FONT_SIZE_PX = 11
CODE_BAND_INSET_PX = 6
# Quarter-circle segments per corner. Four reads as round at a 10 px
# radius and costs 20 vertices a bubble.
CORNER_SEGMENTS = 4

# --- Budgets ---------------------------------------------------------------

# A working window, not the whole history: the record panel holds every
# message, and the overlay redraws on every viewport frame.
MAXIMUM_MESSAGES = 12
MAXIMUM_LINES_NEWEST = 40
MAXIMUM_LINES_OLDER = 6
SCROLL_STEP_PX = 60

# --- Colour ----------------------------------------------------------------

Rgba = tuple[float, float, float, float]

# How far the code band's value sits from the bubble it lies in.
# Measured 2026-09-06 in a live GUI session: with the band pinned to an
# absolute constant, Blender's own dark theme put `wcol_box.inner` at
# 0.114 — within 0.004 of the constant 0.11 — and the band was
# invisible in the screenshot. A band that does not contrast with its
# bubble is not a band, so it is DERIVED from the bubble instead of
# pinned, and every theme gets the same visible step.
CODE_BAND_CONTRAST = 0.10


def shifted_for_contrast(rgba: Rgba, amount: float = CODE_BAND_CONTRAST) -> Rgba:
    """`rgba` moved `amount` away from itself, keeping its alpha.

    Darkens by default and lightens only when there is no room to
    darken, so the result is visible against a dark theme and a light
    one without either becoming a special case elsewhere.
    """
    red, green, blue, alpha = rgba
    direction = -1.0 if max(red, green, blue) >= amount else 1.0
    return (
        min(1.0, max(0.0, red + direction * amount)),
        min(1.0, max(0.0, green + direction * amount)),
        min(1.0, max(0.0, blue + direction * amount)),
        alpha,
    )


# Defaults only: `transcript_overlay.style_from_theme` overrides the
# bubble, band and text colours from the active theme so the overlay
# follows a user's dark/light choice. `ERROR_BUBBLE_RGBA` stays a
# constant because the theme exposes no error-widget colour to read.
SCRIM_RGBA = (0.09, 0.09, 0.09, 0.72)
AGENT_BUBBLE_RGBA = (0.17, 0.17, 0.17, 0.92)
USER_BUBBLE_RGBA = (0.22, 0.26, 0.31, 0.92)
ERROR_BUBBLE_RGBA = (0.45, 0.12, 0.12, 0.92)
CODE_BAND_RGBA = shifted_for_contrast(AGENT_BUBBLE_RGBA)
BODY_TEXT_RGBA = (0.90, 0.90, 0.90, 1.0)
LABEL_TEXT_RGBA = (0.62, 0.68, 0.78, 1.0)

# `scaled()` multiplies exactly the fields whose name ends in this, so
# adding a pixel field to the dataclass scales it without further work.
PIXEL_FIELD_SUFFIX = "_px"
# `bpy.context.preferences.system.ui_scale` reads 0.0 when the
# preferences are not fully initialised — measured in `--background`,
# 2026-09-06. Zero is "unknown", not "a tenth of a pixel", and
# clamping it to a small positive number collapses the whole column to
# an unreadable sliver.
DEFAULT_UI_SCALE = 1.0


@dataclass(frozen=True)
class TranscriptStyle:
    """The overlay's whole parameter set, serializable and frozen."""

    column_width_fraction: float = COLUMN_WIDTH_FRACTION
    column_minimum_width_px: int = COLUMN_MINIMUM_WIDTH_PX
    column_maximum_width_px: int = COLUMN_MAXIMUM_WIDTH_PX
    margin_px: int = COLUMN_MARGIN_PX
    corner_radius_px: int = BUBBLE_CORNER_RADIUS_PX
    padding_px: int = BUBBLE_PADDING_PX
    message_gap_px: int = BUBBLE_GAP_PX
    paragraph_gap_px: int = PARAGRAPH_GAP_PX
    line_spacing_factor: float = LINE_SPACING_FACTOR
    body_font_size_px: int = BODY_FONT_SIZE_PX
    label_font_size_px: int = LABEL_FONT_SIZE_PX
    code_font_size_px: int = CODE_FONT_SIZE_PX
    code_band_inset_px: int = CODE_BAND_INSET_PX
    corner_segments: int = CORNER_SEGMENTS
    maximum_messages: int = MAXIMUM_MESSAGES
    maximum_lines_newest: int = MAXIMUM_LINES_NEWEST
    maximum_lines_older: int = MAXIMUM_LINES_OLDER
    scrim_rgba: Rgba = SCRIM_RGBA
    agent_bubble_rgba: Rgba = AGENT_BUBBLE_RGBA
    user_bubble_rgba: Rgba = USER_BUBBLE_RGBA
    error_bubble_rgba: Rgba = ERROR_BUBBLE_RGBA
    code_band_rgba: Rgba = CODE_BAND_RGBA
    body_text_rgba: Rgba = BODY_TEXT_RGBA
    label_text_rgba: Rgba = LABEL_TEXT_RGBA

    def scaled(self, ui_scale: float) -> TranscriptStyle:
        """This style at `ui_scale`, pixel fields multiplied.

        Colours, fractions, counts and `line_spacing_factor` are
        untouched: they are already dimensionless. Every `*_px` field
        is multiplied and rounded, so `scaled(2.0)` is exactly twice
        `scaled(1.0)` for integer inputs — the overlay's only defence
        against a HiDPI display, where Blender scales the panel it no
        longer draws and nothing scales the pixels it does.

        A non-positive `ui_scale` means Blender has not told us yet and
        is read as 1.0; see `DEFAULT_UI_SCALE`.
        """
        factor = ui_scale if ui_scale > 0.0 else DEFAULT_UI_SCALE
        scaled_fields = {
            field.name: round(getattr(self, field.name) * factor)
            for field in fields(self)
            if field.name.endswith(PIXEL_FIELD_SUFFIX)
        }
        return replace(self, **scaled_fields)
