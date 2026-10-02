# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for the blended bridge's server side: the plan gate, the
wire call, image content, errors raised in Blender, the event log, and
the source fingerprint that keeps the server and Blender fresh.

No Blender: ``send_code`` is replaced with a stub that answers like the
add-on does. The live path is ``test_blender_mcp_with_blender.py``.
"""

__all__ = ()

import asyncio
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest import mock

from blended.agent.outcome import ToolOutcome, outcome_to_json
from blended.agent.plan import MISSING_PLAN_REFUSAL
from blmcp import argument_parser
from blmcp.tools_helpers import blended_bridge, blended_bridge_toolcode, toolcode_format_call

_BOX_ARGUMENTS = {"name": "Crate", "width_m": 0.5, "depth_m": 0.5, "height_m": 0.5}

# One second: coarser than any filesystem's timestamp granularity, so a
# rewrite moved this much later always reads as a new mtime.
_REWRITE_LATER_BY_NS = 1_000_000_000
# A bare interpreter running a few toolcode calls on fake checkouts.
_TOOLCODE_DRIVER_TIMEOUT_S = 60.0


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


class TestSourceFingerprint(unittest.TestCase):

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        package = Path(self._directory.name) / "root" / "pkg"
        self._source = package / "a.py"
        # A watched suffix, so only the __pycache__ skip keeps it out (the
        # suffix filter alone already drops a .pyc).
        self._cached = package / "__pycache__" / "a.py"
        self._skipped = package / "data" / "api"
        self._skipped_source = self._skipped / "x.py"
        for path in (self._source, self._cached, self._skipped_source):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("value = 1\n", encoding="utf-8")
        self._roots = (package,)

    def _fingerprint(self) -> str:
        return blended_bridge.source_fingerprint(self._roots, (self._skipped,))

    def _rewrite_later(self, path: Path, text: str) -> None:
        modified_ns = path.stat().st_mtime_ns + _REWRITE_LATER_BY_NS
        path.write_text(text, encoding="utf-8")
        os.utime(path, ns=(modified_ns, modified_ns))

    def test_unchanged_tree_keeps_its_fingerprint(self) -> None:
        self.assertEqual(self._fingerprint(), self._fingerprint())

    def test_a_same_size_rewrite_changes_the_fingerprint(self) -> None:
        # Only the mtime differs: the edit a size check alone would miss.
        before = self._fingerprint()
        size_before = self._source.stat().st_size
        self._rewrite_later(self._source, "value = 2\n")
        self.assertEqual(self._source.stat().st_size, size_before)
        self.assertNotEqual(self._fingerprint(), before)

    def test_a_resize_under_the_old_mtime_changes_the_fingerprint(self) -> None:
        # Only the size differs: the edit an mtime check alone would miss.
        before = self._fingerprint()
        modified_ns = self._source.stat().st_mtime_ns
        self._source.write_text("value = 22\n", encoding="utf-8")
        os.utime(self._source, ns=(modified_ns, modified_ns))
        self.assertNotEqual(self._fingerprint(), before)

    def test_pycache_and_skipped_paths_do_not_change_it(self) -> None:
        before = self._fingerprint()
        self._rewrite_later(self._cached, "value = 3  # changed\n")
        self._rewrite_later(self._skipped_source, "value = 3  # changed\n")
        self.assertEqual(self._fingerprint(), before)

    def test_a_dangling_symlink_is_not_a_source_file(self) -> None:
        # Emacs keeps `.#name.py -> user@host.pid:boot` beside a modified
        # buffer: a watched suffix with nothing to stat.
        before = self._fingerprint()
        (self._source.parent / ".#a.py").symlink_to("user@host.12345:1700000000")
        self.assertEqual(self._fingerprint(), before)

    def test_missing_root_fails_loud(self) -> None:
        with self.assertRaises(FileNotFoundError):
            blended_bridge.source_fingerprint((Path(self._directory.name) / "absent",), ())


class TestWatcherIsOptIn(unittest.TestCase):
    """Claude Code and Claude Desktop never restart a server that exits."""

    def test_watcher_is_off_unless_asked_for(self) -> None:
        self.assertFalse(argument_parser().parse_args([]).exit_on_source_change)
        self.assertTrue(argument_parser().parse_args(["--exit-on-source-change"]).exit_on_source_change)

    def test_project_configs_opt_in_only_for_omp(self) -> None:
        # Ground truth is the config each client reads, not the default.
        claude_code = json.loads((blended_bridge.REPOSITORY_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        omp = json.loads((blended_bridge.REPOSITORY_ROOT / ".omp" / "mcp.json").read_text(encoding="utf-8"))
        self.assertNotIn("--exit-on-source-change", claude_code["mcpServers"]["blended"].get("args", []))
        self.assertIn("--exit-on-source-change", omp["mcpServers"]["blended"]["args"])
        self.assertEqual(omp["mcpServers"]["blended"]["command"], claude_code["mcpServers"]["blended"]["command"])


class _Exited(BaseException):
    """What the patched ``os._exit`` raises: the process would end here."""

    def __init__(self, exit_code: int) -> None:
        super().__init__(exit_code)
        self.exit_code = exit_code


class _ClockStopped(BaseException):
    """Ends a watcher run that has not exited by the end of its timeline."""


class _HeldOpen:
    """Suspends the coroutine awaiting it once: a tool call still inside Blender."""

    def __await__(self):  # type: ignore[no-untyped-def]
        yield
        return None


class TestSourceWatcher(unittest.TestCase):
    """
    The watcher's exit decision on a fake clock: the fingerprint follows a
    timeline, scheduled tool calls run through the real ``call_tool`` (its
    blended dispatch held open until the call's return time), and
    ``os._exit`` raises. No real sleep and no real exit.
    """

    # pylint: disable=protected-access

    _BASELINE = "baseline"
    _EDITED = "edited"
    _EDITED_AGAIN = "edited-again"
    _END_S = 60.0

    def setUp(self) -> None:
        self._server = blended_bridge.BlendedFastMCP("watcher-probe", instructions="probe")
        self._server._blended = types.SimpleNamespace(call=self._blended_call)
        self._tool_name = sorted(blended_bridge.BLENDED_TOOL_NAMES)[0]
        self._now_s = 0.0
        self._timeline: list[tuple[float, str]] = []
        self._calls: list[tuple[float, float]] = []
        self._running: dict[int, object] = {}
        self._stderr = io.StringIO()
        for name, replacement in (
            ("time", types.SimpleNamespace(sleep=self._sleep, monotonic=lambda: self._now_s)),
            ("os", types.SimpleNamespace(_exit=self._exit)),
            ("sys", types.SimpleNamespace(stderr=self._stderr)),
            ("source_fingerprint", self._fingerprint),
        ):
            patcher = mock.patch.object(blended_bridge, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    async def _blended_call(_name: str, _arguments: dict[str, object]) -> None:
        await _HeldOpen()

    def _fingerprint(self) -> str:
        current = self._BASELINE
        for time_s, value in self._timeline:
            if time_s <= self._now_s:
                current = value
        return current

    def _sleep(self, interval_s: float) -> None:
        # Advance the clock event by event: at a call's start time, step the
        # real call_tool until its dispatch is held open; at its return
        # time, step it to completion, so call_tool's own bookkeeping runs.
        end_s = self._now_s + interval_s
        if end_s > self._END_S:
            raise _ClockStopped()
        events = sorted(
            (event_s, index, is_return)
            for index, (start_s, return_s) in enumerate(self._calls)
            for event_s, is_return in ((start_s, False), (return_s, True))
            if self._now_s < event_s <= end_s
        )
        for event_s, index, is_return in events:
            self._now_s = event_s
            if is_return:
                with self.assertRaises(StopIteration):
                    self._running.pop(index).send(None)  # type: ignore[attr-defined]
            else:
                call = self._server.call_tool(self._tool_name, {})
                call.send(None)
                self._running[index] = call
        self._now_s = end_s

    def _exit(self, exit_code: int) -> None:
        raise _Exited(exit_code)

    def _watch(self) -> tuple[int, float] | None:
        """(exit code, exit time) once the watcher exits, or None if the clock ran out first."""
        try:
            self._server._watch_sources(self._BASELINE)
        except _Exited as exited:
            return exited.exit_code, self._now_s
        except _ClockStopped:
            return None
        raise AssertionError("_watch_sources returned without exiting")

    def test_a_settled_edit_exits_cleanly_once_idle(self) -> None:
        edit_s = 1.5
        self._timeline = [(edit_s, self._EDITED)]
        exited = self._watch()
        self.assertIsNotNone(exited)
        exit_code, exit_s = exited
        self.assertEqual(exit_code, blended_bridge.SOURCE_CHANGED_EXIT_CODE)
        self.assertGreaterEqual(exit_s - edit_s, blended_bridge.SOURCE_SETTLE_S)
        self.assertIn(self._EDITED, self._stderr.getvalue())

    def test_the_exit_waits_for_the_last_response_to_drain(self) -> None:
        # The edit settles while a call runs. call_tool returns before the
        # SDK writes the response, so idle alone is not enough to exit.
        call_returned_s = 6.5
        self._timeline = [(1.5, self._EDITED)]
        self._calls = [(1.8, call_returned_s)]
        exited = self._watch()
        self.assertIsNotNone(exited)
        exit_code, exit_s = exited
        self.assertEqual(exit_code, blended_bridge.SOURCE_CHANGED_EXIT_CODE)
        self.assertGreaterEqual(exit_s - call_returned_s, blended_bridge.SOURCE_RESPONSE_DRAIN_S)

    def test_an_edit_while_waiting_restarts_the_settle_clock(self) -> None:
        # The first edit settles during a long call; a second burst lands
        # just before the call returns, so the exit waits for it to settle.
        second_edit_s = 9.8
        self._timeline = [(1.5, self._EDITED), (second_edit_s, self._EDITED_AGAIN)]
        self._calls = [(1.8, 10.0)]
        exited = self._watch()
        self.assertIsNotNone(exited)
        _exit_code, exit_s = exited
        self.assertGreaterEqual(exit_s - second_edit_s, blended_bridge.SOURCE_SETTLE_S)
        self.assertIn(self._EDITED_AGAIN, self._stderr.getvalue())

    def test_an_edit_reverted_to_the_baseline_never_exits(self) -> None:
        self._timeline = [(1.5, self._EDITED), (2.5, self._BASELINE)]
        self.assertIsNone(self._watch())

    def test_a_broken_watcher_exits_with_the_failure_code_once_idle(self) -> None:
        call_returned_s = 4.5
        self._calls = [(0.5, call_returned_s)]
        with (
            mock.patch.object(blended_bridge, "source_fingerprint", side_effect=RuntimeError("probe")),
            self.assertRaises(_Exited) as exited,
        ):
            self._server._watch_sources_or_exit(self._BASELINE)
        self.assertEqual(exited.exception.exit_code, blended_bridge._WATCHER_FAILED_EXIT_CODE)
        self.assertGreaterEqual(self._now_s - call_returned_s, blended_bridge.SOURCE_RESPONSE_DRAIN_S)
        self.assertIn("RuntimeError: probe", self._stderr.getvalue())


class TestToolcodeReimport(unittest.TestCase):
    """
    The Blender side of freshness, run the way the add-on runs it (a fresh
    exec namespace per call, in an interpreter that writes and reads
    bytecode as Blender's does) against fake ``blended`` checkouts: an
    unchanged fingerprint keeps the imported modules, a changed one
    re-imports them even past a same-size rewrite in the same second, and
    another checkout's copy is refused without being purged.
    """

    # pylint: disable=protected-access

    _DRIVER = textwrap.dedent('''\
        import json
        import os
        import sys

        out = []
        with open(sys.argv[1], encoding="utf-8") as fh:
            steps = json.load(fh)
        for step in steps:
            for path, text in step["write"].items():
                # Keep the old mtime: the worst case, a same-size rewrite
                # in the second the cached bytecode was compiled.
                modified_ns = os.stat(path).st_mtime_ns
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                os.utime(path, ns=(modified_ns, modified_ns))
            namespace = {"result": {}}
            try:
                exec(step["code"], namespace)
                out.append({"outcome": namespace["result"]["outcome"]["text"]})
            except Exception as error:
                out.append({"error": "{:s}: {:s}".format(type(error).__name__, str(error))})
        print(json.dumps(out))
    ''')

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self._root = Path(self._directory.name).resolve()
        self._site_packages = self._root / "site-packages"
        self._site_packages.mkdir()

    @staticmethod
    def _tools_text(value: str) -> str:
        return "VALUE = {!r}\n\n\ndef dispatch_tool(name, arguments, output_directory):\n    return VALUE\n".format(value)

    def _checkout(self, name: str, value: str) -> Path:
        src = self._root / name / "src"
        agent = src / "blended" / "agent"
        agent.mkdir(parents=True)
        (src / "blended" / "__init__.py").write_text("", encoding="utf-8")
        (agent / "__init__.py").write_text("", encoding="utf-8")
        (agent / "outcome.py").write_text(
            "def outcome_to_json(outcome):\n    return {'text': outcome}\n", encoding="utf-8",
        )
        (agent / "tools.py").write_text(self._tools_text(value), encoding="utf-8")
        return src

    def _step(self, src: Path, fingerprint: str, write: dict[str, str] | None = None) -> dict[str, object]:
        params = blended_bridge_toolcode.Params(
            "probe", "{}", str(self._root), str(src), str(self._site_packages), fingerprint,
        )
        return {"code": toolcode_format_call(blended_bridge._TOOL_CALL, params), "write": write or {}}

    def _run(self, steps: list[dict[str, object]]) -> list[dict[str, str]]:
        plan = self._root / "plan.json"
        plan.write_text(json.dumps(steps), encoding="utf-8")
        driver = self._root / "driver.py"
        driver.write_text(self._DRIVER, encoding="utf-8")
        # -I also ignores PYTHONDONTWRITEBYTECODE, so bytecode is written.
        completed = subprocess.run(
            [sys.executable, "-I", "-S", str(driver), str(plan)],
            capture_output=True,
            text=True,
            check=True,
            timeout=_TOOLCODE_DRIVER_TIMEOUT_S,
        )
        results: list[dict[str, str]] = json.loads(completed.stdout)
        return results

    def test_only_a_changed_fingerprint_reimports(self) -> None:
        src = self._checkout("a", "one")
        tools = src / "blended" / "agent" / "tools.py"
        self.assertEqual(len(self._tools_text("one")), len(self._tools_text("two")))
        results = self._run([
            self._step(src, "fingerprint-1"),
            self._step(src, "fingerprint-1", write={str(tools): self._tools_text("two")}),
            self._step(src, "fingerprint-2"),
        ])
        self.assertEqual(results, [{"outcome": "one"}, {"outcome": "one"}, {"outcome": "two"}])
        # The probe is live only if the first import cached bytecode.
        self.assertTrue(any((tools.parent / "__pycache__").glob("tools.*.pyc")))

    def test_another_checkouts_copy_is_refused_and_left_loaded(self) -> None:
        a_src = self._checkout("a", "from-a")
        b_src = self._checkout("b", "from-b")
        results = self._run([
            self._step(a_src, "fingerprint-a"),
            self._step(b_src, "fingerprint-b"),
            self._step(a_src, "fingerprint-a"),
        ])
        self.assertEqual(results[0], {"outcome": "from-a"})
        self.assertIn("another copy is loaded", results[1]["error"])
        self.assertEqual(results[2], {"outcome": "from-a"})


if __name__ == "__main__":
    unittest.main()
