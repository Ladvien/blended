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

WHAT THE PANEL IS FOR. This is a creation task, and creation is the one
cell of the human-AI matrix where the combination measurably beats
either side alone: across 106 experiments / 370 effect sizes, decision
tasks LOSE and creation tasks GAIN, with synergy appearing exactly when
the human alone outperforms the AI alone (g = 0.46, DOI
10.1038/s41562-024-02024-1). The user owns intent and taste; the agent
owns routine construction.

What eats that gain is review cost — experienced developers were
measurably SLOWED on repositories they knew well while believing they
had been sped up (DOI 10.48550/arXiv.2507.09089). So every element here
is scored by how cheaply the user can tell whether the result is right:
the plan and the renders sit next to the prompt box, tool traffic
collapses to one line each, and a turn is one undo step. Uncertainty is
stated impersonally and attached to a measurement rather than hedged in
the first person, which reduces overreliance without the trust penalty
that "I'm not sure" carries (DOI 10.48550/arxiv.2405.00623).

Nothing in this panel fires on its own. Proactive assistance is
accepted when it arrives at a natural workflow boundary and stays
user-triggered (DOI 10.1145/3742413.3789148); until there is a boundary
worth acting on, the agent speaks only when sent.
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
import json
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
# Model-id prefix of the Claude Code CLI lane. Duplicated from
# `blended.agent.claude_code.CLAUDE_CODE_MODEL_PREFIX` on purpose: the
# preferences panel must draw before the library is importable (that is
# where you point it at the library in the first place).
_CLAUDE_CODE_MODEL_PREFIX = "claude-code:"
# The Eye dropdown's "no separate eye" row. It carries a real token
# because Blender DROPS an enum item whose identifier is the empty
# string: measured live 2026-09-05 in a GUI session, assigning "" to
# vision_model_name raised `enum "" not found in ('kimi-k2.7-code:cloud',
# ...)` and the row was absent from the RNA item list — so the eye could
# not be switched off from the UI at all, which is exactly the setting a
# vision-capable writer (any `claude-code:` model) wants.
_EYE_NONE_IDENTIFIER = "none"
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
# The undo step's name in Blender's own undo history: long enough to
# tell two turns apart in the Edit menu, short enough not to run off it.
_UNDO_MESSAGE_CHARACTERS = 48
# The paired render thumbnails. Blender scales an icon by multiples of
# its own icon size, so this is a factor, not pixels.
_THUMBNAIL_SCALE = 3.0
# Redraw only when the panel's data actually moved.
_LAST_DRAWN_REVISION = [-1]


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

    # The handler's handle lives in a module this purge drops, and its
    # code is what the reload exists to replace: down before, up after.
    _remove_overlay()
    result = devreload.purge_library_modules()

    import_error = _ensure_blended_importable(
        preferences.repository_path, preferences.developer_mode
    )
    # Back up on the FRESH module, so the viewport draws the code that
    # was just reloaded — and on the FAILURE path too, so the panel's
    # alert row carries the reason instead of the viewport silently
    # losing its transcript.
    _install_overlay()
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


