"""Script execution with structured traceback capture.

The execution-feedback loop is the single biggest measured lever in
agentic 3D modeling (3DCodeBench: visible tracebacks + <=2 retries took
executability 0.702 -> 0.974). This module's job is to make the
environment tell the truth loudly: every run returns a RunResult with
the full traceback, and failed runs are matched against the drift
catalog so known API moves are surfaced with their fix attached.

Two modes, one result shape:
  * in-process  — when `import bpy` works (bpy wheel, or already inside
    Blender). Used by tests and by the live-session frontend.
  * subprocess  — spawns `$BLENDER --background` for isolation. Used by
    the headless frontend when a full Blender install is present.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import traceback as traceback_module
from dataclasses import dataclass, field
from pathlib import Path

from blended.drift.catalog import DriftEntry, match_traceback

BLENDER_BINARY_ENVIRONMENT_VARIABLE = "BLENDER"
SUBPROCESS_TIMEOUT_SECONDS = 240  # 3DCodeBench's per-script wall clock


@dataclass(frozen=True)
class RunResult:
    ok: bool
    duration_s: float
    blender_version: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback_text: str = ""
    matched_drift: tuple[DriftEntry, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        if self.ok:
            return f"ok in {self.duration_s:.2f}s (Blender {self.blender_version})"
        drift_notes = "".join(
            f"\n  drift[{entry.symbol}]: {entry.fix}"
            for entry in self.matched_drift
        )
        return (
            f"FAILED in {self.duration_s:.2f}s: {self.error_type}: "
            f"{self.error_message}{drift_notes}"
        )


def run_source_in_process(source_code: str, script_name: str = "<agent>") -> RunResult:
    """Execute Python source against the current bpy, capturing failure."""
    import bpy

    started_at = time.perf_counter()
    execution_namespace: dict = {"__name__": "__main__"}
    try:
        compiled = compile(source_code, script_name, "exec")
        exec(compiled, execution_namespace)  # noqa: S102 - this is the harness's job
    except Exception as error:  # noqa: BLE001 - we report, not swallow
        traceback_text = traceback_module.format_exc()
        return RunResult(
            ok=False,
            duration_s=time.perf_counter() - started_at,
            blender_version=bpy.app.version_string,
            error_type=type(error).__name__,
            error_message=str(error),
            traceback_text=traceback_text,
            matched_drift=tuple(match_traceback(traceback_text)),
        )
    return RunResult(
        ok=True,
        duration_s=time.perf_counter() - started_at,
        blender_version=bpy.app.version_string,
    )


def run_script_subprocess(
    script_path: Path,
    blender_binary: str | None = None,
) -> RunResult:
    """Execute a script file in a fresh `blender --background` process."""
    resolved_binary = blender_binary or os.environ.get(
        BLENDER_BINARY_ENVIRONMENT_VARIABLE
    )
    if not resolved_binary:
        raise RuntimeError(
            f"No Blender binary: pass blender_binary or set "
            f"${BLENDER_BINARY_ENVIRONMENT_VARIABLE}."
        )
    bootstrap_path = Path(__file__).with_name("_bootstrap.py")

    started_at = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="blended_run_") as scratch_directory:
        result_path = Path(scratch_directory) / "result.json"
        subprocess.run(
            [
                resolved_binary,
                "--background",
                "--factory-startup",
                "--python",
                str(bootstrap_path),
                "--",
                str(script_path),
                str(result_path),
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
        duration_s = time.perf_counter() - started_at
        if not result_path.exists():
            return RunResult(
                ok=False,
                duration_s=duration_s,
                error_type="HarnessError",
                error_message="Blender exited without writing a result file.",
            )
        result_payload = json.loads(result_path.read_text())

    traceback_text = result_payload.get("traceback_text", "")
    return RunResult(
        ok=result_payload["ok"],
        duration_s=duration_s,
        blender_version=result_payload.get("blender_version", ""),
        error_type=result_payload.get("error_type", ""),
        error_message=result_payload.get("error_message", ""),
        traceback_text=traceback_text,
        matched_drift=tuple(match_traceback(traceback_text)),
    )
