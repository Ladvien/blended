# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tool-code for dispatching one blended tool inside Blender.

Runs in Blender's Python via the add-on's main-thread exec, which is what
``blended.agent.tools.dispatch_tool`` requires (it asserts the main
thread). blended is imported from the repository's ``src`` directory,
with the repository's venv site-packages behind it, the same order as
``blended.evaluate.bench_bridge.prelude``. Each call carries the server's
source fingerprint; when it differs from the one stamped on the imported
``blended`` package, every ``blended`` module is purged from
``sys.modules`` and re-imported, so a ``src/blended`` edit takes effect
without restarting Blender. The stamp is written only once the import
succeeded, and a purge drops it together with the modules it describes.
A purge also deletes this interpreter's cached bytecode for the package:
CPython accepts a timestamp ``.pyc`` whose source has the same size and
the same whole-second mtime, so a same-size edit in the second of the
last compile re-imported the old code (measured in Blender 5.2: a scripted
edit, call, revert, call ran the stale body 20 of 20 times at a 0 s gap).

After a scene-changing call (``plan_required_for``), the objects it
touched are framed in every 3D viewport, and the outcome's text gains a
``viewport:`` line (``blended.viewport_follow``).

The purge is safe because ``src/blended`` registers no bpy classes,
timers, handlers or draw handlers (grep for ``bpy.app.handlers``,
``bpy.app.timers``, ``register_class`` and ``draw_handler_add`` in
``src/blended`` found none on 2026-09-26). That covers this checkout's
copy only, so a ``blended`` imported from anywhere else is refused before
the purge could drop it. Purging the whole package, not single modules,
avoids two partial-reload bugs: a ``typing.NewType`` compared by ``is``
across a re-executed module, and a handle kept in a purged module's
globals that the next import can no longer find.

References: MCP (DOI 10.48550/arXiv.2503.23278);
LL3M, agentic Blender code generation (DOI 10.48550/arXiv.2508.08228).
"""

__all__ = (
    "Params",
    "Result",
    "main",
)

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, NamedTuple

_PACKAGE = "blended"
# Stamped on the imported package: the source fingerprint it was imported at.
_FINGERPRINT_ATTRIBUTE = "_mcp_source_fingerprint"


class Params(NamedTuple):
    tool_name: str
    arguments_json: str
    output_directory: str
    repository_src: str
    venv_site_packages: str
    source_fingerprint: str


class Result(NamedTuple):
    status: str
    outcome: dict[str, Any]


def _refuse_another_copy(package: Any, repository_src: str) -> None:
    loaded = str(Path(package.__file__).resolve().parent.parent)
    if loaded != repository_src:
        raise RuntimeError(
            "Blender imported blended from {:s}, not {:s}: another copy is loaded "
            "(the removed blended_agent add-on, or a blender-mcp from another checkout?). "
            "Disable it and restart Blender.".format(loaded, repository_src)
        )


def main(params: Params) -> Result:
    # Refused before this call touches sys.path or purges anything: the
    # purge would drop another copy silently and leave whatever it
    # registered running against the scene.
    imported = sys.modules.get(_PACKAGE)
    if imported is not None:
        _refuse_another_copy(imported, params.repository_src)

    # Site-packages first, then src, each at the front: src ends up first.
    for path in (params.venv_site_packages, params.repository_src):
        if path not in sys.path:
            sys.path.insert(0, path)

    if getattr(imported, _FINGERPRINT_ATTRIBUTE, None) != params.source_fingerprint:
        for module_name in [
            name for name in list(sys.modules)
            if name == _PACKAGE or name.startswith(_PACKAGE + ".")
        ]:
            del sys.modules[module_name]
        for source in Path(params.repository_src, _PACKAGE).rglob("*.py"):
            Path(importlib.util.cache_from_source(str(source))).unlink(missing_ok=True)
        importlib.invalidate_caches()

    import blended  # pylint: disable=import-outside-toplevel

    _refuse_another_copy(blended, params.repository_src)
    setattr(blended, _FINGERPRINT_ATTRIBUTE, params.source_fingerprint)

    # pylint: disable-next=import-outside-toplevel
    from blended.agent.outcome import outcome_to_json

    # pylint: disable-next=import-outside-toplevel
    from blended.agent.plan import plan_required_for

    # pylint: disable-next=import-outside-toplevel
    from blended.agent.tools import dispatch_tool

    # pylint: disable-next=import-outside-toplevel
    from blended.viewport_follow import follow_viewport

    outcome = dispatch_tool(
        params.tool_name,
        json.loads(params.arguments_json),
        Path(params.output_directory),
    )
    # The user watches this Blender: a scene-changing call leaves what it
    # touched framed, and says so on a `viewport:` line.
    if plan_required_for(params.tool_name):
        outcome = follow_viewport(outcome)
    return Result("ok", outcome_to_json(outcome))
