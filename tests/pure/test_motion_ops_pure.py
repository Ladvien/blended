"""OT-51: what the motion ops promise without Blender or numpy.

The numerics sit in skinclip, which imports numpy; blended puts its venv
ahead of Blender's own site-packages, so a numpy wheel in the venv would
shadow Blender's. The facade, the MCP server and this layer therefore
must import the ops with numpy absent: skinclip is imported inside op
bodies only.
"""

import subprocess
import sys

import pytest
from skinclip.spec import RingSkirtSpec

import blended.ops as ops_facade
from blended.manifest import OP_CONFIG_DATACLASSES, OP_MODULE_NAMES
from blended.ops._contract import changes_scene, is_gated, is_reads_only
from blended.ops.motion import (
    MINIMUM_SKIRT_CHAIN_COUNT,
    ArmatureRotationModeError,
    _require_valid_spec,
)

MOTION_READERS = ("body_capsules_report", "clip_self_intersection_report")
MOTION_WRITERS = ("bake_cloth_chains", "repair_limb_penetration")

BLOCKED_IMPORT_PROGRAM = """
import sys
sys.modules["numpy"] = None   # an import of numpy now raises ImportError
import blended.ops, blended.manifest
from blended.manifest import build_manifest
build_manifest()
import blended.ops.motion
import skinclip.spec
assert blended.ops.RingSkirtSpec is skinclip.spec.RingSkirtSpec
print("IMPORTED", len(blended.ops.__all__))
"""


def test_the_ops_import_with_numpy_unavailable():
    result = subprocess.run(
        [sys.executable, "-c", BLOCKED_IMPORT_PROGRAM],
        capture_output=True,
        text=True,
        check=False,
        env={"BLENDED_DISABLE_PLUGINS": "1", "PATH": ""},
    )

    assert result.returncode == 0, result.stderr
    assert "IMPORTED" in result.stdout


def test_the_readers_are_plan_free_and_the_writers_are_not():
    for name in MOTION_READERS:
        assert is_reads_only(getattr(ops_facade, name)), name
    for name in MOTION_WRITERS:
        function = getattr(ops_facade, name)
        assert changes_scene(function), name
        assert not is_gated(function), f"{name} returns a report, not an object name"


def test_the_module_is_in_the_manifest_and_its_config_object_is_documented():
    assert "motion" in OP_MODULE_NAMES
    assert ("blended.ops.motion", "RingSkirtSpec") in OP_CONFIG_DATACLASSES


def test_the_rotation_mode_error_is_a_value_error_on_the_facade():
    assert ops_facade.ArmatureRotationModeError is ArmatureRotationModeError
    assert issubclass(ArmatureRotationModeError, ValueError)


GOOD_SPEC = {
    "top_height_m": 0.9,
    "knee_height_m": 0.55,
    "hem_height_m": 0.2,
    "blend_height_m": 1.0,
    "inset_m": 0.0,
}


def test_the_facade_exports_skinclips_own_ring_skirt_spec():
    """One class: the schema the model reads is built from skinclip's dataclass, not a copy."""
    assert ops_facade.RingSkirtSpec is RingSkirtSpec
    spec = RingSkirtSpec(**GOOD_SPEC)
    assert spec.count == 12
    assert spec.prefix == "skirt_"
    with pytest.raises(TypeError):
        RingSkirtSpec(12, 0.9, 0.55, 0.2, 1.0, 0.0)  # type: ignore[misc]
    _require_valid_spec(spec)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"count": MINIMUM_SKIRT_CHAIN_COUNT - 1}, "at least"),
        ({"knee_height_m": 0.95}, "hem < knee < top < blend"),
        ({"hem_height_m": 0.55}, "hem < knee < top < blend"),
        ({"blend_height_m": 0.9}, "hem < knee < top < blend"),
        ({"prefix": ""}, "prefix"),
    ],
)
def test_a_ring_skirt_spec_that_would_divide_by_zero_is_refused_before_anything_is_read(
    override, message
):
    """skinclip divides by top - knee and blend - top; blended refuses the equal-height cases up front."""
    with pytest.raises(ValueError, match=message):
        _require_valid_spec(RingSkirtSpec(**{**GOOD_SPEC, **override}))
