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

    def __init__(self, emitted, panels_open=True):
        self.emitted = emitted
        self.scale_y = 1.0
        self.active = True
        self.panels_open = panels_open
        self._alert = False
        self._enabled = True

    @property
    def alert(self):
        return self._alert

    @alert.setter
    def alert(self, value):
        self._alert = value
        self.emitted.append(("alert", value, None))

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = value
        self.emitted.append(("enabled", value, None))

    def _child(self):
        return RecordingLayout(self.emitted, panels_open=self.panels_open)

    def row(self, **kwargs):
        return self._child()

    def column(self, **kwargs):
        return self._child()

    def box(self):
        return self._child()

    def panel(self, idname, default_closed=False):
        """Blender's own disclosure widget: (header, body), body None
        when collapsed. `panels_open` drives which case a test sees —
        real Blender remembers the state per idname, so both have to
        draw correctly."""
        self.emitted.append(("panel", idname, default_closed))
        header = self._child()
        if not self.panels_open:
            return header, None
        return header, self._child()

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

    def progress(self, **kwargs):
        self.emitted.append(("progress", kwargs.get("text", ""), kwargs.get("factor")))

    def template_icon(self, **kwargs):
        self.emitted.append(("template_icon", kwargs.get("icon_value", 0), None))

    def separator(self):
        self.emitted.append(("separator", "", None))


class _ChatProperties:
    prompt = ""
    reference_image = ""
    visible_messages = 24
    show_settings = False
    show_details = False


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


def _make_context(
    module_name, region_width=400, developer_mode=False, region_height=1104
):
    preferences = _Preferences()
    preferences.developer_mode = developer_mode

    context = types.SimpleNamespace()
    context.scene = types.SimpleNamespace(blended_chat=_ChatProperties())
    # A real sidebar measured 561 x 1104 px at ui_scale 2.0 — 27 rows.
    # The stub uses ui_scale 1.0, so 1104 px is 55 rows unless a test
    # says otherwise.
    context.region = types.SimpleNamespace(width=region_width, height=region_height)
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


def _draw(module, context, panels_open=True, panel=None):
    """Draw one panel into a recording layout.

    The stub INHERITS the addon's `_ChatDrawing` mixin, which is how
    both real panels get their drawing — so a helper added to the mixin
    is exercised here without touching this harness.
    """
    emitted = []
    stub_class = type("_PanelStub", (module._ChatDrawing,), {})
    stub = stub_class()
    stub.layout = RecordingLayout(emitted, panels_open=panels_open)
    (panel or module.BLENDED_PT_chat).draw(stub, context)
    return emitted


def _draw_all(module, context, panels_open=True):
    """Both panels, in the order Blender draws them (`bl_order`)."""
    return _draw(module, context, panels_open) + _draw(
        module, context, panels_open, module.BLENDED_PT_history
    )

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
    emitted = _draw_all(module, _make_context("blended_draw_convo"))
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
    emitted = _draw(module, context, panel=module.BLENDED_PT_history)

    message_indices = [
        handle.index
        for kind, name, handle in emitted
        if kind == "operator" and name == "blended.copy_message"
    ]
    assert message_indices == [7, 8, 9, 10], (
        "the copy buttons must carry absolute transcript indices, not "
        "positions inside the visible slice"
    )


def test_every_traffic_event_is_its_own_collapsible_panel():
    """Ten tool/result/thinking events drawn in full pushed the answer
    and the composer off the bottom of the sidebar (screenshot,
    2026-09-04). Each is now its own `layout.panel()`: the header names
    what happened, the body is one click away, and the answer is drawn
    whatever the traffic does."""
    module = _load_addon("blended_draw_tail")
    source = "import bpy\\nprint(1)\\nprint(2)"
    module._STATE.transcript = [
        ("user", "Build a crate"),
        ("thinking", "The user wants a crate.\nI will build it."),
        ("tool", f'run_python({{"source": "{source}", "object_name": "Crate"}})'),
        ("result", "OK: Crate\n  gate: PASS (12 tris)"),
        ("answer", "Built it."),
    ]
    context = _make_context("blended_draw_tail")

    collapsed = _draw_all(module, context, panels_open=False)
    labels = [text for kind, text, _ in collapsed if kind == "label"]
    panel_idnames = [name for kind, name, _ in collapsed if kind == "panel"]
    assert len(panel_idnames) == len(set(panel_idnames)) == 3, (
        "each traffic event needs its OWN disclosure state, so the "
        "idnames must be distinct: one per transcript index"
    )
    assert "run_python · Crate · 3 lines" in labels
    assert "OK: Crate" in labels
    assert "The user wants a crate." in labels
    assert "I will build it." not in labels, "a collapsed body must not draw"
    assert "Built it." in labels, "the answer must survive any amount of traffic"

    expanded = _draw_all(module, context, panels_open=True)
    labels = [text for kind, text, _ in expanded if kind == "label"]
    assert "I will build it." in labels, "a disclosed body must draw in full"


