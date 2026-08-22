"""blended — chat with a modeling agent inside Blender.

Install: Edit > Preferences > Add-ons > Install..., pick this file (or
the zipped folder), enable "blended: Agent Chat". The panel appears in
the 3D viewport sidebar (press N) under the "blended" tab.

THREADING. `bpy` is not thread-safe and must only be touched from the
main thread, but a model call blocks for seconds to minutes — doing it
inline freezes Blender's UI. So:

    background thread  ->  HTTP to the model (no bpy)
    main thread        ->  every tool call that touches bpy
    handoff            ->  bpy.app.timers.register, Blender's supported
                           "run this on the main thread soon" hook

The worker parks a request and waits; the timer picks it up, runs the
tool on the main thread, and hands the result back. Nothing touches bpy
off-thread.
"""

bl_info = {
    "name": "blended: Agent Chat",
    "author": "blended",
    "version": (0, 1, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar (N) > blended",
    "description": "Chat with a modeling agent that builds and gates game assets.",
    "category": "3D View",
}

import queue
import sys
import threading
import traceback
from dataclasses import replace
from pathlib import Path

import bpy

# --- Locating the `blended` package ----------------------------------------
# Two install shapes, both supported:
#   1. Packaged plugin (dist/blended_agent.zip) — the library is VENDORED
#      inside the addon folder, so nothing needs configuring.
#   2. Development — the addon is loaded from the repo and points at
#      <repo>/src, so edits to the library take effect on reload.

_TOOL_REQUESTS: "queue.Queue" = queue.Queue()
_TIMER_INTERVAL_SECONDS = 0.15
_MAXIMUM_TRANSCRIPT_LINES = 400
# Fingerprinting ~40 files at the tool-timer's 0.15s would be wasteful,
# so auto-reload checks on its own slower cadence.
_AUTO_RELOAD_INTERVAL_SECONDS = 1.0
_LAST_FINGERPRINT: dict = {}
_LAST_FINGERPRINT_CHECK = [0.0]


def _ensure_blended_importable(
    repository_root: str, prefer_repository: bool = False
) -> str:
    """Make `blended` importable. Returns '' on success, else an error.

    In developer mode the repository sources are put FIRST so edits take
    effect, even when a vendored copy is also present.
    """
    if prefer_repository and repository_root:
        source_directory = Path(bpy.path.abspath(repository_root)) / "src"
        if (source_directory / "blended").is_dir():
            if str(source_directory) in sys.path:
                sys.path.remove(str(source_directory))
            sys.path.insert(0, str(source_directory))
            return ""
        return f"Developer mode: no `blended` package under {source_directory}."

    # 1. Vendored inside the installed addon — the packaged-plugin case.
    vendored_root = Path(__file__).parent
    if (vendored_root / "blended").is_dir():
        if str(vendored_root) not in sys.path:
            sys.path.insert(0, str(vendored_root))
        return ""

    # 2. Development: point at the repo's src/.
    if not repository_root:
        return (
            "No vendored `blended` package found and no repository path set. "
            "Either install dist/blended_agent.zip, or set the repository "
            "path in this addon's preferences."
        )
    source_directory = Path(bpy.path.abspath(repository_root)) / "src"
    if not (source_directory / "blended").is_dir():
        return f"No `blended` package under {source_directory}."
    if str(source_directory) not in sys.path:
        sys.path.insert(0, str(source_directory))
    return ""


def _reload_library(preferences) -> str:
    """Purge and re-import `blended`, carrying the conversation across.

    Returns a human-readable summary. The live session holds instances
    of the OLD classes, so it is rebuilt — but its messages are plain
    dicts and survive, which is what lets you fix an op mid-conversation
    without losing context.
    """
    from blended import devreload

    source_root = devreload.library_source_root()
    previous_fingerprint = (
        devreload.source_fingerprint(source_root) if source_root else {}
    )
    conversation = devreload.snapshot_conversation(_STATE.session)

    result = devreload.purge_library_modules()

    import_error = _ensure_blended_importable(
        preferences.repository_path, preferences.developer_mode
    )
    if import_error:
        return f"Reload FAILED: {import_error}"

    from blended import devreload as reloaded_devreload

    new_root = reloaded_devreload.library_source_root()
    changed = ()
    if new_root and previous_fingerprint:
        changed = reloaded_devreload.changed_files(
            previous_fingerprint, reloaded_devreload.source_fingerprint(new_root)
        )
    global _LAST_FINGERPRINT
    _LAST_FINGERPRINT = (
        reloaded_devreload.source_fingerprint(new_root) if new_root else {}
    )

    if _STATE.session is not None:
        try:
            _STATE.session = _build_session(preferences)
            # Restore history minus the system prompt, which the rebuilt
            # session regenerates (so prompt edits take effect too).
            _STATE.session.messages.extend(
                message for message in conversation if message.get("role") != "system"
            )
        except Exception as rebuild_error:  # noqa: BLE001
            _STATE.session = None
            return f"Reloaded, but the session could not be rebuilt: {rebuild_error}"

    summary = reloaded_devreload.ReloadResult(
        purged_modules=result.purged_modules, changed_files=changed
    ).summary()
    if conversation:
        summary += f" Conversation kept ({len(conversation)} messages)."
    return summary


def _auto_reload_if_changed(preferences) -> str:
    """Reload when any library source file has changed on disk."""
    import time

    from blended import devreload

    now = time.monotonic()
    if now - _LAST_FINGERPRINT_CHECK[0] < _AUTO_RELOAD_INTERVAL_SECONDS:
        return ""
    _LAST_FINGERPRINT_CHECK[0] = now

    source_root = devreload.library_source_root()
    if source_root is None:
        return ""
    current = devreload.source_fingerprint(source_root)
    if not _LAST_FINGERPRINT:
        globals()["_LAST_FINGERPRINT"] = current
        return ""
    if not devreload.changed_files(_LAST_FINGERPRINT, current):
        return ""
    return _reload_library(preferences)


# --- Main-thread tool bridge -----------------------------------------------


class _ToolRequest:
    """One tool call parked by the worker for the main thread to run."""

    def __init__(self, tool_name, arguments, output_directory):
        self.tool_name = tool_name
        self.arguments = arguments
        self.output_directory = output_directory
        self.completed = threading.Event()
        self.result_text = ""
        self.image_paths: list = []
        self.error = ""


def _drain_tool_requests():
    """Timer callback: run parked tool calls on the MAIN thread."""
    from blended.agent.tools import dispatch_tool

    while True:
        try:
            request = _TOOL_REQUESTS.get_nowait()
        except queue.Empty:
            break
        try:
            request.result_text, request.image_paths = dispatch_tool(
                request.tool_name, request.arguments, request.output_directory
            )
        except Exception as tool_error:  # noqa: BLE001 — surfaced to the model
            request.error = (
                f"{type(tool_error).__name__}: {tool_error}\n"
                f"{traceback.format_exc()[:1500]}"
            )
        finally:
            request.completed.set()

    # Auto-reload runs on the main thread here, and never mid-turn:
    # purging modules while a worker is executing library code would
    # pull the floor out from under it.
    if not _STATE.busy:
        try:
            preferences = bpy.context.preferences.addons[__name__].preferences
            if preferences.developer_mode and preferences.auto_reload:
                summary = _auto_reload_if_changed(preferences)
                if summary:
                    _STATE.log("reload", summary)
        except Exception:  # noqa: BLE001 — dev convenience must never break the timer
            pass

    _redraw_sidebars()
    return _TIMER_INTERVAL_SECONDS


def _redraw_sidebars():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _dispatch_on_main_thread(tool_name, arguments, output_directory):
    """Called FROM the worker thread; blocks until the main thread runs it."""
    request = _ToolRequest(tool_name, arguments, output_directory)
    _TOOL_REQUESTS.put(request)
    request.completed.wait()
    if request.error:
        return request.error, []
    return request.result_text, request.image_paths


# --- Session state ---------------------------------------------------------


class _SessionState:
    def __init__(self):
        self.session = None
        self.worker = None
        self.transcript: list[tuple[str, str]] = []
        self.transcript_path = None  # Markdown log on disk, if enabled
        self.busy = False

    def log(self, kind: str, text: str):
        self.transcript.append((kind, text))
        del self.transcript[:-_MAXIMUM_TRANSCRIPT_LINES]


_STATE = _SessionState()


def _build_session(preferences):
    from blended.agent.loop import (
        AgentSession,
        ModelConfig,
        OllamaClient,
        dispatch_here,
    )

    config = ModelConfig.from_environment(
        model=preferences.model_name,
        endpoint=preferences.endpoint,
        api_key=preferences.api_key,
        vision_model=preferences.vision_model_name,
    )

    def main_thread_dispatch(tool_name, arguments, output_directory):
        """Every bpy-touching tool call, executed on the main thread.

        The turn itself runs on a worker thread, so the normal path is
        the queue-and-wait handoff below. The main-thread branch is for
        a turn driven synchronously: parking a request the timer cannot
        service until the main thread returns would deadlock.
        """
        if threading.current_thread() is threading.main_thread():
            return dispatch_here(tool_name, arguments, output_directory)
        return _dispatch_on_main_thread(tool_name, arguments, output_directory)

    session = AgentSession(
        client=OllamaClient(config),
        output_directory=Path(bpy.app.tempdir) / "blended_agent",
        dispatch=main_thread_dispatch,
    )

    if preferences.log_chat:
        from blended.agent.transcript import ChatTranscript, default_log_directory

        log_directory = (
            Path(bpy.path.abspath(preferences.log_directory))
            if preferences.log_directory
            else default_log_directory(
                bpy.path.abspath(preferences.repository_path)
                if preferences.repository_path
                else None
            )
        )
        session.transcript = ChatTranscript(
            log_directory, routing=config.describe_routing()
        )
        _STATE.transcript_path = session.transcript.markdown_path

    return session


# --- Operators -------------------------------------------------------------


class BLENDED_OT_send(bpy.types.Operator):
    bl_idname = "blended.send_message"
    bl_label = "Send"
    bl_description = "Send your message to the modeling agent"

    def execute(self, context):
        scene_properties = context.scene.blended_chat
        preferences = context.preferences.addons[__name__].preferences

        import_error = _ensure_blended_importable(
            preferences.repository_path, preferences.developer_mode
        )
        if import_error:
            self.report({"ERROR"}, import_error)
            return {"CANCELLED"}

        user_text = scene_properties.prompt.strip()
        if not user_text:
            self.report({"WARNING"}, "Type a message first.")
            return {"CANCELLED"}
        if _STATE.busy:
            self.report({"WARNING"}, "The agent is still working.")
            return {"CANCELLED"}

        if _STATE.session is None:
            try:
                _STATE.session = _build_session(preferences)
            except Exception as build_error:  # noqa: BLE001
                self.report({"ERROR"}, str(build_error))
                return {"CANCELLED"}

        _STATE.log("user", user_text)
        scene_properties.prompt = ""
        _STATE.busy = True

        def worker():
            try:
                _STATE.session.send(
                    user_text,
                    on_event=lambda kind, text: _STATE.log(kind, text),
                )
            except Exception as run_error:  # noqa: BLE001
                _STATE.log("error", str(run_error))
            finally:
                _STATE.busy = False

        _STATE.worker = threading.Thread(target=worker, daemon=True)
        _STATE.worker.start()
        return {"FINISHED"}


class BLENDED_OT_test_connection(bpy.types.Operator):
    bl_idname = "blended.test_connection"
    bl_label = "Test Connection"
    bl_description = "Verify the model is reachable before you start chatting"

    def execute(self, context):
        preferences = context.preferences.addons[__name__].preferences
        import_error = _ensure_blended_importable(
            preferences.repository_path, preferences.developer_mode
        )
        if import_error:
            self.report({"ERROR"}, import_error)
            return {"CANCELLED"}

        from blended.agent.loop import ModelConfig, OllamaClient

        config = ModelConfig.from_environment(
            model=preferences.model_name,
            endpoint=preferences.endpoint,
            api_key=preferences.api_key,
            vision_model=preferences.vision_model_name,
        )
        client = OllamaClient(config)
        status = client.check_connection()
        self.report({"INFO"} if status.ok else {"ERROR"}, status.summary())
        _STATE.log("result" if status.ok else "error", status.summary())

        # The eye is a separate model on the same endpoint — verify it too,
        # or a broken eye only surfaces mid-conversation.
        if status.ok and config.uses_separate_eye:
            eye_status = OllamaClient(
                replace(config, model=config.vision_model)
            ).check_connection()
            self.report(
                {"INFO"} if eye_status.ok else {"WARNING"},
                f"Eye: {eye_status.summary()}",
            )
            _STATE.log(
                "result" if eye_status.ok else "error",
                f"Eye: {eye_status.summary()}",
            )
        _STATE.log("result", f"Routing: {config.describe_routing()}")
        _redraw_sidebars()
        return {"FINISHED"}


class BLENDED_OT_open_transcript(bpy.types.Operator):
    bl_idname = "blended.open_transcript"
    bl_label = "Open Transcript"
    bl_description = (
        "Open this session's Markdown transcript in a Text Editor — a "
        "full-width, scrollable, selectable view of the whole conversation"
    )

    def execute(self, context):
        if _STATE.transcript_path is None:
            self.report({"WARNING"}, "No transcript yet — send a message first.")
            return {"CANCELLED"}
        transcript_path = str(_STATE.transcript_path)
        existing = next(
            (
                text_block
                for text_block in bpy.data.texts
                if text_block.filepath == transcript_path
            ),
            None,
        )
        if existing is None:
            existing = bpy.data.texts.load(transcript_path)
        else:
            # Reload so the view reflects everything written since.
            with bpy.context.temp_override(edit_text=existing):
                bpy.ops.text.reload()

        for area in context.screen.areas:
            if area.type == "TEXT_EDITOR":
                area.spaces.active.text = existing
                self.report({"INFO"}, f"Opened {Path(transcript_path).name}")
                return {"FINISHED"}
        self.report(
            {"INFO"},
            f"Loaded {Path(transcript_path).name} — open a Text Editor to read it.",
        )
        return {"FINISHED"}


class BLENDED_OT_reload(bpy.types.Operator):
    bl_idname = "blended.reload_library"
    bl_label = "Reload Library"
    bl_description = (
        "Re-import the blended library from disk without restarting "
        "Blender. Keeps the current conversation"
    )

    def execute(self, context):
        if _STATE.busy:
            self.report({"WARNING"}, "The agent is still working.")
            return {"CANCELLED"}
        preferences = context.preferences.addons[__name__].preferences
        import_error = _ensure_blended_importable(
            preferences.repository_path, preferences.developer_mode
        )
        if import_error:
            self.report({"ERROR"}, import_error)
            return {"CANCELLED"}
        summary = _reload_library(preferences)
        self.report(
            {"ERROR"} if summary.startswith("Reload FAILED") else {"INFO"}, summary
        )
        _STATE.log("reload", summary)
        _redraw_sidebars()
        return {"FINISHED"}


class BLENDED_OT_reset(bpy.types.Operator):
    bl_idname = "blended.reset_session"
    bl_label = "New Session"
    bl_description = "Clear the conversation and start fresh"

    def execute(self, context):
        if _STATE.busy:
            self.report({"WARNING"}, "The agent is still working.")
            return {"CANCELLED"}
        _STATE.session = None
        _STATE.transcript.clear()
        _redraw_sidebars()
        return {"FINISHED"}


# --- UI --------------------------------------------------------------------


def _wrap_for_region(body_text: str, region_width_px: float, ui_scale: float):
    """Wrap text to the panel's real width.

    Prefers the library implementation (which is unit-tested), but MUST
    NOT depend on it: Blender calls draw() as soon as the panel is
    visible, which can be before anything has put `blended` on sys.path
    — and an exception inside draw() makes Blender silently abandon the
    rest of the panel, so the user sees a half-rendered UI with no error.
    The fallback is the same algorithm inline.
    """
    try:
        from blended.agent.wrapping import wrap_for_region

        return wrap_for_region(body_text, region_width_px, ui_scale)
    except Exception:  # noqa: BLE001 — draw() must never raise
        import textwrap

        characters_per_line = max(
            24, int((region_width_px - 34) / (7.0 * max(ui_scale, 0.1)))
        )
        wrapped_lines: list[str] = []
        for paragraph in body_text.splitlines() or [""]:
            if not paragraph.strip():
                wrapped_lines.append("")
                continue
            wrapped_lines.extend(
                textwrap.wrap(
                    paragraph,
                    width=characters_per_line,
                    break_long_words=True,
                    break_on_hyphens=False,
                )
                or [""]
            )
        return wrapped_lines


_KIND_SPEAKERS = {
    "user": "You",
    "answer": "Agent",
    "vision": "Agent looked at the render",
    "error": "Error",
    "reload": "Reloaded",
    "result": "Tool result",
    "tool": "Tool call",
    "thinking": "Thinking",
}

_KIND_ICONS = {
    "user": "USER",
    "answer": "OUTLINER_OB_LIGHT",
    "tool": "TOOL_SETTINGS",
    "result": "CHECKMARK",
    "thinking": "SORTTIME",
    "vision": "HIDE_OFF",
    "reload": "FILE_REFRESH",
    "error": "ERROR",
}
_PREVIEW_CHARACTERS = 90


class BLENDED_PT_chat(bpy.types.Panel):
    bl_label = "Agent Chat"
    bl_idname = "BLENDED_PT_chat"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "blended"

    def _draw_message(self, layout, kind, body_text, region_width, ui_scale):
        """One chat bubble: a titled box with wrapped body text."""
        speaker = _KIND_SPEAKERS.get(kind)
        if speaker is None:
            return
        bubble = layout.box()
        header = bubble.row()
        header.label(text=speaker, icon=_KIND_ICONS.get(kind, "DOT"))

        body_column = bubble.column(align=True)
        body_column.scale_y = 0.72  # tighten line spacing so it reads as prose
        for line in _wrap_for_region(body_text, region_width, ui_scale):
            body_column.label(text=line if line else " ")

    def draw(self, context):
        layout = self.layout
        scene_properties = context.scene.blended_chat
        preferences = context.preferences.addons[__name__].preferences
        region_width = context.region.width
        ui_scale = context.preferences.system.ui_scale

        # LAYOUT ORDER IS DELIBERATE: the conversation is drawn FIRST and
        # every control is clustered BELOW it. A Blender panel flows
        # top-to-bottom and the region scrolls, so putting controls above a
        # growing transcript means hunting upward past the whole history to
        # reach them. With one control cluster pinned after the history,
        # scrolling to the bottom always lands on everything actionable.

        # --- conversation ------------------------------------------------
        conversation = layout.column()
        if not _STATE.transcript:
            empty_box = conversation.box()
            empty_box.label(text="Ask for an asset to get started.", icon="INFO")
            for example in (
                '"Build a wooden crate, 0.8 m, and show me the renders."',
                '"Make the legs thinner and re-check it."',
            ):
                for line in _wrap_for_region(example, region_width, ui_scale):
                    empty_box.label(text=line)

        visible = _STATE.transcript[-scene_properties.visible_messages :]
        pending_tool_calls: list[str] = []
        for kind, body_text in visible:
            # Tool traffic collapses to a compact activity line unless you
            # ask for detail — otherwise one turn floods the panel and
            # buries the actual conversation.
            if (
                kind in ("tool", "result", "thinking")
                and not scene_properties.show_tool_detail
            ):
                if kind == "tool":
                    pending_tool_calls.append(body_text.split("(")[0])
                continue
            if pending_tool_calls:
                conversation.row().label(
                    text=" · ".join(pending_tool_calls[-6:]), icon="TOOL_SETTINGS"
                )
                pending_tool_calls = []
            self._draw_message(conversation, kind, body_text, region_width, ui_scale)
        if pending_tool_calls:
            conversation.row().label(
                text=" · ".join(pending_tool_calls[-6:]), icon="TOOL_SETTINGS"
            )

        # --- control cluster, everything actionable in one place ---------
        layout.separator()
        controls = layout.box()

        composer = controls.column(align=True)
        composer.prop(scene_properties, "prompt", text="")
        send_row = composer.row(align=True)
        send_row.scale_y = 1.3
        send_row.enabled = not _STATE.busy
        send_row.operator(BLENDED_OT_send.bl_idname, icon="PLAY")

        status_row = controls.row(align=True)
        status_row.label(
            text="Working…" if _STATE.busy else "Ready",
            icon="SORTTIME" if _STATE.busy else "CHECKMARK",
        )
        status_row.operator(BLENDED_OT_open_transcript.bl_idname, text="", icon="TEXT")
        status_row.operator(BLENDED_OT_reset.bl_idname, text="", icon="TRASH")

        if region_width < 300:
            controls.label(
                text="Drag the sidebar edge for a wider chat.", icon="AREA_SWAP"
            )

        settings_header = controls.row(align=True)
        settings_header.prop(
            scene_properties,
            "show_settings",
            icon="TRIA_DOWN" if scene_properties.show_settings else "TRIA_RIGHT",
            text="Settings",
            emboss=False,
        )
        settings_header.label(text=preferences.model_name.split(":")[0])
        if scene_properties.show_settings:
            settings_column = controls.column()
            settings_column.prop(preferences, "model_name")
            settings_column.prop(preferences, "vision_model_name")
            settings_column.prop(preferences, "send_on_enter")
            settings_column.prop(scene_properties, "show_tool_detail")
            settings_column.prop(scene_properties, "visible_messages")
            settings_column.prop(preferences, "developer_mode")
            if preferences.developer_mode:
                settings_column.prop(preferences, "repository_path")
                settings_column.prop(preferences, "auto_reload")
            settings_column.prop(preferences, "log_directory")
            settings_column.operator(BLENDED_OT_test_connection.bl_idname, icon="URL")

        if preferences.developer_mode:
            developer_row = controls.row(align=True)
            developer_row.enabled = not _STATE.busy
            developer_row.operator(
                BLENDED_OT_reload.bl_idname, text="Reload", icon="FILE_REFRESH"
            )
            developer_row.label(
                text="auto" if preferences.auto_reload else "manual",
                icon="TIME" if preferences.auto_reload else "HANDLETYPE_VECTOR_VEC",
            )


class BLENDED_Preferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    repository_path: bpy.props.StringProperty(
        name="blended repository",
        subtype="DIR_PATH",
        description=(
            "Only needed for development installs. Leave empty when you "
            "installed the packaged blended_agent.zip — the library is "
            "vendored inside it."
        ),
        default="",
    )
    model_name: bpy.props.EnumProperty(
        name="Writer",
        description="Drives every turn: writes bpy, calls tools, reads gate reports",
        items=[
            (
                "deepseek-v4-flash:cloud",
                "DeepSeek V4 Flash (Medium Usage)",
                "284B MoE / 13B active, 1M context, tools + thinking. "
                "TEXT ONLY — pair it with an eye. Recommended writer.",
            ),
            (
                "minimax-m3:cloud",
                "MiniMax M3 (High Usage)",
                "Native multimodal — can drive everything alone, but spends "
                "High Usage on every turn.",
            ),
            (
                "kimi-k2.7-code:cloud",
                "Kimi K2.7 Code (High Usage)",
                "Vision + coding-tuned, ~30% fewer thinking tokens.",
            ),
            (
                "qwen3.5:397b-cloud",
                "Qwen 3.5 397B (Medium Usage)",
                "Vision + tools, 256K context.",
            ),
            (
                "kimi-k3:cloud",
                "Kimi K3 (METERED — $3/$15 per 1M)",
                "Strongest VLM available, billed separately from your "
                "subscription. Opt in deliberately.",
            ),
            (
                "qwen3.5:27b",
                "Qwen 3.5 27B (local)",
                "Runs on a 24 GB card. No cloud usage.",
            ),
        ],
        default="deepseek-v4-flash:cloud",
    )
    vision_model_name: bpy.props.EnumProperty(
        name="Eye",
        description=(
            "Called ONLY when a tool returns a render, to describe it back "
            "as text. Required when the writer is text-only."
        ),
        items=[
            (
                "minimax-m3:cloud",
                "MiniMax M3 (High Usage)",
                "Native multimodal. Recommended eye — fires only on renders.",
            ),
            (
                "kimi-k2.7-code:cloud",
                "Kimi K2.7 Code (High Usage)",
                "Vision, fewer thinking tokens.",
            ),
            (
                "qwen3.5:397b-cloud",
                "Qwen 3.5 397B (Medium Usage)",
                "Lightest against your weekly limit.",
            ),
            (
                "kimi-k3:cloud",
                "Kimi K3 (METERED — $3/$15 per 1M)",
                "Best vision available, billed separately.",
            ),
            (
                "",
                "None — writer sees for itself",
                "Only valid if the writer is vision-capable.",
            ),
        ],
        default="minimax-m3:cloud",
    )
    endpoint: bpy.props.StringProperty(
        name="Endpoint",
        default="http://localhost:11434",
        description=(
            "Local daemon proxies cloud models once you have run "
            "`ollama signin`. Falls back to https://ollama.com if a key "
            "is available."
        ),
    )
    developer_mode: bpy.props.BoolProperty(
        name="Developer mode",
        description=(
            "Load the library from the repository instead of the vendored "
            "copy, and show hot-reload controls"
        ),
        default=False,
    )
    auto_reload: bpy.props.BoolProperty(
        name="Auto-reload on file change",
        description=(
            "Watch the library sources and reload automatically when you "
            "save. Never fires mid-turn"
        ),
        default=True,
    )
    send_on_enter: bpy.props.BoolProperty(
        name="Enter sends",
        description=(
            "Send as soon as you confirm the message field. Turn off if "
            "you would rather always click Send"
        ),
        default=True,
    )
    log_chat: bpy.props.BoolProperty(
        name="Log chat to disk",
        description=(
            "Write each session to a Markdown transcript and a JSONL "
            "record. Development artifacts — the repo gitignores them"
        ),
        default=True,
    )
    log_directory: bpy.props.StringProperty(
        name="Log directory",
        subtype="DIR_PATH",
        description=(
            "Where transcripts go. Empty means <repository>/logs, or "
            "~/.blended/logs when no repository is set"
        ),
        default="",
    )
    api_key: bpy.props.StringProperty(
        name="API key (optional)",
        default="",
        subtype="PASSWORD",
        description=(
            "Leave empty when signed in via `ollama signin`. Only needed "
            "if OLLAMA_API_KEY is not visible to Blender — which is the "
            "case when Blender is launched from Finder on macOS."
        ),
    )

    def draw(self, context):
        import os

        layout = self.layout

        vendored = (Path(__file__).parent / "blended").is_dir()
        install_row = layout.row()
        install_row.label(
            text=(
                "Packaged install — library vendored, nothing to configure."
                if vendored
                else "Development install — set the repository path below."
            ),
            icon="CHECKMARK" if vendored else "INFO",
        )

        developer_box = layout.box()
        developer_box.prop(self, "developer_mode")
        if self.developer_mode or not vendored:
            developer_box.prop(self, "repository_path")
        if self.developer_mode:
            developer_box.prop(self, "auto_reload")
            developer_box.label(
                text="Edits to the library reload without restarting Blender.",
                icon="FILE_REFRESH",
            )
            if vendored:
                developer_box.label(
                    text="Repository sources take precedence over the vendored copy.",
                    icon="INFO",
                )
        layout.prop(self, "model_name")

        layout.prop(self, "vision_model_name")

        routing_box = layout.box()
        text_only_writers = ("deepseek-v4-flash:cloud",)
        if self.model_name in text_only_writers and not self.vision_model_name:
            routing_box.label(
                text="This writer cannot see. Pick an Eye, or it will never "
                "look at its own renders.",
                icon="ERROR",
            )
        elif self.vision_model_name and self.vision_model_name != self.model_name:
            routing_box.label(
                text=f"Writer {self.model_name} drives every turn; "
                f"{self.vision_model_name} is called only on renders.",
                icon="CHECKMARK",
            )
        else:
            routing_box.label(
                text=f"{self.model_name} handles text and images.",
                icon="INFO",
            )
        if (
            "kimi-k3" in (self.model_name, self.vision_model_name)
            or self.model_name == "kimi-k3:cloud"
            or self.vision_model_name == "kimi-k3:cloud"
        ):
            routing_box.label(
                text="Kimi K3 is METERED at $3/$15 per 1M — billed on top of "
                "your subscription.",
                icon="ERROR",
            )

        logging_box = layout.box()
        logging_box.prop(self, "log_chat")
        if self.log_chat:
            logging_box.prop(self, "log_directory")
            logging_box.label(
                text="Transcripts are gitignored — safe to keep in the repo.",
                icon="INFO",
            )

        layout.prop(self, "endpoint")
        environment_key = os.environ.get("OLLAMA_API_KEY", "")
        auth_row = layout.row()
        if environment_key:
            auth_row.label(
                text=f"OLLAMA_API_KEY found in environment (…{environment_key[-4:]})",
                icon="CHECKMARK",
            )
        else:
            auth_row.label(
                text="No OLLAMA_API_KEY in environment — fine if you ran "
                "`ollama signin`.",
                icon="INFO",
            )
        layout.prop(self, "api_key")
        layout.operator(BLENDED_OT_test_connection.bl_idname, icon="URL")


def _on_prompt_confirmed(self, context):
    """Fires when the prompt field is confirmed — i.e. you pressed Enter.

    This is the only path that can deliver "Enter sends" from INSIDE the
    field: while a Blender text field has focus it swallows keyboard
    input, so no keymap entry receives the keystroke. Confirming the
    field is the event we actually get.

    The operator is deferred to a one-shot timer rather than called
    inline, because invoking an operator from within a property-update
    callback is not safe in every context Blender may be in.
    """
    try:
        preferences = context.preferences.addons[__name__].preferences
    except (KeyError, AttributeError):
        return
    if not preferences.send_on_enter:
        return
    if _STATE.busy or not self.prompt.strip():
        return

    def _fire_send():
        try:
            bpy.ops.blended.send_message()
        except Exception:  # noqa: BLE001 — a failed send must not kill the timer
            pass
        return None  # one-shot

    bpy.app.timers.register(_fire_send, first_interval=0.0)


class BLENDED_ChatProperties(bpy.types.PropertyGroup):
    prompt: bpy.props.StringProperty(
        name="Message",
        description="What should the agent build? Press Enter to send",
        default="",
        update=_on_prompt_confirmed,
    )
    visible_messages: bpy.props.IntProperty(
        name="Visible messages",
        description="How many recent messages to show",
        default=24,
        min=4,
        max=200,
    )
    show_tool_detail: bpy.props.BoolProperty(
        name="Show tool detail",
        description=(
            "Show every tool call and result in full. Off by default so "
            "the conversation stays readable"
        ),
        default=False,
    )
    show_settings: bpy.props.BoolProperty(
        name="Show settings",
        description="Model and developer options, inline in this panel",
        default=False,
    )


# Cmd+Enter (macOS) / Ctrl+Enter elsewhere, for when focus is NOT in the
# message field — e.g. you clicked into the viewport and want to resend.
# Inside the field these never fire, because Blender's text field
# consumes keyboard events; `_on_prompt_confirmed` covers that case.
_KEYMAP_ENTRIES: list = []


def _register_keymaps():
    key_configuration = bpy.context.window_manager.keyconfigs.addon
    if key_configuration is None:
        return  # background mode has no addon keyconfig
    keymap = key_configuration.keymaps.new(name="3D View", space_type="VIEW_3D")
    for modifier in ("oskey", "ctrl"):
        keymap_item = keymap.keymap_items.new(
            BLENDED_OT_send.bl_idname,
            type="RET",
            value="PRESS",
            **{modifier: True},
        )
        _KEYMAP_ENTRIES.append((keymap, keymap_item))


def _unregister_keymaps():
    for keymap, keymap_item in _KEYMAP_ENTRIES:
        try:
            keymap.keymap_items.remove(keymap_item)
        except (RuntimeError, ReferenceError):
            pass
    _KEYMAP_ENTRIES.clear()


_CLASSES = (
    BLENDED_OT_test_connection,
    BLENDED_Preferences,
    BLENDED_ChatProperties,
    BLENDED_OT_send,
    BLENDED_OT_reset,
    BLENDED_OT_reload,
    BLENDED_OT_open_transcript,
    BLENDED_PT_chat,
)


def register():
    for class_object in _CLASSES:
        bpy.utils.register_class(class_object)
    # Put the library on sys.path NOW rather than lazily on first use, so
    # the panel can rely on it from its very first draw.
    try:
        preferences = bpy.context.preferences.addons[__name__].preferences
        _ensure_blended_importable(
            preferences.repository_path, preferences.developer_mode
        )
    except (KeyError, AttributeError):
        _ensure_blended_importable("")
    bpy.types.Scene.blended_chat = bpy.props.PointerProperty(
        type=BLENDED_ChatProperties
    )
    if not bpy.app.timers.is_registered(_drain_tool_requests):
        bpy.app.timers.register(_drain_tool_requests, persistent=True)
    _register_keymaps()


def unregister():
    _unregister_keymaps()
    if bpy.app.timers.is_registered(_drain_tool_requests):
        bpy.app.timers.unregister(_drain_tool_requests)
    del bpy.types.Scene.blended_chat
    for class_object in reversed(_CLASSES):
        bpy.utils.unregister_class(class_object)
