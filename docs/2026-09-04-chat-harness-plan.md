# 2026-09-04 — In-Blender chat harness: plan

Goal (goal-mode objective): the in-Blender chat is the product surface;
the agent writes bpy through the harness; the model lanes cover
OpenRouter, Ollama and the two llama-swaps; every gate is a script that
exits 0.

Ground truth from the code map (scouts, 2026-09-04):

- Chat UI exists: `blender_addon/__init__.py` — `BLENDED_PT_chat`, `BLENDED_OT_send`
  (worker thread + main-thread tool queue), test_connection, hot-reload.
  Missing: cancel, streaming, a rig/anim/material-aware toolset.
- Lanes: `src/blended/agent/loop.py` — `_implied_endpoint`/`_implied_api_key`,
  `OPENAI_PROTOCOL_ENDPOINTS = (BMB, BIG)`. No OpenRouter. No streaming.
- Ops: no armature / vertex-group / keyframe / node-tree ops (grep confirmed).
- Headless loop driver: `AgentSession.send()` with an injected `dispatch`
  (`scripts/run_3dcode_instance.py:235-246` pattern).
- Prompt pin: v10 `b6627b38f4c1` is hash-locked; new prompt text goes in a
  new revision, never in v10.

## Components (each a small step with its own assertions)

### P1 — OpenRouter lane (`src/blended/agent/loop.py`)
- `OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"`, key file
  `~/.blended/openrouter_api_key` (accepts `OPENROUTER_API_KEY=` prefix).
- Routing: any model id containing `/` (vendor/model form) → OpenRouter.
  Ollama cloud ids use `:cloud`, llama-swap ids have no slash, so the slash is
  an unambiguous discriminator.
- `OPENAI_PROTOCOL_ENDPOINTS` gains OpenRouter; timeout stays the 300 s cloud
  ceiling (only LAN llama-swaps get 900 s).
- Spend guard: OpenRouter is used ONLY by the smoke script with tiny prompts
  and `max_tokens` capped; never by bench or E2E. ($20 budget, user-stated.)
- Tests: `tests/pure/test_openai_transport.py` gains routing + key-file cases.

### P2 — Provider matrix smoke (`scripts/provider_smoke.py`)
- Lanes: openrouter (cheap vision-capable model), bmb (qwen3.8-27b text; image
  lane = big), big (qwen3-vl text + image). Asserts non-empty reply and, for
  the image call, that the reply names the rendered primitive.
- Exit 0 only when every lane passes; prints a table.

### P3 — Domain ops (`src/blended/ops/`)
- `rigging.py`: `add_armature(name, bone_specs)` (config dataclass `BoneSpec`
  with head/tail `_m`), `bind_mesh_to_armature(mesh, armature, automatic_weights)`.
- `weights.py`: `assign_vertex_group_weights(mesh, group_name, weight, predicate)`,
  `vertex_group_report(mesh)`.
- `animation.py`: `keyframe_pose_rotation(armature, bone, frame, rotation_deg)`,
  `keyframe_object_location(obj, frame, location_m)`, `set_frame_range`.
- `material_nodes.py`: `assign_procedural_material(obj, name, kind, scale)`
  (noise / checker → Principled), `material_report(obj)`.
- All exported through `blended.ops.__init__`, so `search_ops` finds them.
- `tests/blender/test_ops_rig_anim_material.py` asserts each op's terminal state.

### P4 — Chat toolset + prompt
- `tools.py`: `inspect_rig`, `inspect_animation`, `inspect_material` report
  tools (armature bones, vertex-group nonzero counts, action keyframes, node
  tree summary) so the writer can verify its own work.
- `prompt_versions.py`: revision 11 (one hunk: the domain lanes clause);
  `ACTIVE` → 11, pin stays 10. Update `test_prompt_search.py` literal.

### P5 — Headless chat E2E (`scripts/chat_e2e.py`, run inside Blender)
- Six scenarios, each = user prompt(s) → `AgentSession.send` → assertions
  via `blended.ops.*_report` + analyzer. Writer: the default Ollama-cloud
  writer (deepseek-v4-pro:cloud), eye kimi. Records a JSONL transcript under
  `outputs/chat_e2e/`. Exit code = all scenarios pass.
- `make chat-e2e` target.

### P6 — Chat UX
- Cancel: `AgentSession.cancel()` flag checked between tool calls + operator.
- Streaming: SSE for OpenAI lanes, NDJSON for Ollama; partial answer event
  `answer_delta`; panel shows the live tail. Tool-call deltas accumulated by
  index before dispatch.
- Pure tests for the stream parsers (canned frames).

### P7 — Design doc (`docs/harness_design.md`)
- ≥10 decisions, each: decision → DOI → code path. Sources: existing
  `docs/research/*` corpus + skill_modules evidence DOIs + new lookups for
  chat/streaming/cancel UX.

### P8 — Gates
- `make test`; `scripts/provider_smoke.py`; `make chat-e2e`; one
  3DCodeBench frozen-20 roll (≤ 0.0706 guard) after prompt v11; GUI launch
  for user visual confirmation.

## Mutations declared up front
- `~/.blended/openrouter_api_key` chmod 600 (read-only for others).
- New files only under `src/`, `scripts/`, `tests/`, `docs/`, `outputs/`.
- No remote-host mutation. No `_evaluate/` writes.
