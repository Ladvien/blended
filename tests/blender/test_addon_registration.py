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
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_repository_lane_without_developer_mode_also_resolves_jinja2():
    """The second dev shape — repository_path set, developer_mode
    unchecked — hits the same venv-only jinja2 hole."""
    module = _load_addon("blended_agent_repo_venv_test")
    error = module._ensure_blended_importable(str(REPOSITORY_ROOT), False)
    assert error == ""
    try:
        from blended.agent.prompt_templates import template_path

        path = template_path("working_agreement_v10")
        assert path.exists()
    finally:
        for path in list(sys.path):
            if "blended/src" in path or ".venv" in path:
                sys.path.remove(path)


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


def test_the_addon_and_the_library_ship_the_same_models():
    """The panel's defaults must be the library's defaults, and both
    must be selectable.

    Two failures are pinned here. A default the enum does not offer
    stops Blender registering the addon outright. A default that
    disagrees with `ModelConfig` is quieter and worse: the panel would
    talk to one model while every script and batch run talked to
    another, and the transcripts would not say so.

    `CONVERGENCE_WRITER_MODEL` is asserted SELECTABLE rather than
    default: it names the writer whose runs minted the golden
    references, so it must stay reachable to reproduce a scored run,
    but the shipped default is qualified separately (see
    tests/pure/test_prompt_templates.py).
    """
    from blended.agent import prompt_versions
    from blended.agent.loop import ModelConfig

    module = _load_addon("blended_agent_writer_test")
    annotations = module.BLENDED_Preferences.__annotations__
    shipped = ModelConfig()
    for property_name, shipped_model in (
        ("model_name", shipped.model),
        ("vision_model_name", shipped.vision_model),
    ):
        keywords = annotations[property_name].keywords
        enum_values = {item[0] for item in keywords["items"]}
        assert keywords["default"] in enum_values, (
            f"{property_name} defaults to {keywords['default']!r}, which the "
            f"dropdown does not offer — Blender would refuse to register"
        )
        assert keywords["default"] == shipped_model, (
            f"the addon ships {keywords['default']!r} for {property_name} "
            f"but the library ships {shipped_model!r} — the panel and the "
            f"batch driver would talk to different models"
        )
    writer_values = {
        item[0] for item in annotations["model_name"].keywords["items"]
    }
    assert prompt_versions.CONVERGENCE_WRITER_MODEL in writer_values, (
        "the writer that minted the goldens is not selectable, so a scored "
        "run can no longer be reproduced from the panel"
    )


def test_no_dropdown_row_carries_an_empty_identifier():
    """Blender DROPS an enum item whose identifier is the empty string.

    Measured live in a GUI session 2026-09-05: the Eye's
    "None — writer sees for itself" row used `""`, and assigning it
    raised `enum "" not found in ('kimi-k2.7-code:cloud', ...)` — the
    row never reached the RNA item list, so the eye could not be
    switched off from the UI at all. Any future row that spells "off"
    as "" would silently vanish the same way.
    """
    module = _load_addon("blended_agent_enum_test")
    for property_name in ("model_name", "vision_model_name"):
        items = module.BLENDED_Preferences.__annotations__[property_name].keywords[
            "items"
        ]
        identifiers = [item[0] for item in items]
        assert all(identifiers), (
            f"{property_name} has an item with an empty identifier: "
            f"{identifiers}"
        )
        assert len(set(identifiers)) == len(identifiers)


def test_the_eye_can_be_switched_off_and_that_means_no_eye():
    """A vision-capable writer (every claude-code model) looks at its
    own renders, which the library spells as an empty vision_model."""
    module = _load_addon("blended_agent_eye_off_test")
    items = module.BLENDED_Preferences.__annotations__[
        "vision_model_name"
    ].keywords["items"]
    identifiers = [item[0] for item in items]
    assert module._EYE_NONE_IDENTIFIER in identifiers
    assert module._eye_model_id(module._EYE_NONE_IDENTIFIER) == ""
    assert module._eye_model_id("claude-code:haiku") == "claude-code:haiku"


