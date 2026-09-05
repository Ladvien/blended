"""The Claude Code lane: transcript folding, the constrained tool-call
envelope, routing, and a full transport round trip against a FAKE
`claude` binary.

The round-trip tests exec a real subprocess, but it is a stub script
that replays canned stream-json — so the whole lane (argv, stdin frame,
frame parsing, error paths, cancel) is covered without a network call,
a token, or the real CLI installed. `scripts/provider_smoke.py` is what
exercises the live binary.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from blended.agent.claude_code import (
    ASSISTANT_LABEL,
    CLAUDE_CODE_DEFAULT_EFFORT,
    CLAUDE_CODE_ENDPOINT,
    CLAUDE_CODE_INSTALL_HINT,
    CLAUDE_CODE_REQUEST_TIMEOUT_SECONDS,
    CONTINUATION_CUE,
    IMAGE_PLACEHOLDER_TOKEN,
    TOOL_CALL_ID_PREFIX,
    TOOL_PROTOCOL_NOTE,
    USER_LABEL,
    ClaudeCodeTransport,
    assistant_message_from_envelope,
    envelope_schema,
    is_claude_code_model,
    model_alias,
    parse_rate_limit,
    render_call,
    resolve_binary,
)
from blended.agent.loop import (
    API_KEY_ENVIRONMENT_VARIABLE,
    BIG_ENDPOINT,
    LOCAL_ENDPOINT,
    ModelConfig,
    OllamaClient,
    _image_placeholders,
    _implied_api_key,
    _implied_endpoint,
)
from blended.agent.tools import TOOL_SCHEMAS

WRITER_MODEL = "claude-code:sonnet"
EYE_MODEL = "claude-code:haiku"
CLOUD_EYE_MODEL = "kimi-k2.7-code:cloud"
FIRST_IMAGE = "Zmlyc3Q="
SECOND_IMAGE = "c2Vjb25k"


# --- transcript folding -------------------------------------------------


def test_the_whole_conversation_folds_into_one_user_frame():
    """One user frame is one billed turn (measured), so N messages must
    still produce exactly one."""
    system_prompt, frame = render_call(
        [
            {"role": "system", "content": "system rules"},
            {"role": "user", "content": "make a crate"},
            {"role": "assistant", "content": "on it"},
            {"role": "tool", "content": "GATE PASS", "tool_name": "run_python"},
        ]
    )
    assert system_prompt == "system rules"
    assert frame["type"] == "user"
    assert frame["message"]["role"] == "user"
    blocks = frame["message"]["content"]
    assert [block["type"] for block in blocks] == ["text"]


def test_the_fold_keeps_roles_and_order_legible():
    _, frame = render_call(
        [
            {"role": "user", "content": "make a crate"},
            {
                "role": "assistant",
                "content": "building",
                "tool_calls": [
                    {
                        "id": "x",
                        "function": {
                            "name": "run_python",
                            "arguments": {"source": "print(1)"},
                        },
                    }
                ],
            },
            {"role": "tool", "content": "GATE PASS", "tool_name": "run_python"},
            {"role": "user", "content": "now add a lid"},
        ]
    )
    text = frame["message"]["content"][0]["text"]
    positions = [
        text.index(USER_LABEL),
        text.index(ASSISTANT_LABEL),
        text.index("[assistant tool call: run_python]"),
        text.index("[tool result: run_python]"),
        text.index("now add a lid"),
        text.index(CONTINUATION_CUE),
    ]
    assert positions == sorted(positions)
    # The arguments have to be readable as data, not prose.
    assert json.dumps({"source": "print(1)"}) in text


def test_a_string_arguments_payload_survives_the_fold():
    """An OpenAI-lane history can carry arguments as a JSON string."""
    _, frame = render_call(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "x",
                        "function": {
                            "name": "run_python",
                            "arguments": '{"source": "print(2)"}',
                        },
                    }
                ],
            }
        ]
    )
    assert 'print(2)' in frame["message"]["content"][0]["text"]


def test_images_land_at_their_placeholder_positions():
    """`Image 1` must point at image 1: the eye's prompt numbers them."""
    _, frame = render_call(
        [
            {
                "role": "user",
                "content": _image_placeholders(2) + "compare these",
                "images": [FIRST_IMAGE, SECOND_IMAGE],
            }
        ]
    )
    blocks = frame["message"]["content"]
    assert [block["type"] for block in blocks] == [
        "text",
        "image",
        "text",
        "image",
        "text",
    ]
    assert "Image 1" in blocks[0]["text"]
    assert blocks[1]["source"]["data"] == FIRST_IMAGE
    assert "Image 2" in blocks[2]["text"]
    assert blocks[3]["source"]["data"] == SECOND_IMAGE
    assert "compare these" in blocks[4]["text"]
    # The placeholder token itself must not survive: the real image did.
    assert IMAGE_PLACEHOLDER_TOKEN not in "".join(
        block.get("text", "") for block in blocks
    )


