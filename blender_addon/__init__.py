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

import importlib
import importlib.util
import os
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
_LAST_ADDON_FINGERPRINT: tuple = ()
# Re-entrancy guard for _hot_reload: the drain timer (0.15 s) can fire
# while the Reload operator is mid-reload, and two concurrent teardowns
# unregister classes twice / read them while unregistered — measured:
# SIGSEGV in RNA_struct_find_property. Reloads serialize instead.
_RELOAD_IN_PROGRESS = False
# A manual reload is deferred (the operator must not unregister its own
# class mid-frame): the timer must stand down until it has run.
_RELOAD_PENDING = False


def _ensure_blended_importable(
    repository_root: str, prefer_repository: bool = False
) -> str:
    """Make `blended` importable. Returns '' on success, else an error.

    In developer mode the repository sources are put FIRST so edits
    take effect, even when a vendored copy is also present. The dev
    lanes ALSO expose the repository venv's site-packages: the only
    jinja2 in a dev checkout lives in the venv, Blender's bundled
    Python has none, and the packaged zip's vendored copy is on a
    different path than the repo sources. Same mechanism the driver
    scripts use; without it the first turn dies with `No module named
    'jinja2'` (measured 2026-08-23).
    """
    if prefer_repository and repository_root:
        source_directory = Path(bpy.path.abspath(repository_root)) / "src"
        if (source_directory / "blended").is_dir():
            _expose_repo_and_venv(source_directory, repository_root)
            return ""
        return f"Developer mode: no `blended` package under {source_directory}."

    # 1. Vendored inside the installed addon — the packaged-plugin case.
    vendored_root = Path(__file__).parent
    if (vendored_root / "blended").is_dir():
        if str(vendored_root) not in sys.path:
            sys.path.insert(0, str(vendored_root))
        return ""

    # 2. Development without developer mode: point at the repo's src/.
    if not repository_root:
        return (
            "No vendored `blended` package found and no repository path set. "
            "Either install dist/blended_agent.zip, or set the repository "
            "path in this addon's preferences."
        )
    source_directory = Path(bpy.path.abspath(repository_root)) / "src"
    if not (source_directory / "blended").is_dir():
        return f"No `blended` package under {source_directory}."
    _expose_repo_and_venv(source_directory, repository_root)
    return ""


def _expose_repo_and_venv(source_directory, repository_root: str) -> None:
    """Put the repo sources first, then the venv's site-packages.

    The venv is the only place jinja2 lives in a dev checkout (the
    driver scripts prepend it the same way). The repo stays ahead of
    the venv so library edits take effect.
    """
    if str(source_directory) in sys.path:
        sys.path.remove(str(source_directory))
    sys.path.insert(0, str(source_directory))
    dev_site_packages = _dev_venv_site_packages(repository_root)
    if dev_site_packages:
        if dev_site_packages in sys.path:
            sys.path.remove(dev_site_packages)
        sys.path.insert(0, dev_site_packages)
        if str(source_directory) in sys.path:
            sys.path.remove(str(source_directory))
        sys.path.insert(0, str(source_directory))


def _dev_venv_site_packages(repository_root: str) -> str:
    """The dev venv's site-packages, or '' when there is none.

    Mirrors the glob the driver scripts use. '' means the venv is
    absent and the next jinja2 import fails with its own message —
    loud, never a hardcoded path.
    """
    venv_root = Path(bpy.path.abspath(repository_root)) / ".venv" / "lib"
    candidates = sorted(venv_root.glob("python3.*/site-packages"))
    return str(candidates[-1]) if candidates else ""


def _addon_source_path(preferences) -> Path:
    """The addon module file hot-reload should re-import.

    Developer mode with a repository path points at the repo copy — the
    file the user actually edits — and falls through to the installed
    copy only when the repo file does not exist. Non-developer installs
    reload the installed copy itself, which is what the fingerprint must
    watch in that case.
    """
    if (
        preferences is not None
        and getattr(preferences, "developer_mode", False)
        and getattr(preferences, "repository_path", "")
    ):
        repository_copy = (
            Path(bpy.path.abspath(preferences.repository_path))
            / "blender_addon"
            / "__init__.py"
        )
        if repository_copy.is_file():
            return repository_copy
    return Path(__file__)


