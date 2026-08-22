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
from pathlib import Path

import bpy

# --- Locating the `blended` package ----------------------------------------
# The addon ships beside the repo rather than inside site-packages, so the
# user points at the repo root once and we put its `src` on sys.path.

_TOOL_REQUESTS: "queue.Queue" = queue.Queue()
_TIMER_INTERVAL_SECONDS = 0.15
_MAXIMUM_TRANSCRIPT_LINES = 400


def _ensure_blended_importable(repository_root: str) -> str:
    """Put <repo>/src on sys.path. Returns '' on success, else an error."""
    source_directory = Path(bpy.path.abspath(repository_root)) / "src"
    if not (source_directory / "blended").is_dir():
        return (
            f"No `blended` package under {source_directory}. "
            f"Set the repository path in the panel."
        )
    if str(source_directory) not in sys.path:
        sys.path.insert(0, str(source_directory))
    return ""


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
        self.busy = False

    def log(self, kind: str, text: str):
        self.transcript.append((kind, text))
        del self.transcript[:-_MAXIMUM_TRANSCRIPT_LINES]


_STATE = _SessionState()


def _build_session(preferences):
    from blended.agent.loop import AgentSession, ModelConfig, OllamaClient
    import blended.agent.loop as loop_module

    config = ModelConfig.from_environment(
        model=preferences.model_name,
        endpoint=preferences.endpoint,
        api_key=preferences.api_key,
    )
    session = AgentSession(
        client=OllamaClient(config),
        output_directory=Path(bpy.app.tempdir) / "blended_agent",
    )

    # Route every tool call through the main thread.
    import blended.agent.tools as tools_module

    original_dispatch = tools_module.dispatch_tool

    def main_thread_dispatch(tool_name, arguments, output_directory):
        if threading.current_thread() is threading.main_thread():
            return original_dispatch(tool_name, arguments, output_directory)
        return _dispatch_on_main_thread(tool_name, arguments, output_directory)

    loop_module.dispatch_tool = main_thread_dispatch
    session._dispatch_override = main_thread_dispatch
    return session


# --- Operators -------------------------------------------------------------


class BLENDED_OT_send(bpy.types.Operator):
    bl_idname = "blended.send_message"
    bl_label = "Send"
    bl_description = "Send your message to the modeling agent"

    def execute(self, context):
        scene_properties = context.scene.blended_chat
        preferences = context.preferences.addons[__name__].preferences

        import_error = _ensure_blended_importable(preferences.repository_path)
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
        import_error = _ensure_blended_importable(preferences.repository_path)
        if import_error:
            self.report({"ERROR"}, import_error)
            return {"CANCELLED"}

        from blended.agent.loop import ModelConfig, OllamaClient

        client = OllamaClient(
            ModelConfig.from_environment(
                model=preferences.model_name,
                endpoint=preferences.endpoint,
                api_key=preferences.api_key,
            )
        )
        status = client.check_connection()
        self.report({"INFO"} if status.ok else {"ERROR"}, status.summary())
        _STATE.log("result" if status.ok else "error", status.summary())
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

_KIND_ICONS = {
    "user": "USER",
    "answer": "OUTLINER_OB_LIGHT",
    "tool": "TOOL_SETTINGS",
    "result": "CHECKMARK",
    "thinking": "SORTTIME",
    "error": "ERROR",
}
_PREVIEW_CHARACTERS = 90