def test_tool_result_images_without_placeholders_still_arrive():
    """`AgentSession` attaches renders to a tool result with no
    placeholder text when the writer is its own eye."""
    _, frame = render_call(
        [
            {
                "role": "tool",
                "content": "rendered 1 view",
                "tool_name": "render_views",
                "images": [FIRST_IMAGE],
            }
        ]
    )
    blocks = frame["message"]["content"]
    assert [block["type"] for block in blocks] == ["text", "image", "text"]
    assert blocks[1]["source"]["data"] == FIRST_IMAGE


def test_no_empty_text_blocks_are_emitted():
    """The API rejects an empty text block, and an empty assistant turn
    with only tool calls is normal."""
    _, frame = render_call(
        [{"role": "user", "content": "", "images": [FIRST_IMAGE]}]
    )
    for block in frame["message"]["content"]:
        if block["type"] == "text":
            assert block["text"].strip()


def test_several_system_messages_join_into_one_prompt():
    system_prompt, _ = render_call(
        [
            {"role": "system", "content": "first"},
            {"role": "system", "content": "second"},
            {"role": "user", "content": "go"},
        ]
    )
    assert system_prompt == "first\n\nsecond"


# --- the constrained envelope -------------------------------------------


def test_the_envelope_pins_each_tool_to_its_own_arguments():
    schema = envelope_schema(TOOL_SCHEMAS)
    variants = schema["properties"]["tool_calls"]["items"]["oneOf"]
    assert len(variants) == len(TOOL_SCHEMAS)
    by_name = {
        variant["properties"]["name"]["const"]: variant for variant in variants
    }
    for tool in TOOL_SCHEMAS:
        function_block = tool["function"]
        variant = by_name[function_block["name"]]
        assert variant["properties"]["arguments"] == function_block["parameters"]
        # Without the description the model names tools it knows nothing
        # about and calls none of them (measured 2026-09-05).
        assert variant["description"] == function_block["description"]
    assert schema["required"] == ["message", "tool_calls"]


def test_the_envelope_becomes_the_assistant_dict_the_loop_consumes():
    message = assistant_message_from_envelope(
        {
            "message": "building it",
            "tool_calls": [
                {"name": "run_python", "arguments": {"source": "print(1)"}},
                {"name": "inspect_object", "arguments": {"object_name": "Crate"}},
            ],
        },
        thinking="considered",
    )
    assert message["role"] == "assistant"
    assert message["content"] == "building it"
    assert message["thinking"] == "considered"
    names = [call["function"]["name"] for call in message["tool_calls"]]
    assert names == ["run_python", "inspect_object"]
    assert message["tool_calls"][0]["function"]["arguments"] == {"source": "print(1)"}
    identifiers = [call["id"] for call in message["tool_calls"]]
    assert all(
        identifier.startswith(TOOL_CALL_ID_PREFIX) for identifier in identifiers
    )
    # Ids must be unique ACROSS turns too: `_cancel_turn` matches
    # results to calls by id, and a per-turn counter would collide.
    second = assistant_message_from_envelope(
        {"message": "", "tool_calls": [{"name": "list_scene", "arguments": {}}]}
    )
    assert second["tool_calls"][0]["id"] not in identifiers


def test_an_answering_turn_carries_no_tool_calls():
    message = assistant_message_from_envelope({"message": "done", "tool_calls": []})
    assert message["tool_calls"] == []
    assert "thinking" not in message


# --- routing ------------------------------------------------------------


