"""What a tool call hands back to the loop (OT-5).

The model reads `text` and looks at `images`; the loop also needs
STRUCTURE the model never sees: which unlinked intermediates this call
created and which it resolved, so a turn cannot end with an operand
nobody linked, consumed or removed. Parsing that out of `text` would be
a second encoding of the harness's own output, so it travels beside it.
The structured transcript (OT-8) grows from here.

Pure: no Blender.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolOutcome:
    text: str
    images: tuple[Path, ...] = ()
    # Object names an UNGATED op created this call (unlinked intermediates).
    intermediates_created: tuple[str, ...] = ()
    # Object names a successful op call linked, consumed or removed —
    # every object-name parameter of the call. Applied BEFORE `created`.
    intermediates_resolved: tuple[str, ...] = ()
