"""One execution path per operation, enforced rather than remembered.

`uv.smart_unwrap` sat in the vocabulary as a "backwards-compatible
shim" over `unwrap_uvs` — a second path to the same result, found by
reading the generated manifest rather than by any test failing. It was
deleted on 2026-08-22. This is what would have caught it.

The check is deliberately crude: it reads the docstrings the manifest
publishes to the agent and fails on the words a compatibility branch
announces itself with. A shim that hides its nature well enough to pass
this is a different problem; one that says "shim" in the sentence the
agent is shown is exactly this one.
"""

import importlib

import pytest

from blended.manifest import OP_MODULE_NAMES, _public_functions

# The vocabulary an agent is handed. Every entry must be the only way
# to do what it does — see CLAUDE.md, one path per feature.
FORBIDDEN_DOCSTRING_MARKERS = (
    "shim",
    "backwards-compatible",
    "backward-compatible",
    "deprecated",
    "legacy",
    "for compatibility",
    "fallback",
)


def _all_operations():
    for module_name in OP_MODULE_NAMES:
        module = importlib.import_module(f"blended.ops.{module_name}")
        for signature, summary in _public_functions(module):
            yield module_name, signature, summary


def test_the_op_vocabulary_is_not_empty():
    """Guards the guard: an import slip would pass everything below."""
    assert len(list(_all_operations())) > 10


@pytest.mark.parametrize("marker", FORBIDDEN_DOCSTRING_MARKERS)
def test_no_operation_advertises_a_second_path(marker):
    offenders = [
        f"blended.ops.{module_name}.{signature.split('(')[0]}: {summary}"
        for module_name, signature, summary in _all_operations()
        if marker in summary.lower()
    ]
    assert not offenders, (
        f"operation docstrings mention {marker!r}, which is how a "
        f"compatibility branch announces itself: {offenders}. One path "
        f"per feature — delete the shim and make the primary right."
    )