def _eye_model_id(vision_model_name: str) -> str:
    """The eye's MODEL id from the dropdown's token.

    `_EYE_NONE_IDENTIFIER` means "no separate eye — the writer looks at
    its own renders", which `ModelConfig` spells as an empty
    `vision_model`. One place converts, so the token never reaches the
    library and the empty string never reaches an enum.
    """
    return "" if vision_model_name == _EYE_NONE_IDENTIFIER else vision_model_name


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
        claude_code_binary_path=plain_value("claude_code_binary_path", ""),
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
    # A reload mid-session must not lose the turn's plan or the right to
    # revert it: both are what the panel is showing at that moment.
    plan = _STATE.plan
    can_revert = _STATE.can_revert
    undo_guard = _STATE.undo_guard
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
    # The overlay's handle lives in a `blended.*` module the purge below
    # is about to drop, so it comes down here or never.
    _remove_overlay()
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
    module._STATE.plan = plan
    module._STATE.can_revert = can_revert
    module._STATE.undo_guard = undo_guard
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
        self.outcome = None  # a ToolOutcome once the main thread ran it
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
            request.outcome = dispatch_tool(
                request.tool_name, request.arguments, request.output_directory
            )
        except Exception as tool_error:  # noqa: BLE001 — surfaced to the model
            request.error = (
                f"{type(tool_error).__name__}: {tool_error}\n"
                f"{traceback.format_exc()[:1500]}"
            )
        finally:
            request.completed.set()

    # The turn is over: give Blender its undo pushes back. This runs on
    # the main thread on purpose — the guard writes a preference, and
    # the worker thread that finished the turn may not touch RNA.
    if not _STATE.busy and _STATE.undo_guard is not None and _STATE.undo_guard.is_open:
        _STATE.undo_guard.close()

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

    # A streaming turn moves _STATE.revision several times a second and
    # an idle session never moves it at all, so this is the difference
    # between a live panel and waking every VIEW_3D area 6.7 times a
    # second for nothing.
    if _STATE.revision != _LAST_DRAWN_REVISION[0]:
        _LAST_DRAWN_REVISION[0] = _STATE.revision
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
        from blended.agent.outcome import ToolOutcome

        return ToolOutcome(request.error)
    return request.outcome


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
        # The reply being streamed right now: (kind, text so far). Drawn
        # as a live bubble under the history and replaced by the whole
        # event ("thinking"/"answer") once the model finishes it.
        self.live_kind = ""
        self.live_text = ""
        # The plan the agent declared for the turn in flight and how far
        # through it the agent reports being. Magentic-UI's measured
        # shape: a list of natural-language steps SHARED between user
        # and agent, with a progress bar over them during execution
        # (DOI 10.48550/arXiv.2507.22358). It is a shared
        # representation, not an approval gate — users approve ~93% of
        # permission prompts, so a gate buys oversight it does not
        # deliver (DOI 10.48550/arxiv.2604.14228).
        self.plan = None
        # Open for exactly as long as the worker runs, so the whole turn
        # collapses into one undo step. H-LAN: match the host's design
        # language, undo/redo included
        # (DOI 10.1080/10447318.2026.2632170).
        self.undo_guard = None
        self.can_revert = False
        # Bumped by every change the panel can see. The timer redraws
        # only when this moved, so an idle sidebar costs nothing —
        # before this, every VIEW_3D area was tagged for redraw 6.7
        # times a second forever.
        self.revision = 0

    def log(self, kind: str, text: str):
        self.revision += 1
        if kind.endswith("_delta"):
            base_kind = kind[: -len("_delta")]
            if base_kind != self.live_kind:
                self.live_kind, self.live_text = base_kind, ""
            self.live_text += text
            return
        self.live_kind, self.live_text = "", ""
        if kind == "plan":
            from blended.agent.plan import decode_plan_event

            self.plan = decode_plan_event(text)
        elif kind == "step" and self.plan is not None:
            self.plan = self.plan.with_step(int(text))
        self.transcript.append((kind, text))
        del self.transcript[:-_MAXIMUM_TRANSCRIPT_LINES]
        disk_transcript = getattr(self.session, "transcript", None)
        if disk_transcript is not None:
            disk_transcript.record(kind, text)


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
        vision_model=_eye_model_id(preferences.vision_model_name),
        claude_code_binary_path=preferences.claude_code_binary_path,
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
        stream_replies=True,
        # The user watches this session, so it owes them a plan before
        # it changes their scene. Batch drivers keep the unplanned
        # contract — see AgentSession.require_plan.
        require_plan=True,
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

        # The photo is read and re-encoded HERE, on the main thread:
        # normalization is `bpy` (Blender's image API is the only
        # decoder available without pip), and the turn itself runs on a
        # worker. A bad path must stop the send rather than surface as
        # an exception inside the worker, where the user sees only a
        # transcript line.
        reference_images: tuple = ()
        photo_path = scene_properties.reference_image.strip()
        if photo_path:
            from blended.capture.reference_photo import normalize_reference_photo

            try:
                reference_images = (
                    normalize_reference_photo(
                        Path(bpy.path.abspath(photo_path)),
                        Path(bpy.app.tempdir) / "blended_agent",
                    ),
                )
            except (ValueError, FileNotFoundError, RuntimeError) as photo_error:
                self.report({"ERROR"}, str(photo_error))
                return {"CANCELLED"}

        if _STATE.session is None:
            try:
                _STATE.session = _build_session(preferences)
            except Exception as build_error:  # noqa: BLE001
                self.report({"ERROR"}, str(build_error))
                return {"CANCELLED"}

        # What the user has selected IS part of the request: "make this
        # taller" is the natural way to ask, and selection is the
        # second-largest family of user-guided controllability
        # techniques in the generative-UI survey
        # (DOI 10.48550/arXiv.2410.22370). Blender already provides
        # world-class selection, so the harness wires the existing
        # selection into the conversation instead of adding widgets.
        from blended.agent.scene_context import (
            collect_scene_context,
            render_scene_context,
            summarize_scene_context,
        )

        scene_context = collect_scene_context(context)
        context_block = render_scene_context(scene_context)
        model_text = f"{user_text}\n\n{context_block}" if context_block else user_text

        _STATE.log("user", user_text)
        if context_block:
            _STATE.log(
                "context",
                summarize_scene_context(
                    scene_context,
                    _characters_per_line(
                        context.region.width if context.region else _NARROW_SIDEBAR_PIXELS,
                        context.preferences.system.ui_scale,
                    ),
                ),
            )
        if not _STATE.prompt_history or _STATE.prompt_history[-1] != user_text:
            _STATE.prompt_history.append(user_text)
        _STATE.history_index = None
        scene_properties.prompt = ""
        # Cleared on send: the photo is in the conversation history from
        # here on, and re-attaching it every turn would bill the same
        # image tokens again.
        scene_properties.reference_image = ""
        _STATE.plan = None
        _STATE.busy = True
        _STATE.revision += 1

        # One undo step for the whole turn: push a named restore point
        # now, then stop Blender pushing one per operator until the turn
        # ends. Opened here rather than in the worker because the
        # preference write must happen on the main thread.
        from blended.ui.turn_undo import TurnUndoGuard

        _STATE.undo_guard = TurnUndoGuard(message=f"blended: {user_text[:_UNDO_MESSAGE_CHARACTERS]}")
        _STATE.undo_guard.open()

        def worker():
            try:
                _STATE.session.send(
                    model_text,
                    on_event=lambda kind, text: _STATE.log(kind, text),
                    reference_images=reference_images,
                )
            except Exception as run_error:  # noqa: BLE001
                _STATE.log("error", str(run_error))
            finally:
                _STATE.busy = False
                _STATE.can_revert = True
                _STATE.revision += 1

        _STATE.worker = threading.Thread(target=worker, daemon=True)
        _STATE.worker.start()
        return {"FINISHED"}


class BLENDED_OT_clear_reference(bpy.types.Operator):
    bl_idname = "blended.clear_reference"
    bl_label = "Clear reference photo"
    bl_description = "Forget the picked photo; the next message goes without it"

    def execute(self, context):
        context.scene.blended_chat.reference_image = ""
        return {"FINISHED"}


class BLENDED_OT_stop(bpy.types.Operator):
    bl_idname = "blended.stop_turn"
    bl_label = "Stop"
    bl_description = (
        "Stop the agent at its next step. The model call in flight finishes; "
        "no further tool runs"
    )

    def execute(self, context):
        if not _STATE.busy or _STATE.session is None:
            self.report({"WARNING"}, "Nothing is running.")
            return {"CANCELLED"}
        _STATE.session.cancel()
        _STATE.log("status", "Stopping after the current step…")
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
            vision_model=_eye_model_id(preferences.vision_model_name),
            claude_code_binary_path=preferences.claude_code_binary_path,
        )
        client = OllamaClient(config)
        status = client.check_connection()
        self.report({"INFO"} if status.ok else {"ERROR"}, status.summary())
        _STATE.log("result" if status.ok else "error", status.summary())

        # The eye is a separate model, and its server follows its own id
        # — `eye_config()` is the single routing rule the runtime uses,
        # so the preflight must probe exactly what the run will hit.
        if status.ok and config.uses_separate_eye:
            eye_status = OllamaClient(config.eye_config()).check_connection()
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


class BLENDED_OT_revert_turn(bpy.types.Operator):
    bl_idname = "blended.revert_turn"
    bl_label = "Revert turn"
    bl_description = (
        "Undo everything the last turn did to the scene, in one step. "
        "The same as Ctrl+Z — the turn is a single undo step on purpose"
    )

    def execute(self, context):
        if _STATE.busy:
            self.report({"WARNING"}, "The agent is still working.")
            return {"CANCELLED"}
        if not _STATE.can_revert:
            self.report({"WARNING"}, "No turn to revert.")
            return {"CANCELLED"}
        from blended.ui.turn_undo import revert_turn

        if not revert_turn():
            self.report({"WARNING"}, "Blender had nothing left to undo.")
            return {"CANCELLED"}
        _STATE.can_revert = False
        _STATE.log("status", "Reverted the last turn.")
        _redraw_sidebars()
        return {"FINISHED"}


