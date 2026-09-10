"""OT-25: the core op set is derived from gate-passing runs and pinned;
the offered set is service tools + readers + core; its fingerprint moves
when it changes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from blended.agent.tool_disclosure import (
    CORE_PIN_PATH,
    MINIMUM_BRIEFS_USING_OP,
    derive_core_ops,
    offered_fingerprint,
    offered_tools,
    read_core_pin,
    reader_ops,
    write_core_pin,
)
from blended.agent.tools import (
    SERVICE_TOOL_NAMES,
    TOOL_SCHEMAS,
    TOOL_SCHEMAS_FINGERPRINT,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _record(brief, passed, *events):
    return {"brief_name": brief, "form_gate_passed": passed, "tool_events": [{"tool_name": n, "ok": ok} for n, ok in events]}


def test_the_core_is_scene_changing_ops_used_in_enough_passing_briefs():
    assert MINIMUM_BRIEFS_USING_OP == 2
    records = [
        _record("a", True, ("add_box", True), ("rig_report", True), ("boolean_union", True)),
        _record("b", True, ("add_box", True), ("boolean_union", False)),
        _record("c", False, ("boolean_union", True), ("add_lathe", True)),  # failed the gate: no vote
        _record("d", True, ("add_lathe", True)),
    ]
    assert derive_core_ops(records) == ("add_box",)  # boolean_union: one passing brief succeeded; rig_report: a reader


def test_the_pin_equals_the_derivation_from_the_real_log():
    records = [json.loads(l) for l in (REPOSITORY_ROOT / "_evaluate" / "iterations.jsonl").read_text().splitlines() if l.strip()]
    assert read_core_pin(REPOSITORY_ROOT / CORE_PIN_PATH) == derive_core_ops(records)


def test_the_offered_set_is_service_readers_and_core_and_is_fingerprinted():
    core = ("add_box", "link_into_scene")
    offered = offered_tools(TOOL_SCHEMAS, core, SERVICE_TOOL_NAMES)
    names = [t["function"]["name"] for t in offered]
    assert set(names) == set(SERVICE_TOOL_NAMES) | set(reader_ops()) | set(core)
    assert "boolean_union" not in names and "search_ops" in names
    assert offered_fingerprint(offered) != TOOL_SCHEMAS_FINGERPRINT
    assert offered_fingerprint(offered) == offered_fingerprint(offered_tools(TOOL_SCHEMAS, core, SERVICE_TOOL_NAMES))


def test_a_missing_pin_is_loud_and_the_writer_round_trips(tmp_path):
    with pytest.raises(FileNotFoundError, match="never assumed"):
        read_core_pin(tmp_path / "none.txt")
    write_core_pin(("add_box", "link_into_scene"), {"add_box": 3, "link_into_scene": 5}, tmp_path / "pin.txt")
    assert read_core_pin(tmp_path / "pin.txt") == ("add_box", "link_into_scene")
