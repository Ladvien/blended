"""OT-20: a brief built through the real dispatcher on op tools alone
re-bakes from the emitted standalone script and passes the form gate."""

from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

PLANTER_CALLS = [
    ("declare_plan", {"steps": ["box", "hollow", "drain", "material"]}),
    ("add_box", {"name": "PlanterBox", "width_m": 0.3, "depth_m": 0.2, "height_m": 0.25, "plan_step": 1}),
    ("link_into_scene", {"object_name": "PlanterBox", "plan_step": 1}),
    ("add_box", {"name": "InnerCavity", "width_m": 0.26, "depth_m": 0.16, "height_m": 0.28, "location_m": [0.0, 0.0, 0.02], "plan_step": 2}),
    ("link_into_scene", {"object_name": "InnerCavity", "plan_step": 2}),
    ("boolean_difference", {"target_name": "PlanterBox", "cutter_name": "InnerCavity", "plan_step": 2}),
    ("boolean_union", {"target_name": "PlanterBox", "addend_name": "Ghost", "plan_step": 2}),  # raises: excluded
    ("add_cylinder", {"name": "DrainCutter", "radius_m": 0.015, "height_m": 0.06, "location_m": [0.0, 0.0, -0.01], "plan_step": 3}),
    ("link_into_scene", {"object_name": "DrainCutter", "plan_step": 3}),
    ("boolean_difference", {"target_name": "PlanterBox", "cutter_name": "DrainCutter", "plan_step": 3}),
    ("run_python", {"source": "print('measured')", "reason": "test fixture: a chunk beside the op calls"}),
    ("assign_material", {"object_name": "PlanterBox", "name": "PlanterWood", "base_color_rgb": [0.55, 0.35, 0.2], "roughness": 0.8, "plan_step": 4}),
    ("render_views", {"object_name": "PlanterBox"}),
]


def test_an_op_built_brief_re_bakes_from_the_standalone_script(tmp_path):
    from blended.agent.tools import dispatch_tool
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.bench_bridge import RecordedCall, prelude, standalone_script
    from blended.evaluate.briefs import get_brief
    from blended.run.executor import run_source_in_process

    bpy.ops.wm.read_factory_settings(use_empty=True)
    recorded = []
    for tool_name, arguments in PLANTER_CALLS:
        outcome = dispatch_tool(tool_name, arguments, tmp_path)
        recorded.append(RecordedCall(tool_name, outcome.validated_arguments if outcome.validated_arguments is not None else arguments, outcome.stage_reached))
    venv = sorted((REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages"))[-1]
    # No orientation epilogue here: the runner appends it for the bench's
    # yaw-only scorer, and it rotates the planter's height onto Y, which
    # the brief's own gate does not expect. The bridge's assembly is what
    # is under test; the epilogue is the runner's and is covered purely.
    script = standalone_script(
        recorded, prelude(str(venv), str(REPOSITORY_ROOT / "src")), "\nprint('re-baked')\n"
    )
    assert script.op_call_count == 9 and script.included_count == 10 and script.excluded_count == 1
    assert "plan_step" not in script.text  # validated arguments: the harness's argument is gone

    # The bench's side: a fresh, empty scene and the script alone.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = run_source_in_process(script.text, "<re-bake>")
    assert result.ok, result.summary()
    assert "measured" in result.stdout_text and "re-baked" in result.stdout_text
    brief = get_brief("planter_box")
    report = evaluate_brief(brief)
    assert report.passes(brief), report.summary(brief)