class BLENDED_OT_show_render(bpy.types.Operator):
    bl_idname = "blended.show_render"
    bl_label = "Open render"
    bl_description = "Open this render at full size in an Image Editor"
    path: bpy.props.StringProperty(default="")

    def execute(self, context):
        image_path = Path(self.path)
        if not self.path or not image_path.exists():
            self.report({"WARNING"}, f"That render is gone: {self.path}")
            return {"CANCELLED"}
        image = bpy.data.images.load(str(image_path), check_existing=True)
        image.reload()  # the agent re-renders to the same path within a turn
        for area in context.screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.spaces.active.image = image
                self.report({"INFO"}, f"Opened {image_path.name}")
                return {"FINISHED"}
        self.report(
            {"INFO"},
            f"Loaded {image_path.name} — the blended workspace has an "
            f"Image Editor ready for it.",
        )
        return {"FINISHED"}


# The `blended` sidebar tab needs one frame more than the layout does:
# a region is 1x1 until Blender has drawn it once, and
# `active_panel_category` is read-only until then. Bounded so a window
# with no 3D viewport cannot spin the timer forever.
_WORKSPACE_TAB_ATTEMPTS = 10
_WORKSPACE_TAB_RETRY_SECONDS = 0.1


class BLENDED_OT_open_workspace(bpy.types.Operator):
    bl_idname = "blended.open_workspace"
    bl_label = "blended workspace"
    bl_description = (
        "Create (or switch to) a workspace laid out for this: the "
        "viewport, an Image Editor for the renders, and a wide chat sidebar"
    )

    def execute(self, context):
        from blended.ui.workspace import (
            activate_chat_tab,
            arrange_workspace,
            ensure_workspace,
        )

        try:
            name = ensure_workspace()
        except Exception as workspace_error:  # noqa: BLE001 — reported, never swallowed
            self.report({"ERROR"}, str(workspace_error))
            return {"CANCELLED"}

        # A freshly copied screen has never been drawn, so its areas
        # have no realised regions: `area.type`, `area_split` and
        # `active_panel_category` all fail to land there (measured live,
        # 2026-09-05 — the layout came out as two Timeline editors). One
        # frame after the window switches to it, they take.
        #
        # The tab needs one frame MORE than the layout: opening the
        # sidebar and selecting its tab cannot happen in the same tick,
        # because the region is 1x1 until it has been drawn once
        # (measured 2026-09-06 — the sidebar came out 561x1104 with
        # `category=Item`, the tab silently unselected). So the timer
        # re-arms until the tab takes, bounded so a headless or
        # sidebar-less window cannot spin it forever.
        attempts = [_WORKSPACE_TAB_ATTEMPTS]

        def _arrange():
            arrange_workspace()
            selected = activate_chat_tab()
            _redraw_sidebars()
            attempts[0] -= 1
            if selected or attempts[0] <= 0:
                return None  # one-shot once the tab is on the panel
            return _WORKSPACE_TAB_RETRY_SECONDS

        bpy.app.timers.register(_arrange, first_interval=0.0)
        self.report({"INFO"}, f"Workspace “{name}” ready.")
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
        # Defer to a one-shot timer that fires after execute() returns.

        def _fire_reload():
            # `_hot_reload` itself logs the summary on the fresh module's
            # state; nothing else to do here but wake the UI.
            _hot_reload(preferences)
            _redraw_sidebars()

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
        _STATE.plan = None
        _STATE.can_revert = False
        _STATE.revision += 1
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
    "status": "Status",
    "result": "Tool result",
    "tool": "Tool call",
    "thinking": "Thinking",
    "context": "Scene",
    "plan": "Plan",
    "render": "Render",
    "reference": "Reference photo",
}

_KIND_ICONS = {
    "user": "USER",
    "answer": "OUTLINER_OB_LIGHT",
    "tool": "TOOL_SETTINGS",
    "result": "CHECKMARK",
    "thinking": "SORTTIME",
    "vision": "HIDE_OFF",
    "reload": "FILE_REFRESH",
    "status": "INFO",
    "error": "ERROR",
    "context": "RESTRICT_SELECT_OFF",
    "plan": "PRESET",
    "render": "IMAGE_DATA",
    "reference": "IMAGE_REFERENCE",
}
# Event kinds that are TRAFFIC, not conversation: each one is its own
# collapsed sub-panel, so the header line says what happened and the
# body is one click away. Drawn in full they pushed the answer and the
# composer off the bottom of the sidebar (measured by screenshot,
# 2026-09-04), which is the whole panel failing at once; drawn as a
# single global toggle they were all-or-nothing. Per-event disclosure
# is Ecological Interface Design's first principle — do not force
# processing to a higher cognitive level than the task demands
# (DOI 10.1109/21.156574). `plan` is in here because its event text is
# the raw JSON of the plan: drawn as a message it filled the panel with
# escapes (measured by screenshot in a live GUI session, 2026-09-05).
_COMPACT_KINDS = (
    "thinking",
    "tool",
    "result",
    "vision",
    "reload",
    "status",
    "context",
    "plan",
)
# Event kinds whose text is an image PATH, not prose: drawn as a
# thumbnail, summarized by file name. `render` is the harness's own
# picture of the scene; `reference` is the user's picture of the real
# object they want built. One tuple, because every place that treats a
# path as pixels must treat both the same way.
_IMAGE_KINDS = ("render", "reference")
# Progress and plan steps drive the plan card, not the conversation.
# `tool_event` is the structured copy of a tool/result pair (OT-8): it
# feeds the transcript file, never the conversation.
_STATE_ONLY_KINDS = ("step", "tool_event")
# Conversation, not traffic: what the GPU overlay paints unless the
# user asks for details. The traffic kinds stay in the record panel,
# where a header line says what happened and the body is one click
# away (DOI 10.1109/21.156574).
_OVERLAY_KINDS = ("user", "answer", "error")
# The cursor the overlay appends while a reply is still streaming.
_LIVE_CURSOR = " ▍"
# Non-empty when the transcript overlay could not be installed. Drawn
# as an alert row on the pinned surface — a draw handler that cannot
# start would otherwise be an empty viewport with no explanation.
_OVERLAY_ERROR = ""
# A compact row is icon + label + copy button: this many characters of
# the row's width are not text.
_COMPACT_ROW_CHROME_CHARACTERS = 8
# `layout.panel()` remembers open/closed state per idname, so the
# transcript index has to be part of it or every event would share one
# switch. Indices are stable: the transcript only ever appends.
_EVENT_PANEL_IDNAME = "blended_event_{index}"
# Plan steps are a list to scan, not prose to read.
_PLAN_STEP_SCALE_Y = 0.9
_EVIDENCE_BEFORE_LABEL = "before"
_EVIDENCE_LATEST_LABEL = "now"
# Blender's row unit is UI_UNIT_Y = 20 px before `ui_scale`, and a real
# sidebar is far smaller than it looks: 561 x 1104 px at ui_scale 2.0
# is 27 ROWS (measured in a live GUI session, 2026-09-05).
_UI_ROW_HEIGHT_PX = 20.0
# The composer is drawn FIRST, so nothing above it can move it: its
# position is structural, not budgeted. Three earlier attempts budgeted
# it instead — reserve rows for it, shrink the answer, make the cards
# yield — and each one still moved it, because a control drawn after a
# variable-height message sits at a variable height by construction
# (measured 2026-09-06: the user reported the input box walking down
# the panel on every reply).
#
# The replies are now off this surface entirely: they are painted by a
# GPU handler in the viewport, so the only thing whose height the model
# decides no longer shares a region with the prompt box. Pointing time
# grows with distance to a target (Fitts, DOI 10.48550/arXiv.2308.12515,
# DOI 10.48550/arXiv.1906.00905) and a target that MOVES has to be
# re-acquired visually before it can be pointed at, so a fixed composer
# is strictly cheaper than a well-fitted one (interaction-cost
# adaptation, DOI 10.48550/arXiv.2204.09162).
# One preview collection for the addon's lifetime, loaded in register()
# and unloaded in unregister(); a panel redraws several times a second
# and must never reload a PNG to draw it.
_PREVIEWS = None


