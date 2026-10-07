# ISSUES.md — open findings from the full-repo review of 2026-10-07

Branch `review/full-repo-2026-10-07`. Every slice of the repo was read by a
reviewer (19 slices: `src/blended`, `tests/`, `scripts/`, the vendored
`blender_mcp/` subtree, docs). Defects with a fix that needed no sign-off were
fixed in the same branch, each with a regression test and a record in
`src/blended/evaluate/mistake_memory.py`. This file lists only what is
**still open**: things that need a decision, a rotation, a re-pin, or a
measurement. It replaces the 2026-09-19 review: its M2, M3, Mi1, Mi2, Mi3, I1
and I2 are fixed in this branch, M1 went with the deleted streamed transport,
and Mi4 (a split report bullet) and I3 (an optional design row) were
cosmetic and are not carried over.

Baseline before the review: pure 713 passed / 2 skipped / 1 xfailed; Blender
247 passed / 1 skipped; `mypy src` 54 errors. After: see the commit message.

## Needs the owner (outside the repo)

### S1 — A live API key is in a public repository's history
`tests/pure/test_openai_transport.py` carried the real bmb llama-swap key (64
hex) since commit `1c65544` ("Working"). The repository is PUBLIC
(`gh repo view`: `visibility PUBLIC`). The working tree no longer has it, but
the key is still in history and must be treated as exposed.
**Action:** add a new key to `apiKeys:` in bmb's `~/llm/llama-swap.yaml`,
re-mint `~/.blended/bmb_api_key`, delete the old entry. A history rewrite is a
separate, destructive decision and was not done. The key's host is a LAN
address (`192.168.1.233`), which limits who can use it; it does not make it
safe to leave. A scan of all history for provider-format tokens (GitHub, AWS,
Anthropic, `sk-`, Ollama `hex.alnum`) found nothing else.

## Security decisions

### S2 — MCP HTTP transport has no DNS-rebinding protection, CORS `*`, no auth
`blender_mcp/mcp/blmcp/__init__.py:73-130`. With `run_python` this is code
execution in Blender for any page that can reach the port; `--host 0.0.0.0`
exposes it to the LAN. Upstream behaviour, opt-in (stdio is the default and is
what `.mcp.json` uses). Needs a design decision, not a patch.

### S3 — The add-on's `host` is not validated
`blender_mcp/addon/blender_mcp_addon/mcp_to_blender_server.py` binds
`("localhost", 9876)` by default (loopback only; browser cross-site requests
fail at `json.loads`). The `host` preference and `--host` accept any string, so
`0.0.0.0` would expose unauthenticated remote code execution. A guard in
`start` that refuses a non-loopback host would close it; upstream may rely on
the flag for containers.

## Pinned text and gates (a fix moves a fingerprint or a golden)

### P1 — The drift catalog's `Action.fcurves` text is wrong, and it is in the prompt
`src/blended/drift/catalog.py:35-40` says reading `action.fcurves` "returns
empty and silently does nothing". Measured on Blender 5.2.0: it raises
`AttributeError: 'Action' object has no attribute 'fcurves'`
(`src/blended/ops/animation.py:10` already says so). The text feeds the
assembled prompt, pinned as `a10:c68237772de1`
(`_evaluate/golden/pinned_assembled_fingerprint.txt`). Replace the sentence
with "action.fcurves does not exist in 5.x: reading it raises AttributeError
('Action' object has no attribute 'fcurves'; measured 5.2.0 LTS)" and re-pin.

### P2 — A wire edge passes the mesh gate
`src/blended/analyze/mesh_checks.py:621-626`: edges with zero faces count as
neither boundary nor non-manifold. Measured: a cube with one hanging wire edge
returns `failures() == []`; only disconnected wire edges are caught, by the
component count. Counting them changes the gate every golden and bench score
was measured under.

### P3 — Splayed legs end 0.35 mm short of the top
`src/blended/ops/legs.py:177`: `SplayedLegSpec.length_m` adds the drop, but the
axial drop is `drop / cos(splay)`. Measured for the stool spec: leg axis ends
at z=0.40965 against `top_z_m` 0.41; the foot circle is exact. The fix is
`hypot(rise, run) + sole_drop_m / cos(splay_rad)`, which moves golden geometry
and `test_the_leg_regains_the_length_the_drop_spent`.

### P4 — `import_glb` recentres on the vertex mean, not the bbox centre
`src/blended/ingest/import_glb.py:76-80`. The result depends on tessellation
density. `_evaluate/visual_gate_calibration.json` and the golden views were
measured with the current recentring (`scripts/calibrate_visual_gate.py:13`).

