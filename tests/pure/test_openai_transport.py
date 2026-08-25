"""The OpenAI-protocol lane (bmb's llama-swap): wire shape and the
tool-call round trip.

llama-swap exposes /v1/chat/completions, not Ollama's /api/chat, so a
client pointed at BMB_ENDPOINT must translate messages, tools, and the
assistant reply — including the tool_call ids that an OpenAI backend
requires on the result messages. All assertions happen at the _request
boundary, the same interception point the vision-transport tests use.
"""

import urllib.error

import pytest

from blended.agent.loop import (
    BMB_ENDPOINT,
    ModelConfig,
    OllamaClient,
)

TOOL_CALL_ID = "call_abc123"


@pytest.fixture
def openai_payloads(monkeypatch):
    """Capture OpenAI-protocol payloads; return canned assistant
    messages with tool calls."""
    payloads: list[dict] = []

    def capture(self, path, payload, timeout_seconds):
        payloads.append((path, payload))
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": TOOL_CALL_ID,
                                "type": "function",
                                "function": {
                                    "name": "run_python",
                                    "arguments": '{"source": "print(1)"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr(OllamaClient, "_request", capture)
    return payloads


def _bmb_client():
    return OllamaClient(
        ModelConfig.from_environment(
            model="qwen3.8-27b", endpoint=BMB_ENDPOINT
        )
    )


def test_bmb_endpoint_uses_the_openai_path_and_wire_shape(openai_payloads):
    client = _bmb_client()
    reply = client.chat(
        [
            {"role": "system", "content": "build"},
            {"role": "user", "content": "make a crate"},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "run_python",
                    "description": "execute",
                    "parameters": {"type": "object"},
                },
            }
        ],
    )

    path, payload = openai_payloads[0]
    assert path == "/v1/chat/completions"
    assert payload["model"] == "qwen3.8-27b"
    assert payload["messages"] == [
        {"role": "system", "content": "build"},
        {"role": "user", "content": "make a crate"},
    ]
    assert payload["tools"][0]["function"]["name"] == "run_python"
    assert "options" not in payload  # OpenAI payload has no Ollama options
    assert payload["max_tokens"] == 16384

    assert reply["tool_calls"][0]["id"] == TOOL_CALL_ID
    assert reply["tool_calls"][0]["function"]["name"] == "run_python"
    assert reply["tool_calls"][0]["function"]["arguments"] == '{"source": "print(1)"}'


def test_tool_result_round_trip_carries_the_call_id(openai_payloads):
    client = _bmb_client()
    client.chat(
        [
            {"role": "user", "content": "go"},
            {
                "role": "tool",
                "content": "GATE: PASS",
                "tool_name": "run_python",
                "tool_call_id": TOOL_CALL_ID,
            },
        ]
    )
    _, payload = openai_payloads[0]
    tool_messages = [m for m in payload["messages"] if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == TOOL_CALL_ID
    assert tool_messages[0]["content"] == "GATE: PASS"
    # The Ollama-only keys must not leak onto the OpenAI wire.
    assert "tool_name" not in tool_messages[0]


def test_images_travel_as_openai_image_url_parts(monkeypatch, tmp_path):
    """The bmb lane is the eye lane for qwen3.8 too: an Ollama `images`
    field must become OpenAI image_url content parts, not be dropped."""
    from blended.agent.loop import _encode_images

    payloads: list[dict] = []

    def capture(self, path, payload, timeout_seconds):
        payloads.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "I see a crate.",
                    }
                }
            ]
        }

    monkeypatch.setattr(OllamaClient, "_request", capture)
    client = OllamaClient(
        ModelConfig.from_environment(model="qwen3.8-27b", endpoint=BMB_ENDPOINT)
    )
    first = tmp_path / "one.png"
    second = tmp_path / "two.png"
    first.write_bytes(b"png")
    second.write_bytes(b"png")
    reply = client.chat(
        [
            {
                "role": "user",
                "content": "What do you see?",
                "images": _encode_images([first, second]),
            }
        ]
    )
    assert reply["content"] == "I see a crate."
    message = payloads[0]["messages"][0]
    assert isinstance(message["content"], list)
    parts = message["content"]
    assert parts[0] == {"type": "text", "text": "What do you see?"}
    assert all(part["type"] == "image_url" for part in parts[1:])
    assert len(parts) == 3
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_ollama_endpoint_keeps_the_ollama_wire_shape(monkeypatch):
    payloads: list[dict] = []

    def capture(self, path, payload, timeout_seconds):
        payloads.append((path, payload))
        return {"message": {"role": "assistant", "content": "ok"}}

    monkeypatch.setattr(OllamaClient, "_request", capture)
    client = OllamaClient(
        ModelConfig.from_environment(model="deepseek-v4-pro:cloud")
    )
    client.chat([{"role": "user", "content": "hi"}])

    path, payload = payloads[0]
    assert path == "/api/chat"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert "options" in payload  # Ollama options stay on the Ollama wire