def _characters_per_line(region_width_px: float, ui_scale: float) -> int:
    """The same estimate wrap_for_region uses, inline so draw() never
    depends on the library being importable."""
    return max(24, int((region_width_px - 34) / (7.0 * max(ui_scale, 0.1))))


def _preview(text: str, limit: int) -> str:
    """The first non-empty line, cut at the END with an ellipsis — Blender
    clips overlong labels in the MIDDLE, which loses the substance."""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(first_line) > limit:
        return first_line[: max(1, limit - 1)] + "…"
    return first_line


def _summarize_event(kind: str, text: str, limit: int) -> str:
    """One line that says what happened, for the collapsed view."""
    if kind == "tool":
        name, _, raw_arguments = text.partition("(")
        try:
            arguments = json.loads(raw_arguments[:-1]) if raw_arguments.endswith(")") else {}
        except ValueError:
            arguments = {}
        parts = [name]
        if isinstance(arguments, dict):
            if arguments.get("object_name"):
                parts.append(str(arguments["object_name"]))
            if arguments.get("domain"):
                parts.append(str(arguments["domain"]))
            if arguments.get("source"):
                parts.append(f"{len(str(arguments['source']).splitlines())} lines")
        return _preview(" · ".join(parts), limit)
    if kind in _IMAGE_KINDS:
        return _preview(Path(text).name, limit)
    if kind == "plan":
        try:
            from blended.agent.plan import decode_plan_event

            plan = decode_plan_event(text)
        except Exception:  # noqa: BLE001 — draw() must never raise
            return _preview(text, limit)
        return _preview(f"{len(plan.steps)} steps · {plan.steps[0]}", limit)
    return _preview(text, limit)


def _display_prose(text: str) -> str:
    """Model answers arrive as Markdown; labels cannot render it, so the
    emphasis markers are dropped rather than shown as asterisks."""
    return text.replace("**", "").replace("`", "")


def _result_failed(text: str) -> bool:
    head = text.lstrip()[:12].upper()
    return head.startswith(("FAILED", "TOOL RAISED", "GATE FAIL"))


_NARROW_SIDEBAR_PIXELS = 300


def _status_text() -> str:
    """Ready, or what the agent is doing right now (its last tool)."""
    if not _STATE.busy:
        return "Ready"
    if _STATE.live_kind == "thinking":
        return "Thinking…"
    if _STATE.live_kind == "content":
        return "Answering…"
    for kind, text in reversed(_STATE.transcript):
        if kind == "tool":
            return f"Running {text.partition('(')[0]}…"
        if kind == "user":
            break
    return "Working…"


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


def _thumbnail_icon(image_path) -> int:
    """The preview icon for a render, or 0 — Blender's "no icon".

    Zero is a real answer, not a failure: it is what a headless
    Blender, a missing file, or an addon whose previews are not loaded
    yet all produce, and `draw()` must never raise (an exception inside
    draw makes Blender silently abandon the rest of the panel).
    """
    if _PREVIEWS is None:
        return 0
    try:
        return _PREVIEWS.icon_for(image_path)
    except Exception:  # noqa: BLE001 — draw() must never raise
        return 0


def _panel_rows(region_height_px, ui_scale) -> int:
    """How many UI rows the region can show at once.

    Used for reporting and for tests, never to decide whether the
    composer is drawn: the composer is drawn first, unconditionally.
    A number that decides nothing cannot be wrong about anything.
    """
    return int(region_height_px / (_UI_ROW_HEIGHT_PX * max(ui_scale, 0.1)))


def _transcript_messages():
    """`_STATE.transcript` as overlay messages, oldest first.

    The overlay's input, and the one place that decides what belongs in
    the CONVERSATION as opposed to the record: replies and the user's
    own prompts always, the traffic kinds only when `show_details` is
    on. Progress events never — they move the plan card.

    The reply being streamed right now is appended last with
    `prefer_tail`, because the words being written are at the END of
    the text and the cursor has to stay visible.
    """
    try:
        from blended.ui.transcript_layout import TranscriptMessage
    except Exception:  # noqa: BLE001 — a draw handler must never raise
        return ()

    try:
        show_details = bool(bpy.context.scene.blended_chat.show_details)
    except (AttributeError, KeyError):
        show_details = False
    shown_kinds = _OVERLAY_KINDS + (_COMPACT_KINDS if show_details else ())

    messages = [
        TranscriptMessage(
            kind=kind,
            label=_KIND_SPEAKERS.get(kind, kind),
            body=body_text,
            index=index,
        )
        for index, (kind, body_text) in enumerate(_STATE.transcript)
        if kind in shown_kinds and kind not in _STATE_ONLY_KINDS
    ]
    if _STATE.live_text:
        live_kind = "answer" if _STATE.live_kind == "content" else _STATE.live_kind
        messages.append(
            TranscriptMessage(
                kind=live_kind,
                label=_KIND_SPEAKERS.get(live_kind, live_kind),
                body=_STATE.live_text + _LIVE_CURSOR,
                index=len(_STATE.transcript),
                prefer_tail=True,
            )
        )
    return tuple(messages)


