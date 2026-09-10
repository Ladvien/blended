"""Derive and pin the core op set from the iteration log (OT-25).

    .venv/bin/python scripts/derive_core_tools.py
    .venv/bin/python scripts/derive_core_tools.py --check   # exit 2 if the pin drifted
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from blended.agent.tool_disclosure import (
    CORE_PIN_PATH,
    MINIMUM_BRIEFS_USING_OP,
    derive_core_ops,
    read_core_pin,
    write_core_pin,
)


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--log", default=str(REPOSITORY_ROOT / "_evaluate" / "iterations.jsonl"))
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    records = [json.loads(line) for line in Path(arguments.log).read_text().splitlines() if line.strip()]
    core = derive_core_ops(records)
    counts: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if record.get("form_gate_passed") and record.get("tool_events"):
            for event in record["tool_events"]:
                if event.get("ok"):
                    counts[event["tool_name"]].add(record["brief_name"])
    brief_counts = {name: len(counts[name]) for name in core}
    print(f"[core] threshold >= {MINIMUM_BRIEFS_USING_OP} briefs; {len(core)} op(s): " + ", ".join(f"{n} ({brief_counts[n]})" for n in core))
    pin_path = REPOSITORY_ROOT / CORE_PIN_PATH
    if arguments.check:
        pinned = read_core_pin(pin_path)
        if pinned != core:
            print(f"[core] pin drifted: pinned {pinned} vs derived {core}", file=sys.stderr)
            return 2
        print("[core] pin matches the derivation")
        return 0
    write_core_pin(core, brief_counts, pin_path)
    print(f"[core] wrote {pin_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
