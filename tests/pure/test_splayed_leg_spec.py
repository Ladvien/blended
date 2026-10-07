"""The placement arithmetic, checked without Blender.

`SplayedLegSpec` exists because the same trigonometry was got wrong
twice — once by this suite's reference stool, once by the agent at
iteration 17 — and both times the symptom was a sole centred at
r=0.1281 m against a specified 0.1400. The identity that prevents it is
one line of algebra, so it is asserted as one line of algebra here,
where it runs on every `make test-pure` rather than only when Blender
is available.
"""

import math

import pytest

from blended.evaluate import briefs
from blended.ops.legs import (
    DEFAULT_SOLE_CLEARANCE_MARGIN_M,
    ImpossibleLeg,
    SplayedLegSpec,
)

# The stool the loop actually builds, so the numbers under test are the
# numbers that failed.
STOOL_SPEC = SplayedLegSpec(
    foot_radius_m=briefs.STOOL_FOOT_CIRCLE_RADIUS_M,
    foot_bearing_deg=0.0,
    top_radius_m=briefs.STOOL_SEAT_DIAMETER_M / 2.0 * 0.45,
    top_z_m=briefs.STOOL_TOTAL_HEIGHT_Z_M - briefs.STOOL_SEAT_THICKNESS_M,
    leg_radius_m=0.022,
)


def _axis_radius_at_ground(spec: SplayedLegSpec) -> float:
    """Where the leg's axis crosses z=0, measured from the base up.

    The base sits at `base_radius_m` and `-sole_drop_m`. Climbing back
    to z=0 walks the axis inward by drop * tan(splay), because going
    down the axis leans outward.
    """
    return spec.base_radius_m - spec.sole_drop_m * math.tan(spec.splay_rad)


def test_the_axis_crosses_the_floor_exactly_on_the_foot_circle():
    """The whole fix, in one assertion."""
    assert _axis_radius_at_ground(STOOL_SPEC) == pytest.approx(
        STOOL_SPEC.foot_radius_m, abs=1e-12
    )


def test_the_base_starts_outboard_of_the_foot_circle():
    """Placing the base ON the circle is exactly the 0.1281 mistake."""
    assert STOOL_SPEC.base_radius_m > STOOL_SPEC.foot_radius_m


def test_the_whole_end_cap_clears_the_cut_plane():
    """A cap that straddles z=0 leaves a crescent, not a sole."""
    minimum_drop_m = STOOL_SPEC.leg_radius_m / math.cos(STOOL_SPEC.splay_rad)
    assert STOOL_SPEC.sole_drop_m >= minimum_drop_m
    assert STOOL_SPEC.sole_drop_m == pytest.approx(
        minimum_drop_m + DEFAULT_SOLE_CLEARANCE_MARGIN_M
    )


def test_the_leg_regains_the_length_the_drop_spent():
    """Dropped and not lengthened, the leg no longer reaches the seat."""
    hypotenuse_m = math.hypot(STOOL_SPEC.rise_m, STOOL_SPEC.run_m)
    assert STOOL_SPEC.length_m == pytest.approx(
        hypotenuse_m + STOOL_SPEC.sole_drop_m
    )


def test_a_vertical_leg_needs_no_outboard_offset():
    """Zero splay is not a special case, it is the same formula at 0."""
    vertical = SplayedLegSpec(
        foot_radius_m=0.1,
        foot_bearing_deg=0.0,
        top_radius_m=0.1,
        top_z_m=0.4,
        leg_radius_m=0.02,
    )
    assert vertical.splay_rad == pytest.approx(0.0)
    assert vertical.base_radius_m == pytest.approx(vertical.foot_radius_m)
    assert _axis_radius_at_ground(vertical) == pytest.approx(
        vertical.foot_radius_m
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"top_z_m": 0.0},
        {"top_z_m": -0.1},
        {"leg_radius_m": 0.0},
        {"foot_radius_m": -0.1},
        {"segment_count": 2},
    ],
)
def test_impossible_legs_raise_rather_than_being_approximated(overrides):
    """No nearest-sane-value fallback: bad numbers fail at the door."""
    import dataclasses

    with pytest.raises(ImpossibleLeg):
        dataclasses.replace(STOOL_SPEC, **overrides)
