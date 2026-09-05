"""Blender-facing UI helpers for the chat panel.

Every module in this package imports `bpy` at module scope: it exists so
the addon's single file does not have to own the panel's machinery, and
so that machinery can be tested inside a real Blender the way the rest
of `tests/blender` is. Nothing here may be imported from the pure test
layer.

The panel itself stays in `blender_addon/__init__.py` — Blender needs the
classes registered from the addon module — but the state behind it
(previews, per-turn undo, the workspace) lives here where it can be
asserted against.
"""
