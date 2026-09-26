# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
blended's tool surface served through this MCP server.

Every tool in ``blended.agent.tools.TOOL_SCHEMAS`` (service tools and
facade ops) is listed beside the upstream tools and dispatched inside
Blender through ``dispatch_tool``, the one door the in-process agent
loop also uses (see ``blended_bridge_toolcode.py``). The server side
keeps what the loop keeps: the plan gate (a scene-changing tool is
refused until ``declare_plan`` succeeded) and one schema-2 ToolEvent per
call in ``logs/mcp-*.jsonl``, the record ``scripts/mine_candidate_ops.py``
mines. Renders come back as MCP image content.

The add-on execs whatever reaches its localhost socket: the exec-over-
localhost threat model of MCP is discussed in DOI 10.48550/arXiv.2503.23278.
Agentic Blender code generation: LL3M, DOI 10.48550/arXiv.2508.08228.
"""

__all__ = (
    "BLENDED_TOOLS",
    "BLENDED_TOOL_NAMES",
    "BlendedFastMCP",
    "BlendedSession",
    "blended_instructions",
)

import base64
import json
import sysconfig
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import anyio
import blended
from blended.agent.outcome import ToolOutcome, outcome_from_json
from blended.agent.plan import MISSING_PLAN_REFUSAL, PLAN_TOOL_NAME, plan_required_for
from blended.agent.system_prompt import build_system_prompt
from blended.agent.tool_event import (
    TOOL_EVENT_KIND,
    dispatched_tool_event,
    encode_tool_event,
    refused_tool_event,
)
from blended.agent.tools import MAXIMUM_TRACEBACK_CHARACTERS, TOOL_SCHEMAS, TOOL_SCHEMAS_FINGERPRINT
from blended.agent.transcript import ChatTranscript, default_log_directory
from mcp import types  # pylint: disable=import-error,no-name-in-module
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module

from blmcp.tools_helpers import (
    toolcode_format_call,
    toolcode_load_from_filepath,
    toolcode_wrap_with_calling_convention,
)
from blmcp.tools_helpers.blended_bridge_toolcode import Params
from blmcp.tools_helpers.connection import send_code

REPOSITORY_SRC = Path(blended.__file__).resolve().parent.parent
REPOSITORY_ROOT = REPOSITORY_SRC.parent
VENV_SITE_PACKAGES = sysconfig.get_paths()["purelib"]

_TOOL_CALL = toolcode_wrap_with_calling_convention(toolcode_load_from_filepath(__file__))

BLENDED_TOOLS: list[types.Tool] = [
    types.Tool(
        name=schema["function"]["name"],
        description=schema["function"]["description"],
        inputSchema=schema["function"]["parameters"],
    )
    for schema in TOOL_SCHEMAS
]
BLENDED_TOOL_NAMES = frozenset(tool.name for tool in BLENDED_TOOLS)

# blended captures renders as PNG only; any other suffix is a bug.
_IMAGE_SUFFIX = ".png"
_IMAGE_MIME_TYPE = "image/png"
_SESSION_NAME_FORMAT = "mcp-%Y-%m-%d-%H%M%S"
_ROUTING = "mcp"
_RAISED_IN_BLENDER_PREFIX = "Tool raised in Blender:\n"


def blended_instructions(upstream_instructions: str) -> str:
    """blended's working agreement, then upstream's instructions."""
    return build_system_prompt() + "\n\n" + upstream_instructions


def _docstring_as_python_313(docstring: str) -> str:
    """
    The docstring as Python 3.13+ compiles it: common indentation of the
    lines after the first removed, whitespace-only lines emptied. On 3.11
    the raw ``__doc__`` keeps the indentation; upstream's tool listing is
    pinned to the 3.13 form.
    """
    lines = docstring.expandtabs().split("\n")
    margin = min(
        (len(line) - len(line.lstrip()) for line in lines[1:] if line.strip()),
        default=0,
    )
    return "\n".join([lines[0].lstrip(), *(line[margin:] if line.strip() else "" for line in lines[1:])])


def _image_content(path: Path) -> types.ImageContent:
    if path.suffix != _IMAGE_SUFFIX:
        raise RuntimeError("blended returned a non-PNG image: {:s}".format(str(path)))
    return types.ImageContent(
        type="image",
        data=base64.b64encode(path.read_bytes()).decode("ascii"),
        mimeType=_IMAGE_MIME_TYPE,
    )


@dataclass
class BlendedSession:
    """
    The plan gate and the transcript for one server process (one MCP
    client session over stdio). A declared plan holds until the next
    ``declare_plan``.
    """

    log_directory: Path
    output_root: Path
    plan_declared: bool = False
    _transcript: ChatTranscript | None = field(default=None, init=False, repr=False)
    _output_directory: Path | None = field(default=None, init=False, repr=False)

    def _open(self) -> tuple[ChatTranscript, Path]:
        # Created on the first call, so a server that serves no blended
        # call leaves no empty log.
        if self._transcript is None or self._output_directory is None:
            session_name = datetime.now().strftime(_SESSION_NAME_FORMAT)
            self._transcript = ChatTranscript(self.log_directory, session_name=session_name, routing=_ROUTING)
            self._output_directory = (self.output_root / session_name).resolve()
            self._output_directory.mkdir(parents=True, exist_ok=True)
        return self._transcript, self._output_directory

    async def call(self, tool_name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        arguments = arguments or {}
        transcript, output_directory = self._open()
        transcript.record("tool", "{:s}({:s})".format(tool_name, json.dumps(arguments)))

        if plan_required_for(tool_name) and not self.plan_declared:
            transcript.record("result", MISSING_PLAN_REFUSAL)
            transcript.record(
                TOOL_EVENT_KIND,
                encode_tool_event(
                    refused_tool_event(tool_name, arguments, MISSING_PLAN_REFUSAL, TOOL_SCHEMAS_FINGERPRINT)
                ),
            )
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=MISSING_PLAN_REFUSAL)],
                isError=True,
            )

        code = toolcode_format_call(
            _TOOL_CALL,
            Params(
                tool_name,
                json.dumps(arguments),
                str(output_directory),
                str(REPOSITORY_SRC),
                VENV_SITE_PACKAGES,
            ),
        )
        started = time.perf_counter()
        try:
            response = await anyio.to_thread.run_sync(send_code, code, True)
        except ConnectionError as error:
            transcript.record("error", str(error))
            raise

        if response["status"] != "ok":
            outcome = ToolOutcome(
                _RAISED_IN_BLENDER_PREFIX + str(response.get("message", ""))[:MAXIMUM_TRACEBACK_CHARACTERS],
                ok=False,
            )
        else:
            result = response["result"]
            assert isinstance(result, dict)
            outcome = outcome_from_json(result["outcome"])
        wall_time_s = time.perf_counter() - started

        if tool_name == PLAN_TOOL_NAME and outcome.ok:
            self.plan_declared = True

        transcript.record("result", outcome.text)
        for image_path in outcome.images:
            transcript.record("render", str(image_path), image_paths=(str(image_path),))
        transcript.record(
            TOOL_EVENT_KIND,
            encode_tool_event(
                dispatched_tool_event(tool_name, arguments, outcome, wall_time_s, TOOL_SCHEMAS_FINGERPRINT)
            ),
        )
        return types.CallToolResult(
            content=[
                types.TextContent(type="text", text=outcome.text),
                *(_image_content(image_path) for image_path in outcome.images),
            ],
            isError=not outcome.ok,
        )


class BlendedFastMCP(FastMCP):  # type: ignore[misc]
    """Upstream's FastMCP server with blended's tools served beside its own."""

    def __init__(self, name: str, instructions: str) -> None:
        super().__init__(name, instructions=instructions)
        self._blended = BlendedSession(
            default_log_directory(REPOSITORY_ROOT),
            REPOSITORY_ROOT / "outputs" / "mcp",
        )

    def add_tool(self, fn: Any, *args: Any, description: str | None = None, **kwargs: Any) -> None:
        if description is None and fn.__doc__:
            description = _docstring_as_python_313(fn.__doc__)
        super().add_tool(fn, *args, description=description, **kwargs)

    async def list_tools(self) -> list[types.Tool]:
        upstream = await super().list_tools()
        overlap = BLENDED_TOOL_NAMES.intersection(tool.name for tool in upstream)
        if overlap:
            raise RuntimeError("Upstream and blended tools share names: {:s}".format(", ".join(sorted(overlap))))
        return [*upstream, *BLENDED_TOOLS]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name in BLENDED_TOOL_NAMES:
            return await self._blended.call(name, arguments)
        return await super().call_tool(name, arguments)
