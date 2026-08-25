"""Run ONE 3DCodeBench instance through the agent, inside a real Blender.

    blender --background --factory-startup \\
        --python scripts/run_3dcode_instance.py -- \\
        --instance ArmChair_seed0 --bench-root /Users/ladvien/3dcodebench

3DCodeBench scores a STANDALONE script: it re-executes `<inst>/<inst>.py`
from an empty scene in a bare Blender and measures the mesh that comes
out. This harness does not write scripts — it drives a live `bpy`
session through `run_python` chunks. The bridge is that the chunks ARE
the script: concatenating the chunks whose Python actually executed
yields exactly the artifact the benchmark re-bakes.

Which chunks count is a correctness question, not a convenience one. A
chunk whose Python raised must be excluded (including it guarantees a
re-bake failure and understates the harness); a chunk whose Python ran
and only blended's own analyzer gate objected must be INCLUDED, because
that gate is this harness's standard, not 3DCodeBench's, and the
geometry exists either way. The three accepted result prefixes below are
read off `src/blended/agent/tools.py` and `HarnessResult.summary()`.

Nothing here writes to `_evaluate/` — a benchmark run must never enter
the canonical convergence evidence.
"""

import argparse
import json
import os
import sys
import time
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

# The task text wrapped around the benchmark's own prompt. It adds only
# what the benchmark's scorers require and this harness's system prompt
# does not already say: one mesh at the origin, no camera/light/render,
# and — the load-bearing one — that geometry built outside a run_python
# chunk will not exist when the emitted script is re-executed.
TASK_TEMPLATE = """\
Build this object as a single mesh in the current empty scene:

{description}

Rules for this task:
- Exactly ONE final mesh object may remain in the scene when you finish. Delete every
  helper, duplicate and temporary object.
- Place it at the world origin. No ground plane, no backdrop, no extra props.
- Build real parametric geometry - loops, modifiers, bmesh ops. Do not stack a few
  primitives and stop.
- Do not add cameras or lights. Do not render to disk from your Python. Do not call
  sys.exit or bpy.ops.wm.quit_blender.
- Every piece of geometry must be created inside `run_python` chunks. Those chunks are
  collected verbatim into a standalone script that is re-executed from an empty scene to
  score this run, so anything built outside a chunk will not exist when it is re-run.
"""

PROMPT_FILENAMES = {
    "description": "prompt_description.txt",
    "instruction": "prompt_instruction.txt",
}


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument("--model-dir", default="blended-deepseek-v4-pro")
    parser.add_argument(
        "--prompt-variant", choices=("description", "instruction"), default="description"
    )
    parser.add_argument("--model", default="")
    parser.add_argument("--vision-model", default="")
    parser.add_argument("--max-tool-calls", type=int, default=24)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def chunk_executed(result_text: str) -> bool:
    """Did this chunk's Python actually run in the session?

    Three accepted shapes, each read off the code that produces it:

    * "Executed OK in ..."  — ungated success (agent/tools.py:234)
    * "OK: ..."             — gated success (HarnessResult.summary())
    * "FAILED at <stage>"   — the Python ran; a LATER stage objected.
                              stage_reached == "execute" is the one case
                              where the Python itself raised.

    Everything else — notably "FAILED: " (the ungated raise path,
    agent/tools.py:248) and "Tool raised ..." — means no geometry.
    """
    if result_text.startswith(("Executed OK in ", "OK: ")):
        return True
    return result_text.startswith("FAILED at ") and not result_text.startswith(
        "FAILED at execute"
    )


def script_prelude() -> str:
    """The two sys.path lines the emitted script needs to stand alone.

    Chunk sources may `import blended.ops` — the `run_python` schema
    advertises it — and the benchmark re-bakes in a bare Blender that has
    never heard of this repository. Disclosed deviation from the
    benchmark's pure-bpy convention; recorded in the comparison notes.
    """
    return (
        "import sys\n"
        f"sys.path.insert(0, {str(venv_site_packages())!r})\n"
        f"sys.path.insert(0, {str(REPOSITORY_ROOT / 'src')!r})\n"
    )


