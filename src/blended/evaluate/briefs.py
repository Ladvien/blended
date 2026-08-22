"""Test briefs: a prompt, and what the result must MEASURE.

A convergence loop needs its acceptance criteria to be executable, not
adjudicated. CADCodeVerify's contribution is exactly this — it recovers
correctness by asking measurable questions of the geometry rather than
asking a VLM whether the picture looks right — and the TikZ visual-
verification study is the reason not to invert that order: verifiers
looking at renders are systematically biased toward accepting.

So every brief carries three kinds of assertion, all measured:

* DIMENSIONS — bounding-box extents per axis, against a named tolerance.
* SOLIDITY PROBES — is there material at this point, or not? This is the
  one that earns its place. "The planter's drainage hole is sealed shut"
  is the canonical wrong-object failure the analyzer cannot see and a
  render will not show: a sealed hole and an open one are the same
  picture from outside. A parity ray cast at the hole's centre answers
  it in a number.
* GROUNDING — the base sits on z=0, within tolerance.
* GROUND CONTACT — each foot presents a flat sole ON z=0, measured as
  an area. Grounding is one number and a single touching point
  satisfies it; standing up requires a face.

Config is separate from construction (project rule): every quantity
below is a named constant with its unit in the name, and briefs compose
those constants. No literal appears inside an assertion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from blended.analyze.mesh_checks import DEFAULT_PROP_TRIANGLE_BUDGET, MeshBudget

# --- Shared tolerances -------------------------------------------------
# Proportion tolerance: the agent is given target dimensions in the
# prompt, so this is a build-accuracy tolerance, not an art tolerance.
DIMENSION_TOLERANCE_M = 0.02
# A base is "on the ground" within this. Tighter than the dimension
# tolerance because snapping to z=0 is an exact operation in the ops
# vocabulary, not an estimate.
GROUNDING_TOLERANCE_M = 0.002
# A sole is "flat on the ground" when its downward face lies in the z=0
# plane within this. Deliberately tighter than GROUNDING_TOLERANCE_M:
# grounding asks where the LOWEST point is, flatness asks whether the
# whole face is down there with it. Measured 2026-08-22 (iteration 4):
# a leg tilted 11.3 deg from vertical and cut at an angle presents a
# sole spanning 0.0118 m in z while its minimum sits exactly at z=0 —
# so base_z passes and the stool still rocks.
SOLE_PLANARITY_TOLERANCE_M = 0.0005
# Sole faces count toward a foot when their centroid falls within this
# of the foot's expected centre. Half the foot-circle radius: wide
# enough for any plausible leg, narrow enough that two feet cannot
# claim the same face.
FOOT_SEARCH_RADIUS_M = 0.07
# A foot must present at least this much flat face. One square
# centimetre — below that it is a chamfer or a numerical sliver, not
# something a stool stands on.
MINIMUM_SOLE_CONTACT_AREA_M2 = 1.0e-4
# Where a foot may sit, measured from the flat sole's own centroid.
# Measured 2026-08-22 (iteration 10): a correct stool's front
# orthographic view puts the 120 and 240 degree legs at the SAME
# world x, so they overlap into what reads as one leg and the view
# cannot show spacing at all. The human answered "Unclear" and was
# right to; placement is not a question a contact sheet can answer.
FOOT_RADIUS_TOLERANCE_M = 0.01
FOOT_ANGLE_TOLERANCE_DEG = 5.0

# --- Brief 1: planter box ----------------------------------------------
PLANTER_WIDTH_X_M = 0.30
PLANTER_DEPTH_Y_M = 0.20
PLANTER_HEIGHT_Z_M = 0.25
PLANTER_WALL_THICKNESS_M = 0.02
PLANTER_DRAIN_HOLE_RADIUS_M = 0.015

# Probe points, derived from the dimensions above so the spec stays
# consistent if a dimension changes.
PLANTER_DRAIN_PROBE_Z_M = PLANTER_WALL_THICKNESS_M / 2.0
PLANTER_CAVITY_PROBE_Z_M = PLANTER_HEIGHT_Z_M * 0.6
PLANTER_WALL_PROBE_X_M = (PLANTER_WIDTH_X_M - PLANTER_WALL_THICKNESS_M) / 2.0
PLANTER_FLOOR_PROBE_X_M = PLANTER_WIDTH_X_M * 0.3

# --- Brief 2: three-legged stool ---------------------------------------
STOOL_SEAT_DIAMETER_M = 0.32
STOOL_TOTAL_HEIGHT_Z_M = 0.45
STOOL_SEAT_THICKNESS_M = 0.04
STOOL_LEG_COUNT = 3
# Feet sit on a circle of this radius; the splay is what made this brief
# worth keeping (see the matrix_world entry in drift/catalog.py).
STOOL_FOOT_CIRCLE_RADIUS_M = 0.14
STOOL_LEG_PROBE_Z_M = 0.03
STOOL_CENTRE_PROBE_Z_M = STOOL_TOTAL_HEIGHT_Z_M * 0.4
STOOL_SEAT_PROBE_Z_M = STOOL_TOTAL_HEIGHT_Z_M - (STOOL_SEAT_THICKNESS_M / 2.0)

AXIS_NAMES = ("x", "y", "z")


@dataclass(frozen=True)
class DimensionSpec:
    """One bounding-box extent the built object must hit."""

    name: str
    axis: str
    expected_m: float
    tolerance_m: float = DIMENSION_TOLERANCE_M

    def __post_init__(self) -> None:
        if self.axis not in AXIS_NAMES:
            raise ValueError(f"{self.name}: axis {self.axis!r} not in {AXIS_NAMES}")


@dataclass(frozen=True)
class SolidityProbe:
    """Is there material at this point?

    `expect_inside=False` is how negative space becomes measurable: a
    drainage hole, a hollow cavity, the gap between a stool's legs.
    """

    name: str
    point_m: tuple[float, float, float]
    expect_inside: bool
    why: str  # what a failure here means, in the brief's own terms


@dataclass(frozen=True)
class ClearAxisProbe:
    """Nothing may block the straight line through this point.

    A parity probe answers "is there material HERE", which is not the
    same question as "does this hole go all the way through". Measured
    2026-08-22 (iteration 1): a planter whose drainage hole was a blind
    RECESS — cut from the cavity down into the floor but not out the
    bottom — passed `drain_hole_is_open`, because a single upward ray
    from inside the recess exits through the open top and counts zero
    crossings. The top-down render showed solid material on the same
    axis. Parity says nothing about the half-space behind the ray.

    So a through-hole is specified as an unobstructed line of sight:
    cast the full length of the axis and require no hit at all.
    """

    name: str
    point_m: tuple[float, float, float]
    axis: str
    why: str

    def __post_init__(self) -> None:
        if self.axis not in AXIS_NAMES:
            raise ValueError(f"{self.name}: axis {self.axis!r} not in {AXIS_NAMES}")


@dataclass(frozen=True)
class GroundContactProbe:
    """The sole at this foot must be a flat face lying on z=0.

    `base_z` is one number — the minimum z of the whole object — so any
    single point touching the floor satisfies it. Measured 2026-08-22
    (iteration 4): the stool passed grounding at base_z +0.0000 m with a
    foot whose cut face was angled, and both the harness's visual
    critique and its pixel scan of the render read the resulting 3-pixel
    silhouette taper as anti-aliasing. Contact is an AREA, not a height,
    so it is measured as one: the total area of faces lying within
    `SOLE_PLANARITY_TOLERANCE_M` of z=0 near this foot.
    """

    name: str
    centre_xy_m: tuple[float, float]
    why: str
    # Where the sole must actually be, in the brief's own terms: on a
    # circle of this radius, at this bearing from +X. Measured from the
    # flat sole's centroid, so it answers "evenly spaced, first on the
    # +X axis" with two numbers instead of a look at a render.
    expected_radius_m: float = 0.0
    expected_angle_deg: float = 0.0
    minimum_area_m2: float = MINIMUM_SOLE_CONTACT_AREA_M2
    planarity_tolerance_m: float = SOLE_PLANARITY_TOLERANCE_M
    search_radius_m: float = FOOT_SEARCH_RADIUS_M
    radius_tolerance_m: float = FOOT_RADIUS_TOLERANCE_M
    angle_tolerance_deg: float = FOOT_ANGLE_TOLERANCE_DEG


@dataclass(frozen=True)
class AssetBrief:
    """A prompt plus its executable acceptance spec."""

    name: str
    object_name: str
    prompt_text: str
    dimensions: tuple[DimensionSpec, ...]
    probes: tuple[SolidityProbe, ...]
    clear_axes: tuple[ClearAxisProbe, ...] = ()
    ground_contacts: tuple[GroundContactProbe, ...] = ()
    budget: MeshBudget = field(default_factory=MeshBudget)
    require_base_at_ground: bool = True
    grounding_tolerance_m: float = GROUNDING_TOLERANCE_M
    # A game asset with no material slot is not shippable, and an empty
    # slot list is the single cheapest thing to forget. Checked
    # deterministically so it never reaches the visual pass.
    require_material: bool = True


def _stool_foot_probes() -> tuple[SolidityProbe, ...]:
    """One probe inside each leg, at the foot circle.

    Legs are placed at even angular intervals starting at +X. The agent
    is told this in the prompt, so it is a spec, not a guess.
    """
    import math

    probes: list[SolidityProbe] = []
    for leg_index in range(STOOL_LEG_COUNT):
        angle_rad = (2.0 * math.pi / STOOL_LEG_COUNT) * leg_index
        probes.append(
            SolidityProbe(
                name=f"leg_{leg_index}_foot_is_solid",
                point_m=(
                    STOOL_FOOT_CIRCLE_RADIUS_M * math.cos(angle_rad),
                    STOOL_FOOT_CIRCLE_RADIUS_M * math.sin(angle_rad),
                    STOOL_LEG_PROBE_Z_M,
                ),
                expect_inside=True,
                why=(
                    f"leg {leg_index} must actually stand at "
                    f"{STOOL_FOOT_CIRCLE_RADIUS_M} m from the axis"
                ),
            )
        )
    return tuple(probes)


def _stool_ground_contacts() -> tuple[GroundContactProbe, ...]:
    """One sole-contact probe per foot, on the same circle as the legs."""
    import math

    contacts: list[GroundContactProbe] = []
    for leg_index in range(STOOL_LEG_COUNT):
        angle_rad = (2.0 * math.pi / STOOL_LEG_COUNT) * leg_index
        contacts.append(
            GroundContactProbe(
                name=f"leg_{leg_index}_sole_is_flat_on_the_ground",
                centre_xy_m=(
                    STOOL_FOOT_CIRCLE_RADIUS_M * math.cos(angle_rad),
                    STOOL_FOOT_CIRCLE_RADIUS_M * math.sin(angle_rad),
                ),
                expected_radius_m=STOOL_FOOT_CIRCLE_RADIUS_M,
                expected_angle_deg=math.degrees(angle_rad),
                why=(
                    f"leg {leg_index} does not stand flat: its sole is "
                    f"angled or missing, so the stool touches the floor "
                    f"along an edge and rocks"
                ),
            )
        )
    return tuple(contacts)


PLANTER_BOX_BRIEF = AssetBrief(
    name="planter_box",
    object_name="PlanterBox",
    prompt_text=(
        f"Build a rectangular garden planter box named 'PlanterBox'. "
        f"It is {PLANTER_WIDTH_X_M} m wide on X, {PLANTER_DEPTH_Y_M} m deep "
        f"on Y, and {PLANTER_HEIGHT_Z_M} m tall on Z, sitting on the ground "
        f"at z=0. The walls and floor are {PLANTER_WALL_THICKNESS_M} m thick. "
        f"The top is open — it is a container, hollow inside, not a solid "
        f"block. There is one drainage hole of radius "
        f"{PLANTER_DRAIN_HOLE_RADIUS_M} m bored straight down through the "
        f"centre of the floor, and it must go all the way through so water "
        f"can actually drain. The finished object must be a single watertight "
        f"manifold mesh under {DEFAULT_PROP_TRIANGLE_BUDGET} triangles, "
        f"with a material assigned, and it must be the only mesh object "
        f"left in the scene when you are done."
    ),
    dimensions=(
        DimensionSpec("width_x", "x", PLANTER_WIDTH_X_M),
        DimensionSpec("depth_y", "y", PLANTER_DEPTH_Y_M),
        DimensionSpec("height_z", "z", PLANTER_HEIGHT_Z_M),
    ),
    probes=(
        SolidityProbe(
            name="drain_hole_is_open",
            point_m=(0.0, 0.0, PLANTER_DRAIN_PROBE_Z_M),
            expect_inside=False,
            why="the drainage hole is sealed shut — water cannot drain",
        ),
        SolidityProbe(
            name="interior_is_hollow",
            point_m=(0.0, 0.0, PLANTER_CAVITY_PROBE_Z_M),
            expect_inside=False,
            why="the planter is a solid block, not a container",
        ),
        SolidityProbe(
            name="floor_is_solid_off_centre",
            point_m=(PLANTER_FLOOR_PROBE_X_M, 0.0, PLANTER_DRAIN_PROBE_Z_M),
            expect_inside=True,
            why="the floor is missing — soil would fall straight out",
        ),
        SolidityProbe(
            name="wall_is_solid",
            point_m=(PLANTER_WALL_PROBE_X_M, 0.0, PLANTER_CAVITY_PROBE_Z_M),
            expect_inside=True,
            why="the side wall has no thickness",
        ),
    ),
    clear_axes=(
        ClearAxisProbe(
            name="drain_hole_goes_all_the_way_through",
            point_m=(0.0, 0.0, 0.0),
            axis="z",
            why=(
                "the drainage hole does not pass through the floor — it is a "
                "blind recess, so water cannot drain"
            ),
        ),
    ),
)

THREE_LEG_STOOL_BRIEF = AssetBrief(
    name="three_leg_stool",
    object_name="Stool",
    prompt_text=(
        f"Build a three-legged wooden stool named 'Stool'. The round seat is "
        f"{STOOL_SEAT_DIAMETER_M} m across and {STOOL_SEAT_THICKNESS_M} m "
        f"thick. Total height is {STOOL_TOTAL_HEIGHT_Z_M} m with the feet on "
        f"the ground at z=0. The {STOOL_LEG_COUNT} legs splay outward as they "
        f"descend: each foot touches the ground on a circle of radius "
        f"{STOOL_FOOT_CIRCLE_RADIUS_M} m from the central axis, with the legs "
        f"evenly spaced and the first one on the +X axis. The space between "
        f"the legs is open — there is no central post and no skirt. The "
        f"finished object must be a single watertight manifold mesh under "
        f"{DEFAULT_PROP_TRIANGLE_BUDGET} triangles, with a material "
        f"assigned, and it must be the only mesh object left in the "
        f"scene when you are done."
    ),
    dimensions=(
        DimensionSpec("seat_diameter_x", "x", STOOL_SEAT_DIAMETER_M),
        DimensionSpec("seat_diameter_y", "y", STOOL_SEAT_DIAMETER_M),
        DimensionSpec("total_height_z", "z", STOOL_TOTAL_HEIGHT_Z_M),
    ),
    probes=(
        *_stool_foot_probes(),
        SolidityProbe(
            name="no_central_post",
            point_m=(0.0, 0.0, STOOL_CENTRE_PROBE_Z_M),
            expect_inside=False,
            why=(
                "the legs collapsed to the central axis instead of splaying "
                "(see drift/catalog.py: matrix_world is stale until update)"
            ),
        ),
        SolidityProbe(
            name="seat_is_solid",
            point_m=(0.0, 0.0, STOOL_SEAT_PROBE_Z_M),
            expect_inside=True,
            why="there is no seat",
        ),
    ),
    ground_contacts=_stool_ground_contacts(),
)

BRIEFS: dict[str, AssetBrief] = {
    PLANTER_BOX_BRIEF.name: PLANTER_BOX_BRIEF,
    THREE_LEG_STOOL_BRIEF.name: THREE_LEG_STOOL_BRIEF,
}


class UnknownBrief(KeyError):
    """Raised when a brief name has no entry. There is no default brief."""


def get_brief(name: str) -> AssetBrief:
    if name not in BRIEFS:
        raise UnknownBrief(f"No brief {name!r}. Available: {', '.join(sorted(BRIEFS))}.")
    return BRIEFS[name]
