"""Regression tests for the harness_core review (2026-10-07). Pure: no bpy."""

import stat
import sys

import pytest

from blended.harness import HarnessResult
from blended.run import executor
from blended.run.executor import execute_captured, run_script_subprocess
from blended.run.retry import run_with_retries
from blended.task import AgentTask, build_gate_feedback, run_agent_task

TASK = AgentTask(object_name="Widget", description="Build a widget.")
FAKE_TIMEOUT_SECONDS = 1
FAKE_EXIT_STATUS = 7
SLEEP_LONGER_THAN_TIMEOUT_SECONDS = 30


def _fake_blender(directory, body: str) -> str:
    """An executable stand-in for the Blender binary: a shell script."""
    script = directory / "fake_blender.sh"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def test_a_chunk_that_calls_sys_exit_comes_back_as_a_failed_result():
    # SystemExit is not an Exception; before the fix it unwound through
    # execute_captured and would quit the host Blender.
    def thunk():
        print("before exit")
        sys.exit(3)

    result, returned = execute_captured(thunk, "<test>", "5.2")
    assert returned is None
    assert not result.ok
    assert result.error_type == "SystemExit"
    assert result.error_message == "3"
    assert "before exit" in result.stdout_text


def test_zero_task_rounds_is_refused_not_an_unbound_variable():
    with pytest.raises(ValueError, match="maximum_rounds"):
        run_agent_task(TASK, write_code=lambda prompt: "", maximum_rounds=0)


def test_negative_retries_is_refused_not_an_index_error():
    with pytest.raises(ValueError, match="maximum_retries"):
        run_with_retries("pass", lambda source, result: source, maximum_retries=-1)


def test_locate_feedback_carries_the_scene_state_reason():
    # `locate` is also where an object that EXISTS but is hidden stops; the
    # feedback must carry that reason instead of claiming it is missing.
    hidden_reason = "'Widget' is in the view layer but HIDDEN"
    result = HarnessResult(
        ok=False,
        stage_reached="locate",
        object_name="Widget",
        execution_summary=f"1 attempt(s), ok; {hidden_reason}",
    )
    feedback = build_gate_feedback(result, TASK)
    assert hidden_reason in feedback
    assert "existed afterwards" not in feedback


def test_subprocess_timeout_is_a_failed_result(tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "SUBPROCESS_TIMEOUT_SECONDS", FAKE_TIMEOUT_SECONDS)
    binary = _fake_blender(tmp_path, f"sleep {SLEEP_LONGER_THAN_TIMEOUT_SECONDS}")
    result = run_script_subprocess(tmp_path / "script.py", blender_binary=binary)
    assert not result.ok
    assert result.error_type == "TimeoutExpired"
    assert result.duration_s < SLEEP_LONGER_THAN_TIMEOUT_SECONDS


def test_subprocess_without_result_file_reports_status_and_stderr(tmp_path):
    binary = _fake_blender(tmp_path, f"echo 'segfault in render' >&2\nexit {FAKE_EXIT_STATUS}")
    result = run_script_subprocess(tmp_path / "script.py", blender_binary=binary)
    assert not result.ok
    assert result.error_type == "HarnessError"
    assert f"status {FAKE_EXIT_STATUS}" in result.error_message
    assert "segfault in render" in result.error_message
