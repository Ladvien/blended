"""The bridge from a live session to 3DCodeBench's standalone script (OT-20).

3DCodeBench (DOI 10.48550/arXiv.2606.01057) scores a STANDALONE script:
it re-executes `<inst>/<inst>.py` from an empty scene in a bare Blender
and measures the mesh that comes out. The harness does not write
scripts — it drives a live `bpy` session through tool calls. The bridge
is that the calls ARE the script: every `run_python` chunk whose Python
ran, and every op-tool call that ran, emitted in order, is the program
the benchmark re-bakes.

Which calls count is a correctness question. A call whose Python raised
(`stage_reached == "execute"`, or no stage at all: refused, unknown,
never dispatched) is excluded — including it guarantees a re-bake
failure and understates the harness. A call whose Python ran and only
the analyzer gate objected (`locate`, `gate`, `export`) is INCLUDED,
because that gate is this harness's standard, not 3DCodeBench's, and
the geometry exists either way. Measured 2026-09-10: the bridge that
read only `run_python` chunks dropped 34 op calls on Bottle and 37 on
Pillar from what the bench re-baked.

An op call is emitted as `_op(name, {validated arguments})`, bound at
bake time through the same `bind_arguments` the loop used, so a
dataclass argument (`tuple[BoneSpec, ...]`, an `EdgeSelector`) is
rebuilt by one converter rather than rendered as Python source by a
second one. The re-bake therefore needs `blended` importable — the
disclosed deviation from the benchmark's pure-bpy convention that the
`sys.path` prelude already carries.

Pure: strings in, a string out.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from blended.stages import STAGE_DONE, STAGE_EXPORT, STAGE_GATE, STAGE_LOCATE

HATCH_TOOL_NAME = "run_python"
# A call whose Python ran: it reached the stage after execute, whatever
# the gate then said.
EXECUTED_STAGES = (STAGE_LOCATE, STAGE_GATE, STAGE_EXPORT, STAGE_DONE)
# The name the emitted script binds an op call through.
OP_HELPER_NAME = "_op"


@dataclass(frozen=True)
class RecordedCall:
    tool_name: str
    # Validated (bound, plan_step stripped, JSON form) for an op tool; as
    # given for run_python — `ToolOutcome.validated_arguments`.
    arguments: dict
    stage_reached: str


def call_executed(call: RecordedCall) -> bool:
    return call.stage_reached in EXECUTED_STAGES


def emits_geometry(tool_name: str) -> bool:
    """A run_python chunk or a facade op; the other service tools change nothing."""
    from blended.agent.tools import OP_FUNCTIONS

    return tool_name == HATCH_TOOL_NAME or tool_name in OP_FUNCTIONS


def prelude(venv_site_packages: str, repository_src: str) -> str:
    """What the emitted script needs to stand alone in a bare Blender."""
    return (
        "import sys\n"
        f"sys.path.insert(0, {venv_site_packages!r})\n"
        f"sys.path.insert(0, {repository_src!r})\n"
        "\n"
        "from blended.agent.op_call import bind_arguments as _bind\n"
        "from blended.agent.tools import OP_FUNCTIONS as _OPS\n"
        "\n"
        "\n"
        f"def {OP_HELPER_NAME}(name, arguments):\n"
        "    return _OPS[name](**_bind(name, _OPS[name], arguments))\n"
    )


@dataclass(frozen=True)
class StandaloneScript:
    text: str
    included_count: int
    excluded_count: int
    op_call_count: int


def standalone_script(
    calls: Sequence[RecordedCall], prelude_text: str, epilogue_text: str
) -> StandaloneScript:
    """The program the benchmark re-bakes, from the recorded call sequence."""
    geometry_calls = [call for call in calls if emits_geometry(call.tool_name)]
    included = [call for call in geometry_calls if call_executed(call)]
    parts = [prelude_text]
    op_call_count = 0
    for index, call in enumerate(included, start=1):
        if call.tool_name == HATCH_TOOL_NAME:
            parts.append(f"\n# --- chunk {index} ---\n{call.arguments['source']}\n")
        else:
            op_call_count += 1
            parts.append(
                f"\n# --- op {index}: {call.tool_name} ---\n"
                f"{OP_HELPER_NAME}({call.tool_name!r}, {call.arguments!r})\n"
            )
    if included:
        parts.append(epilogue_text)
    return StandaloneScript(
        text="".join(parts),
        included_count=len(included),
        excluded_count=len(geometry_calls) - len(included),
        op_call_count=op_call_count,
    )
