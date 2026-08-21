"""Pure layer: the logger needs no bpy."""

from blended.drift.catalog import DRIFT_ENTRIES
from blended.run.executor import RunResult
from blended.run.session_log import SessionLog


def _failed_result() -> RunResult:
    entry = next(
        catalog_entry
        for catalog_entry in DRIFT_ENTRIES
        if "use_auto_smooth" in catalog_entry.symbol
    )
    return RunResult(
        ok=False,
        duration_s=0.5,
        blender_version="5.0.1",
        error_type="AttributeError",
        error_message="no attribute 'use_auto_smooth'",
        traceback_text="...",
        matched_drift=(entry,),
    )


def test_records_append_and_read_back(tmp_path):
    session_log = SessionLog(tmp_path / "session.jsonl")
    session_log.record_attempt("crate", "print(1)", _failed_result(), 0)
    session_log.record_attempt(
        "crate", "print(2)", RunResult(ok=True, duration_s=0.1), 1
    )

    records = session_log.read_records()
    assert len(records) == 2
    assert records[0]["ok"] is False
    assert records[0]["matched_drift"] == ["bpy.types.Mesh.use_auto_smooth"]
    assert records[1]["ok"] is True
    assert records[1]["attempt_index"] == 1
    # Different sources hash differently — the log can distinguish chunks.
    assert records[0]["source_sha256"] != records[1]["source_sha256"]


def test_read_on_missing_file_is_empty(tmp_path):
    assert SessionLog(tmp_path / "absent.jsonl").read_records() == []
