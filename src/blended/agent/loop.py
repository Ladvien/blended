"""The conversational agent loop, over an Ollama-compatible endpoint.

Zero third-party dependencies — Blender's bundled Python has no pip
packages, and an addon that needs `pip install` inside Blender is an
addon nobody runs. Everything here uses `urllib` from the stdlib.

Model choice is CONFIGURATION, not code. `ModelConfig` carries the
model name and endpoint so the same loop runs against a local Ollama,
Ollama Cloud, or anything speaking the same chat API. See
`RECOMMENDED_MODELS` for the reasoning behind the defaults.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

LOCAL_ENDPOINT = "http://localhost:11434"
CLOUD_ENDPOINT = "https://ollama.com"
CHAT_PATH = "/api/chat"
TAGS_PATH = "/api/tags"
REQUEST_TIMEOUT_SECONDS = 300
PREFLIGHT_TIMEOUT_SECONDS = 10

API_KEY_ENVIRONMENT_VARIABLE = "OLLAMA_API_KEY"
HOST_ENVIRONMENT_VARIABLE = "OLLAMA_HOST"

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
    "best_subscription": (
        "minimax-m3:cloud",
        "High Usage tier — the strongest VLM the subscription covers. "
        "Native multimodality, tools + thinking, 1M context (512K "
        "guaranteed on Ollama Cloud), coding/agentic frontier. Default.",
    ),
    "fast_subscription": (
        "kimi-k2.7-code:cloud",
        "High Usage tier. Coding-tuned with ~30% lower thinking-token "
        "usage — noticeably snappier in chat, and lighter on your weekly "
        "limit, at some capability cost.",
    ),
    "light_subscription": (
        "qwen3.5:397b-cloud",
        "Medium Usage tier — cheapest against your limits. Vision + "
        "tools, 256K context. Good when iterating a lot on simple props.",
    ),
    "best_overall_metered": (
        "kimi-k3:cloud",
        "2.81T params, text/image/video, 1M context — the strongest VLM "
        "available. NOT subscription-covered: $3/$15 per 1M tokens, "
        "billed separately. Opt in deliberately.",
    ),
    "local_24gb": (
        "qwen3.5:27b",
        "Vision + tools, fits a 24 GB card at 4-bit. No cloud usage at all.",
    ),
}


@dataclass(frozen=True)
class ModelConfig:
    model: str = RECOMMENDED_MODELS["best_subscription"][0]
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
    ) -> "ModelConfig":
        """Resolve endpoint and auth, preferring the LOCAL daemon.

        With an Ollama subscription, `ollama signin` authenticates the
        local daemon and it proxies cloud models — so pointing at
        localhost with a `:cloud` model name Just Works, with no key
        handling here at all. That path is preferred because it also
        sidesteps a real macOS trap: Blender launched from Finder does
        NOT inherit your shell environment, so OLLAMA_API_KEY is
        invisible to it even though `echo $OLLAMA_API_KEY` works fine in
        a terminal.

        The direct-cloud path (endpoint + Bearer key) is the fallback
        for when the daemon is not running or not signed in.
        """
        import os

        resolved_key = api_key or os.environ.get(API_KEY_ENVIRONMENT_VARIABLE, "")
        resolved_endpoint = (
            endpoint
            or os.environ.get(HOST_ENVIRONMENT_VARIABLE, "")
            or LOCAL_ENDPOINT
        )
        return cls(
            model=model or RECOMMENDED_MODELS["best_subscription"][0],
            endpoint=resolved_endpoint,
            api_key=resolved_key,
            **overrides,
        )

    def with_endpoint(self, endpoint: str) -> "ModelConfig":
        from dataclasses import replace

        return replace(self, endpoint=endpoint)

    @property
    def is_cloud_endpoint(self) -> bool:
        return CLOUD_ENDPOINT in self.endpoint


@dataclass(frozen=True)
class ConnectionStatus:
    ok: bool
    endpoint: str
    detail: str

    def summary(self) -> str:
        return f"{'OK' if self.ok else 'FAILED'} [{self.endpoint}] {self.detail}"


class OllamaClient:
    """Minimal chat client with tool-calling and image attachment."""

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

    def check_connection(self) -> ConnectionStatus:
        """Verify the model is reachable BEFORE the first real turn.

        Tries the configured endpoint, then falls back to direct cloud if
        a key is available — and reports which path actually worked, so a
        misconfiguration is a one-line diagnosis instead of a mystery
        timeout mid-conversation.
        """
        attempts = [self.config.endpoint]
        if not self.config.is_cloud_endpoint and self.config.api_key:
            attempts.append(CLOUD_ENDPOINT)

        failures: list[str] = []
        for endpoint in attempts:
            probe_client = OllamaClient(self.config.with_endpoint(endpoint))
            try:
                probe_client._request(
                    CHAT_PATH,
                    {
                        "model": self.config.model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "stream": False,
                        "options": {"num_predict": 1},
                    },
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
            route = (
                "direct cloud (Bearer key)"
                if CLOUD_ENDPOINT in endpoint
                else "local daemon (proxying cloud models if signed in)"
            )
            return ConnectionStatus(True, endpoint, f"{self.config.model} via {route}")

        hint = ""
        if not self.config.api_key:
            hint = (
                f" No {API_KEY_ENVIRONMENT_VARIABLE} visible to this process — "
                f"on macOS, Blender launched from Finder does not inherit your "
                f"shell environment. Either run `ollama signin` so the local "
                f"daemon handles auth, launch Blender from a terminal, or paste "
                f"the key into the addon preferences."
            )
        return ConnectionStatus(False, self.config.endpoint, "; ".join(failures) + hint)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """One chat completion. Returns the assistant message dict."""
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
        try:
            body = self._request(CHAT_PATH, payload, REQUEST_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as http_error:
            detail = http_error.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(
                f"Model call failed: HTTP {http_error.code} from "
                f"{self.config.endpoint}. {detail}"
            ) from http_error
        except urllib.error.URLError as url_error:
            raise RuntimeError(
                f"Could not reach the model at {self.config.endpoint}: "
                f"{url_error}. Is `ollama serve` running, and is "
                f"{self.config.model!r} available?"
            ) from url_error
        return body.get("message", {})


def _encode_images(image_paths: list[Path]) -> list[str]:
    """Base64-encode images for the chat API."""
    encoded: list[str] = []
    for image_path in image_paths:
        image_bytes = Path(image_path).read_bytes()
        encoded.append(base64.b64encode(image_bytes).decode("ascii"))
    return encoded


@dataclass
class AgentSession:
    """A multi-turn modeling conversation against a live Blender scene."""

    client: OllamaClient = field(default_factory=OllamaClient)
    output_directory: Path = Path("_renders/agent")
    maximum_tool_calls_per_turn: int = 12
    messages: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.messages:
            from blended.agent.system_prompt import build_system_prompt

            self.messages.append(
                {"role": "system", "content": build_system_prompt()}
            )

    def send(self, user_text: str, on_event=None) -> str:
        """Run one user turn to completion, executing tool calls.

        `on_event(kind, text)` is called for streaming UI updates with
        kind in {"thinking", "tool", "result", "answer"}. Returns the
        assistant's final text.
        """
        from blended.agent.tools import TOOL_SCHEMAS, dispatch_tool

        def emit(kind: str, text: str) -> None:
            if on_event is not None:
                on_event(kind, text)

        self.messages.append({"role": "user", "content": user_text})

        for _ in range(self.maximum_tool_calls_per_turn):
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
                emit("tool", f"{tool_name}({json.dumps(arguments)[:200]})")
                try:
                    result_text, image_paths = dispatch_tool(
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
                }
                if image_paths:
                    tool_message["images"] = _encode_images(image_paths)
                self.messages.append(tool_message)

        exhausted = (
            f"Stopped after {self.maximum_tool_calls_per_turn} tool calls in "
            f"one turn without reaching an answer. Tell me how to narrow this."
        )
        emit("answer", exhausted)
        return exhausted
