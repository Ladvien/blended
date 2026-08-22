"""The panel must actually RENDER, not merely register.

Blender calls draw() whenever the panel is visible and silently abandons
the rest of the panel if it raises — you get a half-drawn UI and no
error dialog. Registration passing tells you nothing about this.

Caught exactly that: draw() imported `blended.agent.wrapping`, but on a
fresh install nothing had put the library on sys.path yet, so the panel
rendered its first label and stopped. The user saw only "Ask for an
asset to get started."
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

ADDON_PATH = Path(__file__).resolve().parents[2] / "blender_addon" / "__init__.py"


class RecordingLayout:
    """Stands in for UILayout, recording what the panel emits."""

    def __init__(self, emitted):
        self.emitted = emitted
        self.scale_y = 1.0
        self.enabled = True

    def row(self, **kwargs):
        return RecordingLayout(self.emitted)

    def column(self, **kwargs):
        return RecordingLayout(self.emitted)

    def box(self):
        return RecordingLayout(self.emitted)

    def label(self, **kwargs):
        self.emitted.append(("label", kwargs.get("text", "")))

    def prop(self, data, name, **kwargs):
        getattr(data, name)  # a missing property must fail loudly here
        self.emitted.append(("prop", name))

    def operator(self, idname, **kwargs):
        self.emitted.append(("operator", idname))

    def separator(self):
        self.emitted.append(("separator", ""))


class _ChatProperties:
    prompt = ""
    visible_messages = 24
    show_tool_detail = False
    show_settings = False


class _Preferences:
    model_name = "deepseek-v4-flash:cloud"
    vision_model_name = "minimax-m3:cloud"
    developer_mode = False
    auto_reload = True
    repository_path = ""
    log_directory = ""
    send_on_enter = True
    log_chat = True
    endpoint = "http://localhost:11434"
    api_key = ""


def _make_context(module_name, region_width=400, developer_mode=False):
    preferences = _Preferences()
    preferences.developer_mode = developer_mode

    context = types.SimpleNamespace()
    context.scene = types.SimpleNamespace(blended_chat=_ChatProperties())
    context.region = types.SimpleNamespace(width=region_width)
    context.preferences = types.SimpleNamespace(
        system=types.SimpleNamespace(ui_scale=1.0),
        addons={module_name: types.SimpleNamespace(preferences=preferences)},
    )
    return context


def _load_addon(module_name):
    spec = importlib.util.spec_from_file_location(module_name, ADDON_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _draw(module, context):
    emitted = []
    panel = types.SimpleNamespace(layout=RecordingLayout(emitted))
    panel._draw_message = types.MethodType(module.BLENDED_PT_chat._draw_message, panel)
    module.BLENDED_PT_chat.draw(panel, context)
    return emitted


def test_empty_panel_still_draws_every_control():
    """The failure mode: only the empty-state label rendered."""
    module = _load_addon("blended_draw_empty")
    module._STATE.transcript = []
    emitted = _draw(module, _make_context("blended_draw_empty"))

    operators = {name for kind, name in emitted if kind == "operator"}
    assert "blended.send_message" in operators, "Send button never rendered"
    assert "blended.open_transcript" in operators
    assert "blended.reset_session" in operators
    properties = {name for kind, name in emitted if kind == "prop"}
    assert "prompt" in properties, "message box never rendered"
    assert "show_settings" in properties


def test_draw_survives_the_library_being_unimportable():
    """draw() runs before anything puts `blended` on sys.path."""
    module = _load_addon("blended_draw_noimport")
    module._STATE.transcript = [("user", "make a crate " * 30)]

    purged = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "blended" or name.startswith("blended.")
    }
    saved_path = list(sys.path)
    try:
        sys.path[:] = [
            p for p in sys.path if "blended-skel/src" not in p.replace("\\\\", "/")
        ]
        emitted = _draw(module, _make_context("blended_draw_noimport"))
    finally:
        sys.path[:] = saved_path
        sys.modules.update(purged)

    operators = {name for kind, name in emitted if kind == "operator"}
    assert "blended.send_message" in operators, (
        "draw() aborted when the library was unimportable — the exact bug "
        "that left users with a one-line panel"
    )


def test_draw_renders_a_conversation():
    module = _load_addon("blended_draw_convo")
    module._STATE.transcript = [
        ("user", "Build a crate"),
        ("tool", "run_python({...})"),
        ("result", "GATE: PASS"),
        ("answer", "Built it — 108 triangles, one component."),
    ]
    emitted = _draw(module, _make_context("blended_draw_convo"))
    labels = " ".join(text for kind, text in emitted if kind == "label")
    assert "Build a crate" in labels
    assert "108 triangles" in labels


def test_draw_works_at_every_sidebar_width_and_in_developer_mode():
    module = _load_addon("blended_draw_widths")
    module._STATE.transcript = [("answer", "A sentence long enough to wrap. " * 8)]
    for width in (180, 240, 400, 900):
        emitted = _draw(
            module, _make_context("blended_draw_widths", region_width=width)
        )
        assert any(kind == "operator" for kind, _ in emitted)

    context = _make_context("blended_draw_widths", developer_mode=True)
    context.scene.blended_chat.show_settings = True
    emitted = _draw(module, context)
    operators = {name for kind, name in emitted if kind == "operator"}
    assert "blended.reload_library" in operators
    assert "blended.test_connection" in operators
