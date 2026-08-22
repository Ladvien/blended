"""Hot reload for developing the library while Blender stays open.

The problem: Python caches every import in `sys.modules`. Editing
`blended/ops/primitives.py` and running again gets you the OLD code,
silently — and Blender's own "Reload Scripts" only reloads registered
addons, not an arbitrary package sitting on `sys.path`. Disabling and
re-enabling the addon does not help either, because the submodules
survive in the cache.

The fix is to purge every `blended.*` entry from `sys.modules` so the
next import reads from disk. Every module in this library imports `bpy`
and its siblings INSIDE functions rather than at module top level,
which is what makes purge-and-reimport safe: nothing holds a stale
module reference across the boundary.

Two things must be handled by the caller, not here:
  * a live agent session holds instances of the OLD classes, so it has
    to be rebuilt (its conversation can be carried across — see
    `snapshot_conversation`)
  * reloading mid-turn, while a worker thread is inside library code,
    is not safe; guard on your own busy flag first.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE_NAME = "blended"


@dataclass(frozen=True)
class ReloadResult:
    purged_modules: tuple[str, ...]
    changed_files: tuple[str, ...] = ()

    def summary(self) -> str:
        if not self.purged_modules:
            return "Nothing to reload (library was not imported yet)."
        changed = (
            f"; changed: {', '.join(self.changed_files)}" if self.changed_files else ""
        )
        return f"Reloaded {len(self.purged_modules)} modules{changed}."


def purge_library_modules() -> ReloadResult:
    """Drop every `blended.*` module so the next import re-reads disk.

    Safe to call from inside `blended` itself: deleting a sys.modules
    entry does not unload code that is currently executing — the running
    frame keeps its own reference alive.
    """
    purged = tuple(
        sorted(
            name
            for name in list(sys.modules)
            if name == PACKAGE_NAME or name.startswith(PACKAGE_NAME + ".")
        )
    )
    for module_name in purged:
        del sys.modules[module_name]
    return ReloadResult(purged_modules=purged)


def library_source_root() -> Path | None:
    """Directory the library is currently imported from, if any."""
    module = sys.modules.get(PACKAGE_NAME)
    if module is None:
        return None
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return None
    return Path(module_file).parent


def source_fingerprint(source_root: Path) -> dict[str, float]:
    """Map every .py file under the library to its modification time."""
    return {
        str(path.relative_to(source_root)): path.stat().st_mtime
        for path in sorted(source_root.rglob("*.py"))
    }


def changed_files(
    previous: dict[str, float], current: dict[str, float]
) -> tuple[str, ...]:
    """Files added, removed, or modified between two fingerprints."""
    changed = {name for name, mtime in current.items() if previous.get(name) != mtime}
    changed |= set(previous) - set(current)
    return tuple(sorted(changed))


def snapshot_conversation(session) -> list[dict]:
    """Copy a session's messages so it can be carried across a reload.

    Returned plain — the dicts contain only JSON-ish data, no class
    instances — so it survives the purge that invalidates the session
    object itself.
    """
    if session is None:
        return []
    return [dict(message) for message in getattr(session, "messages", [])]
