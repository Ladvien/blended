"""Golden snapshots of the runs that converged prompt v5.

Sign-off stores the render, the parameter snapshot and the regression
test together, and the harness detects drift against them. These are
the three runs that met the convergence rule on 2026-08-22 — human
verified, both deterministic gates clean, no prompt change between them.

Each is rebuilt by REPLAYING the run's own recorded chunks, so this
suite needs no model, no network and no lucky generation. Replay rather
than re-import: `ingest.import_glb` normalizes what it reads — it
recentres on the vertex centroid and re-grounds — which is right for an
arbitrary generated asset and wrong for evidence, because it moves the
very placement the snapshot exists to pin. The .glb files beside these
tests are for a human to turn; the numbers come from the replay.

This answers a different question from the reference-stool fixtures
next door: those ask "is the brief satisfiable", this asks "does the
thing we signed off still measure the same". A change to a probe, a
tolerance, an op or a builder that silently moves these numbers fails
here.
"""

from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIRECTORY = REPOSITORY_ROOT / "_evaluate" / "golden"
ITERATION_LOG = REPOSITORY_ROOT / "_evaluate" / "iterations.jsonl"

# The three runs that met the convergence rule, and the brief each built.
CONVERGING_ITERATIONS = {"three_leg_stool": 13, "planter_box": 12}

# Measured off the converging runs. Every number here was produced by the
# agent and confirmed by the human; none was chosen to make a test pass.
STOOL_SNAPSHOT = {
    "seat_diameter_x": 0.3200,
    "seat_diameter_y": 0.3200,
    "total_height_z": 0.4500,
    "base_z": 0.0000,
    "sole_contact_area_m2": 0.001228,
    "sole_radius_m": 0.1400,
    "sole_bearings_deg": (0.0, 120.0, 240.0),
}
PLANTER_SNAPSHOT = {
    "width_x": 0.3000,
    "depth_y": 0.2000,
    "height_z": 0.2500,
    "base_z": 0.0000,
}
# A .glb round trip splits vertices at flat-shading seams and re-quantises
# positions, so the snapshot is compared at the precision the format
# actually preserves, not at float equality.
SNAPSHOT_TOLERANCE_M = 0.0005
SOLE_AREA_TOLERANCE_M2 = 5.0e-5
SOLE_BEARING_TOLERANCE_DEG = 1.0


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _measure(brief_name: str):
    """Rebuild the converging run for this brief and score it."""
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief
    from blended.evaluate.replay import load_record, replay_record

    brief = get_brief(brief_name)
    record = load_record(ITERATION_LOG, CONVERGING_ITERATIONS[brief_name])
    assert record["brief_name"] == brief_name, record["brief_name"]
    assert record["prompt_revision"] == 5, record["prompt_revision"]
    replay_record(record, brief.object_name)
    return brief, evaluate_brief(brief)


def _dimension(report, name: str) -> float:
    for measurement in report.dimensions:
        if measurement.spec.name == name:
            return measurement.measured_m
    raise AssertionError(f"no dimension named {name!r} in the report")


def test_golden_stool_still_passes_the_form_gate(empty_scene):
    brief, report = _measure("three_leg_stool")
    assert report.passes(brief), report.summary(brief)


def test_golden_stool_measures_the_signed_off_numbers(empty_scene):
    _, report = _measure("three_leg_stool")

    for name in ("seat_diameter_x", "seat_diameter_y", "total_height_z"):
        assert _dimension(report, name) == pytest.approx(
            STOOL_SNAPSHOT[name], abs=SNAPSHOT_TOLERANCE_M
        ), name
    assert report.base_z_m == pytest.approx(
        STOOL_SNAPSHOT["base_z"], abs=SNAPSHOT_TOLERANCE_M
    )


def test_golden_stool_feet_are_where_they_were_signed_off(empty_scene):
    """The placement probe is the newest gate, so it is the one most
    likely to drift silently. Pin what it measured at sign-off."""
    _, report = _measure("three_leg_stool")

    assert len(report.ground_contacts) == 3
    for measurement in report.ground_contacts:
        assert measurement.contact_area_m2 == pytest.approx(
            STOOL_SNAPSHOT["sole_contact_area_m2"], abs=SOLE_AREA_TOLERANCE_M2
        ), measurement.describe()
        assert measurement.measured_radius_m == pytest.approx(
            STOOL_SNAPSHOT["sole_radius_m"], abs=SNAPSHOT_TOLERANCE_M
        ), measurement.describe()

    bearings = sorted(round(m.measured_angle_deg, 1) for m in report.ground_contacts)
    for measured, expected in zip(bearings, STOOL_SNAPSHOT["sole_bearings_deg"]):
        assert measured == pytest.approx(expected, abs=SOLE_BEARING_TOLERANCE_DEG)


def test_golden_planter_still_passes_the_form_gate(empty_scene):
    brief, report = _measure("planter_box")
    assert report.passes(brief), report.summary(brief)


def test_golden_planter_measures_the_signed_off_numbers(empty_scene):
    _, report = _measure("planter_box")

    for name in ("width_x", "depth_y", "height_z"):
        assert _dimension(report, name) == pytest.approx(
            PLANTER_SNAPSHOT[name], abs=SNAPSHOT_TOLERANCE_M
        ), name
    assert report.base_z_m == pytest.approx(
        PLANTER_SNAPSHOT["base_z"], abs=SNAPSHOT_TOLERANCE_M
    )


def test_golden_planter_drain_still_goes_through(empty_scene):
    """The defect that started the loop. It must never come back."""
    _, report = _measure("planter_box")

    clear = [m for m in report.clear_axes if m.probe.name.startswith("drain_hole")]
    assert clear, "the through-hole probe is missing from the brief"
    for measurement in clear:
        assert measurement.ok, measurement.describe()


def test_golden_evidence_is_stored_beside_the_tests():
    """A snapshot without its render and its asset is not a sign-off."""
    for name in (
        "three_leg_stool_v5_sheet.png",
        "planter_box_v5_sheet.png",
        "three_leg_stool_v5.glb",
        "planter_box_v5.glb",
    ):
        evidence = GOLDEN_DIRECTORY / name
        assert evidence.exists(), f"missing sign-off evidence {evidence}"
        assert evidence.stat().st_size > 0


def test_the_pinned_prompt_is_the_one_that_converged():
    """Pinning is a claim about history; it has to stay true."""
    from blended.agent import prompt_versions

    assert prompt_versions.ACTIVE_PROMPT_REVISION == (
        prompt_versions.PINNED_PROMPT_REVISION
    )
    pinned = prompt_versions.get_revision(prompt_versions.PINNED_PROMPT_REVISION)
    # The hash proves the TEXT did not drift after sign-off.
    assert pinned.identity == "v5:6eadb9526276"
    assert len(prompt_versions.CONVERGENCE_RUNS) == 3
    assert pinned.outcome, "a pinned revision must carry its measured outcome"
