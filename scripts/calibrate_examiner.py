"""Calibrate the examiner: measure its defect detection on a fixture zoo.

    make calibrate-eye            (full zoo: 5 defects + 5 controls)
    make calibrate-eye ARGS="--only missing_leg"   (one fixture, live check)

Each fixture is built by REPLAYING the converged run for its brief (the
same replay the golden tests use) and damaging it through the existing
ops. Each fixture is then examined EXACTLY the way the loop examines a
run: `examine_asset` against the brief's golden per-view directory —
two eye calls per view (reference-first and test-first, MT-bench
position-bias mitigation) — and the verdict comes from the closed tag
vocabulary, not from substring scoring. The old scorer (measure_eye)
counted a denial as a sighting; this calibration's scoring is exact tag
comparison, so negation is not a scoring surface (see mistake memory
"the-eye-scorer-counted-a-denial-as-a-sighting").

Output `_evaluate/eye_calibration.json` licenses machine verdicts:
`Calibration.problems()` must be empty before the loop runs with
`--examiner auto`. The license is identity-bound: a prompt or model
change invalidates the recorded numbers by construction.

Thresholds live in `examiner.py`; their justification: RESP measures
oracle-reference recall 0.76 / auto-reference recall 0.69 for the small
open model against 0.28 for no reference (10.48550/arXiv.2604.11082),
and one false alarm on a clean control ends refinement early (TikZ
10.48550/arXiv.2606.15693), so control specificity must be exactly 1.0.

Runs under `blender --background --factory-startup`.
"""

import argparse
import datetime as _datetime
import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def venv_site_packages() -> Path:
    candidates = sorted(
        (REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages")
    )
    if not candidates:
        raise SystemExit(f"No .venv under {REPOSITORY_ROOT}.")
    return candidates[-1]


sys.path.insert(0, str(venv_site_packages()))
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT))
os.chdir(REPOSITORY_ROOT)

GOLDEN_ROOT = REPOSITORY_ROOT / "_evaluate" / "golden"


def _fixtures() -> dict:
    """Fixture name -> (brief name, expected tags, damage callable).

    Damage callables receive the replayed objects and mutate the scene.
    Detection = non-empty intersection of reported deviations with the
    expected tags; a control is clean only when deviations is empty AND
    the examiner did not abstain.
    """
    return {
        "missing_leg": (
            "three_leg_stool",
            ("missing_part", "wrong_count"),
            lambda objects: _delete_stool_leg_at_positive_x(objects[0]),
        ),
        "floating_seat": (
            "three_leg_stool",
            ("floating_part", "offset_part"),
            lambda objects: _translate_seat(objects[0], 0.05),
        ),
        "fat_seat": (
            "three_leg_stool",
            ("wrong_proportion",),
            lambda objects: _scale_seat(objects[0], 1.5),
        ),
        "sealed_drain": (
            "planter_box",
            ("missing_feature",),
            lambda objects: _seal_drain_hole(objects[0]),
        ),
        "lid_offset": (
            "crate_with_lid",
            ("offset_part",),
            lambda objects: _offset_lid(objects[1], 0.08),
        ),
        # Controls: free (replay, no damage) — a known-clean asset must
        # draw no deviations and no abstention.
        "clean_stool": ("three_leg_stool", (), None),
        "clean_planter": ("planter_box", (), None),
        "clean_crate": ("uv_crate", (), None),
        "clean_column": ("ribbed_column", (), None),
        "clean_crate_with_lid": ("crate_with_lid", (), None),
    }


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", default="_evaluate/iterations.jsonl")
    parser.add_argument("--renders", default="_evaluate/eye_calibration")
    parser.add_argument("--output", default="_evaluate/eye_calibration.json")
    parser.add_argument("--model", default="")
    parser.add_argument("--vision-model", default="")
    parser.add_argument(
        "--only",
        default="",
        help="run one fixture and print its verdict without rewriting "
        "the calibration file (the cheap live check)",
    )
    return parser.parse_args(argv)


