"""Where every pixel of the GPU transcript goes — pure arithmetic.

Pure: imports only `dataclasses`, `math`, `typing` and
`transcript_style`. No `bpy`, no `gpu`, no `blf`. That seam is the
point: text measurement arrives as an injected `measure` callable, so
the whole layout — wrapping, capping, stacking, culling, scrolling — is
testable in `tests/pure` without a GL context, and the same code runs
against real `blf` metrics inside Blender.

Why real metrics matter: the native panel estimated a line at
`(width - 34) / (7 * ui_scale)` characters, which is a guess about an
proportional font. It over-wrapped short glyph runs and under-wrapped
capitals, and there was no way to do better because `UILayout` cannot
report a string's width. `blf.dimensions` can, so wrapping stops being
an estimate.

Coordinates are GPU convention throughout: origin bottom-left, `y_px`
of a rectangle is its BOTTOM edge, `y_px` of a text run is its
BASELINE.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from blended.ui.transcript_style import Rgba, TranscriptStyle

# The one wording for "there is more of this elsewhere", shared with the
# record panel's own truncation so the overlay and the record can never
# disagree about where the rest of a message went.
TRUNCATION_NOTE_TEMPLATE = "… {hidden} more lines — open Conversation"
CODE_FENCE_PREFIX = "```"
# The truncation note is itself a row, so a budget that must FIT has to
# hold one back for it.
TRUNCATION_NOTE_ROWS = 1
# Markdown emphasis markers a proportional font cannot render as
# emphasis. Dropped rather than shown as literal asterisks.
MARKDOWN_EMPHASIS = ("**", "__")
# Baseline sits this multiple of the font size below the line box's top:
# an approximation of ascent that leaves the leading below the glyphs,
# where a reader expects it.
ASCENT_FRACTION = 1.0
# A hard-split word must always advance by at least this many
# characters, or a column narrower than one glyph would loop forever.
MINIMUM_SPLIT_CHARACTERS = 1
QUARTER_TURN_RADIANS = math.pi / 2.0
RECTANGLE_CORNER_COUNT = 4

Measure = Callable[[str, int], float]


@dataclass(frozen=True)
class TranscriptMessage:
    """One message the overlay may draw.

    `kind` selects the bubble colour, `label` is the speaker text the
    caller chose, `index` is the position in the session transcript
    (carried so a future copy action can address the message), and
    `prefer_tail` says a body over budget should keep its LAST lines —
    what a streaming reply needs, because the words being written are
    at the end.
    """

    kind: str
    label: str
    body: str
    index: int
    prefer_tail: bool = False


@dataclass(frozen=True)
class ColumnRect:
    """The region-space box the transcript is allowed to paint in."""

    x_px: int
    y_px: int
    width_px: int
    height_px: int


@dataclass(frozen=True)
class RectRun:
    """One filled rectangle, rounded when `radius_px` is positive."""

    x_px: int
    y_px: int
    width_px: int
    height_px: int
    radius_px: int
    rgba: Rgba


@dataclass(frozen=True)
class TextRun:
    """One line of text at one size, positioned by its baseline."""

    x_px: int
    y_px: int
    text: str
    size_px: int
    rgba: Rgba


@dataclass(frozen=True)
class TranscriptFrame:
    """Everything one draw call needs, and nothing that needs a GPU."""

    rects: tuple[RectRun, ...]
    texts: tuple[TextRun, ...]
    content_height_px: int
    max_scroll_px: int
    clip: tuple[int, int, int, int]


@dataclass(frozen=True)
class _Row:
    """One laid-out line, or one paragraph gap.

    A gap is not a row of empty text: an empty label still occupies a
    full line height, which is what turned every paragraph break into
    double spacing in the native panel.
    """

    text: str
    size_px: int
    is_code: bool = False
    gap_px: int = 0

    @property
    def is_gap(self) -> bool:
        return self.gap_px > 0


def column_rect(
    region_width_px: int,
    region_height_px: int,
    sidebar_inset_px: int,
    style: TranscriptStyle,
) -> ColumnRect | None:
    """The transcript column, or None when the viewport is too narrow.

    Right-aligned against `sidebar_inset_px` so the column sits BESIDE
    the chat sidebar rather than under it. Returning None is a real
    answer — at that width there is no honest way to show wrapped prose,
    and the panel says so instead of drawing an unreadable sliver.
    """
    available_px = region_width_px - sidebar_inset_px
    if available_px < style.column_minimum_width_px + 2 * style.margin_px:
        return None
    width_px = min(
        style.column_maximum_width_px,
        max(
            style.column_minimum_width_px,
            int(available_px * style.column_width_fraction),
        ),
    )
    return ColumnRect(
        x_px=region_width_px - sidebar_inset_px - width_px - style.margin_px,
        y_px=style.margin_px,
        width_px=width_px,
        height_px=region_height_px - 2 * style.margin_px,
    )


def rounded_rect_vertices(
    rect: RectRun, segments: int
) -> tuple[tuple[float, float], ...]:
    """A convex ring of vertices for `rect`, counter-clockwise.

    `radius_px == 0` gives the four corners; otherwise each corner is
    `segments` arc segments, i.e. `segments + 1` points, for
    `4 * (segments + 1)` in total. The radius is clamped to half the
    shorter side so a small bubble cannot turn itself inside out.
    """
    left = float(rect.x_px)
    bottom = float(rect.y_px)
    right = left + rect.width_px
    top = bottom + rect.height_px
    if rect.radius_px <= 0 or segments <= 0:
        return ((right, bottom), (right, top), (left, top), (left, bottom))

    radius = float(min(rect.radius_px, rect.width_px / 2.0, rect.height_px / 2.0))
    corners = (
        # (centre, angle at which the corner's arc starts), CCW from the
        # bottom-right so the ring is one continuous convex polygon.
        ((right - radius, bottom + radius), -QUARTER_TURN_RADIANS),
        ((right - radius, top - radius), 0.0),
        ((left + radius, top - radius), QUARTER_TURN_RADIANS),
        ((left + radius, bottom + radius), 2.0 * QUARTER_TURN_RADIANS),
    )
    vertices: list[tuple[float, float]] = []
    for (centre_x, centre_y), start_angle in corners:
        for step in range(segments + 1):
            angle = start_angle + QUARTER_TURN_RADIANS * step / segments
            vertices.append(
                (
                    centre_x + radius * math.cos(angle),
                    centre_y + radius * math.sin(angle),
                )
            )
    return tuple(vertices)


def _longest_prefix_that_fits(
    word: str, size_px: int, available_px: float, measure: Measure
) -> int:
    """How many leading characters of `word` fit — binary search.

    Never returns 0: a column too narrow for one glyph still has to
    make progress, or wrapping loops forever.
    """
    low, high = MINIMUM_SPLIT_CHARACTERS, len(word)
    while low < high:
        middle = (low + high + 1) // 2
        if measure(word[:middle], size_px) <= available_px:
            low = middle
        else:
            high = middle - 1
    return low


def _wrap_line(
    text: str, size_px: int, available_px: float, measure: Measure
) -> list[str]:
    """Greedy word wrap by measured width, hard-splitting long words."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if current and measure(candidate, size_px) > available_px:
            lines.append(current)
            current = word
        else:
            current = candidate
        # `current` is a single word here whenever it can be too wide —
        # either the line just broke onto it, or it is the first word.
        # A word wider than the column is cut at the last character that
        # fits and the remainder carried onto the next line.
        while measure(current, size_px) > available_px:
            fits = _longest_prefix_that_fits(current, size_px, available_px, measure)
            if fits >= len(current):
                break
            lines.append(current[:fits])
            current = current[fits:]
    if current:
        lines.append(current)
    return lines


