"""Sidebar text wrapping — the fix for Blender clipping label middles."""

from blended.agent.wrapping import (
    MINIMUM_WRAP_CHARACTERS,
    characters_for_width,
    wrap_for_region,
)

NARROW_SIDEBAR_PX = 240   # Blender's default sidebar
WIDE_SIDEBAR_PX = 700     # dragged out


def test_no_line_exceeds_the_region_width():
    long_text = (
        "The gate rejected this mesh because it has 7 disconnected "
        "components and 305 self-intersecting face pairs, which usually "
        "means parts were joined instead of boolean-unioned."
    )
    for width in (NARROW_SIDEBAR_PX, 400, WIDE_SIDEBAR_PX):
        limit = characters_for_width(width)
        for line in wrap_for_region(long_text, width):
            assert len(line) <= limit, f"line overflows at width {width}: {line!r}"


def test_nothing_is_lost_which_is_the_whole_point():
    """Blender clips the MIDDLE of a long label; wrapping must not."""
    original = (
        "Exported and verified: /tmp/assets/crate.glb (12484 bytes, "
        "334 tris round-tripped)."
    )
    rejoined = " ".join(wrap_for_region(original, NARROW_SIDEBAR_PX))
    for fragment in ("Exported and verified", "12484 bytes", "334 tris"):
        assert fragment in rejoined


def test_wider_region_yields_fewer_lines():
    paragraph = "word " * 80
    narrow = wrap_for_region(paragraph, NARROW_SIDEBAR_PX)
    wide = wrap_for_region(paragraph, WIDE_SIDEBAR_PX)
    assert len(wide) < len(narrow)


def test_blank_lines_survive_so_paragraphs_stay_separated():
    wrapped = wrap_for_region("first para\n\nsecond para", WIDE_SIDEBAR_PX)
    assert "" in wrapped
    assert wrapped[0].startswith("first")
    assert wrapped[-1].startswith("second")


def test_long_unbroken_tokens_are_split_not_overflowed():
    """A traceback path with no spaces must still fit."""
    path_like = "/very/long/path/" + "segment" * 30 + ".py"
    limit = characters_for_width(NARROW_SIDEBAR_PX)
    for line in wrap_for_region(path_like, NARROW_SIDEBAR_PX):
        assert len(line) <= limit


def test_ui_scale_narrows_the_line():
    assert characters_for_width(600, ui_scale=2.0) < characters_for_width(600, ui_scale=1.0)


def test_absurdly_narrow_region_still_returns_usable_lines():
    assert characters_for_width(10) == MINIMUM_WRAP_CHARACTERS
    assert wrap_for_region("some text here", 10)
