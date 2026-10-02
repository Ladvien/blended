"""Keep the part being worked on in the user's 3D viewport (MCP only).

The MCP bridge calls `follow_viewport` after every scene-changing tool
call, so a user watching Blender sees the object the agent just touched
without the agent spending a tool call on it. The bench never imports
this: it runs headless, with no viewport and no one watching.

Framing moves each 3D viewport's pivot (`view_location`) to the centre
of the touched objects' world bounding sphere and sets `view_distance`
so that sphere fits. The fit reads Blender's own projection
(`RegionView3D.window_matrix`) instead of rebuilding it from lens and
sensor constants. Selection, the active object, the mode and the view
rotation are never touched: a later operator sees the state the agent
left. The ground truth is `make test-viewport-gui`, where every corner
of each framed bounding box must project inside the region.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

from blended.agent.outcome import ToolOutcome

VIEWPORT_LINE_PREFIX = "viewport:"
_VIEW_3D_AREA_TYPE = "VIEW_3D"
_WINDOW_REGION_TYPE = "WINDOW"
_CAMERA_PERSPECTIVE = "CAMERA"
_PERSPECTIVE = "PERSP"
_ORTHOGRAPHIC = "ORTHO"


@dataclass(frozen=True)
class ViewportFollowConfig:
    # The bounding sphere's radius is scaled by this before it is fitted,
    # leaving room around the part.
    margin_factor: float = 1.15
    # In perspective, the eye stays at least this many clip_starts in
    # front of the sphere's near side, so a tiny part is not cut by the
    # near clip plane.
    near_clearance_per_clip_start: float = 2.0


@dataclass(frozen=True)
class ViewportFraming:
    """What one framing pass did; `line` is what the agent reads."""

    framed_names: tuple[str, ...]
    viewport_count: int
    line: str


def frame_target_names(outcome: ToolOutcome) -> tuple[str, ...]:
    """The objects a call touched: every gated object, then every object
    named in an object-name parameter, de-duplicated, in order. Whether
    each is in the scene is decided in Blender."""
    names = [gate["object_name"] for gate in outcome.gates if gate["object_name"]]
    names.extend(outcome.intermediates_resolved)
    return tuple(dict.fromkeys(names))


def follow_viewport(outcome: ToolOutcome, config: ViewportFollowConfig = ViewportFollowConfig()) -> ToolOutcome:
    """The outcome with a `viewport:` line appended after framing what it
    touched. A framing error is reported on that line, not raised: the
    tool call already changed the scene, and an error result would invite
    the agent to repeat it."""
    try:
        line = frame_in_viewports(frame_target_names(outcome), config).line
    except Exception as error:  # pylint: disable=broad-exception-caught
        line = f"{VIEWPORT_LINE_PREFIX} FAILED to frame: {type(error).__name__}: {error}"
    return dataclasses.replace(outcome, text=f"{outcome.text}\n{line}")


def frame_in_viewports(
    names: tuple[str, ...], config: ViewportFollowConfig = ViewportFollowConfig()
) -> ViewportFraming:
    """Frame the named objects that are in a window's view layer in every
    3D viewport of that window. MAIN THREAD ONLY."""
    import bpy

    if bpy.app.background:
        return ViewportFraming((), 0, f"{VIEWPORT_LINE_PREFIX} not framed: background Blender has no viewport")

    framed: dict[str, None] = {}
    viewport_count = 0
    open_viewport_count = 0
    for window in bpy.context.window_manager.windows:
        areas = [area for area in window.screen.areas if area.type == _VIEW_3D_AREA_TYPE]
        open_viewport_count += len(areas)
        view_layer = window.view_layer
        targets = [bpy.data.objects[name] for name in names if name in view_layer.objects]
        if not targets or not areas:
            continue
        center, radius_m = _bounding_sphere(targets, view_layer.depsgraph)
        for area in areas:
            _fit_area(area, center, radius_m, config)
            viewport_count += 1
        framed.update(dict.fromkeys(target.name for target in targets))

    if open_viewport_count == 0:
        line = f"{VIEWPORT_LINE_PREFIX} not framed: no 3D viewport is open"
    elif not framed:
        line = f"{VIEWPORT_LINE_PREFIX} unchanged: nothing this call touched is in the scene yet"
    else:
        line = f"{VIEWPORT_LINE_PREFIX} framed {', '.join(framed)} in {viewport_count} 3D viewport(s)"
    return ViewportFraming(tuple(framed), viewport_count, line)


def _bounding_sphere(targets, depsgraph):
    """Centre and radius (m) of the world-space sphere around the targets'
    evaluated bounding boxes (modifiers included)."""
    from mathutils import Vector

    corners = []
    for target in targets:
        evaluated = target.evaluated_get(depsgraph)
        corners.extend(evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box)
    low = Vector(tuple(min(corner[axis] for corner in corners) for axis in range(3)))
    high = Vector(tuple(max(corner[axis] for corner in corners) for axis in range(3)))
    center = (low + high) / 2.0
    radius_m = max((corner - center).length for corner in corners)
    return center, radius_m


def _fit_area(area, center, radius_m: float, config: ViewportFollowConfig) -> None:
    space = area.spaces.active
    region_3d = space.region_3d
    if region_3d.view_perspective == _CAMERA_PERSPECTIVE:
        region_3d.view_perspective = _PERSPECTIVE
    # The projection of the perspective now in force, not a stale camera one.
    region_3d.update()
    projection = region_3d.window_matrix
    fitted_radius_m = radius_m * config.margin_factor
    if region_3d.view_perspective == _ORTHOGRAPHIC:
        # An ortho view's half extents grow linearly with view_distance.
        half_extent_per_distance = min(1.0 / projection[0][0], 1.0 / projection[1][1]) / region_3d.view_distance
        distance_m = fitted_radius_m / half_extent_per_distance
    else:
        # The narrower field of view decides; the sphere is tangent to it.
        half_angle_rad = math.atan(min(1.0 / projection[0][0], 1.0 / projection[1][1]))
        distance_m = max(
            fitted_radius_m / math.sin(half_angle_rad),
            fitted_radius_m + space.clip_start * config.near_clearance_per_clip_start,
        )
    region_3d.view_location = center
    region_3d.view_distance = distance_m
    area.tag_redraw()
