"""Evaluate many chunks in ONE Blender process.

Booting Blender-as-module and resetting the scene costs seconds; doing
it per chunk dominates wall clock when iterating on several candidates
(measured during development: a dozen cold starts ran to minutes of
pure overhead). `bpy` is already persistent within a process — what was
missing was a runner that reuses it.

Each chunk gets a factory-reset scene so results stay independent; the
process, the loaded modules, and the render engine setup are shared.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from blended.harness import HarnessResult, HarnessSettings


@dataclass(frozen=True)
class BatchItem:
    label: str
    source_code: str
    object_name: str


def run_batch(
    items: list[BatchItem],
    settings: HarnessSettings | None = None,
) -> dict[str, HarnessResult]:
    """Run every item through the harness, reusing one Blender process.

    Returns {label: HarnessResult}. A chunk that fails does not stop the
    rest — the whole batch is always evaluated so one review pass covers
    every candidate.
    """
    import bpy

    from blended.harness import run_chunk

    base_settings = settings or HarnessSettings()
    results: dict[str, HarnessResult] = {}
    for item in items:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        item_settings = HarnessSettings(
            budget=base_settings.budget,
            output_directory=Path(base_settings.output_directory) / item.label,
            maximum_retries=base_settings.maximum_retries,
            export_glb_path=base_settings.export_glb_path,
            session_log_path=base_settings.session_log_path,
        )
        results[item.label] = run_chunk(
            item.source_code,
            object_name=item.object_name,
            settings=item_settings,
            chunk_label=item.label,
        )
    return results
