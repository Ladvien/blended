"""Streamed replies assemble into the SAME assistant dict the one-shot
path returns — content, thinking, and tool calls with their ids — and a
stop mid-stream drops half-received tool calls instead of dispatching
garbage.

Both wire formats are exercised from canned frames at the `_open`
boundary — the one socket opener both `_request` and `_stream_lines` go
through since OT-35 — so the retry, the line decoding and the cost fold
under test are the real ones.
"""

import contextlib
import io
import json
import urllib.error

import pytest

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


def _body_of(frames):
    """An open-response stand-in: the frames as newline-delimited bytes,
    closed when the consumer is done, iterable line by line like an
    `HTTPResponse`."""
    return contextlib.closing(io.BytesIO(("\n".join(frames) + "\n").encode()))


def _client(monkeypatch, frames, endpoint, **config_overrides):
    """Stub the SOCKET (`_open`), not `_stream_lines`: the real
    line-decoding generator and the real cost fold run on every test."""
    monkeypatch.setattr(
        live_loop.OllamaClient,
        "_open",
        lambda self, path, payload, timeout: _body_of(frames),
    )
    return live_loop.OllamaClient(
        live_loop.ModelConfig(
            model="m", vision_model="", endpoint=endpoint, api_key="k",
            context_length=32_768, **config_overrides,
        )
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
    # The preflight's one-time context note (OT-22) is informational and
    # not part of the streaming contract under test.
    assert [event for event in events if event[0] != "preflight"] == [
        ("thinking_delta", "plan "),
        ("content_delta", "Build"),
        ("content_delta", "ing"),
        ("thinking", "plan "),
        ("answer", "Building"),
    ]


# --- OT-35: the stream retries at the socket, is costed, and is never replayed ---

OLLAMA_DONE_WITH_COUNTS = json.dumps(
    {"message": {"role": "assistant", "content": "!"}, "done": True,
     "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 8}
)
OPENAI_USAGE_CHUNK = "data: " + json.dumps(
    {"choices": [], "usage": {"prompt_tokens": 40, "completion_tokens": 9,
                              "completion_tokens_details": {"reasoning_tokens": 4},
                              "cost": 0.0021}}
)


def _urlopen_streaming(handler):
    """Like test_metered_lane's stand-in, but the body is a line stream."""
    def urlopen(request, timeout=None, context=None):
        return _body_of(handler(request))
    return urlopen


def test_a_streamed_call_refused_by_the_gateway_is_retried_then_streams_once(monkeypatch):
    """The addon's `stream_replies=True` lane was the one path with no
    retry (OT-32 wrapped `_request` only). Two 502s, then the stream: the
    measured backoff is waited, the retries are counted, and every delta
    reaches the UI exactly once."""
    waits = []
    monkeypatch.setattr("blended.agent.loop.time.sleep", lambda s: waits.append(s))
    attempts = {"n": 0}

    def flaky(request):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise urllib.error.HTTPError(
                "/api/chat", 502, "Bad Gateway", {}, io.BytesIO(b"connection reset by peer"))
        return OLLAMA_FRAMES

    monkeypatch.setattr(live_loop.OllamaClient, "_build_request", lambda self, path, payload: path)
    monkeypatch.setattr("blended.agent.loop.urllib.request.urlopen", _urlopen_streaming(flaky))
    client = live_loop.OllamaClient(
        live_loop.ModelConfig(model="m", vision_model="", endpoint=live_loop.LOCAL_ENDPOINT,
                              api_key="k", context_length=32_768))
    deltas = []

    reply = client.chat([{"role": "user", "content": "go"}], on_delta=lambda k, t: deltas.append((k, t)))

    assert reply["content"] == "Built"
    assert waits == list(live_loop.RETRY_BACKOFF_SECONDS[:2])
    assert client.spent.retried_calls == 2
    assert attempts["n"] == 3
    assert deltas == [("thinking", "hmm"), ("content", "Bui"), ("content", "lt")]


class _BodyThatDiesMidStream:
    """One frame, then the connection resets."""

    def __init__(self, first_line: str) -> None:
        self.first_line = first_line

    def __iter__(self):
        yield (self.first_line + "\n").encode()
        raise ConnectionResetError("connection reset by peer")

    def close(self) -> None:
        pass


def test_a_stream_that_dies_after_a_delta_is_not_replayed(monkeypatch):
    """A delta already reached the UI; sending the request again would
    show the reply twice. The failure is raised as it stands, with no
    wait and no retry counted."""
    waits = []
    monkeypatch.setattr("blended.agent.loop.time.sleep", lambda s: waits.append(s))
    opened = {"n": 0}

    def open_once(self, path, payload, timeout):
        opened["n"] += 1
        return contextlib.closing(_BodyThatDiesMidStream(OLLAMA_FRAMES[1]))

    monkeypatch.setattr(live_loop.OllamaClient, "_open", open_once)
    client = live_loop.OllamaClient(
        live_loop.ModelConfig(model="m", vision_model="", endpoint=live_loop.LOCAL_ENDPOINT,
                              api_key="k", context_length=32_768))
    deltas = []

    with pytest.raises(ConnectionResetError):
        client.chat([{"role": "user", "content": "go"}], on_delta=lambda k, t: deltas.append(t))

    assert deltas == ["Bui"]
    assert opened["n"] == 1 and waits == [] and client.spent.retried_calls == 0


def test_an_ollama_stream_is_costed_from_its_done_frame(monkeypatch):
    """Before OT-35 the streamed branch returned before the cost fold, so
    the addon's turn record said 0 tokens for every call."""
    client = _client(monkeypatch, OLLAMA_FRAMES[:3] + [OLLAMA_DONE_WITH_COUNTS], live_loop.LOCAL_ENDPOINT)
    reply = client.chat([{"role": "user", "content": "go"}], on_delta=lambda k, t: None)

    assert reply["content"] == "Built!"
    assert live_loop.STREAM_USAGE_KEY not in reply
    assert client.spent.api_calls == 1
    assert client.spent.input_tokens == 12
    assert client.spent.output_tokens == 8


def test_an_openai_stream_asks_for_usage_and_is_costed_from_the_usage_chunk(monkeypatch):
    payloads = []

    def capture(self, path, payload, timeout):
        payloads.append(payload)
        return _body_of(OPENAI_FRAMES[:3] + [OPENAI_USAGE_CHUNK, "data: [DONE]"])

    monkeypatch.setattr(live_loop.OllamaClient, "_open", capture)
    client = live_loop.OllamaClient(
        live_loop.ModelConfig(model="m", vision_model="", endpoint=live_loop.OPENROUTER_ENDPOINT,
                              api_key="k", context_length=32_768))
    reply = client.chat([{"role": "user", "content": "go"}], on_delta=lambda k, t: None)

    assert payloads[0]["stream"] is True
    assert payloads[0]["stream_options"] == live_loop.OPENAI_STREAM_USAGE_OPTIONS
    assert reply["content"] == "Building"
    assert client.spent.input_tokens == 40
    assert client.spent.output_tokens == 9
    assert client.spent.reasoning_tokens == 4
    assert client.spent.cost_usd == pytest.approx(0.0021)


def test_a_streamed_metered_call_is_stopped_by_the_run_cap(monkeypatch):
    """NFR-27 on the streamed lane: the cap could not see a streamed call
    before OT-35 because no cost was ever folded there."""
    client = _client(
        monkeypatch, OPENAI_FRAMES[:3] + [OPENAI_USAGE_CHUNK, "data: [DONE]"],
        live_loop.OPENROUTER_ENDPOINT, maximum_run_cost_usd=0.001,
    )
    with pytest.raises(live_loop.RunCostExceeded):
        client.chat([{"role": "user", "content": "go"}], on_delta=lambda k, t: None)


def test_a_stream_cut_before_its_final_frame_still_counts_as_a_call(monkeypatch):
    """Unknown tokens are not zero calls: a stopped stream is one API call
    with no counts, so a lane that stops often is still visible."""
    seen = []
    client = _client(monkeypatch, OLLAMA_FRAMES[:3], live_loop.LOCAL_ENDPOINT)
    client.chat([{"role": "user", "content": "go"}], on_delta=lambda k, t: seen.append(t),
                stop_requested=lambda: len(seen) >= 2)
    assert seen == ["hmm", "Bui"]
    assert client.spent.api_calls == 1
    assert client.spent.input_tokens == 0