def _addon_fingerprint(preferences) -> tuple:
    """(mtime, size) of the addon file, enough to notice any save."""
    path = _addon_source_path(preferences)
    try:
        stat = path.stat()
    except OSError:
        return ()
    return (stat.st_mtime, stat.st_size)


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


def _reload_if_changed(preferences) -> None:
    """Hot-reload when the addon file or any library source changed.

    Paced to _AUTO_RELOAD_INTERVAL_SECONDS like the old library-only
    watcher; once a change is detected the fingerprint is advanced so
    the next tick does not reload again. _hot_reload covers BOTH cases:
    it re-imports the addon module AND purges the library.
    """
    import time

    from blended import devreload

    now = time.monotonic()
    if now - _LAST_FINGERPRINT_CHECK[0] < _AUTO_RELOAD_INTERVAL_SECONDS:
        return
    _LAST_FINGERPRINT_CHECK[0] = now

    addon_fingerprint = _addon_fingerprint(preferences)
    source_root = devreload.library_source_root()
    library_fingerprint = (
        devreload.source_fingerprint(source_root) if source_root is not None else {}
    )

    addon_changed = _LAST_ADDON_FINGERPRINT != () and (
        addon_fingerprint != _LAST_ADDON_FINGERPRINT
    )
    library_changed = bool(_LAST_FINGERPRINT) and (
        not library_fingerprint
        or devreload.changed_files(_LAST_FINGERPRINT, library_fingerprint)
    )
    if not addon_changed and not library_changed:
        return
    if _RELOAD_PENDING:
        return  # a manual reload is queued; this tick must stand down
    _hot_reload(preferences)


def _hot_reload(preferences) -> str:
    global _RELOAD_IN_PROGRESS, _RELOAD_PENDING
    if _RELOAD_IN_PROGRESS:
        return ""  # a reload is already running (timer vs operator)
    _RELOAD_IN_PROGRESS = True
    _RELOAD_PENDING = False  # a reload is starting; nothing queued behind it
    try:
        return _hot_reload_unlocked(preferences)
    finally:
        _RELOAD_IN_PROGRESS = False


def _snapshot_preferences(preferences):
    """Read the preference VALUES a reload needs off the RNA object.

    The RNA object stays valid only while its class is registered. A
    reload unregisters that class, so any later attribute read is a
    dangling srna dereference (measured: SIGSEGV in
    RNA_struct_find_property). Everything past a teardown must use
    this plain snapshot — no RNA references cross the boundary.
    """
    import types

    def plain_value(name, default):
        try:
            return getattr(preferences, name)
        except Exception:  # noqa: BLE001 — stub preferences lack most fields
            return default

    return types.SimpleNamespace(
        repository_path=(
            bpy.path.abspath(plain_value("repository_path", ""))
            if plain_value("repository_path", "")
            else ""
        ),
        developer_mode=bool(plain_value("developer_mode", False)),
        model_name=plain_value("model_name", ""),
        endpoint=plain_value("endpoint", ""),
        api_key=plain_value("api_key", ""),
        vision_model_name=plain_value("vision_model_name", ""),
        log_chat=plain_value("log_chat", False),
        log_directory=plain_value("log_directory", ""),
    )


