"""OT-22: a request that will not fit is refused with the sizes named; a
cut reply is an error; a lane with no measured context is reported."""

from __future__ import annotations

import dataclasses

import pytest

from blended.agent.claude_code import TurnCost
from blended.agent.context_preflight import (
    CHARS_PER_TOKEN_ESTIMATE,
    ContextExceeded,
    ReplyTruncated,
    check_reply_fits,
    estimate_tokens,
    preflight,
)
from blended.agent.loop import (
    BMB_ENDPOINT,
    CLAUDE_CODE_CONTEXT_TOKENS,
    CLAUDE_CODE_ENDPOINT,
    LOCAL_ENDPOINT,
    OPENROUTER_ENDPOINT,
    AgentSession,
    ModelConfig,
)
from blended.agent.outcome import ToolOutcome


def test_context_tokens_come_from_each_lanes_own_number():
    assert ModelConfig(model="qwen3.8-27b", endpoint=BMB_ENDPOINT).context_tokens == 65_536
    assert ModelConfig(model="qwen3-32b", endpoint=BMB_ENDPOINT).context_tokens == 32_768
    assert ModelConfig(model="anything", endpoint=LOCAL_ENDPOINT).context_tokens == 32_768  # num_ctx
    assert ModelConfig(model="claude-code:sonnet", endpoint=CLAUDE_CODE_ENDPOINT).context_tokens == CLAUDE_CODE_CONTEXT_TOKENS
    assert ModelConfig(model="some/cloud-model", endpoint=OPENROUTER_ENDPOINT).context_tokens is None


def test_the_estimate_is_the_measured_ratio():
    assert CHARS_PER_TOKEN_ESTIMATE == 3.8
    assert estimate_tokens("x" * 380) == 101


def test_preflight_refuses_with_every_number_named():
    messages = [{"role": "system", "content": "x" * 3800 * 10}]  # ~10,000 tokens
    with pytest.raises(ContextExceeded) as caught:
        preflight(messages, [], 12_000, 4_096, "bmb")
    text = str(caught.value)
    for fragment in ("estimated prompt", "reserved completion 4,096", "> context 12,000", "bmb"):
        assert fragment in text, text
    report = preflight(messages, [], 20_000, 4_096, "bmb")
    assert report.checked and report.context_tokens == 20_000
    unknown = preflight(messages, [], None, 4_096, "openrouter")
    assert not unknown.checked and "no measured context" in unknown.reason


def test_a_cut_reply_is_an_error_on_every_wire():
    with pytest.raises(ReplyTruncated, match="finish_reason=length"):
        check_reply_fits({"choices": [{"finish_reason": "length", "message": {}}], "usage": {"prompt_tokens": 10}}, 65_536, "bmb")
    with pytest.raises(ReplyTruncated, match="done_reason=length"):
        check_reply_fits({"done_reason": "length", "message": {}}, 32_768, "ollama")
    with pytest.raises(ContextExceeded, match="truncated=true"):
        check_reply_fits({"truncated": True, "choices": [{"finish_reason": "stop"}]}, 65_536, "bmb")
    with pytest.raises(ContextExceeded, match="cut the prompt"):
        check_reply_fits({"choices": [{"finish_reason": "stop"}], "usage": {"prompt_tokens": 70_000}}, 65_536, "bmb")
    check_reply_fits({"choices": [{"finish_reason": "stop"}], "usage": {"prompt_tokens": 100}}, 65_536, "bmb")  # fine
    check_reply_fits({"finish_reason": "stop"}, None, "openrouter")  # unknown context: only the cut checks apply


class _Scripted:
    def __init__(self, replies, config):
        self.replies = list(replies)
        self.config = config
        self.spent = TurnCost()
        self.chats = 0

    def chat(self, messages, tools=None):
        self.chats += 1
        return self.replies.pop(0)


def test_the_loop_refuses_before_calling_the_model(tmp_path):
    config = dataclasses.replace(ModelConfig.from_environment(), model="qwen3-32b", endpoint=BMB_ENDPOINT, vision_model="", max_completion_tokens=16_384)
    client = _Scripted([{"role": "assistant", "content": "never"}], config)
    session = AgentSession(client=client, output_directory=tmp_path, dispatch=lambda *a: ToolOutcome("ok"))
    session.messages.append({"role": "user", "content": "y" * 3800 * 20})  # ~20k tokens of history on a 32k lane with 16k reserved
    events = []
    answer = session.send("go", on_event=lambda k, t: events.append((k, t)))

    assert client.chats == 0
    assert answer.startswith("refusing to send on") and "> context 32,768" in answer
    assert [k for k, _ in events] == ["answer"]


def test_an_unmeasured_lane_is_reported_once_and_still_runs(tmp_path):
    config = dataclasses.replace(ModelConfig.from_environment(), model="some/cloud-model", endpoint=OPENROUTER_ENDPOINT, vision_model="")
    client = _Scripted([{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "list_scene", "arguments": {}}}]}, {"role": "assistant", "content": "done"}], config)
    session = AgentSession(client=client, output_directory=tmp_path, dispatch=lambda *a: ToolOutcome("ok"))
    events = []
    assert session.send("go", on_event=lambda k, t: events.append((k, t))) == "done"
    assert client.chats == 2
    assert [t for k, t in events if k == "preflight"] == ["context not checked: no measured context for this model on " + OPENROUTER_ENDPOINT]


def test_an_attached_image_counts_as_an_image_not_as_its_base64():
    from blended.agent.context_preflight import (
        TOKENS_PER_IMAGE_ESTIMATE,
        estimate_request_tokens,
    )

    text_only = [{"role": "tool", "content": "GATE PASS"}]
    with_image = [{"role": "tool", "content": "GATE PASS", "images": ["A" * 900_000]}]
    assert estimate_request_tokens(with_image, None) == estimate_request_tokens(text_only, None) + TOKENS_PER_IMAGE_ESTIMATE
