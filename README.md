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
make install-mcp-addon         # once: symlink the `mcp` extension into Blender,
                               # enable it, allow online access (its socket needs it)
open -a Blender                # the add-on listens on localhost:9876
claude                         # in this directory; .mcp.json registers
                               # .venv/bin/blender-mcp as server `blended`
```

The add-on executes any code sent to localhost:9876.

**What the agent is told.** Claude Code delivers only the first 2,048
characters of an MCP server's instructions (measured: blended sends about
23,000). So the instructions open with a must-read head
(`MCP_INSTRUCTIONS_HEAD`) that condenses working-agreement revision 10;
the full text follows it. A test fails when the active revision moves,
so the head gets reviewed along with it.

**The user's view.** After every scene-changing blended call, the server
frames the objects that call touched in every 3D viewport. Their result
ends with a `viewport:` line saying what was framed, or why nothing was:
background Blender, no 3D viewport, or nothing in the scene yet. An
object made by `add_box` is framed once `link_into_scene` puts it in the
scene. Framing moves only the view's pivot and distance. Selection, the
active object, the mode and the view rotation stay as they were.
`make test-viewport-gui` checks the result against Blender's own
projection in a GUI Blender; a window opens for a few seconds.

**Source edits.** Edits under `src/blended` take effect on the next call
without restarting Blender: Blender purges and re-imports `blended` when
the call's source fingerprint changes. What the server loaded at start
stays until the server restarts: tools, descriptions, parameters,
defaults, plan gating (`reads_only`), the outcome wire format, any
`blmcp` edit, and the instructions. Until then the server lists tools,
gates calls and parses outcomes with that start-time code while Blender
runs the edited code.

Restarting on a source edit is opt-in: `--exit-on-source-change`, stdio
only. It is right only for a client that restarts a server that exits.
omp does, and `.omp/mcp.json` gives it its own `blended` entry with the
flag. Measured: omp spawned that entry, not the one in `.mcp.json`. The
server exits once the sources have held still for 2 s, no call is in
flight, and the last response has had 2 s to drain. Before exiting, it
leaves the declared plan and the session-log name in
`logs/mcp-handoff-<client pid>.json`. The client's next server consumes
that file, keeps the plan, and appends to the same log. A handoff older
than 60 s, or a malformed one, is refused on stderr.

Claude Code (`.mcp.json`) and Claude Desktop
(`~/Library/Application Support/Claude/claude_desktop_config.json`, entry
`blended`) run without the watcher, because neither restarts a stdio
server that exits. After an edit to anything loaded at start, run `/mcp`
in Claude Code, or quit and reopen Desktop (⌘Q). Add-on edits
(`blender_mcp/addon`) still need a Blender restart. `.omp/mcp.json` also
disables any same-named `blender` server that omp would import from
another tool's config (e.g. `uvx blender-mcp` in `~/.claude.json`),
since it would talk to the same port.

## Run

```sh
make test-pure                 # any machine
make test-blender-app          # build → analyze → render, inside the
                               # installed Blender 5.2 (its own Python
                               # 3.13, bundled numpy, no pip)
make test-mcp                  # the MCP server's unit layer (no Blender)
make test-mcp-blender          # MCP client -> server -> real background
                               # Blender -> blended's dispatch_tool
make test-viewport-gui         # viewport framing in a GUI Blender (opens
                               # a window for a few seconds)
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
