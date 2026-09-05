"""The agent-computer interface: the tools the model can actually call.

SWE-agent's measured result — a purpose-built ACI beat a bare shell
18.0% vs 11.0% on the same model — plus its ablations, shape every
choice here:

* A too-large observation window cost MORE than a too-small one
  (-5.3pp vs -3.7pp), so every tool bounds its output.
* Iterative search was WORSE than no search at all (-6.0pp), so
  `search_ops` returns one ranked page and never paginates.
* Guardrails that prevent a bad edit beat recovery after one, because a
  single failed edit drops the next success rate from 90.5% to 57.2% —
  so `run_python` reports the gate verdict with every run rather than
  letting the agent proceed on an unmeasured mesh.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from blended.agent.plan import (
    MAXIMUM_PLAN_STEPS,
    parse_plan_arguments,
)

# Bounded observation windows.
MAXIMUM_SCENE_OBJECTS_LISTED = 40
MAXIMUM_SEARCH_RESULTS = 8
# Anything that is not a letter or a digit is a word separator, so an
# underscore in `assign_material` and a space in 'assign material' are
# the same thing to a searcher.
_SEARCH_WORD_PATTERN = re.compile(r"[^a-z0-9]+")
MAXIMUM_TRACEBACK_CHARACTERS = 1500

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Execute a Python chunk in the live Blender session, then "
                "measure the named object against the analyzer gate. "
                "Returns execution status, anything the chunk PRINTED, any "
                "traceback with known API-drift fixes attached, and the full "
                "gate report. print() is how you ask the scene a question — "
                "print the value you want to check and read it back here. "
                "This is your primary tool — build by running small chunks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Python source. `blended.ops` is importable.",
                    },
                    "object_name": {
                        "type": "string",
                        "description": (
                            "Name of the object to gate after the chunk runs. "
                            "Omit to run the chunk without gating."
                        ),
                    },
                    "plan_step": {
                        "type": "integer",
                        "description": (
                            "The 1-based plan step this call belongs to. "
                            "Set this when you execute a step of the plan "
                            "you declared with declare_plan, so the UI "
                            "advances the progress bar."
                        ),
                    },
                },
                "required": ["source"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_object",
            "description": (
                "Measure an existing object without rebuilding it. Returns "
                "the full analyzer report: triangles, components, manifold "
                "status, self-intersections, normals, UVs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"},
                    "plan_step": {
                        "type": "integer",
                        "description": (
                            "The 1-based plan step this call belongs to."
                        ),
                    },
                },
                "required": ["object_name"],
            },
        },
    },
    # The domain lanes' self-verifier. Voyager's ablation measured
    # self-verification as the single largest component (−73% without
    # it, DOI 10.48550/arXiv.2305.16291); a rig or an action that the
    # writer cannot measure would be the one thing it never verifies.
    {
        "type": "function",
        "function": {
            "name": "inspect_domain",
            "description": (
                "Measure the non-mesh state of an object: its rig (armature "
                "bones and bound meshes), its vertex-group weights, its "
                "animation (action, fcurves, keyframes, frame range), or "
                "its material node tree. Read this back after rigging, "
                "weighting, keyframing or texturing to verify what you did, "
                "the way inspect_object verifies geometry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": (
                            "The armature for `rig`; the mesh for `weights` and "
                            "`material`; either for `animation`."
                        ),
                    },
                    "domain": {
                        "type": "string",
                        "enum": ["rig", "weights", "animation", "material"],
                    },
                    "plan_step": {
                        "type": "integer",
                        "description": (
                            "The 1-based plan step this call belongs to."
                        ),
                    },
                },
                "required": ["object_name", "domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_views",
            "description": (
                "Render an object from front, right, top and three-quarter "
                "into one contact sheet. If you cannot see images yourself, "
                "a vision model describes the render back to you in words. "
                "Use `look_for` to aim that description at a specific "
                "question. Use X-ray to look through geometry when debugging "
                "overlaps or hidden parts. Always look before declaring done."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"},
                    "xray": {
                        "type": "boolean",
                        "description": (
                            "Semi-transparent shading — reveals interpenetration "
                            "and hidden interior geometry."
                        ),
                    },
                    "look_for": {
                        "type": "string",
                        "description": (
                            "What you specifically want checked in the render, "
                            "e.g. 'are all four legs the same length?' or 'is "
                            "the drainage hole open?'. Aims the description at "
                            "your actual question."
                        ),
                    },
                    "plan_step": {
                        "type": "integer",
                        "description": (
                            "The 1-based plan step this call belongs to."
                        ),
                    },
                },
                "required": ["object_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_ops",
            "description": (
                "Find harness operations by keyword. Use this before "
                "guessing a signature. Returns the closest matches with "
                "their exact signatures."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Words to match, in any order: 'boolean union', "
                            "'assign material', 'unwrap', 'snap ground'. "
                            "Every word must appear, so fewer words match "
                            "more broadly."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scene",
            "description": (
                "List mesh objects currently in the scene with their triangle "
                "counts and dimensions. Bounded — use it to orient, not to "
                "search."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_asset",
            "description": (
                "Export an object to .glb and VERIFY it by re-importing the "
                "written file and re-measuring. Only call this on a mesh that "
                "already passes the gate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"},
                    "path": {"type": "string", "description": "Output .glb path."},
                    "plan_step": {
                        "type": "integer",
                        "description": (
                            "The 1-based plan step this call belongs to."
                        ),
                    },
                },
                "required": ["object_name", "path"],
            },
        },
    },
    # The plan tool — Decision D1 of the chat-UX overhaul. The agent
    # declares a numbered plan before it changes the scene; the UI shows
    # it and advances a progress bar through it. The plan is a shared
    # representation, not an approval gate (DOI 10.48550/arXiv.2507.22358
    # shared editable plan + progress bar; DOI 10.48550/arxiv.2604.14228
    # ~93 % of permission prompts are approved, so no approval click).
    {
        "type": "function",
        "function": {
            "name": "declare_plan",
            "description": (
                "Declare your plan as a numbered list of short, "
                "user-readable steps. Call this FIRST, once per turn, "
                "before any tool that changes the scene. The steps are "
                "shown to the user verbatim. Keep each step to one line "
                f"and at most {MAXIMUM_PLAN_STEPS} steps. After declaring, "
                "execute the steps in order, setting plan_step on each "
                "action call to the 1-based step it belongs to."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "The numbered plan steps, in execution order. "
                            "Each step is a short natural-language "
                            "description of what you will do."
                        ),
                    },
                },
                "required": ["steps"],
            },
        },
    },
]


def _report_to_dict(report) -> dict:
    from dataclasses import asdict

    return asdict(report)


def dispatch_tool(
    tool_name: str,
    arguments: dict,
    output_directory: Path = Path("_renders/agent"),
) -> tuple[str, list[Path]]:
    """Execute one tool call. Returns (text_result, image_paths).

    Image paths are returned separately so the caller can attach them to
    the model's next message as actual images — a contact sheet the
    model cannot see is worthless.

    MAIN THREAD ONLY. Everything below touches bpy.
    """
    # Touching bpy off the main thread does not raise. Blender corrupts
    # quietly and segfaults later, usually inside its own draw loop,
    # with nothing in any traceback pointing back here. So say it out
    # loud: a catchable error the agent loop reports as a tool failure
    # beats a dead application every time.
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            f"dispatch_tool({tool_name!r}) ran on thread "
            f"{threading.current_thread().name!r}, not the main thread. "
            f"bpy is not thread-safe. Frontends must pass a main-thread "
            f"dispatcher: AgentSession(dispatch=...)."
        )
    # The plan tool is pure — it touches no bpy, so handle it before
    # the bpy import to keep it testable without Blender. The model
    # sees its own plan echoed back as the tool result.
    if tool_name == "declare_plan":
        try:
            plan = parse_plan_arguments(arguments)
        except ValueError as error:
            return f"FAILED: {error}", []
        numbered = "\n".join(
            f"  {index}. {step}"
            for index, step in enumerate(plan.steps, start=1)
        )
        return f"Plan declared:\n{numbered}", []

    import bpy

    from blended.analyze import MeshBudget, analyze_object

    output_directory = Path(output_directory)

    if tool_name == "run_python":
        from blended.harness import HarnessSettings, run_chunk
        from blended.run.executor import run_source_in_process

        source_code = arguments["source"]
        object_name = arguments.get("object_name")
        if not object_name:
            run_result = run_source_in_process(source_code, "<chat>")
            if run_result.ok:
                printed = (
                    f"\nprinted:\n{run_result.stdout_text}"
                    if run_result.stdout_text
                    else "\n(nothing printed)"
                )
                return (
                    f"Executed OK in {run_result.duration_s:.2f}s.{printed}",
                    [],
                )
            drift_notes = "".join(
                f"\n  KNOWN TRAP [{entry.symbol}]: {entry.fix}"
                for entry in run_result.matched_drift
            )
            printed = (
                f"\nprinted before failing:\n{run_result.stdout_text}"
                if run_result.stdout_text
                else ""
            )
            return (
                (
                    f"FAILED: {run_result.error_type}: {run_result.error_message}\n"
                    f"{run_result.traceback_text[:MAXIMUM_TRACEBACK_CHARACTERS]}"
                    f"{printed}{drift_notes}"
                ),
                [],
            )
        harness_result = run_chunk(
            source_code,
            object_name=object_name,
            settings=HarnessSettings(output_directory=output_directory),
            chunk_label="chat",
        )
        images = (
            [harness_result.contact_sheet_path]
            if harness_result.contact_sheet_path is not None
            else []
        )
        return harness_result.summary(), images

    if tool_name == "inspect_object":
        object_name = arguments["object_name"]
        blender_object = bpy.data.objects.get(object_name)
        if blender_object is None:
            return f"No object named {object_name!r} in the scene.", []
        report = analyze_object(blender_object)
        failures = list(report.failures(MeshBudget()))
        # The same blind spots `run_chunk` had: flawless geometry the
        # user cannot see (unlinked, excluded collection, hidden,
        # hide_render) or cannot use (collapsed or non-finite object
        # transform) passes every mesh check. ONE shared rule, because
        # this tool is what the writer uses to check its own work and it
        # must not disagree with the gate.
        from blended.harness import scene_state_failure

        unusable = scene_state_failure(blender_object)
        if unusable:
            failures.append(unusable)
        verdict = "PASS" if not failures else "FAIL: " + "; ".join(failures)
        return (
            f"GATE {verdict}\n{json.dumps(_report_to_dict(report), indent=1)}",
            [],
        )

    if tool_name == "inspect_domain":
        object_name = arguments["object_name"]
        domain = arguments["domain"]
        blender_object = bpy.data.objects.get(object_name)
        if blender_object is None:
            return f"No object named {object_name!r} in the scene.", []
        if domain == "rig":
            from blended.ops.rigging import rig_report

            if blender_object.type != "ARMATURE":
                return f"{object_name!r} is a {blender_object.type}, not an ARMATURE.", []
            report = rig_report(blender_object)
        elif domain == "weights":
            from blended.ops.weights import weight_report

            if blender_object.type != "MESH":
                return f"{object_name!r} is a {blender_object.type}, not a MESH.", []
            report = weight_report(blender_object)
        elif domain == "animation":
            from blended.ops.animation import animation_report

            report = animation_report(blender_object, bpy.context.scene)
        elif domain == "material":
            from blended.ops.material_nodes import material_report

            if blender_object.type != "MESH":
                return f"{object_name!r} is a {blender_object.type}, not a MESH.", []
            report = material_report(blender_object)
        else:
            return f"Unknown domain {domain!r}.", []
        return f"{domain} report for {object_name}:\n{json.dumps(_report_to_dict(report), indent=1)}", []

    if tool_name == "render_views":
        from blended.capture import CaptureSettings, capture_contact_sheet

        object_name = arguments["object_name"]
        blender_object = bpy.data.objects.get(object_name)
        if blender_object is None:
            return f"No object named {object_name!r} in the scene.", []
        report = analyze_object(blender_object)
        sheet_path = capture_contact_sheet(
            blender_object,
            output_directory,
            settings=CaptureSettings(xray=bool(arguments.get("xray", False))),
            report=report,
        )
        return (
            (
                f"Rendered {object_name} ({'x-ray' if arguments.get('xray') else 'solid'}). "
                f"Look at the attached contact sheet."
            ),
            [sheet_path],
        )

    if tool_name == "search_ops":
        import importlib

        from blended.manifest import OP_MODULE_NAMES, _public_functions

        # Match WORDS, not the raw string. Measured 2026-08-22
        # (iteration 4): 3 of 16 turns were spent on 'boolean union',
        # 'material assign' and 'assign material', all answered "No
        # operation matches" — while `boolean_union` and
        # `assign_material` both exist. A whole-string test cannot span
        # the underscore, and cannot survive word order. Punctuation is
        # flattened on both sides so `_` and ` ` are the same character
        # to a searcher.
        query_tokens = [
            token for token in _SEARCH_WORD_PATTERN.split(arguments["query"].lower())
            if token
        ]
        if not query_tokens:
            return (
                (
                    f"Query {arguments['query']!r} contains no searchable "
                    f"words. Search for an operation by name or purpose, "
                    f"e.g. 'boolean union' or 'assign material'."
                ),
                [],
            )
        matches: list[str] = []
        for module_name in OP_MODULE_NAMES:
            module = importlib.import_module(f"blended.ops.{module_name}")
            for signature, summary in _public_functions(module):
                haystack = _SEARCH_WORD_PATTERN.sub(
                    " ", f"{module_name} {signature} {summary}".lower()
                )
                if all(token in haystack for token in query_tokens):
                    matches.append(
                        f"blended.ops.{module_name}: {signature}\n    {summary}"
                    )
        if not matches:
            return (
                (
                    f"No operation matches all of {query_tokens}. "
                    f"Available modules: {', '.join(OP_MODULE_NAMES)}."
                ),
                [],
            )
        return "\n".join(matches[:MAXIMUM_SEARCH_RESULTS]), []

    if tool_name == "list_scene":
        mesh_objects = [
            scene_object
            for scene_object in bpy.context.scene.objects
            if scene_object.type == "MESH"
        ]
        if not mesh_objects:
            return "Scene is empty (no mesh objects).", []
        bpy.context.view_layer.update()
        lines = []
        for scene_object in mesh_objects[:MAXIMUM_SCENE_OBJECTS_LISTED]:
            triangle_count = sum(
                len(polygon.vertices) - 2 for polygon in scene_object.data.polygons
            )
            dimensions = scene_object.dimensions
            lines.append(
                f"{scene_object.name}: {triangle_count} tris, "
                f"{dimensions.x:.3f} x {dimensions.y:.3f} x {dimensions.z:.3f} m"
            )
        if len(mesh_objects) > MAXIMUM_SCENE_OBJECTS_LISTED:
            lines.append(
                f"... and {len(mesh_objects) - MAXIMUM_SCENE_OBJECTS_LISTED} more"
            )
        return "\n".join(lines), []

    if tool_name == "export_asset":
        from blended.export import export_glb

        object_name = arguments["object_name"]
        blender_object = bpy.data.objects.get(object_name)
        if blender_object is None:
            return f"No object named {object_name!r} in the scene.", []
        export_report = export_glb(blender_object, Path(arguments["path"]))
        failures = export_report.round_trip_failures()
        if failures:
            return "EXPORT VERIFICATION FAILED:\n" + "\n".join(failures), []
        return (
            (
                f"Exported and verified: {export_report.export_path} "
                f"({export_report.file_size_bytes} bytes, "
                f"{export_report.reimported_welded.triangle_count} tris round-tripped)."
            ),
            [],
        )

    return f"Unknown tool: {tool_name}", []
