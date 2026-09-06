"""Photo in, model out: one turn, one photograph, one built asset.

    make photo-to-model ARGS="--photo path/to/thing.jpg"
    make photo-to-model ARGS="--photo thing.jpg --prompt 'Build this as a
        low-poly prop.' --model deepseek-v4-pro:cloud
        --vision-model kimi-k2.7-code:cloud"

The picture, not the prompt, carries the shape: the default prompt says
only "this object", so whatever the writer builds it built from pixels.
A vision-capable writer (the `claude-code:` default) sees the photo
itself; a text-only writer gets the eye's reading of it. Either way the
proof is the contact sheet this prints at the end.

Runs inside `blender --background`: bpy is on the main thread, so
`dispatch_here` — the AgentSession default — is the right dispatcher.

There is no acceptance spec: a photograph carries no dimensions, so the
structural gate is REPORTED, not enforced. The one hard failure is
building nothing at all.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import os
import sys
import traceback
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def venv_site_packages() -> Path:
    """The dev venv's site-packages: jinja2 lives there, not in Blender."""
    candidates = sorted(
        (REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages")
    )
    if not candidates:
        raise SystemExit(f"No .venv under {REPOSITORY_ROOT}.")
    return candidates[-1]


sys.path.insert(0, str(venv_site_packages()))
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
os.chdir(REPOSITORY_ROOT)

# Never `_evaluate/`: tests/pure/test_convergence_rule.py reads the logs
# there, and a photo run is not an evaluation record.
OUTPUT_ROOT = REPOSITORY_ROOT / "outputs" / "photo_to_model"
DEFAULT_PROMPT_REVISION = 11
# Same ceiling as the chat gate: one extra failed chunk over the
# converged mesh budget.
MAXIMUM_TOOL_CALLS_PER_TURN = 36
# What the user says when the photo is doing the talking. It names no
# shape, no part and no dimension on purpose — anything the built model
# gets right about the object came from the picture.
DEFAULT_PROMPT = (
    "Build this object as a clean, low-poly game asset. Match the shape "
    "and proportions in the photo."
)
EVENT_PREVIEW_CHARACTERS = 300


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--photo", required=True, help="the reference photograph")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--revision", type=int, default=DEFAULT_PROMPT_REVISION)
    parser.add_argument("--model", default="")
    # `None` means "leave the config default"; an explicit empty string
    # means "no separate eye — the writer looks at the photo itself",
    # which is exactly how a vision-capable writer runs.
    parser.add_argument("--vision-model", default=None)
    parser.add_argument(
        "--max-tool-calls", type=int, default=MAXIMUM_TOOL_CALLS_PER_TURN
    )
    return parser.parse_args(argv)


def main(argv) -> int:
    import bpy

    from blended.agent.loop import AgentSession, ModelConfig, OllamaClient
    from blended.agent.system_prompt import build_system_prompt
    from blended.analyze import MeshBudget, analyze_object
    from blended.capture import CaptureSettings, capture_contact_sheet
    from blended.capture.reference_photo import normalize_reference_photo
    from blended.export.gltf import export_glb

    arguments = parse_arguments(argv)
    overrides: dict = {}
    if arguments.model:
        overrides["model"] = arguments.model
    if arguments.vision_model is not None:
        overrides["vision_model"] = arguments.vision_model

    stamp = _datetime.datetime.now(_datetime.UTC).strftime("%Y%m%d-%H%M%S")
    output_directory = OUTPUT_ROOT / stamp
    output_directory.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    reference = normalize_reference_photo(
        Path(arguments.photo).resolve(), output_directory
    )
    print(f"[photo] {arguments.photo} -> {reference}", flush=True)

    transcript_path = output_directory / "transcript.jsonl"
    tool_call_count = 0

    def on_event(kind: str, text: str) -> None:
        nonlocal tool_call_count
        with transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": kind, "text": text}) + "\n")
        if kind == "tool":
            tool_call_count += 1
        preview = (
            text
            if len(text) <= EVENT_PREVIEW_CHARACTERS
            else text[:EVENT_PREVIEW_CHARACTERS] + " ..."
        )
        print(f"[{kind}] {preview}", flush=True)

    config = ModelConfig.from_environment(**overrides)
    session = AgentSession(
        client=OllamaClient(config),
        output_directory=output_directory / "agent",
        maximum_tool_calls_per_turn=arguments.max_tool_calls,
        messages=[
            {"role": "system", "content": build_system_prompt(revision=arguments.revision)}
        ],
        # This driver stands in for the live UI, so it holds the UI's
        # contract: a turn that changes the scene declares its plan first.
        require_plan=True,
    )

    print(f"[user] {arguments.prompt}", flush=True)
    answer = ""
    error = ""
    try:
        answer = session.send(
            arguments.prompt, on_event=on_event, reference_images=(reference,)
        )
    except Exception:  # noqa: BLE001 — recorded as the run's finding
        error = traceback.format_exc()[-1500:]
        print(f"[FAIL] the turn raised:\n{error}", flush=True)

    bpy.context.view_layer.update()
    built = [
        scene_object
        for scene_object in bpy.context.scene.objects
        if scene_object.type == "MESH"
    ]
    if not built:
        print("[FAIL] the agent created no mesh", flush=True)
        return 1

    # Reported, not enforced: a photograph carries no acceptance spec.
    budget = MeshBudget()
    structural_failures: dict[str, list[str]] = {}
    for scene_object in built:
        failures = analyze_object(scene_object).failures(budget)
        structural_failures[scene_object.name] = failures
        verdict = "OK" if not failures else f"{len(failures)} findings"
        print(f"[gate] {scene_object.name}: {verdict}", flush=True)
        for failure in failures:
            print(f"   - {failure}", flush=True)

    sheet = capture_contact_sheet(
        built[0],
        output_directory,
        settings=CaptureSettings(),
        extra_objects=tuple(built[1:]),
    )
    exported: list[str] = []
    for scene_object in built:
        destination = output_directory / f"{scene_object.name}.glb"
        export_report = export_glb(scene_object, destination)
        exported.append(str(destination))
        print(
            f"[export] {destination} ({export_report.file_size_bytes} bytes)",
            flush=True,
        )

    summary = {
        "photo": str(Path(arguments.photo).resolve()),
        "normalized_photo": str(reference),
        "prompt": arguments.prompt,
        "writer_model": config.model,
        "vision_model": config.vision_model,
        "tool_calls": tool_call_count,
        "objects": [scene_object.name for scene_object in built],
        "structural_failures": structural_failures,
        "sheet": str(sheet),
        "glb": exported,
        "answer": answer,
        "error": error,
    }
    (output_directory / "summary.json").write_text(json.dumps(summary, indent=1))
    print(f"[sheet] {sheet}", flush=True)
    return 0


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    raise SystemExit(main(argv))