def _hot_reload_unlocked(preferences) -> str:
    """Reload THIS addon module from disk, plus the library it uses.

    The reinstall killer: editing blender_addon/__init__.py (the repo
    copy in developer mode, the installed copy otherwise) and saving is
    enough — the timer picks it up within a second, or the Reload
    button triggers it. The UI classes are unregistered, the module is
    re-imported from disk under its own name, the carried session state
    is transplanted, and everything is re-registered. Returns a
    human-readable summary; "" when the reload was skipped mid-turn.
    """
    from blended import devreload

    # Everything the reload must carry across: a save must never cost
    # the user their conversation, history, or session.
    conversation = _STATE.transcript[:]
    routing = _STATE.routing
    prompt_history = _STATE.prompt_history[:]
    history_index = _STATE.history_index
    old_queue = _TOOL_REQUESTS
    old_session = _STATE.session
    old_library_fingerprint = (
        devreload.source_fingerprint(devreload.library_source_root())
        if devreload.library_source_root() is not None
        else {}
    )
    old_addon_fingerprint = _LAST_ADDON_FINGERPRINT

    # Preference VALUES, read NOW while the class is still registered:
    # any attribute read after the teardown below is a dangling srna
    # dereference (measured: SIGSEGV). The callers pass either the RNA
    # object or a snapshot; normalize to plain data before teardown.
    plain_preferences = _snapshot_preferences(preferences)

    # 1. Tear down the live UI surface. The timer goes FIRST: a tick
    # mid-teardown touches `addons[...].preferences`, and once the
    # Preferences class is unregistered that dereference is a dangling
    # RNA struct (measured: SIGSEGV in RNA_struct_find_property from
    # py_timer_execute). Then the keymap, then the scene property, then
    # the classes — the property deletion must happen while its
    # PropertyGroup class is still registered.
    #
    # BLENDED_Preferences is NEVER unregistered or re-registered here:
    # Blender caches the enabled addon's preferences RNA on first fetch,
    # and swapping the class object mid-session leaves every later
    # `addons[...].preferences` access pointing at freed memory
    # (measured: SIGSEGV in RNA_struct_find_property on a FRESH fetch,
    # backtrace plain_value -> _hot_reload_unlocked). The preferences
    # panel keeps showing the original class — a reload of the UI
    # surface must not invalidate the addon's own preferences.
    if bpy.app.timers.is_registered(_drain_tool_requests):
        bpy.app.timers.unregister(_drain_tool_requests)
    _unregister_keymaps()
    if hasattr(bpy.types.Scene, "blended_chat"):
        del bpy.types.Scene.blended_chat
    for class_object in reversed(_CLASSES):
        if class_object is BLENDED_Preferences:
            continue  # must stay registered — see above
        try:
            bpy.utils.unregister_class(class_object)
        except Exception:  # noqa: BLE001 — keep tearing down
            pass

    # 2. Purge the library, then re-import this module under its own
    # name; register() later re-seeds the library fingerprint.
    result = devreload.purge_library_modules()
    import_error = _ensure_blended_importable(
        plain_preferences.repository_path, plain_preferences.developer_mode
    )
    if import_error:
        # Never leave a torn-down UI behind.
        try:
            register()
        except Exception:  # noqa: BLE001 — report, do not crash
            pass
        return f"Reload FAILED: {import_error}"

    module_name = __name__
    path = _addon_source_path(plain_preferences)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # 3. Transplant the carried state into the fresh module.
    module._STATE.transcript = conversation
    module._STATE.routing = routing
    module._STATE.prompt_history = prompt_history
    module._STATE.history_index = history_index
    module._TOOL_REQUESTS = old_queue
    module._LAST_ADDON_FINGERPRINT = old_addon_fingerprint

    rebuild_error_text = ""
    if old_session is not None:
        try:
            module._STATE.session = module._build_session(plain_preferences)
            module._STATE.session.messages.extend(
                message
                for message in devreload.snapshot_conversation(old_session)
                if message.get("role") != "system"
            )
        except Exception as rebuild_error:  # noqa: BLE001
            module._STATE.session = None
            rebuild_error_text = (
                f"Reloaded, but the session could not be rebuilt: {rebuild_error}"
            )

    # 5. Register the fresh classes, keymap, and timer; advance the
    # addon fingerprint so the next timer tick does not reload again.
    module.register()
    new_addon_fingerprint = module._addon_fingerprint(plain_preferences)
    module._LAST_ADDON_FINGERPRINT = new_addon_fingerprint
    module._redraw_sidebars()

    new_library_fingerprint = (
        devreload.source_fingerprint(devreload.library_source_root())
        if devreload.library_source_root() is not None
        else {}
    )
    changed_library = devreload.changed_files(
        old_library_fingerprint, new_library_fingerprint
    )
    changed_parts = []
    if old_addon_fingerprint != new_addon_fingerprint:
        changed_parts.append("addon")
    if changed_library:
        changed_parts.append(f"library ({len(changed_library)} file(s))")
    changed_text = f" — changed: {', '.join(changed_parts)}" if changed_parts else ""
    summary = (
        f"Reloaded {len(result.purged_modules)} module(s){changed_text}; "
        f"conversation kept ({len(conversation)} messages)."
        if conversation
        else f"Reloaded {len(result.purged_modules)} module(s){changed_text}."
    )
    module._STATE.log("reload", summary)
    if rebuild_error_text:
        return rebuild_error_text
    return summary