def test_both_dropdowns_offer_the_claude_code_lane():
    """The CLI lane is reachable from the UI, writer and eye."""
    module = _load_addon("blended_agent_claude_lane_test")
    annotations = module.BLENDED_Preferences.__annotations__
    writer_ids = {item[0] for item in annotations["model_name"].keywords["items"]}
    eye_ids = {item[0] for item in annotations["vision_model_name"].keywords["items"]}
    assert "claude-code:sonnet" in writer_ids
    assert "claude-code:haiku" in eye_ids
    assert "claude_code_binary_path" in annotations


class _Preferences:
    """Just the two fields the staleness check reads."""

    def __init__(self, developer_mode=False):
        self.developer_mode = developer_mode
        self.repository_path = ""


def test_a_matching_library_is_not_stale():
    module = _load_addon("blended_agent_fresh_test")
    from blended import devreload

    source_root = devreload.library_source_root()
    module._LAST_FINGERPRINT = devreload.source_fingerprint(source_root)

    assert module._stale_library_refusal(_Preferences()) == ""


def test_a_library_that_changed_on_disk_refuses_the_turn():
    """Installing the zip over an ENABLED addon rewrites every file but
    leaves `blended.*` in sys.modules: it is a top-level package on
    sys.path, not a submodule, so Blender never reloads it. Measured
    2026-08-22 — on disk 12345, in memory 300, same module object — and
    the session that crashed had been logging tool calls capped at 212
    chars by an `emit` that no longer existed on disk, so the crashing
    script could not be replayed. A turn must not start on a build
    nobody installed."""
    module = _load_addon("blended_agent_stale_test")

    # A baseline that cannot match the files: every path is unknown-new.
    module._LAST_FINGERPRINT = {"blended/agent/loop.py": 0.0}

    refusal = module._stale_library_refusal(_Preferences())
    assert refusal, "a changed library must refuse the turn"
    assert "not the one installed" in refusal
    assert "click Reload" in refusal


def test_developer_mode_is_told_to_reload_instead():
    """Dev mode has a Reload button; telling it to restart Blender would
    be wrong advice for the one setup that can fix this in place."""
    module = _load_addon("blended_agent_stale_dev_test")
    module._LAST_FINGERPRINT = {"blended/agent/loop.py": 0.0}

    refusal = module._stale_library_refusal(_Preferences(developer_mode=True))
    assert "click Reload" in refusal


def test_addon_source_path_points_at_the_repo_copy_in_developer_mode():
    """Developer mode + repository path must watch the repo file — the
    file the developer actually edits — and fall through to the
    installed copy when the repo copy does not exist."""
    module = _load_addon("blended_agent_source_path_test")

    dev_preferences = _Preferences(developer_mode=True)
    dev_preferences.repository_path = str(Path(__file__).resolve().parents[2])
    assert module._addon_source_path(dev_preferences) == ADDON_PATH

    missing_repo_preferences = _Preferences(developer_mode=True)
    missing_repo_preferences.repository_path = "/nonexistent/repository"
    assert module._addon_source_path(missing_repo_preferences) == Path(module.__file__)

    vendored_preferences = _Preferences()
    assert module._addon_source_path(vendored_preferences) == Path(module.__file__)


