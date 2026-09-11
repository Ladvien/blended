"""Can the writer READ proportions it does not BUILD? A dev-set probe.

`bench_proportion_headroom.py` says the built assets miss the reference's
middle and thin axes by a per-instance bias. Two mechanisms fit that, and
they call for different fixes:

  prompt -> intent   the writer cannot tell from the text what the ratios
                     are; a gate can only make the miss visible;
  intent -> built    the writer knows the ratios and builds something
                     else; a gate that measures the built extents against
                     the writer's own commitment closes the gap.

This asks the writer, text only, one question per DEV instance (BEN-8:
the holdout is for ranking, never for probing): the extent ratios
largest : middle : smallest, with the prompt words that justify them. The
answer's log2 error against the reference's own-frame extents is then
put beside the BUILT asset's error from the headroom JSON for the same
instances. If the stated ratios are closer than the built ones, the
contract has something to hold the writer to.

One text-only call per instance on the daemon lane; no scene, no eye.

    python3 scripts/bench_proportion_probe.py \
      --bench-root /Users/ladvien/3dcodebench \
      --instances-file bench_sets/instances_dev_sweep.txt \
      --headroom-json outputs/bench/proportion_headroom_dev_iter3.json \
      --json outputs/bench/proportion_probe_dev.json \
      --out outputs/bench/proportion_probe_dev.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_proportion_headroom import N_POINTS, SEED, extents_at_percentiles  # noqa: E402
from bench_surface_metrics import pca_frame  # noqa: E402

DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_WRITER = "deepseek-v4-pro:cloud"
# A text-only answer is short; this is the same read ceiling the loop
# gives the cloud lane (loop.REQUEST_TIMEOUT_SECONDS), stated here so the
# probe cannot silently wait longer than a real turn may.
REQUEST_TIMEOUT_SECONDS = 300

QUESTION = (
    "You will model this object in Blender. Before building anything, commit "
    "to its overall proportions.\n\nDescription:\n{description}\n\n"
    "Answer with ONE JSON object and nothing else: "
    '{{"largest": 1.0, "middle": <ratio>, "smallest": <ratio>, '
    '"evidence": "<the words from the description that fix these ratios, '
    'verbatim, or unstated>"}}. '
    "The ratios are the object's three bounding-box extents sorted largest to "
    "smallest, each divided by the largest, so 1.0 >= middle >= smallest > 0. "
    "Think about the real object's shape, not the rendering."
)
JSON_OBJECT = re.compile(r"\{.*\}", re.S)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--instances-file", required=True)
    parser.add_argument("--headroom-json", required=True, help="the BUILT side")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--writer", default=DEFAULT_WRITER)
    parser.add_argument("--json", default="")
    parser.add_argument("--out", default="")
    return parser.parse_args(argv)


def reference_ratios(sc, glb: Path):
    """(largest, middle, smallest) / largest of the reference in its OWN frame."""
    rng = np.random.default_rng(SEED)
    points = sc.normalize_unit_sphere(sc.load_mesh_points(glb, N_POINTS, rng))
    extents = np.sort(extents_at_percentiles(points @ pca_frame(points)))[::-1]
    return extents / extents[0]


def ask(endpoint: str, writer: str, description: str) -> dict:
    payload = {
        "model": writer,
        "stream": False,
        "messages": [{"role": "user", "content": QUESTION.format(description=description)}],
    }
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["message"]["content"]
    match = JSON_OBJECT.search(content)
    if match is None:
        raise ValueError(f"no JSON object in the writer's answer: {content[:200]!r}")
    answer = json.loads(match.group(0))
    ratios = np.array([float(answer["largest"]), float(answer["middle"]), float(answer["smallest"])])
    if not (ratios[0] == 1.0 and ratios[0] >= ratios[1] >= ratios[2] > 0):
        raise ValueError(f"ratios are not 1 >= middle >= smallest > 0: {ratios.tolist()}")
    return {"ratios": ratios, "evidence": str(answer.get("evidence", ""))}


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    sys.path.insert(0, str(bench_root / "metrics"))
    import shape_chamfer as sc  # the scorer's sampling and normalisation

    built = {row["instance"]: row for row in json.loads(Path(arguments.headroom_json).read_text())}
    rows = []
    for instance in Path(arguments.instances_file).read_text().split():
        description = (bench_root / "data" / instance / "prompt_description.txt").read_text().strip()
        reference = reference_ratios(sc, bench_root / "data" / instance / "glb" / f"{instance}.glb")
        stated = ask(arguments.endpoint, arguments.writer, description)
        errors = np.abs(np.log2(reference / stated["ratios"]))
        row = {
            "instance": instance,
            "reference_ratios": reference.round(3).tolist(),
            "stated_ratios": stated["ratios"].round(3).tolist(),
            "evidence": stated["evidence"],
            "stated_log2_error_middle": float(errors[1]),
            "stated_log2_error_smallest": float(errors[2]),
            "built_log2_error_middle": built[instance]["log2_error_middle"] if instance in built else None,
            "built_log2_error_smallest": built[instance]["log2_error_smallest"] if instance in built else None,
        }
        rows.append(row)
        print(
            f"{instance}: ref {row['reference_ratios']} stated {row['stated_ratios']} "
            f"| err M/S stated {errors[1]:.2f}/{errors[2]:.2f} "
            f"built {row['built_log2_error_middle']}/{row['built_log2_error_smallest']}",
            flush=True,
        )
    if arguments.json:
        Path(arguments.json).write_text(json.dumps(rows, indent=1))
    paired = [r for r in rows if r["built_log2_error_middle"] is not None]
    stated_m = np.mean([r["stated_log2_error_middle"] for r in paired])
    stated_s = np.mean([r["stated_log2_error_smallest"] for r in paired])
    built_m = np.mean([r["built_log2_error_middle"] for r in paired])
    built_s = np.mean([r["built_log2_error_smallest"] for r in paired])
    lines = [
        "# Proportion probe: stated versus built, dev set",
        "",
        f"- instances paired: {len(paired)} (writer {arguments.writer})",
        f"- mean |log2 error|, middle axis: stated {stated_m:.3f} vs built {built_m:.3f}",
        f"- mean |log2 error|, smallest axis: stated {stated_s:.3f} vs built {built_s:.3f}",
        "",
        "| instance | reference L:M:S | stated | evidence | stated err M/S | built err M/S |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['instance']} | {r['reference_ratios']} | {r['stated_ratios']} | "
            f"{r['evidence'][:60]} | {r['stated_log2_error_middle']:.2f}/{r['stated_log2_error_smallest']:.2f} | "
            f"{r['built_log2_error_middle']:.2f}/{r['built_log2_error_smallest']:.2f} |"
            if r["built_log2_error_middle"] is not None else
            f"| {r['instance']} | {r['reference_ratios']} | {r['stated_ratios']} | {r['evidence'][:60]} | "
            f"{r['stated_log2_error_middle']:.2f}/{r['stated_log2_error_smallest']:.2f} | – |"
        )
    report = "\n".join(lines) + "\n"
    if arguments.out:
        Path(arguments.out).write_text(report)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
