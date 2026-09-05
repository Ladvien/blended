"""One undo step per turn, plus an explicit Revert turn (D5).

The heuristic H-LAN from Fukaya & Daylamani-Zad (DOI 10.1080/10447318.2026.2632170)
says an AI-driven tool that lives inside a host should match that host's design
language — explicitly including "the ability to undo and redo changes", achieved
"through appropriate use of front-end UI APIs within the host software". Blender's
own front-end UI API is the global undo stack, so a chat turn that creates and
mutates scene objects must collapse to exactly ONE Ctrl+Z, the way a single manual
edit does. Cheap, complete reversal is also what lets the plan run without an
approval gate (D1): every step is reversible, so none needs a confirmation click.

WHY this mechanism, in order:

1. ``open()`` pushes ONE named restore point with ``bpy.ops.ed.undo_push`` while
   global undo is still ON, then flips ``preferences.edit.use_global_undo`` to
   ``False`` and remembers the previous value. The restore point is the step the
   user lands on when they hit Revert.

2. With global undo suppressed for the duration, the turn's own operators
   (``run_python``, mesh ops, material ops, ...) push nothing of their own, so
   the whole turn collapses to that single step regardless of how many operators
   it ran.

3. ``close()`` restores the remembered preference value. It is exception-safe
   and idempotent: a turn that raised, or that the user cancelled, must not leave
   Blender with global undo switched off. ``close()`` without a preceding
   ``open()`` is a no-op, not an error.

4. ``revert_turn()`` pops the restore point with ``bpy.ops.ed.undo()`` and
   reports whether the stack had something to undo; it returns ``False`` rather
   than raising when the stack is empty.

No errors are swallowed. If ``undo_push`` is unavailable the call site raises a
loud, specific message instead of degrading into an un-guarded turn.
"""

from __future__ import annotations

from dataclasses import dataclass

import bpy

__all__ = ["TurnUndoGuard", "revert_turn"]


class _UndoUnavailable(RuntimeError):
    """The host could not push a restore point, so the turn is un-guarded."""


@dataclass
class TurnUndoGuard:
    """One undo step per turn.

    ``open()`` pushes a named restore point and suppresses per-operator undo
    pushes for the duration; ``close()`` restores the user's preference. Use as a
    context manager or pair the calls in a ``try/finally``::

        guard = TurnUndoGuard("chat: user asked for a crate")
        guard.open()
        try:
            ...  # the turn's operators run here
        finally:
            guard.close()
    """

    message: str

    def __post_init__(self) -> None:
        if not self.message:
            raise ValueError("TurnUndoGuard.message must be a non-empty step label")
        self._prior_global_undo: bool | None = None

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> None:
        """Push one named restore point, then suppress per-operator pushes.

        Raises ``_UndoUnavailable`` (a ``RuntimeError``) loudly if the host
        cannot push a step — the turn must not run un-guarded in that case.
        """
        if self._prior_global_undo is not None:
            # Already open: re-opening would push a second restore point and
            # break the "one step per turn" invariant. Treat as a programming
            # error, not a silent no-op.
            raise RuntimeError("TurnUndoGuard.open() called twice without close()")
        try:
            undo_push = bpy.ops.ed.undo_push
        except AttributeError as exc:  # pragma: no cover — defensive
            raise _UndoUnavailable(
                f"bpy.ops.ed.undo_push is unavailable: {exc}. "
                f"Cannot guard turn {self.message!r} — refusing to run un-guarded."
            ) from exc
        undo_push(message=self.message)
        prefs_edit = bpy.context.preferences.edit
        self._prior_global_undo = bool(prefs_edit.use_global_undo)
        prefs_edit.use_global_undo = False

    def close(self) -> None:
        """Restore the remembered global-undo preference.

        Exception-safe and idempotent: a turn that raised, a turn that was
        cancelled, and ``close()`` with no preceding ``open()`` all leave the
        user's preference exactly as it was. Calling ``close()`` twice is the
        same as calling it once.
        """
        prior = self._prior_global_undo
        if prior is None:
            # Either open() was never called, or close() already ran. Not an
            # error: the guarantee is "global undo is never left off", and the
            # preference was never touched here.
            return
        self._prior_global_undo = None
        bpy.context.preferences.edit.use_global_undo = prior

    @property
    def is_open(self) -> bool:
        """True between ``open()`` and ``close()``."""
        return self._prior_global_undo is not None

    # -- context-manager sugar ----------------------------------------------

    def __enter__(self) -> TurnUndoGuard:
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
def revert_turn() -> bool:
    """Pop the turn's restore point.

    Returns ``True`` when Blender reported a successful undo, ``False`` when the
    stack was empty or the undo system is unavailable. Never raises on an empty
    stack: "nothing to undo" is a legitimate state for a Revert button, not an
    error. In ``--background`` the undo system is disabled at startup and
    ``bpy.ops.ed.undo()`` raises a poll-time ``RuntimeError``; that is the same
    "nothing to undo" condition from the caller's perspective, so it is mapped
    to ``False`` rather than propagated.
    """
    try:
        result = bpy.ops.ed.undo()
    except RuntimeError as exc:
        if "undo" in str(exc).lower():
            return False
        raise
    # ``bpy.ops.ed.undo`` returns a set of strings (e.g. {'FINISHED'}) on
    # success and an empty set when there was nothing to undo.
    return bool(result)