"""Pure layer: the GPU transcript's arithmetic.

Everything the overlay decides before a single pixel is touched —
wrapping by measured width, capping a long reply, stacking newest at
the top, culling what is off-column, and how far the stack can scroll.

This suite is why the layout is a separate module. `gpu` cannot be
touched without a GL context (`from_builtin` raises `SystemError` in
`--background`), so a design that mixed layout with rasterising would
be testable only by screenshot. Here `measure` is injected: these tests
pass a monospace-like stub, and `tests/blender/test_transcript_overlay.py`
passes the real `blf` metrics.

`MEASURE_CHARACTER_FACTOR` makes every glyph exactly 0.6 em wide, so
every wrap in this file is arithmetic a reader can check by hand.
"""

from __future__ import annotations

import pytest

from blended.ui.transcript_layout import (
    ColumnRect,
    TranscriptMessage,
    column_rect,
    layout_transcript,
    rounded_rect_vertices,
)
from blended.ui.transcript_style import (
    CODE_BAND_CONTRAST,
    TranscriptStyle,
    shifted_for_contrast,
)

STYLE = TranscriptStyle()
MEASURE_CHARACTER_FACTOR = 0.6
# 400 px wide: inner text width is 400 - 2*16 margin - 2*12 padding =
# 344 px, i.e. 47 body glyphs at 12 px. Tall enough that nothing is
# culled unless a test asks for it.
COLUMN = ColumnRect(x_px=100, y_px=16, width_px=400, height_px=800)
INNER_WIDTH_PX = COLUMN.width_px - 2 * STYLE.margin_px - 2 * STYLE.padding_px
CODE_LINE = (
    "bpy.ops.mesh.primitive_cube_add(size=0.8, location=(0.0, 0.0, 0.4), align='WORLD')"
)


def measure(text: str, size_px: int) -> float:
    return len(text) * size_px * MEASURE_CHARACTER_FACTOR


def _layout(messages, *, column=COLUMN, style=STYLE, scroll_px=0):
    return layout_transcript(
        messages, column=column, style=style, measure=measure, scroll_px=scroll_px
    )


def _bubbles(frame, style=STYLE):
    """The message bubbles: the only rounded rectangles in a frame."""
    return [rect for rect in frame.rects if rect.radius_px == style.corner_radius_px]


def _answer(body: str, index: int = 0, prefer_tail: bool = False):
    return TranscriptMessage(
        kind="answer", label="Agent", body=body, index=index, prefer_tail=prefer_tail
    )


def test_an_empty_transcript_draws_nothing_at_all():
    """Not even the scrim: an unused overlay must be invisible, or the
    viewport carries a grey slab from the moment the addon loads."""
    frame = _layout([])

    assert frame.rects == ()
    assert frame.texts == ()
    assert frame.content_height_px == 0
    assert frame.max_scroll_px == 0
    assert frame.clip == (100, 16, 500, 816)


def test_the_newest_message_is_the_topmost_bubble():
    """Newest at the top, older receding downward — the one direction
    growth costs nothing. Reversing this is what made the user scroll
    to reach their own prompt box in the native panel."""
    frame = _layout(
        [
            _answer("OLDEST reply", index=0),
            _answer("MIDDLE reply", index=1),
            _answer("NEWEST reply", index=2),
        ]
    )

    ordered = [run.text for run in frame.texts if "reply" in run.text]
    assert ordered == ["NEWEST reply", "MIDDLE reply", "OLDEST reply"]
    tops = [rect.y_px + rect.height_px for rect in _bubbles(frame)]
    assert tops == sorted(tops, reverse=True), tops


def test_only_the_newest_messages_are_laid_out():
    """A working window, not the whole history: the overlay redraws on
    every viewport frame and the record panel holds every message."""
    frame = _layout([_answer(f"reply {number}", index=number) for number in range(30)])

    bodies = [run.text for run in frame.texts if run.text.startswith("reply ")]
    assert len(bodies) == STYLE.maximum_messages
    assert bodies[0] == "reply 29", "the newest must be first"
    assert bodies[-1] == f"reply {30 - STYLE.maximum_messages}"


def test_a_bubble_below_the_column_is_culled_but_still_counted():
    """Culled, not clipped: a bubble outside the column emits nothing,
    so a long transcript costs what is VISIBLE. Its height still counts
    or scrolling could never reach it."""
    short_column = ColumnRect(x_px=100, y_px=16, width_px=400, height_px=200)
    messages = [_answer(f"reply {number}", index=number) for number in range(10)]

    frame = _layout(messages, column=short_column)

    assert len(_bubbles(frame)) < STYLE.maximum_messages, "nothing was culled"
    emitted_height = sum(rect.height_px for rect in _bubbles(frame))
    assert frame.content_height_px > emitted_height
    assert frame.max_scroll_px > 0, "culled content has to be reachable"


