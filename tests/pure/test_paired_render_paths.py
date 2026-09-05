"""Pure layer: ``paired_render_paths`` — the (previous, latest) extraction.

The contract is D4 (DOI 10.48550/arXiv.2604.11082): this turn's render
beside the previous one.  ``paired_render_paths`` is the pure half of
``ui.previews`` — it reads the panel's ``(kind, text)`` transcript and
returns the two newest ``render`` paths in order.  No ``bpy`` anywhere,
so it runs on every ``make test-pure``.

Every assertion here is about WHICH paths come back and in WHAT ORDER —
a test that passes with the pair swapped is worthless, so the
three-render case carries a distinct path in each slot and checks the
exact tuple.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from blended.ui.previews import paired_render_paths

# Distinct paths so a swapped pair is caught, not just a non-None pair.
RENDER_PATH_A = "/tmp/renders/alpha_sheet.png"
RENDER_PATH_B = "/tmp/renders/beta_sheet.png"
RENDER_PATH_C = "/tmp/renders/gamma_sheet.png"


def test_no_render_events_returns_both_none():
    previous, latest = paired_render_paths(
        [
            ("user", "make a crate"),
            ("answer", "done"),
            ("thinking", "planning..."),
        ]
    )
    assert previous is None
    assert latest is None


def test_exactly_one_render_returns_none_and_latest():
    previous, latest = paired_render_paths(
        [
            ("user", "make a crate"),
            ("render", RENDER_PATH_A),
            ("answer", "done"),
        ]
    )
    assert previous is None
    assert latest == Path(RENDER_PATH_A)


def test_three_rends_return_two_newest_in_order():
    """The pair is (second-newest, newest) — a swapped return must fail.

    Each slot carries a distinct path so asserting the exact tuple
    catches both an order swap and a wrong-indices bug.
    """
    previous, latest = paired_render_paths(
        [
            ("render", RENDER_PATH_A),
            ("render", RENDER_PATH_B),
            ("render", RENDER_PATH_C),
        ]
    )
    assert previous == Path(RENDER_PATH_B)
    assert latest == Path(RENDER_PATH_C)
    # The exact-tuple assertion: would fail if the function returned
    # (latest, previous) instead of (previous, latest).
    assert (previous, latest) == (Path(RENDER_PATH_B), Path(RENDER_PATH_C))


def test_unrelated_events_between_renders_do_not_change_answer():
    """Ten non-render events between two renders must not shift the pair."""
    filler = [("tool", f"run_python({i})") for i in range(10)]
    previous, latest = paired_render_paths(
        [("render", RENDER_PATH_A), *filler, ("render", RENDER_PATH_B)]
    )
    assert previous == Path(RENDER_PATH_A)
    assert latest == Path(RENDER_PATH_B)


def test_render_kind_is_case_sensitive():
    """``Render`` (capitalized) is not ``render`` — the channel's kind is
    a fixed lowercase token, and a typo in the emitter must not be
    silently absorbed."""
    previous, latest = paired_render_paths(
        [("Render", RENDER_PATH_A), ("render", RENDER_PATH_B)]
    )
    assert previous is None
    assert latest == Path(RENDER_PATH_B)


def test_empty_render_path_raises():
    """An empty path is a contract violation, not a missing render."""
    with pytest.raises(ValueError, match="empty path"):
        paired_render_paths([("render", "")])


def test_whitespace_only_render_path_raises():
    """A whitespace-only path is the same violation — stripped to empty."""
    with pytest.raises(ValueError, match="empty path"):
        paired_render_paths([("render", "   ")])


def test_empty_transcript_returns_both_none():
    previous, latest = paired_render_paths([])
    assert previous is None
    assert latest is None