def _overlay_status():
    """What the transcript overlay is failing at: (message, too_narrow).

    Two states are worth a row on the pinned surface — the handler
    could not be installed, and the handler ran but the viewport is too
    narrow for a readable column. Everything else the overlay does is
    visible in the viewport, which is where it belongs.
    """
    if _OVERLAY_ERROR:
        return _OVERLAY_ERROR, False
    try:
        from blended.ui import transcript_overlay
    except Exception:  # noqa: BLE001 — draw() must never raise
        return "", False
    return transcript_overlay.LAST_DRAW_ERROR, transcript_overlay.COLUMN_TOO_NARROW


def _install_overlay() -> None:
    """(Re)install the GPU transcript handler, recording any failure.

    Called from `register()` and after every library reload, because
    the overlay's CODE lives in `blended.ui.transcript_overlay`: a
    reload that left the old handler running would keep drawing the old
    code, which is the whole point of reloading.

    Removes first, unconditionally, so a reload actually stops the old
    painting instead of leaving the previous handler behind.

    A failure here must never propagate: an exception in `register()`
    silently kills the whole panel (the "no blended tab" symptom), so
    it is recorded and drawn as an alert row instead.
    """
    global _OVERLAY_ERROR
    _remove_overlay()
    _OVERLAY_ERROR = ""
    try:
        from blended.ui.transcript_overlay import register_overlay

        register_overlay(_transcript_messages, lambda: _STATE.revision)
    except Exception as overlay_error:  # noqa: BLE001 — surfaced in the panel
        _OVERLAY_ERROR = str(overlay_error)


def _remove_overlay() -> None:
    """Take the transcript handler down while its owner is importable.

    `devreload.purge_library_modules()` drops every `blended.*` module,
    and the draw handler's handle lives in the module's globals — so
    the FRESH `transcript_overlay` cannot remove a handler installed by
    the module it replaced. Measured 2026-09-06: after one hot reload,
    `sys.modules` held a different module object than the earlier
    import, with the live handle in the stale one. Removing the handler
    BEFORE the purge is what keeps a reload from stacking a second
    overlay that paints the old session's state.
    """
    try:
        from blended.ui.transcript_overlay import unregister_overlay

        unregister_overlay()
    except Exception:  # noqa: BLE001 — a reload must never be blocked
        pass



