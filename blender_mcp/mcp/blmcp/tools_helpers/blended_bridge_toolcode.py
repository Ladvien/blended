# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tool-code for dispatching one blended tool inside Blender.

Runs in Blender's Python via the add-on's main-thread exec, which is what
``blended.agent.tools.dispatch_tool`` requires (it asserts the main
thread). blended is imported from the repository's ``src`` directory,
with the repository's venv site-packages behind it, the same order as
``blended.evaluate.bench_bridge.prelude``. blended modules are imported
once per Blender session: after changing ``src/blended``, restart Blender.

References: MCP (DOI 10.48550/arXiv.2503.23278);
LL3M, agentic Blender code generation (DOI 10.48550/arXiv.2508.08228).
"""

__all__ = (
    "Params",
    "Result",
    "main",
)

import json
import sys
from pathlib import Path
from typing import Any, NamedTuple


class Params(NamedTuple):
    tool_name: str
    arguments_json: str
    output_directory: str
    repository_src: str
    venv_site_packages: str


class Result(NamedTuple):
    status: str
    outcome: dict[str, Any]


def main(params: Params) -> Result:
    # Site-packages first, then src, each at the front: src ends up first.
    for path in (params.venv_site_packages, params.repository_src):
        if path not in sys.path:
            sys.path.insert(0, path)

    import blended  # pylint: disable=import-outside-toplevel

    loaded = str(Path(blended.__file__).resolve().parent.parent)
    if loaded != params.repository_src:
        raise RuntimeError(
            "Blender imported blended from {:s}, not {:s}: a stale copy is loaded "
            "(the removed blended_agent add-on?). Disable it and restart Blender.".format(
                loaded, params.repository_src,
            )
        )

    # pylint: disable-next=import-outside-toplevel
    from blended.agent.outcome import outcome_to_json
    # pylint: disable-next=import-outside-toplevel
    from blended.agent.tools import dispatch_tool

    outcome = dispatch_tool(
        params.tool_name,
        json.loads(params.arguments_json),
        Path(params.output_directory),
    )
    return Result("ok", outcome_to_json(outcome))