def test_the_details_switch_only_changes_what_opens_by_default():
    """`show_details` used to be the ONLY control: all bodies or none.
    It now sets the default state of newly drawn events, and Blender
    remembers each one the user touches."""
    module = _load_addon("blended_draw_default")
    module._STATE.transcript = [("tool", "run_python({})")]
    context = _make_context("blended_draw_default")

    closed_by_default = [
        value for kind, _, value in _draw_all(module, context) if kind == "panel"
    ]
    context.scene.blended_chat.show_details = True
    open_by_default = [
        value for kind, _, value in _draw_all(module, context) if kind == "panel"
    ]
    assert closed_by_default == [True]
    assert open_by_default == [False]


def test_a_failed_tool_result_is_tinted_even_when_collapsed():
    module = _load_addon("blended_draw_fail")
    module._STATE.transcript = [("result", "FAILED: NameError: name 'x' is not defined")]
    emitted = _draw_all(module, _make_context("blended_draw_fail"))
    assert any(value for kind, value, _ in emitted if kind == "alert"), (
        "a failed result must carry the alert tint"
    )


def test_the_working_surface_holds_the_prompt_and_no_reply_text():
    """The split that fixes the measured off-screen failure: the panel
    the user works on carries the prompt box, the status and the cards
    — all fixed height — and NO traffic and NO reply text, so it cannot
    be pushed out of view by a long turn. The record is a separate,
    closed-by-default panel below it, and the replies belong to the GPU
    overlay in the viewport, which now ships on.

    The assertions about the off-state hint row are DELETED rather than
    re-pointed: the row existed only while the overlay was switched off,
    and re-pinning them to the shipped text would pin the switch this
    change removed."""
    module = _load_addon("blended_draw_split")
    module._STATE.transcript = [
        ("user", "Build a crate"),
        ("tool", 'run_python({"source": "x"})'),
        ("result", "OK: Crate"),
        ("answer", "Built it."),
    ]
    pinned = _draw(module, _make_context("blended_draw_split"))

    labels = [text for kind, text, _ in pinned if kind == "label"]
    kinds = [kind for kind, _, _ in pinned]
    assert "textbox" in kinds
    assert "panel" not in kinds, (
        "traffic belongs to the record panel: anything that grows with "
        "the turn must not share a region with the prompt box"
    )
    assert "Built it." not in labels, (
        "replies render in the GPU overlay, not on the pinned surface: a "
        "reply drawn here moves the prompt box by its own length, which "
        "is exactly the defect the user reported (2026-09-06)"
    )
    assert "Ready" in labels, "the status line stays on the surface"

    assert module.BLENDED_PT_history.bl_order > module.BLENDED_PT_chat.bl_order
    assert "DEFAULT_CLOSED" in module.BLENDED_PT_history.bl_options


def test_status_names_the_running_tool_on_one_short_line():
    """'Working… — 10 events so far' on one row was cut mid-sentence in
    a narrow sidebar. The status is one short line, and while busy it
    says what the agent is doing rather than counting events."""
    module = _load_addon("blended_draw_status")
    module._STATE.transcript = [("user", "go"), ("tool", 'run_python({"source": "x"})')]
    module._STATE.busy = True
    emitted = _draw(module, _make_context("blended_draw_status", region_width=180))
    labels = [text for kind, text, _ in emitted if kind == "label"]
    assert "Running run_python…" in labels
    assert not any("events" in text for text in labels)
    module._STATE.live_kind, module._STATE.live_text = "content", "Buil"
    labels = [text for kind, text, _ in _draw(module, _make_context("blended_draw_status")) if kind == "label"]
    assert "Answering…" in labels


def test_tool_call_renders_escaped_newlines_as_lines():
    """The worker logs tool calls as raw JSON strings, so the panel
    showed literal backslash-n escapes as one wall of text. The display
    must decode them; the copy button keeps the raw text."""
    module = _load_addon("blended_draw_newlines")
    raw = 'run_python({"source": "\\nimport bpy\\nprint(math)\\n"})'
    module._STATE.transcript = [("tool", raw)]
    context = _make_context("blended_draw_newlines")
    context.scene.blended_chat.show_details = True
    emitted = _draw_all(module, context)
    labels = [text for kind, text, _ in emitted if kind == "label"]
    assert any("import bpy" in text for text in labels), (
        "escaped newlines were not decoded for display"
    )


def test_error_bubbles_use_the_alert_tint():
    """Errors must read at a glance — the alert tint is the one
    per-widget emphasis Blender exposes.

    Drawn through BOTH panels because the pinned surface no longer
    renders replies at all; the record does, and the GPU overlay paints
    its own `error_bubble_rgba` (asserted in
    tests/pure/test_transcript_layout.py).
    """
    module = _load_addon("blended_draw_alert")
    module._STATE.transcript = [("error", "boom")]
    emitted = _draw_all(module, _make_context("blended_draw_alert"))
    alerts = [value for kind, value, _ in emitted if kind == "alert"]
    assert any(alerts), "error bubble must set the alert tint"
