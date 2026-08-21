"""Blender version pin.

API drift between Blender series is the dominant failure mode for
agent-written bpy code (3DCodeBench: ~85% of failures for models below
the executability floor were 4.x->5.0 drift). Every session asserts the
series it is actually running against before any geometry is built.
"""

from __future__ import annotations

import os

# The Blender series this repo is written against. Bump deliberately,
# and grow drift/catalog.py in the same commit.
TARGET_BLENDER_SERIES: tuple[int, int] = (5, 0)

# Set to "1" to run against a different series anyway (e.g. a CI
# container that only has an older bpy wheel). Skew is allowed, silence
# about skew is not.
ALLOW_SKEW_ENVIRONMENT_VARIABLE = "BLENDED_ALLOW_VERSION_SKEW"


class BlenderVersionError(RuntimeError):
    """Raised when the running Blender series does not match the pin."""


def running_blender_series() -> tuple[int, int]:
    """Return the (major, minor) series of the bpy we are running inside."""
    import bpy

    return (bpy.app.version[0], bpy.app.version[1])


def assert_supported_blender() -> tuple[int, int]:
    """Assert the running Blender matches TARGET_BLENDER_SERIES.

    Returns the running series so callers can log it. Honors the skew
    override environment variable, but never silently.
    """
    running_series = running_blender_series()
    if running_series == TARGET_BLENDER_SERIES:
        return running_series
    if os.environ.get(ALLOW_SKEW_ENVIRONMENT_VARIABLE) == "1":
        print(
            f"blended: WARNING version skew allowed by env: "
            f"running {running_series}, pinned {TARGET_BLENDER_SERIES}"
        )
        return running_series
    raise BlenderVersionError(
        f"Running Blender series {running_series} but this repo is pinned to "
        f"{TARGET_BLENDER_SERIES}. Fix the environment, or export "
        f"{ALLOW_SKEW_ENVIRONMENT_VARIABLE}=1 to proceed knowingly."
    )
