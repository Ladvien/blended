# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for the blended bridge's server side: the plan gate, the
wire call, image content, errors raised in Blender, and the event log.

No Blender: ``send_code`` is replaced with a stub that answers like the
add-on does. The live path is ``test_blender_mcp_with_blender.py``.
"""

__all__ = ()

import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from blended.agent.outcome import ToolOutcome, outcome_to_json
from blended.agent.plan import MISSING_PLAN_REFUSAL
from blmcp.tools_helpers import blended_bridge

_BOX_ARGUMENTS = {"name": "Crate", "width_m": 0.5, "depth_m": 0.5, "height_m": 0.5}


def _ok_response(outcome: ToolOutcome) -> dict[str, object]:
    return {"status": "ok", "result": {"status": "ok", "outcome": outcome_to_json(outcome)}}


class TestBlendedBridge(unittest.TestCase):

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        root = Path(self._directory.name)
        self._log_directory = root / "logs"
        self._session = blended_bridge.BlendedSession(self._log_directory, root / "outputs")
        self._responses: list[dict[str, object]] = []
        self._sent: list[str] = []
        patcher = mock.patch.object(blended_bridge, "send_code", self._send_code)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._directory.cleanup)

    def _send_code(self, code: str, strict_json: bool) -> dict[str, object]:
        self.assertTrue(strict_json)
        self._sent.append(code)
        return self._responses.pop(0)

    def _call(self, tool_name: str, arguments: dict[str, object]) -> object:
        return asyncio.run(self._session.call(tool_name, arguments))

    def _log_rows(self) -> list[dict[str, object]]:
        (jsonl_path,) = self._log_directory.glob("mcp-*.jsonl")
        return [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]

    def test_scene_changing_tool_before_plan_is_refused_without_blender(self) -> None:
        result = self._call("add_box", _BOX_ARGUMENTS)

        self.assertTrue(result.isError)
        self.assertEqual(result.content[0].text, MISSING_PLAN_REFUSAL)
        self.assertEqual(self._sent, [])
        self.assertEqual(self._log_rows()[-1]["data"]["refusal"], MISSING_PLAN_REFUSAL)

    def test_declared_plan_opens_the_gate(self) -> None:
        self._responses = [
            _ok_response(ToolOutcome("Plan declared:\n  1. x")),
            _ok_response(ToolOutcome("Added Crate")),
        ]

        self.assertFalse(self._call("declare_plan", {"steps": ["x"]}).isError)
        result = self._call("add_box", _BOX_ARGUMENTS)

        self.assertFalse(result.isError)
        self.assertEqual(len(self._sent), 2)
        self.assertIn("'add_box'", self._sent[1])

    def test_failed_outcome_carries_its_render_as_image_content(self) -> None:
        png_path = Path(self._directory.name) / "front.png"
        png_bytes = b"\x89PNG\r\n\x1a\nnot-a-real-image"
        png_path.write_bytes(png_bytes)
        self._responses = [_ok_response(ToolOutcome("gate failed", images=(png_path,), ok=False))]

        result = self._call("render_views", {"object_name": "Crate"})

        self.assertTrue(result.isError)
        self.assertEqual(result.content[1].type, "image")
        self.assertEqual(base64.b64decode(result.content[1].data), png_bytes)

    def test_exception_in_blender_is_an_error_result(self) -> None:
        self._responses = [{"status": "error", "message": "Traceback (most recent call last):\n  boom"}]

        result = self._call("render_views", {"object_name": "Crate"})

        self.assertTrue(result.isError)
        self.assertTrue(result.content[0].text.startswith("Tool raised in Blender:"))


if __name__ == "__main__":
    unittest.main()