def test_the_default_endpoint_does_not_override_the_model_pin():
    """The addon always passes preferences.endpoint, and every fresh
    install and saved preference holds the default localhost value.
    That legacy default must count as UNSET — a saved preference must
    not override the model the user just picked (measured: qwen3.8-27b was
    sent to the Ollama daemon and 404'd)."""
    config = ModelConfig.from_environment(
        model="qwen3.8-27b", endpoint="http://localhost:11434"
    )
    assert config.endpoint == BMB_ENDPOINT
    # An EXPLICIT different endpoint still wins.
    explicit = ModelConfig.from_environment(
        model="qwen3.8-27b", endpoint="http://192.168.1.50:1234"
    )
    assert explicit.endpoint == "http://192.168.1.50:1234"



def test_gpt_oss_20b_is_a_bmb_model():
    """gpt-oss-20b-heretic:latest 404'd because NOTHING serves it. The
    real id on bmb's llama-swap is gpt-oss-20b (live /v1/models) and it
    must route to the bmb lane, not the local daemon."""
    writer = ModelConfig.from_environment(model="gpt-oss-20b")
    assert writer.endpoint == BMB_ENDPOINT
    assert writer.uses_openai_protocol
    # As an eye it rides the bmb lane too.
    eye = ModelConfig.from_environment(
        model="qwen3.8-27b", vision_model="gpt-oss-20b"
    ).eye_config()
    assert eye.endpoint == BMB_ENDPOINT


def test_the_bmb_key_file_feeds_bmb_models_only(monkeypatch):
    """A bmb model with no api_key reads the key file — the mechanism
    that makes Finder-launched Blender work without pasting. Non-bmb
    models must NEVER read it (the Ollama env key is the wrong
    credential for llama-swap and vice versa)."""
    from blended.agent.loop import _read_bmb_api_key

    captured: list[dict] = []

    def capture(self, path, payload, timeout_seconds):
        captured.append({"path": path, "headers": self.config.api_key})
        return {"message": {"role": "assistant", "content": "ok"}}

    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setattr(
        "blended.agent.loop._read_bmb_api_key",
        lambda: "a4d18f185e689d64351b51f508255abea08c66f7227cda22912dffc7783d5b47",
    )
    monkeypatch.setattr(OllamaClient, "_request", capture)

    bmb_config = ModelConfig.from_environment(model="qwen3.8-27b", api_key="")
    assert bmb_config.api_key == _read_bmb_api_key()

    ollama_config = ModelConfig.from_environment(
        model="deepseek-v4-pro:cloud", api_key=""
    )
    assert ollama_config.api_key == ""


def test_the_eye_rides_the_daemon_when_the_writer_rides_bmb():
    """A cloud eye does not live on bmb: when the writer is on bmb and
    the eye is a non-bmb model, the eye's config must point at the
    Ollama daemon. (The qwen3.8 eye, by contrast, rides bmb — see
    test_the_qwen3_8_eye_rides_the_bmb_lane.)"""
    writer = ModelConfig.from_environment(model="qwen3.8-27b")
    eye = writer.eye_config()
    assert eye.endpoint == "http://localhost:11434"
    assert eye.model == "kimi-k2.7-code:cloud"
    # The vision describer follows the same rule.
    from blended.agent.loop import VisionDescriber

    client = OllamaClient(writer)
    describer = VisionDescriber(client, writer.vision_model)
    assert describer.client.config.uses_openai_protocol


def test_reasoning_content_maps_to_thinking(monkeypatch):
    def capture(self, path, payload, timeout_seconds):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "final answer",
                        "reasoning_content": "think step by step",
                    }
                }
            ]
        }

    monkeypatch.setattr(OllamaClient, "_request", capture)
    client = _bmb_client()
    reply = client.chat([{"role": "user", "content": "hi"}])
    assert reply["content"] == "final answer"
    assert reply["thinking"] == "think step by step"


def test_the_qwen3_8_eye_rides_the_bmb_lane():
    """Picking the bmb model as the eye routes it to bmb's OpenAI lane —
    the same server that serves the writer — so one local model covers
    text and vision. This is the replacement for the qwen3.5:27b local
    vision slot (never installed, 16 GiB pull, no disk room)."""
    writer = ModelConfig.from_environment(
        model="qwen3.8-27b", vision_model="qwen3.8-27b"
    )
    eye = writer.eye_config()
    assert eye.endpoint == BMB_ENDPOINT
    assert eye.model == "qwen3.8-27b"
    assert eye.uses_openai_protocol
    # The describer routes the same way.
    from blended.agent.loop import VisionDescriber

    client = OllamaClient(writer)
    describer = VisionDescriber(client, "qwen3.8-27b")
    assert describer.client.config.endpoint == BMB_ENDPOINT


def test_the_401_hint_names_the_bmb_key_for_openai_lanes(monkeypatch):
    """A 401 on the bmb lane must say 'paste the llama-swap key', not
    'run ollama signin' — the two lanes authenticate differently.

    The config is built DIRECTLY (not via from_environment) so the
    test cannot be polluted by the real key file or a shell env key
    from another test's environment.
    """
    def forbidden(self, path, payload, timeout_seconds):
        raise urllib.error.HTTPError(path, 401, "unauthorized", None, None)

    monkeypatch.setattr(OllamaClient, "_request", forbidden)
    client = OllamaClient(
        ModelConfig(model="qwen3.8-27b", endpoint=BMB_ENDPOINT, api_key="")
    )
    status = client.check_connection()
    assert not status.ok
    assert "llama-swap" in status.detail and ".api-key" in status.detail
    assert "ollama signin" not in status.detail