def _delete_stool_leg_at_positive_x(blender_object) -> None:
    """Delete the +X leg's faces (the bearing-0 leg on the foot circle).

    The terminal stool (iterations 47/42/34) has legs at foot-circle
    radius 0.14 with bearings 0/120/240 and a seat whose bottom sits at
    z=0.51. Faces below z=0.50 near +X with |y| < 0.05 belong to the
    +X leg only; the 120 and 240 degree legs sit at x=-0.07.
    """
    import bmesh

    working_mesh = bmesh.new()
    working_mesh.from_mesh(blender_object.data)
    try:
        leg_faces = [
            face
            for face in working_mesh.faces
            if (centre := face.calc_center_median()).z < 0.50
            and 0.05 < centre.x < 0.20
            and abs(centre.y) < 0.05
        ]
        bmesh.ops.delete(working_mesh, geom=leg_faces, context="FACES")
        working_mesh.to_mesh(blender_object.data)
    finally:
        working_mesh.free()


def _translate_seat(blender_object, offset_z_m: float) -> None:
    """Move the seat (everything above the leg tops) up by `offset_z_m`."""
    import bmesh

    working_mesh = bmesh.new()
    working_mesh.from_mesh(blender_object.data)
    try:
        for vertex in working_mesh.verts:
            if vertex.co.z > 0.505:
                vertex.co.z += offset_z_m
        working_mesh.to_mesh(blender_object.data)
    finally:
        working_mesh.free()


def _scale_seat(blender_object, factor: float) -> None:
    """Scale the seat (everything above the leg tops) about the Z axis."""
    import bmesh

    working_mesh = bmesh.new()
    working_mesh.from_mesh(blender_object.data)
    try:
        for vertex in working_mesh.verts:
            if vertex.co.z > 0.505:
                vertex.co.x *= factor
                vertex.co.y *= factor
        working_mesh.to_mesh(blender_object.data)
    finally:
        working_mesh.free()


def _seal_drain_hole(blender_object) -> None:
    """Union a plug into the drain hole so it reads as sealed."""
    from blended.ops.booleans import boolean_union
    from blended.ops.primitives import add_cylinder, link_into_scene

    plug = add_cylinder(
        "DrainPlug",
        radius_m=0.014,
        height_m=0.025,
        location_m=(0.0, 0.0, 0.01),
    )
    link_into_scene(plug)
    boolean_union(blender_object, plug)


def _offset_lid(lid_object, offset_x_m: float) -> None:
    """Slide the lid sideways off the crate body."""
    lid_object.location.x += offset_x_m


