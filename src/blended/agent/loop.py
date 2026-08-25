"""The conversational agent loop, over an Ollama- or OpenAI-compatible
endpoint.

Zero third-party dependencies — Blender's bundled Python has no pip
packages, and an addon that needs `pip install` inside Blender is an
addon nobody runs. Everything here uses `urllib` from the stdlib.

Model choice is CONFIGURATION, not code. `ModelConfig` carries the
model name and the endpoint, and the same loop runs against a local
Ollama, Ollama Cloud, llama-swap on bmb (OpenAI protocol), or anything
speaking the Ollama or OpenAI chat APIs. See `RECOMMENDED_MODELS` for
the reasoning behind the defaults.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

LOCAL_ENDPOINT = "http://localhost:11434"
CLOUD_ENDPOINT = "https://ollama.com"
CHAT_PATH = "/api/chat"
TAGS_PATH = "/api/tags"
OPENAI_CHAT_PATH = "/v1/chat/completions"
# llama-swap on bmb speaks the OpenAI protocol; bmb exposes the port
# directly on the LAN at this address (no SSH tunnel needed).
BMB_ENDPOINT = "http://192.168.1.233:9292"
REQUEST_TIMEOUT_SECONDS = 300
# The preflight sends a real one-token chat, so it pays whatever the
# model's cold start costs. Measured 2026-08-22: a cloud model proxied
# through a local daemon answered `ping` in 23.3 s from cold, against a
# 10 s preflight — so the harness refused to score a run on a backend
# that was working. Generous relative to a cold start, still far short
# of REQUEST_TIMEOUT_SECONDS, so a genuinely dead endpoint is reported
# rather than waited on.
PREFLIGHT_TIMEOUT_SECONDS = 90

API_KEY_ENVIRONMENT_VARIABLE = "OLLAMA_API_KEY"
HOST_ENVIRONMENT_VARIABLE = "OLLAMA_HOST"
# Where the bmb llama-swap key lives on THIS machine (written from
# bmb's llama-swap.yaml, chmod 0600). Finder-launched Blender has no
# shell environment, so the key must come from a file, not an export.
BMB_API_KEY_FILE = Path.home() / ".blended" / "bmb_api_key"


def _read_bmb_api_key() -> str:
    """The bmb llama-swap key, or "" when the file is absent.

    Absent is fine — the addon preference or a manually created file
    can supply it. An unreadable or malformed file FAILS LOUDLY (raises)
    rather than silently sending an empty key and 401ing.
    """
    if not BMB_API_KEY_FILE.exists():
        return ""
    key = BMB_API_KEY_FILE.read_text(encoding="utf-8").strip()
    if len(key) != 64 or not all(c in "0123456789abcdef" for c in key):
        raise RuntimeError(
            f"{BMB_API_KEY_FILE} does not hold a 64-hex llama-swap key "
            f"(got {len(key)} chars). Fix or remove the file."
        )
    return key

# Why these, given what this harness actually asks of a model.
#
# The job is: write bpy Python, call tools, read measured gate reports,
# and LOOK at contact sheets. The analyzer is the hard gate, so vision
# is advisory — but a stronger VLM still catches wrong-object failures
# the gate cannot (measured here: a planter that passed every
# structural check with its drainage hole sealed shut).
#
# BILLING MATTERS. Ollama Cloud splits two ways, and the model pages
# show which is which:
#   * a usage-level label (Low/Medium/High Usage) -> covered by the
#     subscription, drawing on session and weekly limits
#   * per-token dollar pricing -> metered, billed on top
# kimi-k3 is the strongest VLM on the platform but is METERED at
# $3/$15 per 1M tokens. Everything defaulted to below is
# subscription-covered.
RECOMMENDED_MODELS = {
    "writer": (
        "deepseek-v4-pro:cloud",
        (
            "1.65T MoE. Drives every turn: writes bpy, calls tools, reads "
            "gate reports. The writer this harness CONVERGED on — v9's "
            "pin rests on runs scored with it. Default writer. "
            "deepseek-v4-flash is deliberately absent: it was scored "
            "through v1-v4 and never converged this suite — the last two "
            "blockers were not prompt wording but a writer too weak to "
            "place geometry (see the v5 pin comment in prompt_versions)."
        ),
    ),
    "eye": (
        "kimi-k2.7-code:cloud",
        (
            "High Usage tier, vision + coding-tuned. Calibrated 2026-08-24: "
            "sensitivity 0.80 (4/5), control specificity 1.00 (5/5) — the "
            "only LICENSED examiner. minimax-m3:cloud was the old default "
            "but is broken on this harness: it answers in message.thinking "
            "and returns empty content (measured 2026-08-24), so every "
            "examiner call would fail the JSON contract."
        ),
    ),
    "single_model_subscription": (
        "kimi-k2.7-code:cloud",
        (
            "Vision + coding-tuned, so it can drive everything itself. "
            "minimax-m3:cloud used to hold this slot but returns empty "
            "content (thinking trap) — see the eye entry."
        ),
    ),
    "single_model_fast": (
        "kimi-k2.7-code:cloud",
        (
            "High Usage tier, vision + coding-tuned, ~30% fewer thinking "
            "tokens. Good one-model compromise."
        ),
    ),
    "best_overall_metered": (
        "kimi-k3:cloud",
        (
            "2.81T params, text/image/video, 1M context — the strongest VLM "
            "available. NOT subscription-covered: $3/$15 per 1M tokens, "
            "billed separately. Opt in deliberately."
        ),
    ),
    # bmb's llama-swap (OpenAI protocol at BMB_ENDPOINT, exposed
    # directly on the LAN). These ids are EXACTLY what bmb's /v1/models
    # serves — a dropdown id that is not in this tuple has no server,
    # which is how gpt-oss-20b-heretic:latest 404'd (nothing anywhere
    # serves it; the real served id is gpt-oss-20b).
    "local_writer_bmb": (
        "qwen3.8-27b",
        (
            "bmb llama-swap (OpenAI protocol via "
            f"{BMB_ENDPOINT}, exposed directly on the LAN). Local "
            "and free; no subscription usage. Pair it with an Eye "
            "for vision. The id is exactly what /v1/models serves."
        ),
    ),
}
# Every model bmb's llama-swap serves, per its /v1/models (verified
# against the live endpoint 2026-08-23).
BMB_MODEL_IDS = (
    "gemma-4-26b-a4b",
    "glm-ocr",
    "gpt-oss-20b",
    "hermes-4-14b",
    "qwen3-32b",
    "qwen3.8-27b",
)

# What the eye is asked when a tool hands back a render. It describes;
# it does not adjudicate. The analyzer already returned a hard verdict on
# structure, and the measured failure mode of VLM critics is a bias
# toward accepting — so asking one to "check if this is correct" invites
# a rubber stamp. Asking it to REPORT lets the writer do the judging.
VISION_DESCRIBE_PROMPT = """\
You are the eyes for another agent that cannot see. It is building a 3D
game asset in Blender and has just rendered it.

