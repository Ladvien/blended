"""Cancelling a turn: the loop stops at the next seam and leaves the
history consistent.

Consistency matters more than speed here: an OpenAI-protocol backend
(llama-swap, OpenRouter) rejects a conversation where an assistant
tool_call has no tool result, so a cancel that just returned would
poison every later turn of the session.
"""

import dataclasses

from blended.agent.outcome import ToolOutcome

TWO_CALL_REPLY = {
    "role": "assistant",
    "content": "",
    "tool_calls": [
        {
            "id": "call_1",
            "function": {"name": "run_python", "arguments": {"source": "a = 1"}},
        },
        {
            "id": "call_2",
            "function": {"name": "run_python", "arguments": {"source": "b = 2"}},
        },
    ],
}
ANSWER_REPLY = {"role": "assistant", "content": "done"}


class ScriptedClient:
    def __init__(self, replies):
        from blended.agent.loop import ModelConfig

        self.replies = list(replies)
        self.config = dataclasses.replace(
            ModelConfig.from_environment(), model="scripted", vision_model=""
        )

    def chat(self, messages, tools=None):
        return self.replies.pop(0)


def test_cancel_between_tool_calls_answers_every_pending_call(tmp_path):
    from blended.agent.loop import CANCELLED_ANSWER, CANCELLED_TOOL_RESULT, AgentSession

    session = AgentSession(client=ScriptedClient([TWO_CALL_REPLY, ANSWER_REPLY]))
    executed = []

    def dispatch(tool_name, arguments, output_directory):
        executed.append(arguments["source"])
        session.cancel()  # the user hits Stop while the first tool runs
        return ToolOutcome("ok")

    session.dispatch = dispatch
    events = []
    answer = session.send("build two things", on_event=lambda k, t: events.append((k, t)))

    assert answer == CANCELLED_ANSWER
    assert executed == ["a = 1"]
    tool_results = {m["tool_call_id"]: m["content"] for m in session.messages if m["role"] == "tool"}
    assert tool_results == {"call_1": "ok", "call_2": CANCELLED_TOOL_RESULT}
    assert events[-1] == ("answer", CANCELLED_ANSWER)
    # The next turn starts clean: the flag does not linger.
    assert session.send("continue") == "done"