def test_a_claude_code_id_implies_the_cli_and_no_credential():
    assert is_claude_code_model(WRITER_MODEL)
    assert not is_claude_code_model("kimi-k2.7-code:cloud")
    assert model_alias(WRITER_MODEL) == "sonnet"
    assert _implied_endpoint(WRITER_MODEL) == CLAUDE_CODE_ENDPOINT
    assert _implied_api_key(WRITER_MODEL, "an-ollama-key") == ""


def test_the_lane_is_neither_ollama_nor_openai_and_gets_its_own_ceiling():
    config = ModelConfig.from_environment(model=WRITER_MODEL, vision_model="")
    assert config.uses_claude_code
    assert not config.uses_openai_protocol
    assert not config.is_openrouter
    assert config.api_key == ""
    assert config.request_timeout_seconds == CLAUDE_CODE_REQUEST_TIMEOUT_SECONDS
    assert config.claude_code_effort == CLAUDE_CODE_DEFAULT_EFFORT


def test_a_cloud_eye_beside_a_cli_writer_falls_back_to_the_daemon(monkeypatch):
    """The CLI serves only its own ids, so a cloud eye must not inherit
    it — and must still get the Ollama credential."""
    monkeypatch.setenv(API_KEY_ENVIRONMENT_VARIABLE, "ollama-key")
    eye = ModelConfig.from_environment(
        model=WRITER_MODEL, vision_model=CLOUD_EYE_MODEL
    ).eye_config()
    assert eye.endpoint == LOCAL_ENDPOINT
    assert eye.api_key == "ollama-key"
    assert not eye.uses_claude_code


def test_a_cli_eye_beside_a_llama_swap_writer_rides_the_cli(monkeypatch):
    monkeypatch.setenv(API_KEY_ENVIRONMENT_VARIABLE, "ollama-key")
    eye = ModelConfig.from_environment(
        model="qwen3-vl", endpoint=BIG_ENDPOINT, vision_model=EYE_MODEL
    ).eye_config()
    assert eye.endpoint == CLAUDE_CODE_ENDPOINT
    assert eye.uses_claude_code
    # The CLI owns its auth; no harness credential may ride to it.
    assert eye.api_key == ""


# --- argv ---------------------------------------------------------------


def test_the_command_disables_every_built_in_capability(fake_binary):
    transport = ClaudeCodeTransport(WRITER_MODEL, binary_path=str(fake_binary))
    arguments = transport.command("system rules", TOOL_SCHEMAS)
    assert arguments[0] == str(fake_binary)
    for flag in (
        "--print",
        "--tools",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--safe-mode",
        "--no-session-persistence",
        "--include-partial-messages",
    ):
        assert flag in arguments
    assert arguments[arguments.index("--tools") + 1] == ""
    assert arguments[arguments.index("--model") + 1] == "sonnet"
    assert arguments[arguments.index("--effort") + 1] == CLAUDE_CODE_DEFAULT_EFFORT
    schema = json.loads(arguments[arguments.index("--json-schema") + 1])
    assert schema == envelope_schema(TOOL_SCHEMAS)
    # The schema is useless on its own: Claude Code is itself an agent
    # harness, so a model reading "you have these tools" emits a NATIVE
    # tool call, which `--tools ""` refuses. The note that redirects it
    # to the envelope must ship with the schema, never apart from it.
    system_prompt = arguments[arguments.index("--system-prompt") + 1]
    assert system_prompt.startswith("system rules")
    assert TOOL_PROTOCOL_NOTE in system_prompt
    # Stateless: Claude Code's own session store would be a second
    # source of truth beside AgentSession.messages.
    assert "--resume" not in arguments
    assert "--session-id" not in arguments


def test_a_toolless_call_sends_neither_schema_nor_protocol_note(fake_binary):
    transport = ClaudeCodeTransport(WRITER_MODEL, binary_path=str(fake_binary))
    arguments = transport.command("system rules", None)
    assert "--json-schema" not in arguments
    assert TOOL_PROTOCOL_NOTE not in arguments[arguments.index("--system-prompt") + 1]


def test_an_unknown_effort_is_refused():
    with pytest.raises(ValueError, match="effort"):
        ClaudeCodeTransport(WRITER_MODEL, effort="turbo")


def test_a_missing_binary_names_the_fix(tmp_path):
    with pytest.raises(RuntimeError) as error:
        resolve_binary(str(tmp_path / "nope"))
    assert CLAUDE_CODE_INSTALL_HINT in str(error.value)