def _stale_library_refusal(preferences) -> str:
    """Refuse the turn when memory and disk hold different libraries.

    Installing the zip over an ENABLED addon rewrites every file but does
    NOT reload `blended.*`: it is a top-level package on sys.path, not a
    submodule of this addon, so `sys.modules` keeps the previous build and
    Blender never re-runs register(). Measured 2026-08-22 by installing a
    zip whose REQUEST_TIMEOUT_SECONDS was 12345: on disk 12345, in memory
    300, same module object.

    That is not a cosmetic staleness. The session that crashed this box
    logged every tool call capped at exactly 212 characters — the old
    `emit` with `[:200]`, a line that does not exist on disk — so the
    crashing script could not be read back, let alone replayed. Running a
    build nobody installed is the "magic result" case: fail loudly.
    """
    from blended import devreload

    source_root = devreload.library_source_root()
    if source_root is None or not _LAST_FINGERPRINT:
        return ""
    changed = devreload.changed_files(
        _LAST_FINGERPRINT, devreload.source_fingerprint(source_root)
    )
    if not changed:
        return ""
    remedy = "click Reload in the panel"
    return (
        f"{len(changed)} library file(s) on disk no longer match the "
        f"`blended` loaded in this session (first: {changed[0]}). You are "
        f"about to run a build that is not the one installed — {remedy} "
        f"before sending, or the transcript will not describe what ran."
    )


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
            if preferences.auto_reload:
                _reload_if_changed(preferences)
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
        self.routing = ""
        self.prompt_history: list[str] = []
        self.history_index: int | None = None
        self.suppress_prompt_send = False

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
    _STATE.routing = config.describe_routing()

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

        stale = _stale_library_refusal(preferences)
        if stale:
            self.report({"ERROR"}, stale)
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
        if not _STATE.prompt_history or _STATE.prompt_history[-1] != user_text:
            _STATE.prompt_history.append(user_text)
        _STATE.history_index = None
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
    bl_label = "Reload"
    bl_description = (
        "Reload the addon UI and library from disk without restarting "
        "Blender. Keeps the current conversation"
    )

    def execute(self, context):
        if _STATE.busy:
            self.report({"WARNING"}, "The agent is still working.")
            return {"CANCELLED"}
        # The reload unregisters THIS operator's class, so it must not
        # run inside its frame: `self.report` after the teardown touches
        # the dead operator's RNA and segfaults (measured:
        # Operator.__getattribute__ -> path_resolve on a freed struct).
        # The preferences must be a PLAIN snapshot: the RNA object would
        # be dangling by the time the deferred reload reads it.
        global _RELOAD_PENDING
        preferences = _snapshot_preferences(
            context.preferences.addons[__name__].preferences
        )
        _RELOAD_PENDING = True  # the drain timer stands down until this runs
        # the dead operator's RNA and segfaults (measured:
        # Operator.__getattribute__ -> path_resolve on a freed struct).
        # Defer to a one-shot timer that fires after execute() returns.
        def _fire_reload():
            # `_hot_reload` itself logs the summary on the fresh module's
            # state; nothing else to do here but wake the UI.
            _hot_reload(preferences)
            _redraw_sidebars()
            return None  # one-shot

        bpy.app.timers.register(_fire_reload, first_interval=0.0)
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
def _conversation_text() -> str:
    """The whole session as plain text, ready to paste into a report.

    The routing line is the first thing a debugging paste needs: the
    same prompt behaves differently on different writers, and the
    transcripts this session already lost to a 200-char truncation are
    the reason every event is copied RAW — never wrapped, never capped.
    """
    blocks: list[str] = []
    if _STATE.routing:
        blocks.append(f"routing: {_STATE.routing}")
    for kind, body_text in _STATE.transcript:
        blocks.append(f"{_KIND_SPEAKERS.get(kind, kind)}:\n{body_text}")
    return "\n\n".join(blocks)


