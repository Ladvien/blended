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

DEFAULT_ENDPOINT = "http://localhost:11434"
CHAT_PATH = "/api/chat"
REQUEST_TIMEOUT_SECONDS = 300

# Why these, given what this harness actually asks of a model.
#
# The job is: write bpy Python, call tools, read measured gate reports,
# and occasionally LOOK at a contact sheet. That is a coding-and-tools
# job first and a vision job second — the analyzer is the hard gate, and
# VLM visual judgement is advisory (measured bias toward accepting, and
# reliability that DEGRADES as the generator improves). So coding
# strength and tool discipline outrank raw vision quality.
RECOMMENDED_MODELS = {
    "default": (
        "kimi-k2.7-code",
        "Vision + tools + thinking, explicitly coding-tuned for "
        "long-horizon work with ~30% lower thinking-token usage — the "
        "latency that matters most in interactive chat.",
    ),
    "strongest": (
        "kimi-k3",
        "Native multimodal agentic, highest ceiling. Choose when asset "
        "complexity matters more than turn latency.",
    ),
    "long_context": (
        "minimax-m3",
        "1M context and native multimodality — for very long sessions "
        "where the whole build history stays in context.",
    ),
    "local_24gb": (
        "qwen3.5:27b",
        "Vision + tools, fits a 24 GB card at 4-bit. The practical "
        "local option; also a good cheap critic alongside a stronger "
        "cloud writer.",
    ),
    "local_small": (
        "gemma4:12b",
        "Vision + tools at a size that leaves VRAM headroom for Blender "
        "itself. Weakest coding of the four — expect more gate failures.",
    ),
}


@dataclass(frozen=True)
class ModelConfig:
    model: str = RECOMMENDED_MODELS["default"][0]
    endpoint: str = DEFAULT_ENDPOINT
    temperature: float = 0.3  # low: this is engineering, not brainstorming
    context_length: int = 32768
    api_key: str = ""  # set for Ollama Cloud


class OllamaClient:
    """Minimal chat client with tool-calling and image attachment."""

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig()

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

        request = urllib.request.Request(
            self.config.endpoint.rstrip("/") + CHAT_PATH,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if self.config.api_key:
            request.add_header("Authorization", f"Bearer {self.config.api_key}")
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as error:
            raise RuntimeError(
                f"Could not reach the model at {self.config.endpoint}: {error}. "
                f"Is `ollama serve` running, and is {self.config.model!r} pulled?"
            ) from error
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
