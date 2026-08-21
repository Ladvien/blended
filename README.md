# blended

A Blender-based harness for agentic modeling of game assets.

The agent's artifact is a **program** (`Parameters` + `Builder` Python
modules), not a mesh. The harness's job is to make the environment tell
the truth: structured tracebacks with known-API-drift fixes attached, a
mesh analyzer as the hard acceptance gate, and multi-view captures for
inspection. Rendered critique advises; the analyzer decides.

## Layout

```
src/blended/
  version.py     Blender series pin (5.0) + skew assertion
  drift/         API drift catalog — grows with every instructive traceback
  ops/           reusable construction vocabulary (bmesh/data API, no bpy.ops)
  builders/      Parameters + Builder pairs (first prop: the crate)
  analyze/       the mesh analyzer — the hard gate
  capture/       front/right/top/three-quarter renders
  run/           executor: structured traceback capture, in-process & subprocess
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