class BLENDED_OT_copy_message(bpy.types.Operator):
    bl_idname = "blended.copy_message"
    bl_label = "Copy message"
    bl_description = "Copy this exact, unwrapped text to the clipboard"
    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        if 0 <= self.index < len(_STATE.transcript):
            context.window_manager.clipboard = _STATE.transcript[self.index][1]
            self.report({"INFO"}, "Copied to clipboard.")
        else:
            self.report({"WARNING"}, "That message is no longer in the session.")
        return {"FINISHED"}


class BLENDED_OT_copy_conversation(bpy.types.Operator):
    bl_idname = "blended.copy_conversation"
    bl_label = "Copy conversation"
    bl_description = (
        "Copy the whole conversation, with routing and tool traffic, "
        "for pasting into a report"
    )

    def execute(self, context):
        context.window_manager.clipboard = _conversation_text()
        self.report({"INFO"}, "Conversation copied to clipboard.")
        return {"FINISHED"}


class BLENDED_PT_chat(bpy.types.Panel):
    bl_label = "Agent Chat"
    bl_idname = "BLENDED_PT_chat"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "blended"

    def _draw_message(self, layout, kind, body_text, region_width, ui_scale, index):
        """One chat bubble: a titled box with wrapped body text."""
        speaker = _KIND_SPEAKERS.get(kind)
        if speaker is None:
            return
        bubble = layout.box()
        if kind == "error":
            # The one per-widget emphasis Blender exposes: the theme's
            # alert tint on the bubble border/labels. Errors should read
            # at a glance, not as one more grey block.
            bubble.alert = True
        header = bubble.row()
        header.label(text=speaker, icon=_KIND_ICONS.get(kind, "DOT"))
        header.operator(
            BLENDED_OT_copy_message.bl_idname,
            text="",
            icon="COPYDOWN",
            emboss=False,
        ).index = index

        body_column = bubble.column(align=True)
        body_column.scale_y = 0.8  # tighten line spacing so it reads as prose
        # Tool calls carry ESCAPED text (the worker logs the raw JSON
        # string): render the escapes so the code reads line-by-line,
        # not as one long "sea of text". The copy button keeps the RAW
        # text, so nothing is lost.
        display_text = body_text
        if kind == "tool":
            display_text = body_text.replace("\\n", "\n").replace("\\t", "\t")
        wrapped = _wrap_for_region(display_text, region_width, ui_scale)
        for line in wrapped:
            if not line.strip():
                # A blank line is a paragraph separator, not a row: an
                # empty label still occupies a full line height, which is
                # what doubled every paragraph gap into an unreadable
                # 2.0-spaced wall of text.
                body_column.scale_y = 0.3
                body_column.label(text=" ")
                body_column.scale_y = 0.8
                continue
            body_column.label(text=line)

    def draw(self, context):
        layout = self.layout
        scene_properties = context.scene.blended_chat
        preferences = context.preferences.addons[__name__].preferences
        region_width = context.region.width
        ui_scale = context.preferences.system.ui_scale

        # LAYOUT: the conversation is drawn FIRST, oldest at the top,
        # and every control is clustered BELOW it — the composer sits at
        # the bottom, like a chat. Blender panel regions cannot scroll
        # programmatically (View2D is read-only through RNA; no scroll
        # operator in 5.2), so "the newest stays reachable" is achieved
        # by adjacency: scrolling to the bottom lands on the latest
        # message with the input right beneath it. Each event is its own
        # entry in the log — tool calls, results, and thinking included.

        # --- conversation, oldest first ----------------------------------
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
        visible_offset = max(
            0, len(_STATE.transcript) - scene_properties.visible_messages
        )
        for index, (kind, body_text) in enumerate(visible):
            self._draw_message(
                conversation,
                kind,
                body_text,
                region_width,
                ui_scale,
                visible_offset + index,
            )

        # --- control cluster, pinned AFTER the history --------------------
        layout.separator()
        controls = layout.box()

        composer = controls.column(align=True)
        composer.textbox(
            scene_properties,
            "prompt",
            initial_visible_lines=2,
            placeholder="Ask for an asset to build, or a change to make…",
        )
        send_row = composer.row(align=True)
        send_row.scale_y = 1.3
        send_row.enabled = not _STATE.busy
        send_row.operator(BLENDED_OT_send.bl_idname, icon="PLAY")
        hint_row = composer.row(align=True)
        hint_row.scale_y = 0.8
        hint_row.label(
            text="Enter sends · Ctrl+Enter sends from the viewport",
            icon="INFO",
        )

        # Status text on its own short line, event count on another —
        # neither can be truncated at any sidebar width (a single
        # "Working… — 10 events so far" label was cut mid-sentence).
        status_row = controls.row(align=True)
        status_row.label(
            text="Working…" if _STATE.busy else "Ready",
            icon="SORTTIME" if _STATE.busy else "CHECKMARK",
        )
        status_row.operator(
            BLENDED_OT_copy_conversation.bl_idname,
            text="",
            icon="COPYDOWN",
            emboss=True,
        )
        status_row.operator(BLENDED_OT_open_transcript.bl_idname, text="", icon="TEXT")
        status_row.operator(BLENDED_OT_reset.bl_idname, text="", icon="TRASH")

        event_count_row = controls.row(align=True)
        event_count_row.scale_y = 0.7
        event_count_row.label(
            text=(
                f"{len(_STATE.transcript)} events so far"
                if _STATE.busy
                else f"{len(_STATE.transcript)} events"
            )
        )

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
            settings_column.prop(scene_properties, "visible_messages")
            settings_column.prop(preferences, "developer_mode")
            if preferences.developer_mode:
                settings_column.prop(preferences, "repository_path")
                settings_column.prop(preferences, "auto_reload")
            settings_column.prop(preferences, "log_directory")
            settings_column.operator(BLENDED_OT_test_connection.bl_idname, icon="URL")

        reload_row = controls.row(align=True)
        reload_row.enabled = not _STATE.busy
        reload_row.operator(
            BLENDED_OT_reload.bl_idname, text="Reload", icon="FILE_REFRESH"
        )
        reload_row.label(
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
                "deepseek-v4-pro:cloud",
                "DeepSeek V4 Pro (High Usage)",
                "1.65T MoE. The writer the convergence loop CONVERGED on — "
                "prompt v9's pin rests on runs scored with it. Default.",
            ),
            (
                "deepseek-v4-flash:cloud",
                "DeepSeek V4 Flash (Medium Usage)",
                "284B MoE / 13B active, 1M context, tools + thinking. "
                "TEXT ONLY — pair it with an eye. Measured too weak to "
                "place geometry on this suite's briefs (v1-v4); it is "
                "here as a user choice, not a recommendation.",
            ),
            (
                "kimi-k2.7-code:cloud",
                "Kimi K2.7 Code (High Usage)",
                "Vision + coding-tuned, ~30% fewer thinking tokens. "
                "Calibrated 2026-08-24 as the LICENSED examiner eye "
                "(0.80 sensitivity / 1.00 specificity).",
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
                "gpt-oss-20b",
                "GPT-OSS 20B (bmb llama-swap)",
                "20.9B MoE, tools + thinking, ~12 GB of VRAM, served by "
                "bmb's llama-swap (OpenAI protocol at 192.168.1.233:9292, "
                "no tunnel). TEXT ONLY — pair it with an eye. No cloud "
                "usage, so it keeps working when the monthly cap is reached.",
            ),
            (
                "qwen3.8-27b",
                "Qwen 3.8 27B (bmb llama-swap)",
                "Local writer served by bmb's llama-swap (OpenAI protocol "
                "at 192.168.1.233:9292, no tunnel). Vision-capable on the "
                "OpenAI wire — pick qwen3.8-27b as the Eye to see renders. "
                "No cloud usage.",
            ),
        ],
        default="deepseek-v4-pro:cloud",
    )
    vision_model_name: bpy.props.EnumProperty(
        name="Eye",
        description=(
            "Called ONLY when a tool returns a render, to describe it back "
            "as text. Required when the writer is text-only."
        ),
        items=[
            (
                "kimi-k2.7-code:cloud",
                "Kimi K2.7 Code (High Usage)",
                "Calibrated 2026-08-24: sensitivity 0.80 (4/5), control "
                "specificity 1.00 (5/5) — the LICENSED examiner. "
                "minimax-m3:cloud was removed: it answers in thinking "
                "and returns empty content, failing the examiner contract.",
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
                "qwen3-vl:8b-instruct",
                "Qwen3-VL 8B Instruct (local)",
                "8.8B vision, ~7 GB of VRAM, no cloud usage. Measured "
                "2026-08-22: 0.20 sensitivity on the examiner fixture zoo "
                "with no false positives on 5 controls — good enough to "
                "DESCRIBE a render, not to judge one. Pick the -instruct "
                "build, not qwen3-vl:8b: the thinking build fills its whole "
                "context deliberating and returns nothing.",
            ),
            (
                "qwen3.8-27b",
                "Qwen 3.8 27B (bmb llama-swap)",
                "The bmb model as the eye: rides the same OpenAI lane as "
                "the writer, no cloud usage. Pick this when the writer is "
                "also qwen3.8-27b — one local model for text and vision.",
            ),
            (
                "",
                "None — writer sees for itself",
                "Only valid if the writer is vision-capable.",
            ),
        ],
        default="kimi-k2.7-code:cloud",
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
            "Required for the bmb llama-swap models (qwen3.8-27b, "
            "gpt-oss-20b) — that key lives on bmb at ~/llm/.api-key. "
            "Leave empty for the Ollama lanes when signed in via "
            "`ollama signin`."
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
        text_only_writers = (
            "deepseek-v4-flash:cloud",
            "gpt-oss-20b",
        )
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
                text="bmb models need the llama-swap key in API key below; "
                "Ollama lanes work with `ollama signin` alone.",
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
    if _STATE.suppress_prompt_send:
        _STATE.suppress_prompt_send = False
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

class BLENDED_OT_history(bpy.types.Operator):
    """Walk the prompts you have sent, like a shell's history.

    Up steps back through past prompts; Down (when walking) steps
    forward again. Reaching either end returns you to the prompt you
    were typing. Blender's text field swallows arrow keys while it has
    focus, so these are wired to Ctrl+Up / Ctrl+Down — the same chord
    the field does not consume and the user is most likely to discover.
    """
    bl_idname = "blended.history"
    bl_label = "Recall previous prompt"
    bl_description = (
        "Step back (or forward) through the prompts you have sent. "
        "Ctrl+Up / Ctrl+Down, since arrow keys are eaten by the text field"
    )
    direction: bpy.props.EnumProperty(
        items=(
            ("UP", "Up", "Earlier prompt"),
            ("DOWN", "Down", "Later prompt"),
        ),
        default="UP",
    )

    def execute(self, context):
        history = _STATE.prompt_history
        if not history:
            return {"CANCELLED"}
        scene_properties = context.scene.blended_chat

        if _STATE.history_index is None:
            _STATE.history_index = len(history)
        if self.direction == "UP":
            _STATE.history_index = max(0, _STATE.history_index - 1)
        else:
            _STATE.history_index = min(len(history), _STATE.history_index + 1)

        # Assigning `prompt` fires its update handler, which sends on
        # Enter — recalling history must NOT send anything.
        _STATE.suppress_prompt_send = True
        scene_properties.prompt = (
            history[_STATE.history_index]
            if _STATE.history_index < len(history)
            else ""
        )
        return {"FINISHED"}


def _register_keymaps():
    key_configuration = bpy.context.window_manager.keyconfigs.addon
    if key_configuration is None:
        return  # background mode has no addon keyconfig
    keymap = key_configuration.keymaps.new(name="3D View", space_type="VIEW_3D")
    # Heal orphans first: a crashed session skips unregister(), leaving
    # our items in the keyconfig — re-adding them then raises
    # RuntimeError("already registered"), which aborts register() and
    # silently kills the whole panel (the "no blended tab" symptom).
    # Removing pre-existing copies makes registration idempotent.
    for existing in list(keymap.keymap_items):
        if existing.idname in {
            BLENDED_OT_send.bl_idname,
            BLENDED_OT_history.bl_idname,
        }:
            keymap.keymap_items.remove(existing)
    for modifier in ("oskey", "ctrl"):
        keymap_item = keymap.keymap_items.new(
            BLENDED_OT_send.bl_idname,
            type="RET",
            value="PRESS",
            **{modifier: True},
        )
        _KEYMAP_ENTRIES.append((keymap, keymap_item))
    for direction, key_type in (("UP", "UP_ARROW"), ("DOWN", "DOWN_ARROW")):
        keymap_item = keymap.keymap_items.new(
            BLENDED_OT_history.bl_idname,
            type=key_type,
            value="PRESS",
            ctrl=True,
        )
        keymap_item.properties.direction = direction
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
    BLENDED_OT_history,
    BLENDED_OT_copy_message,
    BLENDED_OT_copy_conversation,
    BLENDED_PT_chat,
)