class BLENDED_PT_chat(bpy.types.Panel):
    bl_label = "Agent Chat"
    bl_idname = "BLENDED_PT_chat"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "blended"

    def draw(self, context):
        layout = self.layout
        scene_properties = context.scene.blended_chat

        status_row = layout.row()
        status_row.label(
            text="Working…" if _STATE.busy else "Ready",
            icon="SORTTIME" if _STATE.busy else "CHECKMARK",
        )
        status_row.operator(BLENDED_OT_reset.bl_idname, text="", icon="FILE_REFRESH")

        transcript_box = layout.box()
        if not _STATE.transcript:
            transcript_box.label(text="Ask for an asset to get started.", icon="INFO")
        for kind, text in _STATE.transcript[-scene_properties.visible_lines:]:
            for line_index, line in enumerate(text.splitlines() or [""]):
                if not line.strip():
                    continue
                transcript_box.label(
                    text=line[:_PREVIEW_CHARACTERS],
                    icon=_KIND_ICONS.get(kind, "DOT") if line_index == 0 else "BLANK1",
                )

        layout.prop(scene_properties, "prompt", text="")
        send_row = layout.row()
        send_row.enabled = not _STATE.busy
        send_row.operator(BLENDED_OT_send.bl_idname, icon="PLAY")


class BLENDED_Preferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    repository_path: bpy.props.StringProperty(
        name="blended repository",
        subtype="DIR_PATH",
        description="Path to the blended repo (the folder containing src/)",
        default="",
    )
    model_name: bpy.props.EnumProperty(
        name="Model",
        description="Which model drives the agent",
        items=[
            ("minimax-m3:cloud", "MiniMax M3 (subscription, best)",
             "High Usage tier. Native multimodal, 1M context. Recommended."),
            ("kimi-k2.7-code:cloud", "Kimi K2.7 Code (subscription, fast)",
             "High Usage tier. Coding-tuned, ~30% fewer thinking tokens."),
            ("qwen3.5:397b-cloud", "Qwen 3.5 397B (subscription, light)",
             "Medium Usage tier — lightest against your weekly limit."),
            ("kimi-k3:cloud", "Kimi K3 (METERED — $3/$15 per 1M)",
             "Strongest VLM available, but billed separately from your "
             "subscription. Opt in deliberately."),
            ("qwen3.5:27b", "Qwen 3.5 27B (local)",
             "Runs on a 24 GB card. No cloud usage."),
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
        layout.prop(self, "repository_path")
        layout.prop(self, "model_name")

        billing_box = layout.box()
        if self.model_name == "kimi-k3:cloud":
            billing_box.label(
                text="Metered: $3/$15 per 1M tokens, billed on top of your "
                     "subscription.",
                icon="ERROR",
            )
        elif self.model_name.endswith("-cloud") or ":cloud" in self.model_name:
            billing_box.label(
                text="Covered by your Ollama subscription (usage limits apply).",
                icon="CHECKMARK",
            )
        else:
            billing_box.label(text="Runs locally — no cloud usage.", icon="DESKTOP")

        layout.prop(self, "endpoint")
        environment_key = os.environ.get("OLLAMA_API_KEY", "")
        auth_row = layout.row()
        if environment_key:
            auth_row.label(
                text=f"OLLAMA_API_KEY found in environment "
                     f"(…{environment_key[-4:]})",
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


class BLENDED_ChatProperties(bpy.types.PropertyGroup):
    prompt: bpy.props.StringProperty(
        name="Message", description="What should the agent build?", default=""
    )
    visible_lines: bpy.props.IntProperty(
        name="Visible lines", default=30, min=5, max=200
    )


_CLASSES = (
    BLENDED_OT_test_connection,
    BLENDED_Preferences,
    BLENDED_ChatProperties,
    BLENDED_OT_send,
    BLENDED_OT_reset,
    BLENDED_PT_chat,
)


def register():
    for class_object in _CLASSES:
        bpy.utils.register_class(class_object)
    bpy.types.Scene.blended_chat = bpy.props.PointerProperty(
        type=BLENDED_ChatProperties
    )
    if not bpy.app.timers.is_registered(_drain_tool_requests):
        bpy.app.timers.register(_drain_tool_requests, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_drain_tool_requests):
        bpy.app.timers.unregister(_drain_tool_requests)
    del bpy.types.Scene.blended_chat
    for class_object in reversed(_CLASSES):
        bpy.utils.unregister_class(class_object)