def test_every_run_stays_inside_the_column():
    """The wrap-width property, and the reason this design exists: a
    character-count estimate cannot guarantee it, a measured wrap can."""
    prose = (
        "The crate is 0.8 m on a side with eight slats, mitred at the "
        "corners and bevelled 2 mm so the edges catch a highlight."
    )
    frame = _layout([_answer(prose), TranscriptMessage("user", "You", prose, 1)])

    left_limit = COLUMN.x_px + STYLE.margin_px + STYLE.padding_px
    right_limit = COLUMN.x_px + COLUMN.width_px - STYLE.margin_px - STYLE.padding_px
    for run in frame.texts:
        assert run.x_px == left_limit
        assert measure(run.text, run.size_px) <= right_limit - left_limit, run.text
    for rect in frame.rects:
        assert rect.x_px >= COLUMN.x_px
        assert rect.x_px + rect.width_px <= COLUMN.x_px + COLUMN.width_px


def test_a_word_wider_than_the_column_is_hard_split():
    """An unbroken 200-character token — a path, a hash, a base64 blob —
    must be cut, not allowed to run out of the bubble."""
    frame = _layout([_answer("x" * 200)])

    rows = [run.text for run in frame.texts if run.text.startswith("x")]
    assert len(rows) > 1, "the token was never split"
    assert "".join(rows) == "x" * 200, "hard-splitting must not lose characters"
    for row in rows:
        assert measure(row, STYLE.body_font_size_px) <= INNER_WIDTH_PX


def test_a_long_body_is_capped_and_says_how_much_is_hidden():
    """The model decides how long its reply is, so the overlay caps it
    and points at the record. 200 source lines, 40 allowed, so 160 are
    hidden — and the wording is the record panel's own, so the two can
    never disagree about where the rest went."""
    frame = _layout([_answer("\n".join(f"line {n}" for n in range(200)))])

    rows = [run.text for run in frame.texts if run.text != "Agent"]
    assert len(rows) == STYLE.maximum_lines_newest + 1
    assert rows[0] == "line 0"
    assert rows[STYLE.maximum_lines_newest - 1] == "line 39"
    assert rows[-1] == "… 160 more lines — open Conversation"


def test_prefer_tail_keeps_the_last_lines():
    """What a streaming reply needs: the words being written are at the
    END of the text, and the cursor has to stay visible.

    The note goes ABOVE a tail-kept message, because that is the side
    the hidden rows are on — a note at the bottom of a stream points
    down at rows that are actually above it.
    """
    frame = _layout(
        [_answer("\n".join(f"line {n}" for n in range(200)), prefer_tail=True)]
    )

    rows = [run.text for run in frame.texts if run.text != "Agent"]
    assert rows[-1] == "line 199", "the streaming cursor must be the last row"
    assert "line 0" not in rows
    assert rows[0].endswith("more lines — open Conversation")
    assert rows[1] == "line 160"


def test_a_streaming_reply_is_capped_to_what_the_column_can_show():
    """The measured regression, 2026-09-06: a 31-row stream in a 28-row
    column put its own cursor below the fold, so the one thing a stream
    exists to show was off-screen. A tail-kept message is therefore
    capped by the COLUMN, not only by the line budget."""
    short_column = ColumnRect(x_px=100, y_px=16, width_px=400, height_px=300)
    body = "\n".join(f"line {n}" for n in range(30)) + "\nstill being writ ▍"

    frame = _layout([_answer(body, prefer_tail=True)], column=short_column)

    rows = [run.text for run in frame.texts if run.text != "Agent"]
    assert rows[-1] == "still being writ ▍", "the cursor is not the last row"
    bubble = _bubbles(frame)[0]
    assert bubble.height_px <= short_column.height_px - 2 * STYLE.margin_px, (
        "the streaming bubble is taller than the column it sits in"
    )
    assert bubble.y_px >= short_column.y_px, "the bubble hangs below the column"
    assert len(rows) < 31, "nothing was capped"


def test_a_finished_reply_is_not_capped_by_the_column():
    """Only a stream trades length for a visible tail. A finished reply
    keeps its full line budget and is reached by scrolling, so nothing
    the model said is silently dropped at a small window size."""
    short_column = ColumnRect(x_px=100, y_px=16, width_px=400, height_px=300)
    body = "\n".join(f"line {n}" for n in range(30))

    frame = _layout([_answer(body)], column=short_column)

    assert frame.max_scroll_px > 0
    assert _bubbles(frame)[0].height_px > short_column.height_px


