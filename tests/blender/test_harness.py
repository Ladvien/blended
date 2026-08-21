"""The one-call loop, both front doors."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")
pytest.importorskip("PIL.Image", reason="contact sheets require Pillow")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_run_builder_full_loop_with_export(empty_scene, tmp_path):
    from blended.builders import PalletBuilder, PalletParameters
    from blended.harness import HarnessSettings, run_builder

    result = run_builder(
        PalletBuilder(PalletParameters()),
        HarnessSettings(
            output_directory=tmp_path,
            export_glb_path=tmp_path / "pallet.glb",
        ),
    )
    assert result.ok, result.summary()
    assert result.stage_reached == "done"
    assert result.contact_sheet_path.exists()
    assert (tmp_path / "pallet.glb").exists()
    assert result.export_failures == ()


def test_run_chunk_retries_and_logs(empty_scene, tmp_path):
    import json

    from blended.harness import HarnessSettings, run_chunk
    from tests.blender.test_retry import (
        BROKEN_SMOOTH_CRATE_SOURCE,
        FIXED_SMOOTH_CRATE_SOURCE,
    )

    log_path = tmp_path / "session.jsonl"
    result = run_chunk(
        BROKEN_SMOOTH_CRATE_SOURCE,
        object_name="RetryCrate",
        fix_source=lambda source, run_result: FIXED_SMOOTH_CRATE_SOURCE,
        settings=HarnessSettings(
            output_directory=tmp_path, session_log_path=log_path
        ),
        chunk_label="retry_crate",
    )
    assert result.ok, result.summary()
    assert "2 attempt(s)" in result.execution_summary
    log_records = [
        json.loads(line) for line in log_path.read_text().splitlines()
    ]
    assert len(log_records) == 2
    assert log_records[0]["ok"] is False and log_records[1]["ok"] is True


def test_gate_failure_still_produces_review_sheet(empty_scene, tmp_path):
    from blended.harness import HarnessSettings, run_chunk

    OPEN_BOX_SOURCE = """
import sys
sys.path.insert(0, "src")
import bmesh
import bpy
from blended.ops import add_box, link_into_scene

open_box = add_box("OpenChunk", 1.0, 1.0, 1.0)
link_into_scene(open_box)
working = bmesh.new(); working.from_mesh(open_box.data)
working.faces.ensure_lookup_table(); working.faces.remove(working.faces[0])
working.to_mesh(open_box.data); working.free()
"""
    result = run_chunk(
        OPEN_BOX_SOURCE,
        object_name="OpenChunk",
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert not result.ok
    assert result.stage_reached == "gate"
    assert result.gate_failures
    assert result.contact_sheet_path.exists()  # failures are reviewable


def test_missing_object_is_a_distinct_failure(empty_scene, tmp_path):
    from blended.harness import HarnessSettings, run_chunk

    result = run_chunk(
        "x = 1",
        object_name="NeverBuilt",
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert not result.ok
    assert result.stage_reached == "locate"
    assert "not found" in result.execution_summary
