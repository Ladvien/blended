"""OT-20: the standalone script carries op calls, includes what ran, and
keeps the chunk format the bench already re-bakes. Pure."""

from __future__ import annotations

from blended.evaluate.bench_bridge import (
    EXECUTED_STAGES,
    OP_HELPER_NAME,
    RecordedCall,
    call_executed,
    emits_geometry,
    prelude,
    standalone_script,
)
from blended.stages import STAGE_DONE, STAGE_EXECUTE, STAGE_GATE

PRELUDE = prelude("/venv/site-packages", "/repo/src")
EPILOGUE = "\n# --- epilogue ---\nprint('done')\n"


def test_inclusion_is_by_stage_not_by_text():
    assert EXECUTED_STAGES == ("locate", "gate", "export", "done")
    assert call_executed(RecordedCall("add_box", {}, STAGE_GATE))  # ran; the gate objected
    assert not call_executed(RecordedCall("add_box", {}, STAGE_EXECUTE))  # the Python raised
    assert not call_executed(RecordedCall("add_box", {}, ""))  # refused or never dispatched
    assert emits_geometry("run_python") and emits_geometry("boolean_union")
    assert not emits_geometry("render_views") and not emits_geometry("declare_plan")


def test_op_calls_are_emitted_in_order_through_the_binder():
    calls = [
        RecordedCall("declare_plan", {"steps": ["a"]}, ""),
        RecordedCall("add_box", {"name": "A", "width_m": 0.3, "depth_m": 0.2, "height_m": 0.25, "location_m": [0.0, 0.0, 0.0]}, STAGE_DONE),
        RecordedCall("run_python", {"source": "print('mid')", "reason": "r"}, STAGE_DONE),
        RecordedCall("boolean_union", {"target_name": "A", "addend_name": "B"}, STAGE_EXECUTE),  # raised: excluded
        RecordedCall("add_armature", {"name": "Rig", "bones": [{"name": "root", "head_m": [0, 0, 0], "tail_m": [0, 0, 1], "parent_name": "", "connected": False}]}, STAGE_DONE),
        RecordedCall("inspect_object", {"object_name": "A"}, ""),
    ]
    script = standalone_script(calls, PRELUDE, EPILOGUE)
    assert (script.included_count, script.excluded_count, script.op_call_count) == (3, 1, 2)
    body = script.text[len(PRELUDE):]
    assert body.startswith("\n# --- op 1: add_box ---\n_op('add_box', {'name': 'A'")
    assert "\n# --- chunk 2 ---\nprint('mid')\n" in body
    assert "_op('add_armature', {'name': 'Rig', 'bones': [{'name': 'root'" in body
    assert "boolean_union" not in body and "inspect_object" not in body
    assert body.endswith(EPILOGUE)
    assert f"def {OP_HELPER_NAME}(name, arguments):" in PRELUDE and "bind_arguments as _bind" in PRELUDE


def test_a_record_of_chunks_only_keeps_the_chunk_format():
    """The chunk body and the epilogue are byte-identical to the pre-OT-20
    assembly; only the prelude grew the op helper."""
    calls = [RecordedCall("run_python", {"source": "a = 1", "reason": "r"}, STAGE_DONE)]
    script = standalone_script(calls, PRELUDE, EPILOGUE)
    assert script.text == PRELUDE + "\n# --- chunk 1 ---\na = 1\n" + EPILOGUE
    assert PRELUDE.startswith("import sys\nsys.path.insert(0, '/venv/site-packages')\nsys.path.insert(0, '/repo/src')\n")
    # The host Blender's own `blended` (an installed addon's bundled copy)
    # is evicted before the script imports the tree it names.
    assert "del sys.modules[_name]" in PRELUDE
    assert PRELUDE.index("del sys.modules") < PRELUDE.index("from blended.agent.op_call")


def test_nothing_ran_means_no_epilogue():
    script = standalone_script([RecordedCall("add_box", {"name": "A"}, STAGE_EXECUTE)], PRELUDE, EPILOGUE)
    assert script.text == PRELUDE and script.included_count == 0 and script.excluded_count == 1
