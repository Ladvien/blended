"""Build the crate, gate it, and render the four inspection views.

Run from the repo root with any Python that can `import bpy`:
    python examples/build_crate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import bpy  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)

from blended.analyze import MeshBudget, analyze_object  # noqa: E402
from blended.builders import CrateBuilder, CrateParameters  # noqa: E402
from blended.capture import capture_views  # noqa: E402
from blended.version import assert_supported_blender  # noqa: E402

assert_supported_blender()
crate_object = CrateBuilder(CrateParameters()).build()
report = analyze_object(crate_object)
failures = report.failures(MeshBudget())
print(report)
if failures:
    raise SystemExit(f"GATE FAILED: {failures}")
captured = capture_views(crate_object, Path("_renders/crate_example"))
print("GATE PASSED. Views:", ", ".join(str(path) for path in captured.values()))
