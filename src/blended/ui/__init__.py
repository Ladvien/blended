"""Blender-facing UI helpers for the chat panel.

Almost every module in this package imports `bpy` at module scope: it
exists so the addon's single file does not have to own the panel's
machinery, and so that machinery can be tested inside a real Blender
the way the rest of `tests/blender` is.

There are exactly two exceptions, and they are the only modules here
that `tests/pure` may import: `transcript_style` (the GPU overlay's
parameters) and `transcript_layout` (its arithmetic). Both are pure
Python by contract — no `bpy`, no `gpu`, no `blf` — because the
overlay's wrapping, capping, stacking and scrolling are worth testing
without a GL context. `transcript_overlay`, which rasterises what they
compute, is not pure and belongs to the Blender layer like the rest.
This `__init__.py` stays code-free so importing either pure module
cannot drag `bpy` in through the package.

The panel itself stays in `blender_addon/__init__.py` — Blender needs the
classes registered from the addon module — but the state behind it
(previews, per-turn undo, the workspace) lives here where it can be
asserted against.
"""