Describe what is actually in these views, concretely and literally:
- What object does this appear to be? Does it read as the intended thing?
- Proportions: anything too thick, thin, tall, short, or misplaced?
- Parts: are the expected pieces present, and positioned sensibly?
- Anything visibly wrong, missing, floating, intersecting, or duplicated?

Report what you SEE. Do not say whether it passes or fails — a separate
analyzer already measured the geometry. Do not speculate about topology,
normals, or manifoldness; you cannot see those. If something looks
right, say so plainly rather than inventing problems.

Be specific and brief: 3-6 sentences."""


@dataclass(frozen=True)
class ModelConfig:
    model: str = RECOMMENDED_MODELS["writer"][0]
    # The eye. Set to "" to make the writer handle images itself, which
    # only works if the writer is vision-capable — deepseek-v4-flash is
    # not, so leaving this empty with the default writer means renders
    # are never actually looked at.
    vision_model: str = RECOMMENDED_MODELS["eye"][0]
    endpoint: str = LOCAL_ENDPOINT
    temperature: float = 0.3  # low: this is engineering, not brainstorming
    context_length: int = 32768
    api_key: str = ""

    @classmethod
    def from_environment(
        cls,
        model: str = "",
        endpoint: str = "",
        api_key: str = "",
        **overrides,
    ) -> ModelConfig:
        """Resolve endpoint and auth.

        The model implies its server when nothing explicit was given:
        qwen3.8 is bmb's llama-swap, everything else rides the local
        daemon (which proxies cloud models once `ollama signin` has
        authenticated it). An explicit non-default endpoint or
        OLLAMA_HOST wins over the model's implied server — but the
        default `http://localhost:11434` is treated as UNSET, because
        it is what every fresh install and every saved preference holds,
        and it must not override the model the user just picked.

        The daemon-first path also sidesteps a real macOS trap: Blender
        launched from Finder does NOT inherit your shell environment, so
        OLLAMA_API_KEY is invisible to it even though
        `echo $OLLAMA_API_KEY` works fine in a terminal.
        """
        import os

        resolved_model = model or RECOMMENDED_MODELS["writer"][0]
        # Auth order, one path per lane:
        #   * an explicit api_key (addon preference) always wins;
        #   * a bmb model reads the bmb key file (~/.blended/bmb_api_key,
        #     0600, written from bmb's llama-swap.yaml) — Finder-launched
        #     Blender has no shell environment, so the key must come from
        #     a file, not an export;
        #   * every other lane falls back to OLLAMA_API_KEY.
        # The Ollama env key is deliberately NOT sent to bmb: it is the
        # wrong credential for llama-swap and would 401.
        resolved_key = api_key
        if not resolved_key:
            if resolved_model in BMB_MODEL_IDS:
                resolved_key = _read_bmb_api_key()
            else:
                resolved_key = os.environ.get(API_KEY_ENVIRONMENT_VARIABLE, "")
        explicit_endpoint = (
            endpoint if endpoint and endpoint != LOCAL_ENDPOINT else ""
        )
        resolved_endpoint = (
            explicit_endpoint
            or os.environ.get(HOST_ENVIRONMENT_VARIABLE, "")
            or (
                BMB_ENDPOINT
                if resolved_model in BMB_MODEL_IDS
                else LOCAL_ENDPOINT
            )
        )
        return cls(
            model=resolved_model,
            endpoint=resolved_endpoint,
            api_key=resolved_key,
            **overrides,
        )

    def with_endpoint(self, endpoint: str) -> ModelConfig:
        from dataclasses import replace

        return replace(self, endpoint=endpoint)

    @property
    def is_cloud_endpoint(self) -> bool:
        return CLOUD_ENDPOINT in self.endpoint

    @property
    def uses_openai_protocol(self) -> bool:
        """llama-swap (bmb) and other OpenAI-shaped servers."""
        return BMB_ENDPOINT in self.endpoint

    @property
    def uses_separate_eye(self) -> bool:
        """True when a distinct vision model handles images."""
        return bool(self.vision_model) and self.vision_model != self.model

    def eye_config(self) -> ModelConfig:
        """The config for this config's vision model.

        An eye that IS the bmb model rides the bmb OpenAI lane (the
        wire now carries images). Any other eye — a daemon model or a
        cloud model — rides the Ollama daemon when the writer is on
        bmb, because only the bmb model is served by bmb.
        """
        eye = replace(self, model=self.vision_model)
        if self.vision_model in BMB_MODEL_IDS:
            eye = replace(eye, endpoint=BMB_ENDPOINT)
        elif self.uses_openai_protocol:
            eye = replace(eye, endpoint=LOCAL_ENDPOINT)
        return eye

    def describe_routing(self) -> str:
        if self.uses_separate_eye:
            return (
                f"writer={self.model} (text/tools), "
                f"eye={self.vision_model} (images only)"
            )
        return f"{self.model} handles text and images"


@dataclass(frozen=True)
class ConnectionStatus:
    ok: bool
    endpoint: str
    detail: str

    def summary(self) -> str:
        return f"{'OK' if self.ok else 'FAILED'} [{self.endpoint}] {self.detail}"


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """Convert Ollama-style message dicts to OpenAI chat message dicts.

    The common subset survives: role + content, tool results with their
    tool_call_id, and the Ollama `images` field becomes OpenAI
    image_url parts — bmb's qwen3.8 is used as the EYE too, so the
    OpenAI lane carries images, not just text. Unknown keys are dropped
    silently.
    """
    converted: list[dict] = []
    for message in messages:
        role = message.get("role", "user")
        converted_message = {"role": role}
        content = message.get("content", "")
        images = message.get("images")
        if images:
            parts: list[dict] = []
            if content:
                parts.append({"type": "text", "text": content})
            for image in images:
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image}"},
                    }
                )
            converted_message["content"] = parts
        else:
            converted_message["content"] = content
        if role == "tool" and message.get("tool_call_id"):
            converted_message["tool_call_id"] = message["tool_call_id"]
        converted.append(converted_message)
    return converted


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "parameters": tool["function"].get("parameters", {}),
            },
        }
        for tool in tools
    ]


def _assistant_message_from_openai(body: dict) -> dict:
    """OpenAI chat-completions body -> the assistant message dict the
    loop already consumes, ids preserved for the tool-result round
    trip."""
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    tool_calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        tool_calls.append(
            {
                "id": call.get("id", ""),
                "function": {
                    "name": function.get("name", ""),
                    "arguments": function.get("arguments") or {},
                },
            }
        )
    normalized = {
        "role": message.get("role", "assistant"),
        "content": message.get("content") or "",
        "tool_calls": tool_calls,
    }
    reasoning = message.get("reasoning_content")
    if reasoning:
        normalized["thinking"] = reasoning
    return normalized


class OllamaClient:
    """Minimal chat client with tool-calling and image attachment.

    One client, two wire protocols, chosen per endpoint:
    Ollama /api/chat (local daemon and cloud) or OpenAI
    /v1/chat/completions (bmb's llama-swap).
    """

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig.from_environment()

    def _request(self, path: str, payload: dict | None, timeout_seconds: int):
        request = urllib.request.Request(
            self.config.endpoint.rstrip("/") + path,
            data=json.dumps(payload).encode("utf-8") if payload else None,
            headers={"Content-Type": "application/json"},
            method="POST" if payload else "GET",
        )
        if self.config.api_key:
            request.add_header("Authorization", f"Bearer {self.config.api_key}")
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _chat_path(self) -> str:
        return OPENAI_CHAT_PATH if self.config.uses_openai_protocol else CHAT_PATH

    def _chat_payload(self, messages, tools=None) -> dict:
        if self.config.uses_openai_protocol:
            payload = {
                "model": self.config.model,
                "messages": _to_openai_messages(messages),
                "temperature": self.config.temperature,
                # The bmb writer is a REASONING build: its 65536-token
                # context and thinking budget make 4096 a starvation cap —
                # measured live 2026-08-23: the tool round trip returned
                # EMPTY content with finish_reason=length, then answered
                # in 72 tokens with 16384. The whole lane is capped by
                # REQUEST_TIMEOUT_SECONDS, so this only sets the ceiling.
                "max_tokens": 16384,
                "stream": False,
            }
            if tools:
                payload["tools"] = _to_openai_tools(tools)
            return payload
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_ctx": self.config.context_length,
            },
        }
        if tools:
            payload["tools"] = tools
        return payload

    def check_connection(self) -> ConnectionStatus:
        """Verify the model is reachable BEFORE the first real turn.

        Tries the configured endpoint, then falls back to direct cloud if
        a key is available — and reports which path actually worked, so a
        misconfiguration is a one-line diagnosis instead of a mystery
        timeout mid-conversation.
        """
        attempts = [self.config.endpoint]
        if (
            not self.config.is_cloud_endpoint
            and not self.config.uses_openai_protocol
            and self.config.api_key
        ):
            # Ollama lanes fall back to direct cloud; the bmb lane has
            # ONE server and ONE key — no fallback.
            attempts.append(CLOUD_ENDPOINT)

        failures: list[str] = []
        for endpoint in attempts:
            probe_client = OllamaClient(self.config.with_endpoint(endpoint))
            try:
                probe_client._request(
                    probe_client._chat_path(),
                    probe_client._chat_payload(
                        [{"role": "user", "content": "ping"}]
                    ),
                    PREFLIGHT_TIMEOUT_SECONDS,
                )
            except urllib.error.HTTPError as http_error:
                body = http_error.read().decode("utf-8", "replace")[:200]
                failures.append(f"{endpoint}: HTTP {http_error.code} {body}")
                continue
            except Exception as error:  # noqa: BLE001 — diagnostic path
                failures.append(f"{endpoint}: {error}")
                continue
            self.config = self.config.with_endpoint(endpoint)
            if self.config.uses_openai_protocol:
                route = f"llama-swap (bmb) via {BMB_ENDPOINT}"
            elif CLOUD_ENDPOINT in endpoint:
                route = "direct cloud (Bearer key)"
            else:
                route = "local daemon (proxying cloud models if signed in)"
            return ConnectionStatus(True, endpoint, f"{self.config.model} via {route}")

        hint = ""
        if not self.config.api_key:
            if self.config.uses_openai_protocol:
                hint = (
                    f" bmb's llama-swap requires its API key (it 401s "
                    f"without one, verified live 2026-08-23). The key lives "
                    f"on bmb at ~/llm/.api-key — paste it into the addon's "
                    f"API key preference. Finder-launched Blender does not "
                    f"inherit your shell environment."
                )
            else:
                hint = (
                    f" No {API_KEY_ENVIRONMENT_VARIABLE} visible to this "
                    f"process — on macOS, Blender launched from Finder does "
                    f"not inherit your shell environment. Either run "
                    f"`ollama signin` so the local daemon handles auth, "
                    f"launch Blender from a terminal, or paste the key into "
                    f"the addon preferences."
                )
        return ConnectionStatus(False, self.config.endpoint, "; ".join(failures) + hint)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """One chat completion. Returns the assistant message dict."""
        payload = self._chat_payload(messages, tools)
        try:
            body = self._request(self._chat_path(), payload, REQUEST_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as http_error:
            detail = http_error.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(
                f"Model call failed: HTTP {http_error.code} from "
                f"{self.config.endpoint}. {detail}"
            ) from http_error
        except urllib.error.URLError as url_error:
            raise RuntimeError(
                f"Could not reach the model at {self.config.endpoint}: "
                f"{url_error}. Is the server running, and is "
                f"{self.config.model!r} available?"
            ) from url_error
        if self.config.uses_openai_protocol:
            return _assistant_message_from_openai(body)
        return body.get("message", {})


class VisionDescriber:
    """Turns rendered images into text for a writer that cannot see.

    Kept as a separate one-shot call rather than a second conversation:
    the eye gets the images plus a focused question and returns a
    description. It holds no history, makes no tool calls, and never
    decides anything — so a High Usage model is spent only on the turns
    that actually contain a render, instead of on every turn.
    """

    def __init__(self, client: OllamaClient, vision_model: str) -> None:
        self.client = client
        self.vision_model = vision_model

    def describe(
        self, image_paths: list[Path], question: str = "", prompt: str = ""
    ) -> str:
        """Describe the images, or answer a caller's OWN prompt verbatim.

        `prompt` replaces the template entirely: the examiner supplies a
        fully-rendered prompt with a closed tag vocabulary and a JSON
        output contract, and prepending advisory prose written for the
        writer would contaminate it. Empty `prompt` keeps the writer's
        own question wording; both paths get the image placeholders,
        because both hand the eye several same-size renders at once.
        """
        if prompt:
            text = prompt
        else:
            text = VISION_DESCRIBE_PROMPT
            if question:
                text += f"\n\nThe agent specifically wants to know: {question}"
        message = {
            "role": "user",
            "content": _image_placeholders(len(image_paths)) + text,
            "images": _encode_images(image_paths),
        }
        eye_config = replace(self.client.config, model=self.vision_model)
        if self.vision_model in BMB_MODEL_IDS:
            # The eye IS a bmb model: it rides the bmb OpenAI lane.
            eye_config = replace(eye_config, endpoint=BMB_ENDPOINT)
        elif self.client.config.uses_openai_protocol:
            # The bmb lane is text-only for non-bmb eyes; they live on
            # the daemon.
            eye_config = replace(eye_config, endpoint=LOCAL_ENDPOINT)
        eye_client = OllamaClient(eye_config)
        reply = eye_client.chat([message])
        return (reply.get("content") or "").strip()


def _image_placeholders(image_count: int) -> str:
    """One labelled `[img]` placeholder per image, separated by text.

    Without placeholders, Ollama's renderer prepends `[img-0][img-1]...`
    back to back, and llama.cpp's mtmd tokenizer merges *consecutive*
    same-size bitmaps into video frames for the qwen-vl family
    (ollama/ollama#17321, ggml-org/llama.cpp#24303, both open). Every
    render this harness makes is the same size, so a two-image message
    arrived as ONE fused image and the examiner correctly answered
    `cannot_tell` — it had never been shown the render under review.
    Measured 2026-08-22 against qwen3-vl:8b on ollama 0.32.14: 1055
    prompt tokens fused, 2089 with these placeholders, and the eye then
    names both objects and tracks their order when swapped.

    The renderer substitutes placeholders in order, so `Image 1` is the
    first path — which is what `examiner.md.j2` means by "the FIRST
    image".
    """
    return (
        "".join(f"Image {index}:\n[img]\n" for index in range(1, image_count + 1))
        + "\n"
    )


def _encode_images(image_paths: list[Path]) -> list[str]:
    """Base64-encode images for the chat API."""
    encoded: list[str] = []
    for image_path in image_paths:
        image_bytes = Path(image_path).read_bytes()
        encoded.append(base64.b64encode(image_bytes).decode("ascii"))
    return encoded


# Where a tool call is executed. The loop runs on a worker thread (the
# model call blocks for seconds to minutes) but `bpy` is main-thread
# only, so the live-Blender frontend has to move execution somewhere
# else. That seam is a CONSTRUCTOR ARGUMENT, never a patched module
# attribute: `send` resolves its tools by local import, so a patch on
# this module is invisible to it. When the seam was a patch, every tool
# call ran bpy on the worker thread and Blender segfaulted inside its
# own draw loop with nothing in any traceback.
ToolDispatch = Callable[[str, dict, Path], tuple[str, list[Path]]]


def dispatch_here(
    tool_name: str, arguments: dict, output_directory: Path
) -> tuple[str, list[Path]]:
    """Execute the tool on the CALLING thread. Main thread only."""
    from blended.agent.tools import dispatch_tool

    return dispatch_tool(tool_name, arguments, output_directory)


@dataclass
class AgentSession:
    """A multi-turn modeling conversation against a live Blender scene."""

    client: OllamaClient = field(default_factory=OllamaClient)
    output_directory: Path = Path("_renders/agent")
    # Measured, not guessed. three_leg_stool needs 17 calls to build and
    # verify itself (iteration 10) and then has nothing left to answer
    # with — three consecutive runs ended in the exhaustion string
    # holding a finished asset. 24 leaves room to report and to absorb
    # one failed chunk, while still capping a runaway loop.
    maximum_tool_calls_per_turn: int = 24
    messages: list[dict] = field(default_factory=list)
    # A plain function as a dataclass default: __init__ assigns it to the
    # INSTANCE, so `self.dispatch(...)` calls it unbound — no phantom
    # `self` argument. Frontends override it; nothing patches it.
    dispatch: ToolDispatch = dispatch_here

    def __post_init__(self) -> None:
        if not self.messages:
            from blended.agent.system_prompt import build_system_prompt

            self.messages.append({"role": "system", "content": build_system_prompt()})

    def send(self, user_text: str, on_event=None) -> str:
        """Run one user turn to completion, executing tool calls.

        `on_event(kind, text)` is called for streaming UI updates with
        kind in {"thinking", "tool", "result", "answer"}. Returns the
        assistant's final text.
        """
        from blended.agent.tools import TOOL_SCHEMAS

        def emit(kind: str, text: str) -> None:
            if on_event is not None:
                on_event(kind, text)

        self.messages.append({"role": "user", "content": user_text})

        executed_tool_call_count = 0
        while executed_tool_call_count < self.maximum_tool_calls_per_turn:
            assistant_message = self.client.chat(self.messages, TOOL_SCHEMAS)
            self.messages.append(assistant_message)

            thinking_text = assistant_message.get("thinking")
            if thinking_text:
                emit("thinking", thinking_text)

            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                answer = assistant_message.get("content", "")
                emit("answer", answer)
                return answer

            for tool_call in tool_calls:
                function_block = tool_call.get("function", {})
                tool_name = function_block.get("name", "")
                raw_arguments = function_block.get("arguments", {})
                arguments = (
                    json.loads(raw_arguments)
                    if isinstance(raw_arguments, str)
                    else raw_arguments
                )
                emit("tool", f"{tool_name}({json.dumps(arguments)})")
                executed_tool_call_count += 1
                try:
                    result_text, image_paths = self.dispatch(
                        tool_name, arguments, self.output_directory
                    )
                except Exception as tool_error:  # noqa: BLE001 — reported to the model
                    import traceback

                    result_text = (
                        f"Tool raised {type(tool_error).__name__}: {tool_error}\n"
                        f"{traceback.format_exc()[:1500]}"
                    )
                    image_paths = []
                emit("result", result_text)

                tool_message: dict = {
                    "role": "tool",
                    "content": result_text,
                    "tool_name": tool_name,
                    # Carried so an OpenAI-protocol backend (llama-swap)
                    # can match the result to the assistant's call;
                    # Ollama ignores unknown keys.
                    "tool_call_id": tool_call.get("id", ""),
                }
                if image_paths:
                    if self.client.config.uses_separate_eye:
                        describer = VisionDescriber(
                            self.client, self.client.config.vision_model
                        )
                        try:
                            description = describer.describe(
                                image_paths, arguments.get("look_for", "")
                            )
                        except Exception as eye_error:  # noqa: BLE001
                            description = (
                                f"(The vision model could not be reached: "
                                f"{eye_error}. You are working blind on this "
                                f"render — rely on the gate report and ask "
                                f"the user to look.)"
                            )
                        emit("vision", description)
                        tool_message["content"] = (
                            f"{result_text}\n\n"
                            f"--- what the render shows "
                            f"({self.client.config.vision_model}) ---\n"
                            f"{description}"
                        )
                    else:
                        tool_message["images"] = _encode_images(image_paths)
                self.messages.append(tool_message)

        exhausted = (
            f"Stopped after {executed_tool_call_count} tool calls in one turn "
            f"(budget {self.maximum_tool_calls_per_turn}) without reaching an "
            f"answer. Tell me how to narrow this."
        )
        emit("answer", exhausted)
        return exhausted
