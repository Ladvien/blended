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
        self._alert = False

    @property
    def alert(self):
        return self._alert

    @alert.setter
    def alert(self, value):
        self._alert = value
        self.emitted.append(("alert", value, None))

    def row(self, **kwargs):
        return RecordingLayout(self.emitted)

    def column(self, **kwargs):
        return RecordingLayout(self.emitted)

    def box(self):
        return RecordingLayout(self.emitted)

    def label(self, **kwargs):
        self.emitted.append(("label", kwargs.get("text", ""), None))

    def prop(self, data, name, **kwargs):
        getattr(data, name)  # a missing property must fail loudly here
        self.emitted.append(("prop", name, None))

    def operator(self, idname, **kwargs):
        handle = types.SimpleNamespace()
        self.emitted.append(("operator", idname, handle))
        return handle

    def textbox(self, data, name, **kwargs):
        getattr(data, name)
        self.emitted.append(("textbox", name, None))

    def separator(self):
        self.emitted.append(("separator", "", None))


class _ChatProperties:
    prompt = ""
    visible_messages = 24
    show_settings = False


class _Preferences:
    model_name = "deepseek-v4-flash:cloud"
    vision_model_name = "kimi-k2.7-code:cloud"
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

    operators = {name for kind, name, _ in emitted if kind == "operator"}
    assert "blended.send_message" in operators, "Send button never rendered"
    assert "blended.open_transcript" in operators
    assert "blended.reset_session" in operators
    textboxes = {name for kind, name, _ in emitted if kind == "textbox"}
    assert "prompt" in textboxes, "multiline message box never rendered"
    properties = {name for kind, name, _ in emitted if kind == "prop"}
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

    operators = {name for kind, name, _ in emitted if kind == "operator"}
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
    labels = " ".join(text for kind, text, _ in emitted if kind == "label")
    assert "Build a crate" in labels
    assert "108 triangles" in labels


def test_copy_buttons_address_the_transcript_not_the_visible_slice():
    """The copy operators index _STATE.transcript, so the buttons must
    receive ABSOLUTE indices — with more events than visible_messages
    the visible slice starts mid-transcript and slice positions would
    copy the wrong message."""
    module = _load_addon("blended_draw_copy")
    module._STATE.transcript = [("user", f"old message {i}") for i in range(8)] + [
        ("tool", "run_python("),
        ("result", "GATE: PASS"),
        ("answer", "the recent visible"),
    ]
    context = _make_context("blended_draw_copy")
    context.scene.blended_chat.visible_messages = 4
    emitted = _draw(module, context)

    message_indices = [
        handle.index
        for kind, name, handle in emitted
        if kind == "operator" and name == "blended.copy_message"
    ]
def test_tool_events_draw_as_their_own_entries_newest_first():
    """Each tool call/result is its own log entry — no merged traffic
    row — and the log tails NEWEST FIRST, so the latest message sits
    directly under the controls and is visible without scrolling."""
    module = _load_addon("blended_draw_tail")
    module._STATE.transcript = [
        ("user", "Build a crate"),
        ("tool", "run_python({...})"),
        ("result", "GATE: PASS"),
        ("answer", "Built it."),
    ]
    emitted = _draw(module, _make_context("blended_draw_tail"))
    message_indices = [
        handle.index
        for kind, name, handle in emitted
        if kind == "operator" and name == "blended.copy_message"
    ]
    assert message_indices == [0, 1, 2, 3], (
        "oldest-first chat view must give one entry per event: "
        f"{message_indices}"
    )
    labels = " ".join(text for kind, text, _ in emitted if kind == "label")
    assert "Tool call" in labels
    assert "Tool result" in labels
    assert "GATE: PASS" in labels


def test_composer_sits_after_the_conversation():
    """The send box must render BELOW the whole history: scrolling to
    the bottom lands on the newest message with the input right beneath
    it. A composer above the log forces constant scrolling (regression:
    the layout was temporarily inverted to 'solve' auto-scroll)."""
    module = _load_addon("blended_draw_composer_below")
    module._STATE.transcript = [
        ("user", "Build a crate"),
        ("answer", "Built it."),
    ]
    emitted = _draw(module, _make_context("blended_draw_composer_below"))
    labels = [text for kind, text, _ in emitted if kind == "label"]
    if "You" not in labels:
        pytest.fail("conversation never rendered")
    composer_hint = (
        "Enter sends · Ctrl+Enter sends from the viewport"
    )
    assert composer_hint in labels
    assert labels.index(composer_hint) > labels.index("You"), (
        "composer rendered above the conversation"
    )


def test_status_text_and_event_count_are_short_own_lines():
    """'Working… — 10 events so far' on one row was cut mid-sentence in
    a narrow sidebar. The status text and the count must each sit on
    their own short line so neither can truncate."""
    module = _load_addon("blended_draw_status")
    module._STATE.transcript = [("answer", "ok")]
    module._STATE.busy = True
    emitted = _draw(module, _make_context("blended_draw_status", region_width=180))
    labels = [text for kind, text, _ in emitted if kind == "label"]
    assert "Working…" in labels
    assert "1 events so far" in labels
    assert not any(text.startswith("Working… —") for text in labels)


def test_tool_call_renders_escaped_newlines_as_lines():
    """The worker logs tool calls as raw JSON strings, so the panel
    showed literal backslash-n escapes as one wall of text. The display
    must decode them; the copy button keeps the raw text."""
    module = _load_addon("blended_draw_newlines")
    raw = 'run_python({"source": "\\nimport bpy\\nprint(math)\\n"})'
    module._STATE.transcript = [("tool", raw)]
    emitted = _draw(module, _make_context("blended_draw_newlines"))
    labels = [text for kind, text, _ in emitted if kind == "label"]
    assert any("import bpy" in text for text in labels), (
        "escaped newlines were not decoded for display"
    )


def test_error_bubbles_use_the_alert_tint():
    """Errors must read at a glance — the alert tint is the one
    per-widget emphasis Blender exposes."""
    module = _load_addon("blended_draw_alert")
    module._STATE.transcript = [("error", "boom")]
    emitted = _draw(module, _make_context("blended_draw_alert"))
    alerts = [value for kind, value, _ in emitted if kind == "alert"]
    assert any(alerts), "error bubble must set the alert tint"
