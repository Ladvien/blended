"""Scene context: what the user has selected, wired into the conversation.

Selection is the second-largest family of user-guided controllability
techniques in generative-AI applications (DOI 10.48550/arXiv.2410.22370,
Luera et al. survey of UI design and interaction techniques). Blender
already provides world-class selection natively, so the harness wires the
existing selection into the prompt instead of adding widgets. This module
reads the live selection once, freezes it into an immutable snapshot, and
renders two views: a compact prompt block and a one-line panel summary.

Only ``collect_scene_context`` touches bpy, and only through the
``context`` parameter it receives — no bpy import lives in this module,
so the pure renderers can be exercised without a Blender runtime.

The depsgraph lags selection and transform assignment (the same trap
recorded in ``src/blended/harness.py``'s ``_synchronise_view_layer``),
so ``collect_scene_context`` calls ``context.view_layer.update()`` before
reading anything.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Named constants (no magic numbers) ---

#: Maximum number of selected objects carried in the snapshot and listed
#: by name in the rendered block. The overflow beyond this is reported
#: as a count, never silently dropped.
MAXIMUM_SELECTED_OBJECTS_LISTED = 8

#: Decimal places for dimensions and location.  The rendered block shows
#: this many digits after the point (``0.60`` not ``0.6``).
DIMENSION_DECIMALS = 2

#: Separator between the three dimension components in the rendered block.
DIMENSION_SEPARATOR = "×"

#: Separator between the three location components inside the parentheses.
LOCATION_SEPARATOR = ", "

#: The ellipsis character used to mark end-truncation in the panel line.
#: Matches ``_preview`` in ``blender_addon/__init__.py`` which established
#: the in-repo precedent: Blender clips overlong labels in the MIDDLE,
#: which loses the substance, so we cut at the END instead.
ELLIPSIS = "…"

#: Prefix marking the scene-context block in the rendered prompt text.
SCENE_PREFIX = "[scene]"


# --- Immutable snapshots ---


@dataclass(frozen=True)
class ObjectSnapshot:
    """One selected object, frozen at collection time."""

    name: str
    object_type: str
    dimensions_m: tuple[float, float, float]
    location_m: tuple[float, float, float]


@dataclass(frozen=True)
class SceneContext:
    """The whole scene state the agent needs, frozen at collection time.

    ``selected`` is capped at ``MAXIMUM_SELECTED_OBJECTS_LISTED`` entries
    (active object first, then the rest by name).  ``selected_total_count``
    carries the true count so the renderer can report overflow explicitly
    instead of silently truncating.
    """

    active_object_name: str  # "" when there is no active object
    selected: tuple[ObjectSnapshot, ...]
    selected_total_count: int
    mode: str  # "OBJECT", "EDIT_MESH", …
    total_object_count: int
    frame_current: int


# --- Collector (the ONLY bpy-touching function) ---


def collect_scene_context(context) -> SceneContext:
    """Read the live scene state into an immutable ``SceneContext``.

    Takes a ``bpy.types.Context``.  Calls ``context.view_layer.update()``
    first because the depsgraph lags selection and transform assignment
    (trap recorded in ``harness._synchronise_view_layer``).
    """
    # Sync the depsgraph before reading — load-bearing, same reason as
    # harness._synchronise_view_layer: an object linked or a transform
    # assigned in the preceding tick is absent from view_layer state
    # until the depsgraph catches up.
    context.view_layer.update()

    active_object = context.active_object
    active_name: str = active_object.name if active_object is not None else ""

    selected_objects = list(context.selected_objects)
    if active_object is not None and active_object in selected_objects:
        # Active first, then the rest sorted by name.
        selected_objects.remove(active_object)
        ordered = [active_object] + sorted(
            selected_objects, key=lambda obj: obj.name
        )
    else:
        ordered = sorted(selected_objects, key=lambda obj: obj.name)

    selected_total = len(ordered)
    capped = ordered[:MAXIMUM_SELECTED_OBJECTS_LISTED]

    snapshots = tuple(
        ObjectSnapshot(
            name=obj.name,
            object_type=obj.type,
            dimensions_m=tuple(
                round(value, DIMENSION_DECIMALS) for value in obj.dimensions
            ),
            location_m=tuple(
                round(value, DIMENSION_DECIMALS)
                for value in obj.matrix_world.translation
            ),
        )
        for obj in capped
    )

    return SceneContext(
        active_object_name=active_name,
        selected=snapshots,
        selected_total_count=selected_total,
        mode=context.mode,
        total_object_count=len(context.scene.objects),
        frame_current=context.scene.frame_current,
    )


# --- Pure renderers (no bpy) ---


def _format_dimensions(dims: tuple[float, float, float]) -> str:
    """``0.60×0.40×0.50 m`` — the documented precision and separator."""
    return (
        f"{dims[0]:.{DIMENSION_DECIMALS}f}"
        f"{DIMENSION_SEPARATOR}"
        f"{dims[1]:.{DIMENSION_DECIMALS}f}"
        f"{DIMENSION_SEPARATOR}"
        f"{dims[2]:.{DIMENSION_DECIMALS}f} m"
    )


def _format_location(loc: tuple[float, float, float]) -> str:
    """``(0.00, 0.00, 0.25)`` — the documented precision and separator."""
    return (
        f"({loc[0]:.{DIMENSION_DECIMALS}f}"
        f"{LOCATION_SEPARATOR}"
        f"{loc[1]:.{DIMENSION_DECIMALS}f}"
        f"{LOCATION_SEPARATOR}"
        f"{loc[2]:.{DIMENSION_DECIMALS}f})"
    )


def _format_selected(context: SceneContext) -> str:
    """The ``selected: …`` clause, with explicit overflow when capped."""
    names = [snap.name for snap in context.selected]
    overflow = context.selected_total_count - len(context.selected)
    if overflow > 0:
        return ", ".join(names) + f" {ELLIPSIS} (+{overflow} more)"
    return ", ".join(names)


def render_scene_context(context: SceneContext) -> str:
    """The block appended to the user's prompt.

    Compact, deterministic, machine-parseable-by-eye, e.g.::

        [scene] active=Crate 0.60×0.40×0.50 m at (0.00, 0.00, 0.25) | selected: Crate | mode OBJECT | 3 objects | frame 1

    Returns ``""`` when there is nothing worth saying: no active object,
    no selection, and an empty scene.  An empty string means the caller
    appends nothing.
    """
    if (
        not context.active_object_name
        and not context.selected
        and context.total_object_count == 0
    ):
        return ""

    parts: list[str] = [SCENE_PREFIX]

    if context.active_object_name:
        active_snapshot = next(
            (snap for snap in context.selected if snap.name == context.active_object_name),
            None,
        )
        if active_snapshot is not None:
            parts.append(
                f"active={active_snapshot.name} "
                f"{_format_dimensions(active_snapshot.dimensions_m)} "
                f"at {_format_location(active_snapshot.location_m)}"
            )
        else:
            # Active object exists but is not among the capped selection
            # snapshots — name it without dimensions.
            parts.append(f"active={context.active_object_name}")

    selected_str = _format_selected(context)
    if selected_str:
        parts.append(f"selected: {selected_str}")

    parts.append(f"mode {context.mode}")
    parts.append(f"{context.total_object_count} objects")
    parts.append(f"frame {context.frame_current}")

    return " | ".join(parts)


def summarize_scene_context(context: SceneContext, limit: int) -> str:
    """One line for the panel, cut at the END with an ellipsis.

    Blender clips overlong labels in the MIDDLE, which loses the
    substance (see ``_preview`` in ``blender_addon/__init__.py`` for the
    in-repo precedent).  This function cuts at the end so the leading
    information survives.

    Never returns more than ``limit`` characters.  Ends with the ellipsis
    exactly when the full rendered text was longer than ``limit``.
    """
    text = render_scene_context(context)
    if not text:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(ELLIPSIS):
        return ELLIPSIS[:limit]
    return text[: limit - len(ELLIPSIS)] + ELLIPSIS