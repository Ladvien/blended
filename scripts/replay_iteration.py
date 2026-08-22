"""Rebuild the scene an iteration produced, from its own log.

    make replay ITERATION=10

The iteration log records every run_python source in full, so a scored
run is reproducible: replaying it recreates the exact mesh, re-scores it
against the brief, and writes a .glb. A render answers questions a
single viewpoint can answer; a .glb answers the rest — measured
2026-08-22, the contact sheet's front view puts a stool's 120 and 240
degree legs at the same world x, so it cannot show leg spacing at all.
"""

import argparse
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
os.chdir(REPOSITORY_ROOT)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iteration", type=int, required=True)
    parser.add_argument("--log", default="_evaluate/iterations.jsonl")
    return parser.parse_args(argv)


def main(argv) -> int:
    import bpy

    from blended.capture import CaptureSettings, capture_contact_sheet
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief
    from blended.evaluate.replay import load_record, replay_record
    from blended.export.gltf import export_glb

    arguments = parse_arguments(argv)
    record = load_record(Path(arguments.log), arguments.iteration)
    brief = get_brief(record["brief_name"])

    bpy.ops.wm.read_factory_settings(use_empty=True)

    def announce(index, total, result):
        print(f"[replay] chunk {index}/{total}: "
              f"{'ok' if result.ok else 'FAILED'}", flush=True)

    built = replay_record(record, brief.object_name, on_chunk=announce)
    report = evaluate_brief(brief)
    print(report.summary(brief), flush=True)

    render_directory = Path(record["render_path"]).parent
    sheet = capture_contact_sheet(
        built, render_directory, settings=CaptureSettings()
    )
    print(f"[replay] wrote {sheet}", flush=True)

    destination = render_directory / f"{brief.object_name}.glb"
    export_report = export_glb(built, destination)
    print(
        f"[replay] wrote {destination} "
        f"({export_report.file_size_bytes} bytes), round trip "
        f"{'OK' if export_report.passes(brief.budget) else 'FAILED'}",
        flush=True,
    )
    for failure in export_report.round_trip_failures(brief.budget):
        print(f"   - {failure}", flush=True)
    return 0


extra_arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
raise SystemExit(main(extra_arguments))