class _ChatDrawing:
    """The drawing both panels share.

    The chat is TWO panels on purpose. A Blender region cannot be
    scrolled programmatically (View2D is read-only through RNA and 5.2
    has no scroll operator), so anything drawn after a growing
    conversation eventually sits below the visible area — measured in a
    live GUI session on 2026-09-05, where one finished turn pushed the
    plan card, the renders and the composer off the bottom. Splitting
    them means the surface a reviewer works on — status, plan, renders,
    the answer, the prompt box — is always the first thing in the tab,
    and the full record is one disclosure below it. That is the
    conversational UI's own division of space: the prompt box is the
    primary interaction space and the history is the secondary one
    (DOI 10.48550/arXiv.2410.22370).
    """

    def _draw_traffic(
        self, layout, kind, body_text, index, region_width, ui_scale, expanded
    ):
        """One traffic event: a collapsible sub-panel whose header says
        what happened and whose body holds the whole text.

        `layout.panel()` is Blender's own disclosure widget — it looks
        like every other collapsed section in the application and
        Blender remembers each one's state itself (H-LAN: match the
        design language of the host environment,
        DOI 10.1080/10447318.2026.2632170). Per-event rather than one
        global switch, because a global switch forces the user to read
        everything to read anything (DOI 10.1109/21.156574).
        """
        limit = _characters_per_line(region_width, ui_scale) - _COMPACT_ROW_CHROME_CHARACTERS
        header, body = layout.panel(
            _EVENT_PANEL_IDNAME.format(index=index), default_closed=not expanded
        )
        failed = kind == "result" and _result_failed(body_text)
        if failed:
            header.alert = True
        header.label(
            text=_summarize_event(kind, body_text, limit),
            icon=_KIND_ICONS.get(kind, "DOT"),
        )
        header.operator(
            BLENDED_OT_copy_message.bl_idname, text="", icon="COPYDOWN", emboss=False
        ).index = index
        if body is None:
            return
        if failed:
            body.alert = True
        self._draw_body(body, kind, body_text, region_width, ui_scale)

    def _draw_message(
        self, layout, kind, body_text, region_width, ui_scale, index, max_rows=None
    ):
        """One chat bubble: a titled box with wrapped body text."""
        speaker = _KIND_SPEAKERS.get(kind)
        if speaker is None:
            return
        bubble = layout.box()
        if kind == "error" or (kind == "result" and _result_failed(body_text)):
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
        self._draw_body(
            bubble, kind, body_text, region_width, ui_scale, max_rows=max_rows
        )

    def _draw_body(
        self, layout, kind, body_text, region_width, ui_scale, max_rows=None
    ):
        """The text of one event, wrapped to the region — the one place
        a body is rendered, so a bubble and a disclosed panel can never
        disagree about what an event says."""
        if kind in _IMAGE_KINDS:
            self._draw_thumbnail(layout, Path(body_text), label=Path(body_text).name)
            return
        if kind == "plan":
            # The event text is the plan's wire form. A reader wants the
            # steps, not the JSON that carried them.
            try:
                from blended.agent.plan import decode_plan_event

                self._draw_plan(layout, decode_plan_event(body_text), busy=False)
                return
            except Exception:  # noqa: BLE001 — draw() must never raise
                pass
        body_column = layout.column(align=True)
        body_column.scale_y = 0.8  # tighten line spacing so it reads as prose
        # Tool calls carry ESCAPED text (the worker logs the raw JSON
        # string): render the escapes so the code reads line-by-line,
        # not as one long "sea of text". The copy button keeps the RAW
        # text, so nothing is lost.
        display_text = body_text
        if kind == "tool":
            display_text = body_text.replace("\\n", "\n").replace("\\t", "\t")
        elif kind in ("answer", "thinking", "vision"):
            display_text = _display_prose(body_text)
        wrapped = _wrap_for_region(display_text, region_width, ui_scale)
        if max_rows is not None and len(wrapped) > max_rows:
            # Cut the ROWS, not the source lines: one paragraph wraps to
            # ten rows in a real sidebar, which is how an "8-line" cap
            # still lost the prompt box (measured 2026-09-05).
            hidden = len(wrapped) - max_rows
            wrapped = wrapped[:max_rows]
            wrapped.append(f"… {hidden} more lines — open Conversation")
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

    def _draw_plan(self, layout, plan, busy, steps=True):
        """The turn's plan and how far through it the agent reports being.

        Magentic-UI's measured shape: natural-language steps shared
        between user and agent, with a progress bar over them during
        execution (DOI 10.48550/arXiv.2507.22358). Steps are drawn
        verbatim — the model wrote them for the user to read.

        The step state is deliberately conservative: while the turn runs,
        only steps BEFORE the reported one are done; once it ends, steps
        the agent never reached stay pending rather than being claimed.

        `steps=False` draws the header and the bar only. The pinned
        surface uses it once the turn is over: the step list is what a
        user watches DURING a turn, and afterwards it is competing for
        rows with the answer they are actually reading. The full list
        stays in the record.
        """
        card = layout.box()
        header = card.row(align=True)
        header.label(text="Plan", icon=_KIND_ICONS["plan"])
        header.label(text=plan.status_text())
        if steps:
            for number, step_text in enumerate(plan.steps, start=1):
                if number < plan.current_step or (
                    not busy and number <= plan.current_step
                ):
                    icon, done = "CHECKMARK", True
                elif number == plan.current_step:
                    icon, done = "PLAY", False
                else:
                    icon, done = "DOT", False
                row = card.row(align=True)
                row.scale_y = _PLAN_STEP_SCALE_Y
                row.active = not done  # completed steps recede, current reads
                row.label(text=f"{number}. {step_text}", icon=icon)
        card.progress(text=plan.status_text(), factor=plan.progress_fraction())

    def _draw_thumbnail(self, layout, image_path, label):
        """One render, as a clickable thumbnail.

        `icon_for` returns 0 (Blender's "no icon") when the preview
        cannot be made, so the row always carries the button that opens
        the file — the picture is the nice case, not the only case.
        """
        column = layout.column(align=True)
        column.label(text=label)
        icon_identifier = _thumbnail_icon(image_path)
        if icon_identifier:
            column.template_icon(icon_value=icon_identifier, scale=_THUMBNAIL_SCALE)
        column.operator(
            BLENDED_OT_show_render.bl_idname, text="Open", icon="ZOOM_IN"
        ).path = str(image_path)

    def _draw_evidence(self, layout, previous_path, latest_path):
        """This turn's render beside the one before it.

        RESP measured reference pairing at +0.32 F1 / +0.12 accuracy for
        spotting visual defects, almost all of it recovering recall
        (0.28 → 0.76) — a single frame with nothing to compare against is
        the condition where a reviewer accepts what they are shown
        (DOI 10.48550/arXiv.2604.11082). The same pairing is what lets a
        human see drift between two turns.
        """
        card = layout.box()
        card.label(text="Renders", icon=_KIND_ICONS["render"])
        pair = card.row(align=True)
        if previous_path is not None:
            self._draw_thumbnail(pair, previous_path, label=_EVIDENCE_BEFORE_LABEL)
        self._draw_thumbnail(pair, latest_path, label=_EVIDENCE_LATEST_LABEL)

    def _draw_conversation(self, layout, scene_properties, region_width, ui_scale):
        """The record: every event, oldest first, each disclosable."""
        if not _STATE.transcript:
            empty_box = layout.box()
            empty_box.label(text="Ask for an asset to get started.", icon="INFO")
            for example in (
                '"Build a wooden crate, 0.8 m, and show me the renders."',
                '"Make this thinner and re-check it."',
            ):
                for line in _wrap_for_region(example, region_width, ui_scale):
                    empty_box.label(text=line)
            return

        visible = _STATE.transcript[-scene_properties.visible_messages :]
        visible_offset = max(
            0, len(_STATE.transcript) - scene_properties.visible_messages
        )
        if visible_offset:
            layout.label(
                text=f"…{visible_offset} earlier events in the transcript",
                icon="TEXT",
            )
        for index, (kind, body_text) in enumerate(visible):
            if kind in _STATE_ONLY_KINDS:
                # Progress, not conversation: it moves the plan card.
                continue
            if kind in _COMPACT_KINDS or kind in _IMAGE_KINDS:
                self._draw_traffic(
                    layout,
                    kind,
                    body_text,
                    visible_offset + index,
                    region_width,
                    ui_scale,
                    expanded=scene_properties.show_details,
                )
                continue
            self._draw_message(
                layout,
                kind,
                body_text,
                region_width,
                ui_scale,
                visible_offset + index,
            )

    def _draw_session_controls(self, controls, scene_properties, preferences):
        """Status, the session actions, and Settings — all fixed height.

        Drawn immediately under the composer so every CLICKABLE control
        on the surface has a position that does not depend on what the
        agent said. Only the message stack below can grow.
        """
        # One short status line that cannot truncate at any sidebar
        # width, then the session actions as icons.
        status_row = controls.row(align=True)
        status_row.label(
            text=_status_text(),
            icon="SORTTIME" if _STATE.busy else "CHECKMARK",
        )
        revert = status_row.row(align=True)
        revert.enabled = _STATE.can_revert and not _STATE.busy
        revert.operator(
            BLENDED_OT_revert_turn.bl_idname, text="", icon="LOOP_BACK", emboss=True
        )
        status_row.prop(
            scene_properties,
            "show_details",
            text="",
            icon="ALIGN_JUSTIFY" if scene_properties.show_details else "ALIGN_LEFT",
            emboss=True,
        )
        status_row.operator(
            BLENDED_OT_copy_conversation.bl_idname,
            text="",
            icon="COPYDOWN",
            emboss=True,
        )
        status_row.operator(BLENDED_OT_open_transcript.bl_idname, text="", icon="TEXT")
        status_row.operator(BLENDED_OT_reset.bl_idname, text="", icon="TRASH")

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
                reload_row = settings_column.row(align=True)
                reload_row.enabled = not _STATE.busy
                reload_row.operator(
                    BLENDED_OT_reload.bl_idname, text="Reload", icon="FILE_REFRESH"
                )
            settings_column.prop(preferences, "log_directory")
            settings_column.operator(BLENDED_OT_test_connection.bl_idname, icon="URL")
            # A layout built for this work: the viewport, an Image Editor
            # for the renders, and a sidebar wide enough to read
            # (H-LAN, DOI 10.1080/10447318.2026.2632170).
            settings_column.operator(
                BLENDED_OT_open_workspace.bl_idname, icon="WORKSPACE"
            )


