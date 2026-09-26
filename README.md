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

## Chat (Claude Code over MCP)

The agent is Claude Code driving Blender through the `blended` MCP
server: Blender Lab's `blender_mcp` (GPL-3.0-or-later, vendored as a git
subtree at `blender_mcp/`) extended to serve blended's full tool surface
(`TOOL_SCHEMAS`) through `dispatch_tool`, with the plan gate and a
schema-2 `logs/mcp-*.jsonl` per session.

```sh
make install-mcp-addon         # once: build + install the `mcp` extension,
                               # allow online access (its socket needs it)
open -a Blender                # the add-on listens on localhost:9876
claude                         # in this directory; .mcp.json registers
                               # .venv/bin/blender-mcp as server `blended`
```

The add-on executes any code sent to localhost:9876. blended is imported
once per Blender session from `src/`: after changing `src/blended`,
restart Blender.

## Run

```sh
make test-pure                 # any machine
make test-blender-app          # build → analyze → render, inside the
                               # installed Blender 5.2 (its own Python
                               # 3.13, bundled numpy, no pip)
make test-mcp                  # the MCP server's unit layer (no Blender)
make test-mcp-blender          # MCP client -> server -> real background
                               # Blender -> blended's dispatch_tool
make test                      # pure + Blender app + MCP unit; the gate
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
