"""The addon must actually load and register inside Blender.

A syntax or registration error here means NOTHING appears in Blender's
UI — no panel, no preferences — which is indistinguishable from "the
user is looking in the wrong place". Caught exactly that: a duplicate
`description=` keyword that `ast.parse` accepts and `compile` rejects.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

ADDON_PATH = Path(__file__).resolve().parents[2] / "blender_addon" / "__init__.py"


def test_addon_source_compiles():
    """compile() catches duplicate keywords that ast.parse() does not."""
    compile(ADDON_PATH.read_text(), str(ADDON_PATH), "exec")


def _load_addon(module_name="blended_agent_under_test"):
    spec = importlib.util.spec_from_file_location(module_name, ADDON_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_addon_registers_and_unregisters_cleanly():
    module = _load_addon()
    try:
        module.register()
    except Exception as registration_error:  # noqa: BLE001
        pytest.fail(f"register() raised: {registration_error}")
    try:
        assert hasattr(bpy.types.Scene, "blended_chat")
        registered_names = {cls.__name__ for cls in module._CLASSES}
        assert "BLENDED_PT_chat" in registered_names
        assert "BLENDED_Preferences" in registered_names
        assert "BLENDED_OT_reload" in registered_names
    finally:
        module.unregister()
    assert not hasattr(bpy.types.Scene, "blended_chat")


def test_preferences_expose_the_developer_controls():
    """The settings the docs tell users to look for must exist."""
    module = _load_addon("blended_agent_prefs_test")
    annotations = module.BLENDED_Preferences.__annotations__
    for expected in (
        "developer_mode",
        "auto_reload",
        "repository_path",
        "model_name",
        "vision_model_name",
    ):
        assert expected in annotations, f"missing preference: {expected}"


def test_panel_and_operators_have_required_blender_identifiers():
    module = _load_addon("blended_agent_ids_test")
    assert module.BLENDED_PT_chat.bl_category == "blended"
    assert module.BLENDED_PT_chat.bl_space_type == "VIEW_3D"
    assert module.BLENDED_PT_chat.bl_region_type == "UI"
    for operator_class in (
        module.BLENDED_OT_send,
        module.BLENDED_OT_reset,
        module.BLENDED_OT_reload,
        module.BLENDED_OT_test_connection,
    ):
        assert operator_class.bl_idname.startswith("blended.")
