"""Rebuild a scored iteration from its own recorded calls.

The iteration log stores every run_python source in full, so a scored
run is reproducible without a model, a network, or a lucky generation.
Verified 2026-08-22: replaying iterations 10 and 11 reproduced their
acceptance reports number for number.

This is what a golden snapshot is checked against. Re-importing the
exported .glb would NOT do: `ingest.import_glb` normalizes what it
reads — it recentres on the vertex centroid and re-grounds — which is
right for an arbitrary generated asset and wrong for evidence, because
it moves the very placement the snapshot exists to pin.

MAIN THREAD ONLY: executes chunks against the live scene.
"""

from __future__ import annotations

import json
from pathlib import Path

RUN_PYTHON_PREFIX = "run_python("


class IterationNotFound(KeyError):
    """No such iteration in the log. There is no nearest match."""


class ReplayProducedNothing(RuntimeError):
    """The replayed chunks did not leave the brief's object behind."""


def load_record(log_path: Path, iteration: int) -> dict:
    records = [json.loads(line) for line in Path(log_path).read_text().splitlines()]
    matching = [record for record in records if record["iteration"] == iteration]
    if not matching:
        available = sorted({record["iteration"] for record in records})
        raise IterationNotFound(
            f"No iteration {iteration} in {log_path}. Recorded: {available}."
        )
    return matching[-1]


def sources_from(record: dict) -> list[str]:
    """The run_python sources of one record, in the order they ran."""
    sources = []
    for call in record["tool_calls"]:
        if not call.startswith(RUN_PYTHON_PREFIX):
            continue
        arguments = json.loads(call[len(RUN_PYTHON_PREFIX) : -1])
        sources.append(arguments["source"])
    return sources


def steps_applied(record: dict, brief) -> list:
    """The refinement steps the run actually executed, in order.

    A record carries one `LOCALITY <step_name>: ...` line per executed
    step, so which steps ran is recorded, not assumed. Replay and the
    golden tests score the terminal asset against the brief composed
    from exactly these steps — a record from before the suite gained
    steps must not be graded against steps it never ran.
    """
    executed = {
        line.split(":", 1)[0].removeprefix("LOCALITY ").strip()
        for line in record.get("refinement_locality", ())
    }
    return [step for step in brief.refinements if step.name in executed]


def replay_record(record: dict, object_names: tuple[str, ...], on_chunk=None):
    """Re-run a record's chunks into the current scene, return its objects.

    Returns the objects in `object_names` order, so a multi-part brief
    comes back the way the brief names its parts. Chunks that failed in
    the original run fail here too; that is the point of a faithful
    replay, and the objects are what is judged.
    """
    import bpy

    from blended.run.executor import run_source_in_process

    sources = sources_from(record)
    for index, source in enumerate(sources, 1):
        result = run_source_in_process(source)
        if on_chunk is not None:
            on_chunk(index, len(sources), result)
    bpy.context.view_layer.update()
    rebuilt = []
    for object_name in object_names:
        rebuilt_object = bpy.data.objects.get(object_name)
        if rebuilt_object is None:
            raise ReplayProducedNothing(
                f"replaying {len(sources)} chunk(s) left no object named "
                f"{object_name!r} — the log is not reproducible"
            )
        rebuilt.append(rebuilt_object)
    return rebuilt
