"""Word wrapping for Blender's sidebar panel.

Blender's `UILayout.label()` cannot wrap. Given text wider than the
region it CLIPS THE MIDDLE and inserts an ellipsis — so the beginning
and end survive and the substance vanishes, which is the worst possible
failure for reading an agent's output.

There is no wrapping primitive to reach for: labels are the only text
element the panel API offers. So wrapping has to be done manually,
against the region's real pixel width, and the result emitted as one
label per line.

The character-width estimate is the conventional one used by Blender
addons — the UI font is not monospaced and the API exposes no text
measurement, so this is necessarily approximate. It errs narrow: a
slightly short line looks fine, while a slightly long one gets clipped
by Blender and loses its middle again.
"""

from __future__ import annotations

import textwrap

APPROXIMATE_CHARACTER_WIDTH_PX = 7.0
PANEL_HORIZONTAL_PADDING_PX = 34
MINIMUM_WRAP_CHARACTERS = 24


def characters_for_width(region_width_px: float, ui_scale: float = 1.0) -> int:
    """How many characters fit across a region of this pixel width."""
    usable_width_px = region_width_px - PANEL_HORIZONTAL_PADDING_PX
    characters = int(usable_width_px / (APPROXIMATE_CHARACTER_WIDTH_PX * max(ui_scale, 0.1)))
    return max(MINIMUM_WRAP_CHARACTERS, characters)


def wrap_for_region(
    body_text: str, region_width_px: float, ui_scale: float = 1.0
) -> list[str]:
    """Wrap text to the region width, one entry per rendered label line.

    Blank lines are preserved so paragraph breaks survive, and long
    unbroken tokens (file paths, tracebacks) are split rather than
    allowed to overflow and be clipped.
    """
    characters_per_line = characters_for_width(region_width_px, ui_scale)

    wrapped_lines: list[str] = []
    for paragraph in body_text.splitlines() or [""]:
        if not paragraph.strip():
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(
            textwrap.wrap(
                paragraph,
                width=characters_per_line,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return wrapped_lines
