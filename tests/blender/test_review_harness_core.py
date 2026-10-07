"""Regression tests for the harness_core review (2026-10-07). Needs bpy."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

BOX_SOURCE_TEMPLATE = """
import sys
sys.path.insert(0, "src")
from blended.ops import add_box, link_into_scene

link_into_scene(add_box("{name}", 1.0, 1.0, 1.0))
"""


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_batch_exports_one_file_per_item(empty_scene, tmp_path):
    from blended.harness import HarnessSettings
    from blended.run.batch import BatchItem, run_batch

    items = [
        BatchItem(label=name, source_code=BOX_SOURCE_TEMPLATE.format(name=name), object_name=name)
        for name in ("BoxA", "BoxB")
    ]
    results = run_batch(
        items,
        HarnessSettings(output_directory=tmp_path, export_glb_path=tmp_path / "out.glb"),
    )
    assert all(result.ok for result in results.values()), [r.summary() for r in results.values()]
    export_paths = {label: result.export_path for label, result in results.items()}
    assert len(set(export_paths.values())) == len(items), export_paths
    assert all(path.exists() for path in export_paths.values())


def test_batch_refuses_duplicate_labels(empty_scene, tmp_path):
    from blended.harness import HarnessSettings
    from blended.run.batch import BatchItem, run_batch

    item = BatchItem(label="same", source_code="pass", object_name="Nothing")
    with pytest.raises(ValueError, match="unique"):
        run_batch([item, item], HarnessSettings(output_directory=tmp_path))


def test_chunk_calling_sys_exit_is_reported_in_process(empty_scene):
    from blended.run.executor import run_source_in_process

    result = run_source_in_process("import sys\nsys.exit(3)")
    assert not result.ok
    assert result.error_type == "SystemExit"