def test_older_messages_get_a_smaller_line_budget():
    """Older replies are context, not the thing being read."""
    body = "\n".join(f"line {n}" for n in range(200))
    frame = _layout([_answer(body, index=0), _answer("newest", index=1)])

    rows = [run.text for run in frame.texts if run.text.startswith("line ")]
    assert len(rows) == STYLE.maximum_lines_older


def test_an_empty_source_line_is_a_gap_not_a_row():
    """An empty text row still occupies a full line height, which is
    what turned every paragraph break into double spacing in the native
    panel. A gap is shorter and carries no glyph."""
    with_gap = _layout([_answer("alpha\n\nbeta")])
    without_gap = _layout([_answer("alpha\nbeta")])

    assert [run.text for run in with_gap.texts] == ["Agent", "alpha", "beta"]
    assert (
        _bubbles(with_gap)[0].height_px - _bubbles(without_gap)[0].height_px
        == STYLE.paragraph_gap_px
    )


def test_a_fenced_code_block_is_banded_and_never_wrapped():
    """Wrapping a code line destroys the one thing that makes it
    readable, so code keeps its own breaks and gets a darker band
    instead. The fences carry nothing once the band is visible."""
    frame = _layout(
        [_answer(f"Here is the code:\n```python\n{CODE_LINE}\n```\nRendered five views.")]
    )

    texts = [run.text for run in frame.texts]
    assert CODE_LINE in texts, "the code line was wrapped or dropped"
    assert measure(CODE_LINE, STYLE.code_font_size_px) > INNER_WIDTH_PX, (
        "this test proves nothing unless the code line overflows the column"
    )
    assert not [text for text in texts if text.startswith("```")]
    bands = [rect for rect in frame.rects if rect.rgba == STYLE.code_band_rgba]
    assert len(bands) == 1
    assert bands[0].height_px == round(
        STYLE.code_font_size_px * STYLE.line_spacing_factor
    )


def test_code_is_drawn_at_the_code_size():
    frame = _layout([_answer(f"```\n{CODE_LINE}\n```")])

    code_run = next(run for run in frame.texts if run.text == CODE_LINE)
    assert code_run.size_px == STYLE.code_font_size_px


def test_max_scroll_is_zero_when_everything_fits():
    frame = _layout([_answer("Built it."), _answer("Bevelled it.", index=1)])

    assert frame.max_scroll_px == 0


def test_scrolling_to_the_maximum_lands_the_oldest_bubble_on_the_margin():
    """The scroll bound's contract: at `max_scroll_px` the oldest kept
    bubble sits on the column's bottom margin — no further, so the
    stack can never be scrolled off the screen."""
    short_column = ColumnRect(x_px=100, y_px=16, width_px=400, height_px=240)
    messages = [_answer(f"reply {number}", index=number) for number in range(8)]

    unscrolled = _layout(messages, column=short_column)
    scrolled = _layout(
        messages, column=short_column, scroll_px=unscrolled.max_scroll_px
    )

    assert "reply 0" not in [run.text for run in unscrolled.texts]
    assert "reply 0" in [run.text for run in scrolled.texts]
    assert min(rect.y_px for rect in _bubbles(scrolled)) == (
        short_column.y_px + STYLE.margin_px
    )


@pytest.mark.parametrize(
    ("kind", "attribute"),
    (
        ("error", "error_bubble_rgba"),
        ("user", "user_bubble_rgba"),
        ("answer", "agent_bubble_rgba"),
        ("thinking", "agent_bubble_rgba"),
    ),
)
def test_the_bubble_colour_says_what_kind_of_message_it_is(kind, attribute):
    """Errors have to read at a glance; anything the agent said that is
    not an error is one colour, so the exception stands out."""
    frame = _layout([TranscriptMessage(kind, "Label", "body", 0)])

    assert _bubbles(frame)[0].rgba == getattr(STYLE, attribute)


def test_the_scrim_covers_the_whole_column_behind_the_bubbles():
    frame = _layout([_answer("Built it.")])

    scrim = frame.rects[0]
    assert scrim.rgba == STYLE.scrim_rgba
    assert (scrim.x_px, scrim.y_px) == (COLUMN.x_px, COLUMN.y_px)
    assert (scrim.width_px, scrim.height_px) == (COLUMN.width_px, COLUMN.height_px)
    assert scrim.radius_px == 0


def test_column_rect_refuses_a_viewport_too_narrow_to_read():
    """None is a real answer: at that width there is no honest way to
    show wrapped prose, and the panel says so instead of drawing an
    unreadable sliver."""
    assert column_rect(500, 900, 200, STYLE) is None
    assert (
        column_rect(STYLE.column_minimum_width_px + 2 * STYLE.margin_px, 900, 0, STYLE)
        is not None
    )


