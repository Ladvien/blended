# blended

A Blender-based harness for agentic modeling of game assets.

The agent's artifact is a **program** (`Parameters` + `Builder` Python
modules), not a mesh. The harness's job is to make the environment tell
the truth: structured tracebacks with known-API-drift fixes attached, a
mesh analyzer as the hard acceptance gate, and multi-view captures for
inspection. Rendered critique advises; the analyzer decides.

## One call

```python
from blended.builders import BarrelBuilder, BarrelParameters
from blended.harness import HarnessSettings, run_builder

result = run_builder(
    BarrelBuilder(BarrelParameters()),
    HarnessSettings(export_glb_path="out/barrel.glb"),
)
print(result.summary())  # execute -> gate -> contact sheet -> verified export
```

`run_chunk(source, object_name, fix_source=...)` is the same loop for
agent-written code: tracebacks come back annotated with known API-drift
fixes, retries are capped at 2, and every attempt lands in the session
log. Failures still produce a contact sheet — a failure you cannot
review is a failure you will repeat.

## Layout

```
src/blended/
  harness.py     run_chunk / run_builder - the one-call loop
  version.py     Blender series pin (5.2) + skew assertion
  reset.py       wipe to a canonical empty scene, with the wipe ASSERTED
  drift/         API drift catalog — grows with every instructive traceback
  ops/           reusable construction vocabulary (bmesh/data API, no bpy.ops)
  builders/      Parameters + Builder pairs (first prop: the crate)
  analyze/       the mesh analyzer (the hard gate) + metamorphic relations
  capture/       front/right/top/three-quarter renders
  run/           executor, retry loop, JSONL session log
  ingest/        GLB import + bounded cleanup (the generated-mesh lane)
  export/        glTF export with welded round-trip verification
  evaluate/      briefs, acceptance, mistake memory, reproducibility digest
tests/pure/      no Blender required, runs anywhere
tests/blender/   requires `import bpy` (pip wheel or Blender's Python)
docs/            roadmap + research
```

## Run

```sh
make test-pure                 # any machine
make test-blender-app          # build → analyze → render, inside the
                               # installed Blender 5.2 (its own Python
                               # 3.13, bundled numpy, no pip)
make test                      # both layers; this is the gate
make test-repro ARGS="--builder barrel"
                               # build twice in two fresh Blenders under
                               # different PYTHONHASHSEED; identical
                               # semantic digests or exit 1
```

`make test-blender` runs the same Blender-tier suite against a
pip-installed `bpy` wheel instead. It needs a venv whose Python matches
the wheel's (Blender 5.2 is cp313; this repo's `.venv` is 3.11, so
`pip install bpy` there cannot produce 5.2), and a bare run with no
wheel collects nothing and exits 5 — which is not a pass.

## Read

- `docs/2026-08-21-harness-roadmap.md` — the staged plan and design commitments.
- `docs/research/2026-08-20-agentic-blender-game-asset-harness-research.md` — the evidence.