class BLENDED_PT_chat(_ChatDrawing, bpy.types.Panel):
    """The working surface: composer FIRST, then fixed-height controls.

    It draws NO reply text. The replies are painted by a GPU handler in
    the viewport (`blended.ui.transcript_overlay`), which is the only
    way to give them real padding, measured wrapping and a scroll
    position — and it keeps everything that grows with a turn out of
    the region that holds the prompt box.
    """

    bl_label = "Agent Chat"
    bl_idname = "BLENDED_PT_chat"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "blended"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene_properties = context.scene.blended_chat
        preferences = context.preferences.addons[__name__].preferences
        region_width = context.region.width
        ui_scale = context.preferences.system.ui_scale

        # Order matters, and the ONE rule is that the composer is
        # drawn first. Everything after it is FIXED height — status,
        # Settings, the renders card, the plan card — so nothing on
        # this surface can move the primary interaction space
        # (DOI 10.48550/arXiv.2410.22370). The replies, the one thing
        # whose height the model decides, are not drawn here at all.
        controls = layout.column()

        composer = controls.column(align=True)
        composer.textbox(
            scene_properties,
            "prompt",
            initial_visible_lines=2,
            placeholder="Ask for an asset, or a change to make…  (Ctrl+↑ recalls)",
        )
        send_row = composer.row(align=True)
        send_row.scale_y = 1.3
        if _STATE.busy:
            send_row.operator(BLENDED_OT_stop.bl_idname, icon="CANCEL")
        else:
            # The binding is printed ON the button: showing hotkeys in
            # place is what moves a user from pointing to expert
            # keyboard use (ExposeHK, DOI 10.1145/2470654.2470735).
            send_row.operator(
                BLENDED_OT_send.bl_idname, text="Send   ⌘⏎", icon="PLAY"
            )

        # The picker, one fixed-height row under the Send button:
        # Blender's own file browser IS the "give it a picture" surface,
        # so nothing here reimplements one. No thumbnail on this
        # surface — a preview is three UI units tall and the whole
        # pinned budget is 27 rows at ui_scale 2.0; the picture appears
        # in the Conversation record as a `reference` event.
        photo_row = controls.row(align=True)
        photo_row.prop(
            scene_properties, "reference_image", text="", icon="IMAGE_REFERENCE"
        )
        if scene_properties.reference_image:
            photo_row.operator(
                BLENDED_OT_clear_reference.bl_idname, text="", icon="X"
            )

        self._draw_session_controls(controls, scene_properties, preferences)

        # The overlay's failure modes, reported where the user is
        # looking rather than in the console. Each is a single
        # fixed-height row, so none can move the composer.
        overlay_error, column_too_narrow = _overlay_status()
        if overlay_error:
            alert_row = controls.row()
            alert_row.alert = True
            alert_row.label(
                text=f"Transcript overlay failed: {overlay_error}", icon="ERROR"
            )
        if column_too_narrow:
            controls.label(
                text="Viewport too narrow for the transcript — widen it.",
                icon="AREA_SWAP",
            )

        if region_width < _NARROW_SIDEBAR_PIXELS:
            controls.label(text="Drag the sidebar edge wider.", icon="AREA_SWAP")

        if not (_STATE.transcript or _STATE.live_text):
            empty_box = controls.box()
            empty_box.label(text="Ask for an asset to get started.", icon="INFO")
            for example in (
                '"Build a wooden crate, 0.8 m, and show me the renders."',
                '"Make this thinner and re-check it."',
            ):
                for line in _wrap_for_region(example, region_width, ui_scale):
                    empty_box.label(text=line)

        try:
            from blended.ui.previews import paired_render_paths

            previous_render, latest_render = paired_render_paths(_STATE.transcript)
        except Exception:  # noqa: BLE001 — draw() must never raise
            previous_render = latest_render = None

        if latest_render is not None:
            self._draw_evidence(controls, previous_render, latest_render)

        # The step list is what a user watches while the agent works.
        # Once the turn is over it collapses to its header and bar; the
        # record keeps every step.
        if _STATE.plan is not None:
            self._draw_plan(controls, _STATE.plan, _STATE.busy, steps=_STATE.busy)


