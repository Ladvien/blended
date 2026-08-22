"""The tool-dispatch seam: WHERE a tool call is executed.

`bpy` is main-thread only, but the agent loop runs on a worker thread
because a model call blocks for seconds to minutes. So the live-Blender
frontend has to move tool execution back to the main thread, and that
only works if the loop calls the dispatcher it was HANDED.

Regression: the seam used to be a monkeypatch on this module, while
`send` resolved `dispatch_tool` by local import — so the patch was
never seen, every tool call ran bpy on the worker thread, and Blender
segfaulted inside its own draw loop with nothing in any traceback.

These tests are deliberately in the pure layer: no bpy anywhere. If the
loop ever reaches for the real dispatcher again, `import bpy` fails
here and the test goes red — which is exactly the signal that was
missing when Blender was simply dying.
"""

import dataclasses
import threading

import pytest

TOOL_CALL_REPLY = {
    "role": "assistant",
    "content": "",
    "tool_calls": [
        {
            "function": {
                "name": "run_python",
                "arguments": {"source": "pass", "object_name": "Crate"},
            }
        }
    ],
}
ANSWER_REPLY = {"role": "assistant", "content": "Built Crate — gate passed."}


class ScriptedClient:
    """Replays fixed assistant messages so the LOOP is what's tested."""

    def __init__(self, replies):
        from blended.agent.loop import ModelConfig

        self.replies = list(replies)
        self.seen_messages = []
        self.config = dataclasses.replace(
            ModelConfig.from_environment(), model="scripted", vision_model=""
        )

    def chat(self, messages, tools=None):
        self.seen_messages.append(list(messages))
        return self.replies.pop(0)


def _session(dispatch, output_directory):
    from blended.agent.loop import AgentSession

    return AgentSession(
        client=ScriptedClient([TOOL_CALL_REPLY, ANSWER_REPLY]),
        output_directory=output_directory,
        dispatch=dispatch,
    )


def test_the_injected_dispatcher_is_what_runs_the_tool(tmp_path):
    calls = []

    def recording_dispatch(tool_name, arguments, output_directory):
        calls.append((tool_name, arguments, output_directory))
        return "GATE PASS", []

    answer = _session(recording_dispatch, tmp_path).send("Make me a crate.")

    assert answer == "Built Crate — gate passed."
    assert [tool_name for tool_name, _, _ in calls] == ["run_python"]
    assert calls[0][1]["object_name"] == "Crate"
    # The session's own output directory, not the dispatcher's default.
    assert calls[0][2] == tmp_path


def test_a_turn_driven_off_the_main_thread_still_uses_the_injection(tmp_path):
    """The exact shape of the crash: the turn runs on a worker thread.

    The frontend's dispatcher is where the handoff back to the main
    thread lives, so it MUST be what gets called from there.
    """
    dispatching_threads = []

    def recording_dispatch(tool_name, arguments, output_directory):
        dispatching_threads.append(threading.current_thread())
        return "GATE PASS", []

    session = _session(recording_dispatch, tmp_path)
    worker = threading.Thread(target=lambda: session.send("Make me a crate."))
    worker.start()
    worker.join(timeout=10)

    assert not worker.is_alive(), "the turn never finished"
    assert dispatching_threads == [worker]


def test_the_default_dispatcher_runs_on_the_calling_thread():
    """Guards the dataclass trap: a function default must stay unbound.

    If `dispatch` were resolved as a class attribute it would bind as a
    method and be handed a phantom `self`.
    """
    from blended.agent.loop import AgentSession, dispatch_here

    assert AgentSession().dispatch is dispatch_here


def test_touching_bpy_off_the_main_thread_is_an_error_not_a_segfault():
    """The backstop under the seam, at the point bpy is reached."""
    from blended.agent.tools import dispatch_tool

    failures = []

    def call_from_worker():
        try:
            dispatch_tool("list_scene", {}, None)
        except BaseException as error:  # noqa: BLE001 — the assertion IS the error
            failures.append(error)

    worker = threading.Thread(target=call_from_worker, name="not-main")
    worker.start()
    worker.join(timeout=10)

    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeError)
    assert "not the main thread" in str(failures[0])


def test_the_main_thread_reaches_bpy(monkeypatch):
    """The guard must not be the reason nothing ever runs.

    Called on the main thread it falls through to the real body, whose
    first act is `import bpy` — absent in the pure layer, which is the
    observable proof that the guard let it past.
    """
    from blended.agent.tools import dispatch_tool

    with pytest.raises(ModuleNotFoundError, match="bpy"):
        dispatch_tool("list_scene", {}, None)


def test_iteration_record_carries_the_models_that_ran():
    """A prompt is tuned against a model, not in the abstract.

    v1-v5 were scored against deepseek-v4-flash; comparing a later run
    on a different writer without recording which one would attribute a
    model change to the prompt.
    """
    from blended.evaluate.iteration_log import IterationRecord

    record = IterationRecord(
        iteration=1,
        brief_name="three_leg_stool",
        prompt_identity="v5:6eadb9526276",
        prompt_revision=5,
        started_at="2026-08-22T00:00:00+00:00",
        writer_model="deepseek-v4-pro:cloud",
        vision_model="minimax-m3:cloud",
    )
    assert record.writer_model == "deepseek-v4-pro:cloud"
    assert record.vision_model == "minimax-m3:cloud"
