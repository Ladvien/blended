"""Scene context renderers, tested as pure behavior.

No bpy import: the renderers are pure functions over immutable snapshots,
so every assertion here is about what a consumer sees in the prompt block
or panel line — never about plumbing.
"""

from __future__ import annotations

from blended.agent.scene_context import (
    DIMENSION_DECIMALS,
    DIMENSION_SEPARATOR,
    ELLIPSIS,
    MAXIMUM_SELECTED_OBJECTS_LISTED,
    ObjectSnapshot,
    SceneContext,
    render_scene_context,
    summarize_scene_context,
)


def _snapshot(
    name: str,
    dims: tuple[float, float, float] = (0.0, 0.0, 0.0),
    loc: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> ObjectSnapshot:
    return ObjectSnapshot(
        name=name,
        object_type="MESH",
        dimensions_m=dims,
        location_m=loc,
    )


def _context(
    active: str = "",
    selected: tuple[ObjectSnapshot, ...] = (),
    selected_total: int | None = None,
    mode: str = "OBJECT",
    total: int = 0,
    frame: int = 1,
) -> SceneContext:
    return SceneContext(
        active_object_name=active,
        selected=selected,
        selected_total_count=selected_total if selected_total is not None else len(selected),
        mode=mode,
        total_object_count=total,
        frame_current=frame,
    )


# ---------------------------------------------------------------------------
# render_scene_context
# ---------------------------------------------------------------------------


def test_empty_context_renders_to_empty_string():
    """Nothing to say → empty string → the caller appends nothing."""
    context = _context(active="", selected=(), total=0)
    assert render_scene_context(context) == ""


def test_nonempty_scene_with_no_selection_still_renders():
    """Objects exist but none selected: the block names the scene state,
    it does not collapse to empty."""
    context = _context(active="", selected=(), total=5, mode="OBJECT")
    rendered = render_scene_context(context)
    assert rendered != ""
    assert "5 objects" in rendered
    assert "mode OBJECT" in rendered


def test_active_object_named_first_even_when_alphabetically_last():
    """The user picked "Zebra" as active; it must head the selection list
    despite sorting after "Apple" and "Mango"."""
    zebra = _snapshot("Zebra")
    apple = _snapshot("Apple")
    mango = _snapshot("Mango")
    context = _context(
        active="Zebra",
        selected=(zebra, apple, mango),
        total=3,
    )
    rendered = render_scene_context(context)

    selected_clause = rendered.split("selected: ")[1].split(" |")[0]
    names = [n.strip() for n in selected_clause.split(",")]
    assert names[0] == "Zebra"
    assert "Apple" in names
    assert "Mango" in names


def test_dimensions_and_location_use_documented_precision_and_separator():
    """0.6 must render as 0.60 (two decimals) and the dimension separator
    must be the documented × character, not an x or a *."""
    crate = _snapshot("Crate", dims=(0.6, 0.4, 0.5), loc=(0.0, 0.0, 0.25))
    context = _context(active="Crate", selected=(crate,), total=3)
    rendered = render_scene_context(context)

    expected_dims = (
        f"0.60{DIMENSION_SEPARATOR}0.40{DIMENSION_SEPARATOR}0.50 m"
    )
    assert expected_dims in rendered
    assert "(0.00, 0.00, 0.25)" in rendered
    # A plausible bug: using the wrong separator or wrong precision.
    assert "0.6×0.4×0.5" not in rendered
    assert "0.60x0.40x0.50" not in rendered


def test_precision_tracks_the_named_constant():
    """If DIMENSION_DECIMALS were changed to 3, the rendered text must
    change to match — proving the constant is load-bearing, not a
    coincidence."""
    value = 0.123456
    snap = _snapshot("Probe", dims=(value, value, value), loc=(value, value, value))
    context = _context(active="Probe", selected=(snap,), total=1)
    rendered = render_scene_context(context)

    expected = f"{value:.{DIMENSION_DECIMALS}f}"
    assert expected in rendered


def test_overflow_reports_count_not_silent_truncation():
    """Nine selected, cap eight: the text must say (+1 more), not drop
    the ninth name as if it were never there."""
    count = MAXIMUM_SELECTED_OBJECTS_LISTED + 1
    snapshots = tuple(_snapshot(f"Obj{i:02d}") for i in range(count))
    context = _context(
        active="",
        selected=snapshots[:MAXIMUM_SELECTED_OBJECTS_LISTED],
        selected_total=count,
        total=count,
    )
    rendered = render_scene_context(context)

    assert "(+1 more)" in rendered
    # The capped name must NOT appear — it was excluded, and the overflow
    # count says so explicitly rather than hiding the truncation.
    capped_name = f"Obj{MAXIMUM_SELECTED_OBJECTS_LISTED:02d}"
    assert capped_name not in rendered
    # The last listed name IS present.
    last_listed = f"Obj{MAXIMUM_SELECTED_OBJECTS_LISTED - 1:02d}"
    assert last_listed in rendered


def test_at_cap_reports_no_overflow():
    """Exactly eight selected: no overflow indicator, all eight named."""
    count = MAXIMUM_SELECTED_OBJECTS_LISTED
    snapshots = tuple(_snapshot(f"Obj{i:02d}") for i in range(count))
    context = _context(
        active="",
        selected=snapshots,
        selected_total=count,
        total=count,
    )
    rendered = render_scene_context(context)

    assert "more)" not in rendered
    assert ELLIPSIS not in rendered.split("selected: ")[1].split(" |")[0]


# ---------------------------------------------------------------------------
# summarize_scene_context
# ---------------------------------------------------------------------------


def test_summarize_empty_context_is_empty():
    assert summarize_scene_context(_context(), 80) == ""


def test_summarize_never_exceeds_limit():
    crate = _snapshot("Crate", dims=(0.6, 0.4, 0.5), loc=(0.0, 0.0, 0.25))
    context = _context(active="Crate", selected=(crate,), total=3)
    full = render_scene_context(context)

    for limit in (1, 5, 10, 20, len(full) - 1, len(full), len(full) + 10):
        summary = summarize_scene_context(context, limit)
        assert len(summary) <= limit, f"limit={limit}: len={len(summary)}"


def test_summarize_ellipsis_exactly_when_truncated():
    crate = _snapshot("Crate", dims=(0.6, 0.4, 0.5), loc=(0.0, 0.00, 0.25))
    context = _context(active="Crate", selected=(crate,), total=3)
    full = render_scene_context(context)

    # Limit >= full length → no ellipsis.
    assert not summarize_scene_context(context, len(full)).endswith(ELLIPSIS)
    assert not summarize_scene_context(context, len(full) + 5).endswith(ELLIPSIS)

    # Limit < full length → ellipsis.
    for limit in (5, 10, 20, len(full) - 1):
        summary = summarize_scene_context(context, limit)
        assert summary.endswith(ELLIPSIS), f"limit={limit}: {summary!r}"
        # The ellipsis replaced the tail, so the summary is the prefix.
        assert summary[:-len(ELLIPSIS)] == full[:limit - len(ELLIPSIS)]


def test_summarize_zero_limit_returns_empty():
    crate = _snapshot("Crate", dims=(0.6, 0.4, 0.5))
    context = _context(active="Crate", selected=(crate,), total=1)
    assert summarize_scene_context(context, 0) == ""