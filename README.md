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
  version.py     Blender series pin (5.0) + skew assertion
  drift/         API drift catalog — grows with every instructive traceback
  ops/           reusable construction vocabulary (bmesh/data API, no bpy.ops)
  builders/      Parameters + Builder pairs (first prop: the crate)
  analyze/       the mesh analyzer — the hard gate
  capture/       front/right/top/three-quarter renders
  run/           executor, retry loop, JSONL session log
  ingest/        GLB import + bounded cleanup (the generated-mesh lane)
  export/        glTF export with welded round-trip verification
tests/pure/      no Blender required, runs anywhere
tests/blender/   requires `import bpy` (pip wheel or Blender's Python)
docs/            roadmap + research
```

## Run

```sh
make test-pure                 # any machine
pip install bpy                # Blender 5.0 as a module (Python 3.11)
make test-blender              # build → analyze → render, end to end
```

## Read

- `docs/2026-08-21-harness-roadmap.md` — the staged plan and design commitments.
- `docs/research/2026-08-20-agentic-blender-game-asset-harness-research.md` — the evidence.