def _rows_for_body(
    body: str, style: TranscriptStyle, available_px: float, measure: Measure
) -> list[_Row]:
    """Body text as laid-out rows: wrapped prose, verbatim code, gaps.

    A run of lines between ``` fences is code: it keeps its own line
    breaks (wrapping a code line destroys the one thing that makes it
    readable), draws at `code_font_size_px`, and gets a band behind it.
    The fence lines themselves carry no information a reader needs once
    the band is visible, so they are dropped.
    """
    rows: list[_Row] = []
    in_code = False
    for source_line in body.split("\n"):
        if source_line.strip().startswith(CODE_FENCE_PREFIX):
            in_code = not in_code
            continue
        if in_code:
            rows.append(_Row(text=source_line, size_px=style.code_font_size_px, is_code=True))
            continue
        if not source_line.strip():
            rows.append(_Row(text="", size_px=0, gap_px=style.paragraph_gap_px))
            continue
        display_line = source_line
        for marker in MARKDOWN_EMPHASIS:
            display_line = display_line.replace(marker, "")
        rows.extend(
            _Row(text=wrapped, size_px=style.body_font_size_px)
            for wrapped in _wrap_line(
                display_line, style.body_font_size_px, available_px, measure
            )
        )
    return rows


def _tail_row_budget(column: ColumnRect, style: TranscriptStyle) -> int:
    """How many body rows a TAIL-kept bubble may use inside `column`.

    A streaming reply is capped by this rather than by the line budget
    alone: its newest words are at the END, so a bubble taller than the
    column puts the cursor below the fold — which is the one thing a
    stream exists to show (measured in a live GUI session, 2026-09-06:
    a 31-row stream in a 28-row column ended off-screen).

    One row is held back for the truncation note, because the note is
    itself a row and a budget that forgot it overflowed the column by
    exactly one line.
    """
    body_pitch_px = round(style.body_font_size_px * style.line_spacing_factor)
    label_pitch_px = round(style.label_font_size_px * style.line_spacing_factor)
    usable_px = (
        column.height_px
        - 2 * style.margin_px
        - 2 * style.padding_px
        - label_pitch_px
    )
    return max(1, usable_px // body_pitch_px - TRUNCATION_NOTE_ROWS)


def _capped(rows: list[_Row], budget: int, prefer_tail: bool, size_px: int) -> list[_Row]:
    """`rows` cut to `budget` TEXT rows, with a note saying what is hidden.

    Gaps do not spend the budget — they are whitespace, not lines — but
    gaps interior to the kept slice survive, so paragraph structure is
    not destroyed by truncation.

    The note goes on the side the hidden rows are on: below a head-kept
    message, above a tail-kept one. A note at the bottom of a stream
    would point down at rows that are actually above it.
    """
    text_positions = [index for index, row in enumerate(rows) if not row.is_gap]
    if len(text_positions) <= budget:
        return rows
    hidden = len(text_positions) - budget
    note = _Row(text=TRUNCATION_NOTE_TEMPLATE.format(hidden=hidden), size_px=size_px)
    if prefer_tail:
        return [note, *rows[text_positions[-budget] :]]
    return [*rows[: text_positions[budget - 1] + 1], note]


def _bubble_rgba(kind: str, style: TranscriptStyle) -> Rgba:
    if kind == "error":
        return style.error_bubble_rgba
    if kind == "user":
        return style.user_bubble_rgba
    return style.agent_bubble_rgba


def _row_height_px(row: _Row, style: TranscriptStyle) -> int:
    if row.is_gap:
        return row.gap_px
    return round(row.size_px * style.line_spacing_factor)


def layout_transcript(
    messages: Sequence[TranscriptMessage],
    *,
    column: ColumnRect,
    style: TranscriptStyle,
    measure: Measure,
    scroll_px: int = 0,
) -> TranscriptFrame:
    """Lay the transcript out newest-first in `column`.

    Newest at the TOP is the same invariant the native stack had and
    for the same reason: a reply must never move the thing above it.
    Here nothing is above it at all — the column starts at the top edge
    and grows downward, off the bottom, where growth costs nothing.

    `scroll_px` raises the whole stack, revealing older bubbles below;
    `max_scroll_px` is the offset at which the oldest kept bubble's
    bottom edge lands on the column's bottom margin.
    """
    clip = (
        column.x_px,
        column.y_px,
        column.x_px + column.width_px,
        column.y_px + column.height_px,
    )
    if not messages:
        return TranscriptFrame((), (), 0, 0, clip)

    newest_first = list(reversed(messages))[: style.maximum_messages]

    bubble_x_px = column.x_px + style.margin_px
    bubble_width_px = column.width_px - 2 * style.margin_px
    content_x_px = bubble_x_px + style.padding_px
    content_width_px = bubble_width_px - 2 * style.padding_px
    label_pitch_px = round(style.label_font_size_px * style.line_spacing_factor)

    rects: list[RectRun] = [
        RectRun(
            x_px=column.x_px,
            y_px=column.y_px,
            width_px=column.width_px,
            height_px=column.height_px,
            radius_px=0,
            rgba=style.scrim_rgba,
        )
    ]
    texts: list[TextRun] = []

    column_top_px = column.y_px + column.height_px
    cursor_y_px = column_top_px - style.margin_px + scroll_px
    content_height_px = 0

    for position, message in enumerate(newest_first):
        budget = (
            style.maximum_lines_newest
            if position == 0
            else style.maximum_lines_older
        )
        if message.prefer_tail:
            # A stream is read at its END, so it is capped by what the
            # COLUMN can show and not only by the line budget: a bubble
            # taller than the column would put the cursor below the fold.
            budget = min(budget, _tail_row_budget(column, style))
        rows = _capped(
            _rows_for_body(message.body, style, content_width_px, measure),
            budget=budget,
            prefer_tail=message.prefer_tail,
            size_px=style.body_font_size_px,
        )
        bubble_height_px = (
            2 * style.padding_px
            + label_pitch_px
            + sum(_row_height_px(row, style) for row in rows)
        )
        bubble_top_px = cursor_y_px
        bubble_bottom_px = bubble_top_px - bubble_height_px

        # Culled, not clipped: a bubble outside the column emits nothing
        # at all, so a long transcript costs what is VISIBLE rather than
        # what exists. Its height still counts, or scrolling would not
        # reach it.
        if bubble_bottom_px < column_top_px and bubble_top_px > column.y_px:
            rects.append(
                RectRun(
                    x_px=bubble_x_px,
                    y_px=bubble_bottom_px,
                    width_px=bubble_width_px,
                    height_px=bubble_height_px,
                    radius_px=style.corner_radius_px,
                    rgba=_bubble_rgba(message.kind, style),
                )
            )
            row_top_px = bubble_top_px - style.padding_px
            texts.append(
                TextRun(
                    x_px=content_x_px,
                    y_px=round(row_top_px - style.label_font_size_px * ASCENT_FRACTION),
                    text=message.label,
                    size_px=style.label_font_size_px,
                    rgba=style.label_text_rgba,
                )
            )
            row_top_px -= label_pitch_px
            code_band_top_px: int | None = None
            for row in rows:
                height_px = _row_height_px(row, style)
                if row.is_code and code_band_top_px is None:
                    code_band_top_px = row_top_px
                if not row.is_code and code_band_top_px is not None:
                    rects.append(
                        _code_band(
                            bubble_x_px, bubble_width_px, code_band_top_px, row_top_px, style
                        )
                    )
                    code_band_top_px = None
                if not row.is_gap:
                    texts.append(
                        TextRun(
                            x_px=content_x_px,
                            y_px=round(row_top_px - row.size_px * ASCENT_FRACTION),
                            text=row.text,
                            size_px=row.size_px,
                            rgba=style.body_text_rgba,
                        )
                    )
                row_top_px -= height_px
            if code_band_top_px is not None:
                rects.append(
                    _code_band(
                        bubble_x_px, bubble_width_px, code_band_top_px, row_top_px, style
                    )
                )

        content_height_px += bubble_height_px
        if position + 1 < len(newest_first):
            content_height_px += style.message_gap_px
        cursor_y_px = bubble_bottom_px - style.message_gap_px

    return TranscriptFrame(
        rects=tuple(rects),
        texts=tuple(texts),
        content_height_px=content_height_px,
        max_scroll_px=max(
            0, content_height_px - (column.height_px - 2 * style.margin_px)
        ),
        clip=clip,
    )


def _code_band(
    bubble_x_px: int,
    bubble_width_px: int,
    top_px: int,
    bottom_px: int,
    style: TranscriptStyle,
) -> RectRun:
    """The darker band behind a run of code rows.

    Inset from the bubble's edge rather than aligned to the text, so the
    band reads as a block of code and not as a highlight on each line.
    """
    return RectRun(
        x_px=bubble_x_px + style.code_band_inset_px,
        y_px=bottom_px,
        width_px=bubble_width_px - 2 * style.code_band_inset_px,
        height_px=top_px - bottom_px,
        radius_px=0,
        rgba=style.code_band_rgba,
    )