def register():
    for class_object in _CLASSES:
        # A hot reload keeps BLENDED_Preferences registered (unregistering
        # it invalidates the addon's cached preferences RNA — measured
        # SIGSEGV); anything else already registered is a torn-down
        # duplicate and must not be re-added.
        if hasattr(bpy.types, class_object.__name__):
            continue
        bpy.utils.register_class(class_object)
    # Put the library on sys.path NOW rather than lazily on first use, so
    # the panel can rely on it from its very first draw.
    try:
        preferences = bpy.context.preferences.addons[__name__].preferences
        _ensure_blended_importable(
            preferences.repository_path, preferences.developer_mode
        )
    except (KeyError, AttributeError):
        preferences = None
        _ensure_blended_importable("")
    # The baseline the staleness gate compares against: what `blended`
    # looked like on disk at the moment this session imported it.
    global _LAST_FINGERPRINT
    try:
        from blended import devreload

        source_root = devreload.library_source_root()
        _LAST_FINGERPRINT = (
            devreload.source_fingerprint(source_root) if source_root else {}
        )
    except Exception:  # noqa: BLE001 — a missing library is reported on use
        _LAST_FINGERPRINT = {}
    # The baseline the auto-reload watcher compares against: the addon
    # file as it was when this session imported it.
    global _LAST_ADDON_FINGERPRINT
    _LAST_ADDON_FINGERPRINT = _addon_fingerprint(preferences)
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
    if hasattr(bpy.types.Scene, "blended_chat"):
        del bpy.types.Scene.blended_chat
    for class_object in reversed(_CLASSES):
        # A hot reload never re-registers BLENDED_Preferences (see
        # register()), so its fresh counterpart is not registered here.
        if class_object is BLENDED_Preferences and not hasattr(
            bpy.types, class_object.__name__
        ):
            continue
        try:
            bpy.utils.unregister_class(class_object)
        except (RuntimeError, ReferenceError):
            pass
