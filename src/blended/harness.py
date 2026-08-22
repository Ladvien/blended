"""The harness entry point: the whole loop in one call.

    execute (retry <= 2, logged) -> analyzer gate -> contact sheet
        -> (optional) verified glTF export

Two front doors, one spine:

* run_chunk(source, ...)  — the AGENT path: source code in, structured
  result out. The fix_source callback is where the agent rewrites code
  from the drift-annotated retry prompt.
* run_builder(builder, ...) — the LIBRARY path: a Parameters+Builder
  object in, same gates, same result.

Design commitments enforced here rather than re-argued per call site:
the analyzer is the hard gate; the contact sheet is produced on FAIL
as well as PASS (a failure you cannot review is a failure you will
repeat); export only runs on gate-passing meshes and is itself
verified by welded round trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from blended.analyze.mesh_checks import MeshBudget, MeshReport

DEFAULT_OUTPUT_DIRECTORY = Path("_renders/harness")


@dataclass(frozen=True)
class HarnessSettings:
    budget: MeshBudget = MeshBudget()
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY
    maximum_retries: int = 2
    export_glb_path: Path | None = None  # set to also export + round-trip
    session_log_path: Path | None = None


@dataclass(frozen=True)
class HarnessResult:
    ok: bool
    stage_reached: str  # "execute" | "locate" | "gate" | "export" | "done"
    object_name: str = ""
    report: MeshReport | None = None
    gate_failures: tuple[str, ...] = field(default_factory=tuple)
    contact_sheet_path: Path | None = None
    export_failures: tuple[str, ...] = field(default_factory=tuple)
    export_path: Path | None = None
    export_file_size_bytes: int = 0
    execution_summary: str = ""

    def summary(self) -> str:
        verdict = "OK" if self.ok else f"FAILED at {self.stage_reached}"
        lines = [f"{verdict}: {self.object_name or '<no object>'}"]
        if self.execution_summary:
            lines.append(f"  execute: {self.execution_summary}")
        if self.report is not None:
            lines.append(
                f"  gate: {'PASS' if not self.gate_failures else 'FAIL'} "
                f"({self.report.triangle_count} tris, "
                f"{self.report.connected_component_count} components)"
            )
        lines.extend(f"    - {failure}" for failure in self.gate_failures)
        lines.extend(f"  export: {failure}" for failure in self.export_failures)
        if self.export_path is not None and not self.export_failures:
            lines.append(
                f"  export: verified round-trip "
                f"({self.export_path}, {self.export_file_size_bytes} bytes)"
            )
        if self.contact_sheet_path is not None:
            lines.append(f"  sheet: {self.contact_sheet_path}")
        return "\n".join(lines)


def _gate_capture_export(
    blender_object, settings: HarnessSettings, execution_summary: str
) -> HarnessResult:
    """The shared back half: analyze, sheet, optionally export."""
    from blended.analyze import analyze_object
    from blended.capture import capture_contact_sheet

    report = analyze_object(blender_object)
    gate_failures = tuple(report.failures(settings.budget))
    contact_sheet_path = capture_contact_sheet(
        blender_object,
        settings.output_directory,
        report=report,
        budget=settings.budget,
    )
    if gate_failures:
        return HarnessResult(
            ok=False,
            stage_reached="gate",
            object_name=blender_object.name,
            report=report,
            gate_failures=gate_failures,
            contact_sheet_path=contact_sheet_path,
            execution_summary=execution_summary,
        )

    export_path: Path | None = None
    export_file_size_bytes = 0
    if settings.export_glb_path is not None:
        from blended.export import export_glb

        export_report = export_glb(blender_object, settings.export_glb_path)
        export_failures = tuple(export_report.round_trip_failures(settings.budget))
        export_path = export_report.export_path
        export_file_size_bytes = export_report.file_size_bytes
        if export_failures:
            return HarnessResult(
                ok=False,
                stage_reached="export",
                object_name=blender_object.name,
                report=report,
                contact_sheet_path=contact_sheet_path,
                export_failures=export_failures,
                execution_summary=execution_summary,
            )

    return HarnessResult(
        ok=True,
        stage_reached="done",
        object_name=blender_object.name,
        report=report,
        contact_sheet_path=contact_sheet_path,
        export_path=export_path,
        export_file_size_bytes=export_file_size_bytes,
        execution_summary=execution_summary,
    )


def run_chunk(
    source_code: str,
    object_name: str,
    fix_source=None,
    settings: HarnessSettings = HarnessSettings(),
    chunk_label: str = "<agent>",
) -> HarnessResult:
    """The agent path: execute source, then gate the named object."""
    import bpy

    from blended.run.retry import run_with_retries
    from blended.run.session_log import SessionLog

    session_log = (
        SessionLog(settings.session_log_path)
        if settings.session_log_path is not None
        else None
    )
    if fix_source is None:
        maximum_retries = 0

        def fix_source(previous_source, result):  # pragma: no cover
            return previous_source
    else:
        maximum_retries = settings.maximum_retries

    outcome = run_with_retries(
        source_code,
        fix_source,
        maximum_retries=maximum_retries,
        script_name=chunk_label,
        session_log=session_log,
    )
    execution_summary = (
        f"{outcome.attempt_count} attempt(s), {outcome.final_result.summary()}"
    )
    if not outcome.ok:
        return HarnessResult(
            ok=False, stage_reached="execute", execution_summary=execution_summary
        )

    built_object = bpy.data.objects.get(object_name)
    if built_object is None:
        return HarnessResult(
            ok=False,
            stage_reached="locate",
            object_name=object_name,
            execution_summary=execution_summary
            + f"; expected object {object_name!r} not found in scene",
        )
    return _gate_capture_export(built_object, settings, execution_summary)


def run_builder(
    builder, settings: HarnessSettings = HarnessSettings()
) -> HarnessResult:
    """The library path: build via a Parameters+Builder object, then gate."""
    try:
        built_object = builder.build()
    except Exception as build_error:  # noqa: BLE001 — reported, not swallowed
        import traceback

        return HarnessResult(
            ok=False,
            stage_reached="execute",
            execution_summary=(
                f"builder raised {type(build_error).__name__}: {build_error}\n"
                f"{traceback.format_exc()}"
            ),
        )
    return _gate_capture_export(built_object, settings, execution_summary="builder ok")