def main(argv) -> int:
    import bpy

    from blended.agent.loop import (
        AgentSession,
        ModelConfig,
        OllamaClient,
        dispatch_here,
    )
    from blended.version import assert_supported_blender

    arguments = parse_arguments(argv)
    assert_supported_blender()

    bench_root = Path(arguments.bench_root).resolve()
    prompt_path = (
        bench_root
        / "data"
        / arguments.instance
        / PROMPT_FILENAMES[arguments.prompt_variant]
    )
    if not prompt_path.exists():
        print(f"[ERR] missing {prompt_path}", flush=True)
        return 1
    description = prompt_path.read_text().strip()

    work_directory = (
        bench_root / arguments.results_root / arguments.model_dir / arguments.instance
    )
    work_directory.mkdir(parents=True, exist_ok=True)
    script_path = work_directory / f"{arguments.instance}.py"
    metadata_path = work_directory / ".agent_meta.json"
    if script_path.exists() and not arguments.overwrite:
        print(f"[SKIP] {arguments.instance}", flush=True)
        return 0

    # A fresh, empty scene: the benchmark re-bakes from empty, so the run
    # must not be able to lean on a default cube.
    bpy.ops.wm.read_factory_settings(use_empty=True)

    configuration_overrides = {}
    if arguments.model:
        configuration_overrides["model"] = arguments.model
    if arguments.vision_model:
        configuration_overrides["vision_model"] = arguments.vision_model
    client = OllamaClient(ModelConfig.from_environment(**configuration_overrides))

    status = client.check_connection()
    print(f"[connection] {status.summary()}", flush=True)
    if not status.ok:
        metadata_path.write_text(
            json.dumps(
                {
                    "instance": arguments.instance,
                    "task": "text_to_3d",
                    "model": client.config.model,
                    "status": "ERR_CONNECTION",
                    "error": status.detail,
                },
                indent=2,
            )
        )
        return 1

    # The system prompt is NOT overridden: AgentSession.__post_init__
    # seeds the pinned working agreement when `messages` is empty, and
    # that prompt is precisely what is under test here.
    recorded: list[tuple[str, str]] = []

    def recording_dispatch(tool_name, arguments_dict, output_directory):
        text, images = dispatch_here(tool_name, arguments_dict, output_directory)
        if tool_name == "run_python":
            recorded.append((arguments_dict.get("source", ""), text))
        return text, images

    session = AgentSession(
        client=client,
        output_directory=work_directory / "_agent",
        maximum_tool_calls_per_turn=arguments.max_tool_calls,
        dispatch=recording_dispatch,
    )

    transcript_path = work_directory / ".agent_transcript.txt"
    transcript: list[str] = []

    def on_event(kind: str, text: str) -> None:
        transcript.append(f"--- {kind} ---\n{text}")
        preview = text if len(text) <= 400 else text[:400] + " ..."
        print(f"[{kind}] {preview}", flush=True)

    task_text = TASK_TEMPLATE.format(description=description)
    print(f"[instance] {arguments.instance}", flush=True)
    started = time.monotonic()
    try:
        session.send(task_text, on_event=on_event)
    except RuntimeError as model_error:
        # The transport died mid-run (measured: an Ollama cloud 502 with
        # "no route to host"). That is an INVALID run, not a modeling
        # failure, so no `<inst>.py` is written: the sweep's skip logic
        # keys on that file, and emitting a partial script here would
        # bake an infrastructure hiccup into the harness's score and
        # make the instance permanently un-rerunnable. Record the reason
        # and leave the instance re-runnable.
        duration_seconds = round(time.monotonic() - started, 2)
        transcript_path.write_text("\n\n".join(transcript))
        metadata_path.write_text(
            json.dumps(
                {
                    "instance": arguments.instance,
                    "task": "text_to_3d",
                    "model": client.config.model,
                    "status": "ERR_MODEL_CALL",
                    "duration_s": duration_seconds,
                    "num_turns": len(recorded),
                    "error": str(model_error)[:1000],
                },
                indent=2,
            )
        )
        print(f"[ERR_MODEL_CALL] {arguments.instance} {model_error}", flush=True)
        return 1
    duration_seconds = round(time.monotonic() - started, 2)
    transcript_path.write_text("\n\n".join(transcript))

    included = [source for source, text in recorded if chunk_executed(text)]
    excluded_count = len(recorded) - len(included)

    # Each chunk carries its own index so a re-bake traceback points at
    # the chunk the agent actually ran.
    parts = [script_prelude()]
    for index, source in enumerate(included, start=1):
        parts.append(f"\n# --- chunk {index} ---\n{source}\n")
    script_text = "".join(parts)
    script_path.write_text(script_text)

    metadata_path.write_text(
        json.dumps(
            {
                "instance": arguments.instance,
                "task": "text_to_3d",
                "model": client.config.model,
                "status": "OK_AGENT_DONE" if included else "ERR_NO_SCRIPT",
                "duration_s": duration_seconds,
                "code_chars": len(script_text),
                "num_turns": len(recorded),
                "n_chunks_included": len(included),
                "n_chunks_excluded": excluded_count,
                "max_tool_calls": arguments.max_tool_calls,
                "writer": client.config.model,
                "eye": client.config.vision_model,
                "prompt_variant": arguments.prompt_variant,
            },
            indent=2,
        )
    )
    print(
        f"[{'OK_AGENT_DONE' if included else 'ERR_NO_SCRIPT'}] {arguments.instance} "
        f"chunks={len(included)}/{len(recorded)} {duration_seconds}s",
        flush=True,
    )
    return 0


extra_arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
raise SystemExit(main(extra_arguments))