### P5 — `examiner.py` passes `view_name`; the template never renders it
`src/blended/evaluate/examiner.py:372` vs `prompts/examiner.md.j2` (pinned).
Harmless (jinja ignores extras); drop the argument or render it.

## Dead code and spec

### D1 — `run_batch`, `run_script_subprocess`, `run/_bootstrap.py` have no callers
Nothing in `src/`, `scripts/`, `blender_mcp/` or the Makefile calls them; the
spec's EXE-9/EXE-10 require them. They now have tests
(`tests/*/test_review_harness_core.py`). One-path rule: delete them and the
two spec rows, or keep them on purpose.

### D2 — `reset_scene` leaves frame range, unit scale and render resolution
Measured in Blender 5.2 after `reset_scene`: `frame_start/end/current`
(5/99/42), `unit_settings.scale_length` (0.01) and `render.resolution_x` (321)
survive. Harm to rebuild digests is PROPOSED (both builds inherit the same
leak); measure before changing.

### D3 — Tests that never run in the matrix
`tests/pure/test_bench_proportion_headroom.py` calls `importorskip("numpy")`;
`.venv` has neither numpy nor trimesh, so its four tests are the skipped file in
`make test-pure`. Run directly under system python they pass. Add numpy and
trimesh to the dev group, or move the test to `tests/blender/`.

### D4 — Vendored MCP package declares neither `blended` nor `anyio`
`blender_mcp/mcp/pyproject.toml`: `blmcp.tools_helpers.blended_bridge` imports
`blended` and `anyio`, and `requires-python >=3.10` differs from the root's
`>=3.11`. Declaring `blended` would be circular with the root's `blender-mcp`
dependency and touches `uv.lock`.

### D5 — Upstream tool quirks pinned by upstream tests
`get_objects_summary_toolcode.py:36` fills `hide_viewport` from
`obj.hide_get()` (view-layer hide); `render_*` tools reduce `output_path` to its
basename under `bpy.app.tempdir/blender_mcp` and let Blender append `.png`
(the returned path then does not exist). Pinned by
`test_blender_mcp_with_blender.py:752-810` and `test_tool_listing.py`.

### D6 — `bench_bridge` re-indents multi-line string literals
`src/blended/evaluate/bench_bridge.py` (~184): a chunk that raised after
changing the scene is wrapped with `textwrap.indent`, which also indents the
inside of triple-quoted strings, so the replayed text differs from the live
run. A fix changes the script format `tests/pure/test_bench_bridge.py` pins.

### D7 — The tool-call cap is checked at the top of the loop
`src/blended/agent/loop.py`: one reply carrying several calls can exceed
`maximum_tool_calls_per_turn` while the stop text still says "budget N".
`tests/pure/test_turn_caps.py` may pin the current behaviour.

### D8 — `tests/pure/test_agent_cancel.py` is named for a deleted method
It tests the token-budget seam since `AgentSession.cancel` was deleted. Not
renamed because `BACKLOG_DONE.md`, the spec and a mistake-memory guard cite the
path.

## PROPOSED (unmeasured; nothing was changed for these)

- `src/blended/evaluate/digest.py:105` `_uv_component` hashes UVs in raw loop
  order while faces are sorted; whether loop order is nondeterministic is not
  measured.
- `src/blended/evaluate/visual_diff.py` `CALIBRATION_PATH` is relative to the
  working directory; a launch from another directory prints "uncalibrated"
  and skips the gate instead of failing.
- `src/blended/agent/claude_code.py` `check_connection`: `claude auth status`
  printing valid JSON that is not an object would raise `AttributeError`; a
  watchdog kill mid-frame surfaces as `JSONDecodeError`.
- `src/blended/agent/prompt_search.py:129` rejected-hunk memory keys on
  line-range strings, so the same edit at a shifted line is not recognised.
- `src/blended/agent/skill_modules.py:119` `validate_modules()` does not check
  duplicate names.
- `src/blended/evaluate/examiner.py` numeric claims ("0.66-alignment", the RESP
  recall figures) were not re-checked against the cited papers; the DOIs were.
- `.mcp.json` hardcodes `/Users/ladvien/blended/.venv/bin/blender-mcp`; the
  README says both `.mcp.json` and `.omp/mcp.json` need editing on another
  checkout.
- `src/blended/ops/heal.py` (~55) dedupes sliver edges by `edge.index` after
  `remove_doubles`; could not make indices collide in a probe.