# --- the round trip, against a stub binary ------------------------------

FAKE_BINARY_SOURCE = '''#!/usr/bin/env python3
"""A stand-in for `claude`: replays canned frames, records its input."""
import json, os, sys, time

here = os.path.dirname(os.path.abspath(__file__))
if "auth" in sys.argv:
    sys.stdout.write(json.dumps(json.load(open(os.path.join(here, "auth.json")))))
    sys.exit(0)
open(os.path.join(here, "argv.json"), "w").write(json.dumps(sys.argv[1:]))
open(os.path.join(here, "stdin.txt"), "w").write(sys.stdin.read())
delay = float(os.environ.get("FAKE_CLAUDE_DELAY_SECONDS", "0"))
if delay:
    time.sleep(delay)
for line in open(os.path.join(here, "frames.jsonl")):
    sys.stdout.write(line)
    sys.stdout.flush()
'''


def _result_frame(**overrides) -> dict:
    frame = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": '{"message":"on it","tool_calls":[]}',
        "structured_output": {
            "message": "on it",
            "tool_calls": [
                {"name": "run_python", "arguments": {"source": "print(1)"}}
            ],
        },
    }
    frame.update(overrides)
    return frame


RATE_LIMIT_FRAME = {
    "type": "rate_limit_event",
    "rate_limit_info": {
        "status": "allowed",
        "resetsAt": 1788634200,
        "unifiedWindows": {
            "five_hour": {"utilization": 0.25},
            "seven_day": {"utilization": 0.5},
        },
    },
}


@pytest.fixture
def fake_binary(tmp_path):
    """An executable stub whose canned frames a test can rewrite."""
    binary = tmp_path / "claude"
    binary.write_text(FAKE_BINARY_SOURCE)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "loggedIn": True,
                "authMethod": "claude.ai",
                "subscriptionType": "max",
            }
        )
    )
    _write_frames(binary, [RATE_LIMIT_FRAME, _result_frame()])
    return binary


def _write_frames(binary: Path, frames: list[dict]) -> None:
    (binary.parent / "frames.jsonl").write_text(
        "".join(json.dumps(frame) + "\n" for frame in frames)
    )


def _transport(binary: Path, **overrides) -> ClaudeCodeTransport:
    return ClaudeCodeTransport(WRITER_MODEL, binary_path=str(binary), **overrides)


def test_the_round_trip_yields_a_schema_constrained_tool_call(fake_binary):
    transport = _transport(fake_binary)
    message = transport.chat(
        [
            {"role": "system", "content": "system rules"},
            {"role": "user", "content": "make a crate"},
        ],
        TOOL_SCHEMAS,
    )
    assert message["content"] == "on it"
    assert message["tool_calls"][0]["function"]["name"] == "run_python"
    # Exactly one user frame reached the CLI.
    sent = (fake_binary.parent / "stdin.txt").read_text().strip().splitlines()
    assert len(sent) == 1
    assert json.loads(sent[0])["type"] == "user"
    assert transport.last_rate_limit.five_hour_utilization == 0.25


def test_a_toolless_round_trip_returns_the_plain_text_result(fake_binary):
    _write_frames(
        fake_binary,
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "weighing it"},
                        {"type": "text", "text": "a red cube"},
                    ]
                },
            },
            _result_frame(result="a red cube", structured_output=None),
        ],
    )
    message = _transport(fake_binary).chat(
        [{"role": "user", "content": "describe this"}]
    )
    assert message["content"] == "a red cube"
    assert message["thinking"] == "weighing it"
    assert message["tool_calls"] == []


def test_deltas_stream_to_the_caller(fake_binary):
    _write_frames(
        fake_binary,
        [
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "hmm"},
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "a red "},
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "cube"},
                },
            },
            _result_frame(result="a red cube", structured_output=None),
        ],
    )
    seen: list[tuple[str, str]] = []
    message = _transport(fake_binary).chat(
        [{"role": "user", "content": "describe this"}],
        None,
        on_delta=lambda kind, text: seen.append((kind, text)),
    )
    assert seen == [
        ("thinking", "hmm"),
        ("content", "a red "),
        ("content", "cube"),
    ]
    assert message["content"] == "a red cube"