def main(argv) -> int:
    import bpy

    from blended.agent.loop import ModelConfig, OllamaClient, VisionDescriber
    from blended.capture import CaptureSettings, capture_views
    from blended.evaluate.briefs import get_brief
    from blended.evaluate.examiner import (
        EXAMINED_VIEW_NAMES,
        examine_asset,
        examiner_identity,
    )
    from blended.evaluate.replay import load_record, replay_record

    arguments = parse_arguments(argv)

    # A typo'd fixture name is free to catch, so catch it before paying
    # for a connection probe.
    fixtures = _fixtures()
    only = arguments.only
    if only:
        if only not in fixtures:
            raise SystemExit(
                f"unknown fixture {only!r}. Known: {', '.join(sorted(fixtures))}"
            )
        fixtures = {only: fixtures[only]}

    configuration_overrides = {}
    if arguments.model:
        configuration_overrides["model"] = arguments.model
    if arguments.vision_model:
        configuration_overrides["vision_model"] = arguments.vision_model
    client = OllamaClient(ModelConfig.from_environment(**configuration_overrides))
    status = client.check_connection()
    print(f"[connection] {status.summary()}", flush=True)
    if not status.ok:
        raise SystemExit(f"Model unreachable: {status.detail}")

    vision_model = client.config.vision_model
    eye = VisionDescriber(client, vision_model)
    render_root = Path(arguments.renders)
    render_root.mkdir(parents=True, exist_ok=True)
    output_path = Path(arguments.output)

    fixture_records: list[dict] = []
    for fixture_name, (brief_name, expected_tags, damage) in sorted(fixtures.items()):
        print(f"\n=== fixture {fixture_name} (brief {brief_name}) ===", flush=True)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        brief = get_brief(brief_name)
        record = load_record(Path(arguments.log), _converging_iteration(brief_name))
        built = replay_record(record, brief.part_names)
        if damage is not None:
            damage(built)
        bpy.context.view_layer.update()

        render_directory = render_root / fixture_name
        render_directory.mkdir(parents=True, exist_ok=True)
        captured = capture_views(
            built[0],
            render_directory,
            settings=CaptureSettings(),
            extra_objects=tuple(built[1:]),
        )
        missing_views = set(EXAMINED_VIEW_NAMES) - set(captured)
        if missing_views:
            raise SystemExit(
                f"fixture {fixture_name}: capture_views did not produce "
                f"{sorted(missing_views)}"
            )

        golden_directory = (
            GOLDEN_ROOT / f"{brief_name}_v{record['prompt_revision']}"
        )
        verdict = examine_asset(
            eye, golden_directory, render_directory, brief, vision_model
        )
        if expected_tags:
            detected = bool(set(verdict.deviations) & set(expected_tags))
        else:
            detected = verdict.deviations == () and not verdict.abstained
        fixture_records.append(
            {
                "name": fixture_name,
                "brief": brief_name,
                "expected_tags": list(expected_tags),
                "deviations": list(verdict.deviations),
                "detected": detected,
                "abstained": verdict.abstained,
            }
        )
        print(verdict.summary(), flush=True)
        print(
            f"[fixture] {fixture_name}: expected {list(expected_tags)} "
            f"reported {list(verdict.deviations)} detected={detected} "
            f"abstained={verdict.abstained}",
            flush=True,
        )

    if only:
        print(
            f"[only] {only}: detected={fixture_records[0]['detected']} "
            f"deviations={fixture_records[0]['deviations']} "
            f"abstained={fixture_records[0]['abstained']}",
            flush=True,
        )
        print(
            f"[only] calibration file {output_path} was NOT rewritten",
            flush=True,
        )
        return 0

    defective = [f for f in fixture_records if f["expected_tags"]]
    controls = [f for f in fixture_records if not f["expected_tags"]]
    sensitivity = sum(f["detected"] for f in defective) / len(defective)
    control_specificity = sum(f["detected"] for f in controls) / len(controls)

    calibration = {
        "examiner_identity": examiner_identity(vision_model),
        "vision_model": vision_model,
        "recorded_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "view_names": list(EXAMINED_VIEW_NAMES),
        "fixtures": fixture_records,
        "sensitivity": sensitivity,
        "control_specificity": control_specificity,
    }
    output_path.write_text(
        json.dumps(calibration, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print("\n================ EXAMINER CALIBRATION ================", flush=True)
    print(
        f"sensitivity          : {sensitivity:.2f} "
        f"({sum(f['detected'] for f in defective)}/{len(defective)})",
        flush=True,
    )
    print(
        f"control specificity  : {control_specificity:.2f} "
        f"({sum(f['detected'] for f in controls)}/{len(controls)})",
        flush=True,
    )
    print(f"examiner identity    : {calibration['examiner_identity']}", flush=True)
    print(f"calibration written  : {output_path}", flush=True)
    return 0


def _converging_iteration(brief_name: str) -> int:
    """The converging run for this brief (kept beside the golden tests)."""
    return {
        "three_leg_stool": 47,
        "planter_box": 48,
        "uv_crate": 49,
        "ribbed_column": 50,
        "crate_with_lid": 51,
    }[brief_name]


extra_arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
raise SystemExit(main(extra_arguments))