def test_hot_reload_swaps_the_loaded_module_and_keeps_the_session():
    """The reinstall killer: _hot_reload must re-import the module under
    its own name, re-register the classes, and carry the conversation,
    history, and session across."""
    module = _load_addon("blended_agent_reload_test")
    module._STATE.transcript = [("user", "keep me"), ("answer", "and me")]
    module._STATE.routing = "writer=test"
    module._STATE.prompt_history = ["first prompt", "second prompt"]
    module._STATE.history_index = 1
    # The panel's live state, not just the record: a dev-mode reload
    # mid-turn used to blank the plan card and the revert button.
    from blended.agent.plan import TurnPlan

    module._STATE.plan = TurnPlan(steps=("build it", "check it"), current_step=2)
    module._STATE.can_revert = True
    preferences = _Preferences(developer_mode=True)
    preferences.repository_path = str(Path(__file__).resolve().parents[2])
    module_name = module.__name__

    summary = module._hot_reload(preferences)

    fresh_module = sys.modules[module_name]
    assert fresh_module is not module, "hot reload did not swap the module"
    assert hasattr(bpy.types, "BLENDED_PT_chat"), "panel not re-registered"
    assert fresh_module._STATE.transcript[:2] == [
        ("user", "keep me"),
        ("answer", "and me"),
    ]
    assert fresh_module._STATE.transcript[-1][0] == "reload"
    assert fresh_module._STATE.routing == "writer=test"
    assert fresh_module._STATE.prompt_history == ["first prompt", "second prompt"]
    assert fresh_module._STATE.history_index == 1  # carried verbatim
    assert fresh_module._STATE.plan == module._STATE.plan, (
        "the reload dropped the turn's plan: the card the user was "
        "reading disappears mid-session"
    )
    assert fresh_module._STATE.can_revert is True, (
        "the reload dropped the right to revert a turn that is still "
        "in the scene"
    )
    assert fresh_module._TOOL_REQUESTS is module._TOOL_REQUESTS
    assert "conversation kept (2 messages)" in summary
    assert fresh_module._STATE.session is None  # no session existed to rebuild

    fresh_module.unregister()
    assert not hasattr(bpy.types.Scene, "blended_chat")


def test_register_heals_orphaned_keymap_items_from_a_crashed_session():
    """A crashed session skips unregister(), leaving this addon's
    keymap items orphaned in the addon keyconfig. Re-adding them raises
    RuntimeError('already registered') and register() aborts — the
    whole panel silently disappears (the missing 'blended' tab). The
    register path must remove stale copies first."""
    module = _load_addon("blended_agent_orphan_heal")
    key_configuration = bpy.context.window_manager.keyconfigs.addon
    keymap = key_configuration.keymaps.new(name="3D View", space_type="VIEW_3D")
    orphan = keymap.keymap_items.new(
        module.BLENDED_OT_send.bl_idname,
        type="RET",
        value="PRESS",
        ctrl=True,
    )
    try:
        module.register()
        # Registration must not raise "already registered": the orphan
        # gets removed before the fresh bindings are added, so the
        # panel and keymap both come up.
        send_items = [
            item
            for item in keymap.keymap_items
            if item.idname == module.BLENDED_OT_send.bl_idname
        ]
        assert send_items, "register() left no Send bindings"
        assert hasattr(bpy.types, "BLENDED_PT_chat"), "panel not registered"
    finally:
        module.unregister()
        try:
            keymap.keymap_items.remove(orphan)
        except (RuntimeError, ReferenceError):
            pass


def test_an_idle_session_does_not_ask_for_a_redraw():
    """The drain timer runs 6.7 times a second for the whole session.
    It used to tag every VIEW_3D area for redraw on every one of those
    ticks whether anything had changed or not; now it redraws exactly
    when the panel's data moved, which is what makes streaming cheap
    AND idling free."""
    module = _load_addon("blended_agent_redraw_test")
    redraws = []
    module._redraw_sidebars = lambda: redraws.append(1)

    module._drain_tool_requests()  # first tick after load: state is unseen
    first_tick = len(redraws)
    module._drain_tool_requests()
    module._drain_tool_requests()
    assert len(redraws) == first_tick, (
        "an idle session must not wake the viewport"
    )

    module._STATE.log("status", "the agent said something")
    module._drain_tool_requests()
    assert len(redraws) == first_tick + 1, "a new event must repaint the panel"

    module._STATE.busy = True
    module._STATE.revision += 1  # what BLENDED_OT_send does when it starts
    module._drain_tool_requests()
    assert len(redraws) == first_tick + 2, "starting a turn must repaint"