def test_column_rect_right_aligns_against_the_sidebar():
    """With region overlap on, the window region's width includes the
    pixels the sidebar covers, so the column has to be inset by the
    sidebar's width to sit BESIDE the chat rather than under it."""
    sidebar_inset_px = 300
    column = column_rect(1200, 900, sidebar_inset_px, STYLE)

    assert column.x_px + column.width_px + STYLE.margin_px == 1200 - sidebar_inset_px
    assert column.y_px == STYLE.margin_px
    assert column.height_px == 900 - 2 * STYLE.margin_px
    assert STYLE.column_minimum_width_px <= column.width_px
    assert column.width_px <= STYLE.column_maximum_width_px


def test_column_rect_clamps_the_width_at_both_ends():
    # 34% of 400 px is 136, below the minimum; 34% of 4000 is 1360,
    # above the maximum.
    narrow = column_rect(400, 900, 0, STYLE)
    wide = column_rect(4000, 900, 0, STYLE)

    assert narrow.width_px == STYLE.column_minimum_width_px
    assert wide.width_px == STYLE.column_maximum_width_px


def test_an_uninitialised_ui_scale_is_read_as_one():
    """`bpy.context.preferences.system.ui_scale` reads 0.0 when the
    preferences are not fully initialised — measured in `--background`,
    2026-09-06. Clamping that to a small positive factor collapsed the
    whole column to an unreadable sliver (a 320 px minimum became 32),
    so zero has to mean 1.0.
    """
    assert STYLE.scaled(0.0) == STYLE
    assert STYLE.scaled(1.0) == STYLE
    assert STYLE.scaled(2.0).margin_px == 2 * STYLE.margin_px
    assert STYLE.scaled(2.0).column_minimum_width_px == (
        2 * STYLE.column_minimum_width_px
    )
    assert STYLE.scaled(2.0).line_spacing_factor == STYLE.line_spacing_factor


def test_the_code_band_always_contrasts_with_the_bubble():
    """The measured defect, 2026-09-06: the band was an absolute
    constant and Blender's own dark theme put the bubble within 0.004
    of it, so the band was invisible in the live screenshot. Deriving
    it means every theme gets the same visible step, in whichever
    direction there is room for."""
    dark = shifted_for_contrast((0.11, 0.11, 0.11, 0.95))
    light = shifted_for_contrast((0.90, 0.90, 0.90, 0.95))
    black = shifted_for_contrast((0.0, 0.0, 0.0, 0.95))

    assert dark[:3] == pytest.approx([0.01, 0.01, 0.01])
    assert light[:3] == pytest.approx([0.80, 0.80, 0.80])
    assert black[:3] == pytest.approx([CODE_BAND_CONTRAST] * 3), (
        "a black bubble has no room to darken: the band must lighten"
    )
    assert dark[3] == light[3] == black[3] == 0.95, "alpha must survive"
    assert STYLE.code_band_rgba != STYLE.agent_bubble_rgba
    assert abs(STYLE.code_band_rgba[0] - STYLE.agent_bubble_rgba[0]) == pytest.approx(
        CODE_BAND_CONTRAST
    )



def test_rounded_rect_vertices_stay_inside_the_rect():
    """A ring the renderer fans into triangles: it must be a closed
    convex outline of the rectangle, never a vertex outside it."""
    frame = _layout([_answer("Built it.")])
    bubble = _bubbles(frame)[0]

    vertices = rounded_rect_vertices(bubble, STYLE.corner_segments)
    assert len(vertices) == 4 * (STYLE.corner_segments + 1)
    for x_px, y_px in vertices:
        assert bubble.x_px <= x_px <= bubble.x_px + bubble.width_px
        assert bubble.y_px <= y_px <= bubble.y_px + bubble.height_px


def test_a_square_rect_is_four_vertices():
    """`radius_px == 0` — the scrim and the code bands — needs no arc."""
    frame = _layout([_answer("Built it.")])

    assert len(rounded_rect_vertices(frame.rects[0], STYLE.corner_segments)) == 4


def test_the_radius_cannot_turn_a_small_bubble_inside_out():
    """A radius wider than half the box would fold the outline."""
    from blended.ui.transcript_layout import RectRun

    tiny = RectRun(
        x_px=0, y_px=0, width_px=8, height_px=6, radius_px=40, rgba=(0, 0, 0, 1)
    )

    for x_px, y_px in rounded_rect_vertices(tiny, STYLE.corner_segments):
        assert 0 <= x_px <= 8
        assert 0 <= y_px <= 6
