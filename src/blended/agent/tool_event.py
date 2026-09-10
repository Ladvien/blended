"""One tool call, as a structured record (OT-8, AGT-17 v2).

Free-text transcripts are readable and not minable. Every tool call the
loop dispatches — or refuses — becomes one `ToolEvent`: the tool, the
arguments as VALIDATED (bound to the op signature, plan_step stripped),
the plan step, whether it succeeded and at which stage it stopped, the
gate verdicts with the analyzer fields when it was gated, the wall time,
and for the escape hatch the reason and the source hash. The loop emits
it on the `tool_event` channel as JSON; the chat transcript stores it
under `data`; the iteration record carries the sequence. This is the
dataset the missing-op miner (OT-12) and the trace exporter (OT-18)
read, and the only encoding they accept.

Pure: no Blender.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

# The event kind on the (kind, text) channel. The text is the JSON below.
TOOL_EVENT_KIND = "tool_event"
TOOL_EVENT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class ToolEvent:
    tool_name: str
    arguments: dict
    ok: bool
    # One of blended.stages.STAGES for run_python and op tools; "" for a
    # tool that executes nothing in the scene (search_ops, list_scene,
    # inspect_*, render_views, declare_plan).
    stage_reached: str
    wall_time_s: float
    plan_step: int | None = None
    # One JSON verdict per gated object: object_name, stage_reached,
    # object_type, scene_state, gate_failures, world_extents_m, report.
    gates: tuple[dict, ...] = field(default_factory=tuple)
    images: tuple[str, ...] = field(default_factory=tuple)
    # run_python only: the candidate_op record's inputs (OT-7, OT-12).
    hatch_reason: str = ""
    source_sha256: str = ""
    # Non-empty when the loop refused the call before dispatch (plan
    # not declared). A refused call has ok=False and no stage.
    refusal: str = ""
    # The tool set the model was SHOWN for this call (OT-25): service
    # tools + readers + the core set, fingerprinted like the whole set.
    offered_tools_fingerprint: str = ""
    schema_version: int = TOOL_EVENT_SCHEMA_VERSION


def encode_tool_event(event: ToolEvent) -> str:
    return json.dumps(asdict(event), sort_keys=True)


def decode_tool_event(text: str) -> ToolEvent:
    """Round-trip of `encode_tool_event`; loud on any other schema."""
    payload = json.loads(text)
    version = payload.get("schema_version")
    if version != TOOL_EVENT_SCHEMA_VERSION:
        raise ValueError(
            f"tool event schema {version!r}, expected {TOOL_EVENT_SCHEMA_VERSION}: "
            f"a v1 transcript has no structured tool events to read"
        )
    payload["gates"] = tuple(payload["gates"])
    payload["images"] = tuple(payload["images"])
    return ToolEvent(**payload)
