"""Streamed replies assemble into the SAME assistant dict the one-shot
path returns — content, thinking, and tool calls with their ids — and a
stop mid-stream drops half-received tool calls instead of dispatching
garbage.

Both wire formats are exercised from canned frames at the
`_stream_lines` boundary, the streaming twin of `_request`.
"""

import json

from blended.agent import loop as live_loop

OPENAI_FRAMES = [
    "data: " + json.dumps({"choices": [{"delta": {"reasoning": "plan "}}]}),
    "data: " + json.dumps({"choices": [{"delta": {"content": "Build"}}]}),
    "data: " + json.dumps({"choices": [{"delta": {"content": "ing"}}]}),
    "data: "
    + json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_a",
                                "function": {"name": "run_python", "arguments": '{"sou'},
                            }
                        ]
                    }
                }
            ]
        }
    ),
    "data: "
    + json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": 'rce": "pass"}'}}
                        ]
                    }
                }
            ]
        }
    ),
    "data: [DONE]",
]

OLLAMA_FRAMES = [
    json.dumps({"message": {"role": "assistant", "thinking": "hmm"}, "done": False}),
    json.dumps({"message": {"role": "assistant", "content": "Bui"}, "done": False}),
    json.dumps({"message": {"role": "assistant", "content": "lt"}, "done": False}),
    json.dumps(
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "list_scene", "arguments": {}}}
                ],
            },
            "done": True,
        }
    ),
]


def _client(monkeypatch, frames, endpoint):
    monkeypatch.setattr(
        live_loop.OllamaClient,
        "_stream_lines",
        lambda self, path, payload, timeout: iter(frames),
    )
    return live_loop.OllamaClient(
        live_loop.ModelConfig(model="m", vision_model="", endpoint=endpoint, api_key="k")
    )


def test_openai_stream_assembles_content_thinking_and_indexed_tool_calls(monkeypatch):
    deltas = []
    client = _client(monkeypatch, OPENAI_FRAMES, live_loop.OPENROUTER_ENDPOINT)
    reply = client.chat([{"role": "user", "content": "go"}], on_delta=lambda k, t: deltas.append((k, t)))

    assert reply["content"] == "Building"
    assert reply["thinking"] == "plan "
    assert reply["tool_calls"] == [
        {"id": "call_a", "function": {"name": "run_python", "arguments": '{"source": "pass"}'}}
    ]
    assert deltas == [("thinking", "plan "), ("content", "Build"), ("content", "ing")]


def test_ollama_stream_assembles_the_same_shape(monkeypatch):
    deltas = []
    client = _client(monkeypatch, OLLAMA_FRAMES, live_loop.LOCAL_ENDPOINT)
    reply = client.chat([{"role": "user", "content": "go"}], on_delta=lambda k, t: deltas.append((k, t)))

    assert reply["content"] == "Built"
    assert reply["thinking"] == "hmm"
    assert reply["tool_calls"][0]["function"]["name"] == "list_scene"
    assert [k for k, _ in deltas] == ["thinking", "content", "content"]


def test_a_stop_mid_stream_keeps_the_text_and_drops_unfinished_tool_calls(monkeypatch):
    seen = []
    client = _client(monkeypatch, OPENAI_FRAMES, live_loop.OPENROUTER_ENDPOINT)

    def stop_after_three_frames():
        return len(seen) >= 3

    reply = client.chat(
        [{"role": "user", "content": "go"}],
        on_delta=lambda k, t: seen.append(t),
        stop_requested=stop_after_three_frames,
    )
    assert reply["content"] == "Building"
    assert reply["tool_calls"] == []


def test_the_session_forwards_deltas_only_when_streaming_is_on(monkeypatch):
    client = _client(monkeypatch, OPENAI_FRAMES[:3] + ["data: [DONE]"], live_loop.OPENROUTER_ENDPOINT)
    events = []
    session = live_loop.AgentSession(client=client, stream_replies=True)
    answer = session.send("hi", on_event=lambda k, t: events.append((k, t)))
    assert answer == "Building"
    assert events == [
        ("thinking_delta", "plan "),
        ("content_delta", "Build"),
        ("content_delta", "ing"),
        ("thinking", "plan "),
        ("answer", "Building"),
    ]
