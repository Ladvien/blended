"""Wipe the scene to a canonical empty state, then assert the wipe took.

A rebuild that starts from residue measures the previous build. scp's
harness learned this twice: Blender's undo stack is unreliable from
script-driven operators, so `ui/turn_undo.py`'s GUI path is not a
mechanism a rebuild may trust, and a wipe that is not asserted is a
wipe that silently left an object behind — after which every count,
extent and digest in the run belongs to two builds at once.

So this module does two separable things, and the postcondition is the
important half: `reset_scene()` wipes, `assert_clean_scene()` proves it.
Anything that rebuilds (the metamorphic probe, the reproducibility
digest) calls the assertion, not just the wipe.

Frames per second belongs in a *reset* for one measured reason: the FBX
importer rewrites `scene.render.fps` on load, which resamples every clip
already in the scene. A canonical fps is therefore part of "clean", and
`CANONICAL_FPS` is the number to save and restore around any import that
touches it (see `blended.drift.catalog`).

MAIN THREAD ONLY: everything below touches bpy.
"""

from __future__ import annotations

CANONICAL_FPS = 24

# Wiped in dependency order: objects before the data they reference, so
# removing a mesh never trips a user count that an object still holds.
WIPE_COLLECTIONS = (
    "objects",
    "meshes",
    "armatures",
    "curves",
    "metaballs",
    "volumes",
    "grease_pencils",
    "materials",
    "images",
    "cameras",
    "lights",
    "lightprobes",
    "speakers",
    "actions",
    "particles",
    "collections",
)

# Materials and images are deliberately NOT required to be empty: a live
# GUI session holds an unremovable "Render Result" / "Viewer Node" image,
# and default materials regenerate. Requiring them would make the
# assertion fail in the GUI and pass headless, which is worse than not
# checking them.
MUST_BE_EMPTY = ("objects", "meshes", "armatures", "collections")

# A failure lists the leftover datablocks by name, because "3 objects
# remain" sends the reader back to the console. Capped so a wipe that
# left 4,000 objects behind does not produce a 4,000-name message.
LEFTOVER_NAMES_REPORTED = 10


class SceneNotClean(RuntimeError):
    """The wipe did not take, or the scene is not in canonical state."""


def reset_scene(fps: int = CANONICAL_FPS) -> None:
    """Wipe to an empty canonical scene, then assert the wipe took.

    Every name in WIPE_COLLECTIONS must resolve on bpy.data: a renamed
    collection is a loud failure surfaced by assert_clean_scene, not a
    silent skip, because a silent skip is how a whole datablock class
    stops being wiped forever.  Measured in Blender 5.2.0: the RNA
    collection is named ``grease_pencils`` (type BlendDataGreasePencilsV3),
    NOT ``grease_pencils_v3`` — the latter was never a bpy.data attribute
    and the row was dead until this fix.
    """
    import bpy

    missing = [
        name
        for name in WIPE_COLLECTIONS
        if getattr(bpy.data, name, None) is None
    ]
    if missing:
        raise SceneNotClean(
            f"bpy.data has no collection(s): {', '.join(missing)} — "
            f"a wipe-list name does not resolve; update WIPE_COLLECTIONS"
        )

    for collection_name in WIPE_COLLECTIONS:
        collection = getattr(bpy.data, collection_name)
        for datablock in list(collection):
            collection.remove(datablock)

    # Removal drops the direct users; the purge collects what those
    # datablocks referenced in turn (node groups, node trees, actions).
    bpy.data.orphans_purge(
        do_local_ids=True, do_linked_ids=True, do_recursive=True
    )

    bpy.context.scene.render.fps = fps
    assert_clean_scene(fps)


def assert_clean_scene(fps: int = CANONICAL_FPS) -> None:
    """Raise SceneNotClean listing EVERY problem at once.

    One problem per raise would make a caller fix, re-run, and discover
    the next one — three Blender launches to learn what one message can
    say.
    """
    import bpy

    problems: list[str] = []

    for collection_name in MUST_BE_EMPTY:
        collection = getattr(bpy.data, collection_name, None)
        if collection is None:
            problems.append(f"bpy.data has no {collection_name!r} collection")
            continue
        leftover = [datablock.name for datablock in collection]
        if leftover:
            shown = ", ".join(leftover[:LEFTOVER_NAMES_REPORTED])
            if len(leftover) > LEFTOVER_NAMES_REPORTED:
                shown += f", +{len(leftover) - LEFTOVER_NAMES_REPORTED} more"
            problems.append(f"{len(leftover)} {collection_name} remain: {shown}")

    scene_fps = bpy.context.scene.render.fps
    if scene_fps != fps:
        problems.append(
            f"scene.render.fps is {scene_fps}, not the canonical {fps}: "
            f"an FBX import rewrites it and resamples every clip"
        )

    # A scene that cannot be evaluated is not clean, it is broken: every
    # measurement downstream reads `evaluated_get` and would return
    # stored values with no error.
    try:
        bpy.context.view_layer.update()
        bpy.context.evaluated_depsgraph_get()
    except Exception as error:  # noqa: BLE001 — reported, not raised
        problems.append(f"depsgraph will not evaluate: {error}")

    if problems:
        raise SceneNotClean("; ".join(problems))