class BLENDED_PT_history(_ChatDrawing, bpy.types.Panel):
    """The record, below the pinned surface and closed by default.

    Everything the turn did, oldest first, each event disclosable. It
    is closed by default because the working loop — ask, watch the plan,
    look at the render, read the answer — needs none of it, and an open
    record is what pushed that loop off the bottom of the sidebar
    (measured 2026-09-05).
    """

    bl_label = "Conversation"
    bl_idname = "BLENDED_PT_history"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "blended"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        self._draw_conversation(
            self.layout,
            context.scene.blended_chat,
            context.region.width,
            context.preferences.system.ui_scale,
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
            (
                "claude-code:sonnet",
                "Claude Sonnet (Claude Code CLI)",
                "Runs through the signed-in Claude Code CLI on this "
                "machine: no API key, no metered balance, covered by your "
                "Claude subscription's 5h/7d windows. Vision-capable, so "
                "you can leave the Eye on 'None' and let it look at its "
                "own renders. Tool calls are schema-CONSTRAINED here, not "
                "parsed out of prose.",
            ),
            (
                "claude-code:opus",
                "Claude Opus (Claude Code CLI)",
                "The strongest model on the CLI lane, same subscription "
                "auth as Sonnet and the same 5h/7d windows — it just "
                "spends them faster.",
            ),
        ],
        default="claude-code:sonnet",
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
                "qwen3-vl",
                "Qwen3-VL 8B Instruct (big llama-swap)",
                "8B vision, Q8_0 + F16 projector, no cloud usage and no "
                "API key. Served by big's llama-swap at "
                "192.168.1.110:8081 on the OpenAI wire, not by this "
                "machine — picking it routes there automatically. Pair "
                "it with the qwen3.8-27b writer for a fully-local run. "
                "Measured 0.20-0.40 sensitivity on the examiner fixture "
                "zoo with no false positives on the controls: good "
                "enough to DESCRIBE a render, not to judge one.",
            ),
            (
                "qwen3.8-27b",
                "Qwen 3.8 27B (bmb llama-swap)",
                "The bmb model as the eye: rides the same OpenAI lane as "
                "the writer, no cloud usage. Pick this when the writer is "
                "also qwen3.8-27b — one local model for text and vision.",
            ),
            (
                "claude-code:sonnet",
                "Claude Sonnet (Claude Code CLI) — sees its own renders",
                "The DEFAULT eye. Picking the same model as the writer "
                "means no second call: the render reaches the writer "
                "itself as a native image block, so nothing is lost to a "
                "prose summary in between. Measured 2026-09-05: two "
                "renders arrive unfused and in order (swapping them "
                "swaps the answer). Calibrated on the fixture zoo before "
                "it was made the default.",
            ),
            (
                "claude-code:haiku",
                "Claude Haiku (Claude Code CLI)",
                "The cheapest model on the CLI lane for an eye that only "
                "describes renders. No API key; your Claude subscription "
                "covers it. Renders arrive as real image blocks, unfused "
                "and in order (measured 2026-09-05).",
            ),
            (
                _EYE_NONE_IDENTIFIER,
                "None — writer sees for itself",
                "Only valid if the writer is vision-capable — every "
                "claude-code model is, and so are the kimi models.",
            ),
        ],
        default="claude-code:sonnet",
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
            "`ollama signin`. big's llama-swap (`qwen3-vl`) needs none "
            "— leave this empty and it will not be sent there."
        ),
    )
    claude_code_binary_path: bpy.props.StringProperty(
        name="Claude Code binary (optional)",
        default="",
        subtype="FILE_PATH",
        description=(
            "Only for the claude-code models. Leave empty and the addon "
            "looks on PATH and in the standard install directories — "
            "needed because Blender launched from Finder inherits no "
            "shell PATH. The CLI owns its own sign-in; no key goes here."
        ),
    )

    def draw(self, context):

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
        eye_model = _eye_model_id(self.vision_model_name)
        if self.model_name in text_only_writers and not eye_model:
            routing_box.label(
                text="This writer cannot see. Pick an Eye, or it will never "
                "look at its own renders.",
                icon="ERROR",
            )
        elif eye_model and eye_model != self.model_name:
            routing_box.label(
                text=f"Writer {self.model_name} drives every turn; "
                f"{eye_model} is called only on renders.",
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
        if _CLAUDE_CODE_MODEL_PREFIX in (self.model_name or "") or (
            _CLAUDE_CODE_MODEL_PREFIX in (self.vision_model_name or "")
        ):
            layout.prop(self, "claude_code_binary_path")
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

    bpy.app.timers.register(_fire_send, first_interval=0.0)


class BLENDED_ChatProperties(bpy.types.PropertyGroup):
    prompt: bpy.props.StringProperty(
        name="Message",
        description="What should the agent build? Press Enter to send",
        default="",
        update=_on_prompt_confirmed,
    )
    reference_image: bpy.props.StringProperty(
        name="Reference photo",
        description=(
            "A picture of the object to build; sent with your next message"
        ),
        default="",
        subtype="FILE_PATH",
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
    show_details: bpy.props.BoolProperty(
        name="Show details",
        description=(
            "Expand tool calls, tool results and thinking to their full text. "
            "Off, each is one line so the conversation stays readable"
        ),
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


class BLENDED_OT_scroll_transcript(bpy.types.Operator):
    """Scroll the GPU transcript under the pointer.

    The overlay is not a region, so Blender's own scrolling does not
    reach it — and a modal operator to capture the wheel would take the
    viewport hostage. A keymap item that PASSES THROUGH outside the
    transcript column costs nothing everywhere else: the wheel keeps
    zooming the scene exactly as it did.
    """

    bl_idname = "blended.scroll_transcript"
    bl_label = "Scroll transcript"
    bl_options = {"INTERNAL"}

    delta_px: bpy.props.IntProperty(default=0)

    def invoke(self, context, event):
        from blended.ui.transcript_overlay import (
            cursor_is_over_transcript,
            scroll_by,
        )

        if not cursor_is_over_transcript(
            context, event.mouse_region_x, event.mouse_region_y
        ):
            # The wheel still zooms the viewport everywhere else.
            return {"PASS_THROUGH"}
        scroll_by(self.delta_px)
        context.area.tag_redraw()
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
            BLENDED_OT_scroll_transcript.bl_idname,
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
    # The wheel scrolls the transcript when the pointer is inside its
    # column and zooms the viewport everywhere else — the operator
    # returns PASS_THROUGH outside the column, so this steals nothing.
    # Wheel UP moves toward the newest reply, which is at the top.
    #
    # Safe to bind unconditionally only because
    # `cursor_is_over_transcript` now shares `_draw`'s emptiness test:
    # before that fix it answered True for the column's geometry with
    # nothing painted, which would swallow viewport zoom over a measured
    # 353 x 868 px strip of empty viewport on every fresh session.
    from blended.ui.transcript_style import SCROLL_STEP_PX

    for key_type, direction in (("WHEELUPMOUSE", -1), ("WHEELDOWNMOUSE", 1)):
        keymap_item = keymap.keymap_items.new(
            BLENDED_OT_scroll_transcript.bl_idname, type=key_type, value="PRESS"
        )
        keymap_item.properties.delta_px = direction * SCROLL_STEP_PX
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
    BLENDED_OT_clear_reference,
    BLENDED_OT_stop,
    BLENDED_OT_reset,
    BLENDED_OT_reload,
    BLENDED_OT_open_transcript,
    BLENDED_OT_history,
    BLENDED_OT_copy_message,
    BLENDED_OT_copy_conversation,
    BLENDED_OT_revert_turn,
    BLENDED_OT_show_render,
    BLENDED_OT_open_workspace,
    BLENDED_OT_scroll_transcript,
    BLENDED_PT_chat,
    BLENDED_PT_history,
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
    # The panel draws render thumbnails from disk, so the preview
    # collection has to exist before its first draw. A failure here is
    # reported by `_thumbnail_icon` returning 0 (no picture, still a
    # working Open button) rather than by breaking registration.
    global _PREVIEWS
    try:
        from blended.ui.previews import RenderPreviews

        _PREVIEWS = RenderPreviews()
        _PREVIEWS.load()
    except Exception:  # noqa: BLE001 — an unconfigured library is reported on use
        _PREVIEWS = None
    # The transcript is drawn by a GPU handler in the VIEWPORT, not by
    # this panel: `UILayout` has no pixel vocabulary and a Blender
    # region cannot be scrolled from Python, so a conversation drawn in
    # the sidebar eventually pushes its own prompt box off the bottom.
    _install_overlay()
    _register_keymaps()


def unregister():
    global _PREVIEWS
    # Before the keymaps, so the wheel items and the handler they drive
    # come down together.
    _remove_overlay()
    _unregister_keymaps()
    if bpy.app.timers.is_registered(_drain_tool_requests):
        bpy.app.timers.unregister(_drain_tool_requests)
    if _PREVIEWS is not None:
        _PREVIEWS.unload()
        _PREVIEWS = None
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