def test_a_stop_returns_what_arrived_and_kills_the_turn(fake_binary):
    _write_frames(
        fake_binary,
        [
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "half an "},
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "answer"},
                },
            },
            _result_frame(),
        ],
    )
    message = _transport(fake_binary).chat(
        [{"role": "user", "content": "describe this"}],
        TOOL_SCHEMAS,
        stop_requested=lambda: True,
    )
    # The first frame is absorbed, then the stop is seen: the caller
    # gets exactly what arrived, and no tool call is invented.
    assert message["tool_calls"] == []
    assert message["content"] == "half an"


def test_an_error_result_is_reported_loudly(fake_binary):
    _write_frames(
        fake_binary,
        [
            RATE_LIMIT_FRAME,
            _result_frame(
                subtype="error_during_execution", is_error=True, result="upstream 529"
            ),
        ],
    )
    with pytest.raises(RuntimeError) as error:
        _transport(fake_binary).chat([{"role": "user", "content": "go"}], TOOL_SCHEMAS)
    detail = str(error.value)
    assert "error_during_execution" in detail
    assert "upstream 529" in detail
    # The window numbers travel with the failure: overage is rejected on
    # this account, so a limit hit is a hard stop the user must see.
    assert "5h window" in detail


def test_a_missing_envelope_names_the_stale_cli(fake_binary):
    _write_frames(fake_binary, [_result_frame(structured_output=None)])
    with pytest.raises(RuntimeError, match="claude update"):
        _transport(fake_binary).chat([{"role": "user", "content": "go"}], TOOL_SCHEMAS)


def test_no_result_frame_is_an_error_not_an_empty_answer(fake_binary):
    _write_frames(fake_binary, [RATE_LIMIT_FRAME])
    with pytest.raises(RuntimeError, match="no result frame"):
        _transport(fake_binary).chat([{"role": "user", "content": "go"}], TOOL_SCHEMAS)


def test_a_hung_turn_hits_the_ceiling(fake_binary, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_DELAY_SECONDS", "5")
    with pytest.raises(RuntimeError, match="did not answer within"):
        _transport(fake_binary, timeout_seconds=1).chat(
            [{"role": "user", "content": "go"}], TOOL_SCHEMAS
        )


def test_the_preflight_checks_auth_before_it_spends_a_token(fake_binary):
    ok, detail = _transport(fake_binary).check_connection(TOOL_SCHEMAS)
    assert ok
    assert "claude.ai" in detail and "max" in detail
    assert "5h window" in detail


def test_a_signed_out_cli_fails_the_preflight(fake_binary):
    (fake_binary.parent / "auth.json").write_text(json.dumps({"loggedIn": False}))
    ok, detail = _transport(fake_binary).check_connection(TOOL_SCHEMAS)
    assert not ok
    assert "claude auth login" in detail


def test_the_client_routes_a_claude_id_through_the_transport(fake_binary):
    """The lane is reachable the same way every other lane is: build a
    config, build the client, call chat."""
    client = OllamaClient(
        ModelConfig.from_environment(
            model=WRITER_MODEL,
            vision_model="",
            claude_code_binary_path=str(fake_binary),
        )
    )
    message = client.chat([{"role": "user", "content": "make a crate"}], TOOL_SCHEMAS)
    assert message["tool_calls"][0]["function"]["name"] == "run_python"
    argv = json.loads((fake_binary.parent / "argv.json").read_text())
    assert "--safe-mode" in argv


def test_the_rate_limit_summary_reads_as_percentages():
    snapshot = parse_rate_limit(RATE_LIMIT_FRAME)
    assert snapshot.allowed
    assert snapshot.resets_at_epoch_seconds == 1788634200
    assert snapshot.summary() == "limits 25% of the 5h window, 50% of the 7d window"
    exhausted = parse_rate_limit(
        {"rate_limit_info": {"status": "rejected", "unifiedWindows": {}}}
    )
    assert not exhausted.allowed
    assert "rejected" in exhausted.summary()


def test_the_stub_binary_is_not_the_real_one(fake_binary):
    """Guard the guard: these tests must never reach the real CLI."""
    assert os.access(fake_binary, os.X_OK)
    assert "canned frames" in fake_binary.read_text()
