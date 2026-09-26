# ISSUES.md — code review of the fine-tune-decision + local-llama-server changes

**Date:** 2026-09-19
**Reviewers:** `CharmingPelican` (reviewer, local llama-server lane + transport test) · `VariedPigeon` (reviewer, bench scripts + markdown)
**Object:** the change described in the request, judged against the **working tree** (the change request's diff for the local lane is an *earlier* form — see F-I0, the disk code is canonical).
**Overall:** no critical findings. **3 major, 3 minor, 4 info.**
- CharmingPelican verdict: **minor** (3 major, 2 minor, 1 info)
- VariedPigeon verdict: **pass** (2 minor, 3 info)

The three **major** findings are all in `src/blended/agent/loop.py` and are worth fixing before merge.

## Verified facts (no action needed)
Independently confirmed by both reviewers (and by direct string checks):

1. **`OPS_TASK_TEMPLATE` is byte-identical to the `TASK_TEMPLATE` this patch deleted** from `scripts/run_3dcode_instance.py` — both **1,100 chars**. The production multi-turn runner's prompt is unchanged; `SINGLE_SHOT_RULE` reaches only `SINGLE_SHOT_OPS_TASK_TEMPLATE` (`bench_task_prompt.py:85-87`), never the runner (formats `OPS_TASK_TEMPLATE` at `run_3dcode_instance.py:233`). The "archive stays comparable to itself" claim is **true**.
2. **`RAW_TASK_TEMPLATE == OPS_TASK_TEMPLATE` with exactly `CHUNK_RULE` removed** (`bench_task_prompt.py:81-82`, string-equality verified).
3. **`canonical_orientation_epilogue()` move is clean:** the 28-line block in `bench_bridge.py:118-145` is identical to the block removed from the runner; `bench_bridge.py` adds no import for it; the runner imports it and the call site is intact (`run_3dcode_instance.py:275-277`); `scripts/run_finetune_arm.py:295-299` consumes the same definition — no duplicate.
4. **`diagnose_3dcode.py` divide-by-zero is genuinely fixed** by a short-circuiting conditional; no code parses the printed line.
5. **`shape_error_decompose.py --json`** emits a valid JSON object with the keys the consumers read; `rows` and `checked` both in scope.
6. **Routing wiring verified by running the config:** both local ids → `http://127.0.0.1:8091`, `uses_openai_protocol=True`, `constrains_tool_calls=True`, `api_key=""`; `qwen3.8-27b` (bmb) and `qwen3-vl` (big) → `constrains_tool_calls=False`. Envelope confined to the one lane.
7. **Seed on both wires** — the single test `test_a_pinned_seed_reaches_both_wires_and_an_unset_one_is_not_sent` (`test_openai_transport.py:243-272`) asserts seed on both wires and **absence** (not falsiness) on both; seed 0 passes through; the new test passes (21 passed, 0 failures).
8. **Empty-content risk is loud, not silent:** `ReplyTruncated` on `finish_reason length` before decode; schema-valid empty envelope → `EmptyReply`. The 7B empty-content/length failure is caught.

## MAJOR

### M1 — Streamed path never decodes the constrained envelope
`src/blended/agent/loop.py:1737` (CharmingPelican)

`_chat_payload` attaches `response_format` for any constrained lane with tools (`loop.py:1434-1452`), and `chat()` sets `payload["stream"]=True` afterwards (`loop.py:1687-1690`), so a **streamed** call on this lane still carries the envelope schema. The streamed consumer has no matching branch: `_chat_streamed` → `_assemble_openai_stream` (`loop.py:1120-1137`) only folds `delta.content`, `delta.reasoning` and wire `delta.tool_calls` and **never reaches `assistant_message_from_envelope`**.

**Effect:** the envelope JSON is returned verbatim as `content` with `tool_calls==[]` — every tool call is silently dropped and the raw JSON is appended as the assistant's answer. Only the one-shot branch passes `constrained=self.config.constrains_tool_calls` (`loop.py:1715-1717`). Trigger: `AgentSession(stream_replies=True)` (`loop.py:2174-2180`), set unconditionally by the addon (`blender_addon/__init__.py:746`). Latent today only because the two ids are absent from the addon writer enum (`blender_addon/__init__.py:2053-2124`) and `run_finetune_arm.py:231` calls `chat()` without `on_delta` — but `chat()` is a public entry point whose two paths now **disagree for the same config**.

**Fix:** have `_chat_streamed` run the same envelope decode over the assembled message when `self.config.constrains_tool_calls` and no wire tool calls arrived.

### M2 — Decoder accepts any JSON object as an envelope (erases non-envelope dicts)
`src/blended/agent/loop.py:1026` (CharmingPelican)

The constrained decode accepts **any** top-level JSON object: `json.loads` succeeds, the only guard is `isinstance(envelope, dict)` (`loop.py:1026`); `assistant_message_from_envelope` then reads `envelope.get("message") or ""` and `envelope.get("tool_calls") or []` (`claude_code.py:389-403`). A dict that is **not** the harness envelope returns `content=""` and `tool_calls=[]`, **discarding the model's actual text**, and `check_reply_is_a_turn` raises `EmptyReply` ("produced nothing") while the real text is gone from the record.

This contradicts the function's own docstring (promises a non-parsing reply is left alone — the promise holds for non-JSON and JSON scalars, **not** the dict case). Reachable because `constrained` is derived from the **endpoint**, not the request: `response_format` is only added when tools are present (`loop.py:1434`), yet `chat()` passes `constrained=True` for **every** reply on this lane, including tool-less raw-format arms where no grammar constrains output. The documented checkpoint shape is a bare JSON call object (`loop.py:1441-1448`) — exactly a dict-but-not-envelope.

**Fix:** decode only when the parsed dict carries the envelope's two required keys; otherwise fall through to the raw-text path.

### M3 — New lane inherits the 300 s cloud ceiling, not the local one
`src/blended/agent/loop.py:828` (CharmingPelican)

`request_timeout_seconds` returns `LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS` only for `LLAMA_SWAP_ENDPOINTS` (bmb+big, `loop.py:826-828`); the new endpoint was added to `OPENAI_PROTOCOL_ENDPOINTS` but **not** that predicate, so it falls back to `REQUEST_TIMEOUT_SECONDS=300` (`loop.py:91`). Verified by running the config: `ModelConfig.from_environment(model="blenderllm").request_timeout_seconds` is **300** vs 2000 for `qwen3.8-27b`.

A non-streamed llama.cpp reply arrives in one blocking read after generation completes; any completion >300 s raises `TimeoutError` at the status line — the exact failure this file already records for the same lane class (`loop.py:96-99`, `247-252`). `TimeoutError` is retryable (`loop.py:253`), so the request is **re-sent ~5× across 1655 s** before the error is raised. Measured cost on the arms this lane was added for: constrained arm — longest returned completion 276.11 s, 11 synthesized timeout rows; raw arm — the only two completions >300 s were **886.0 s** and **1162.73 s**, both exact sums of the retry ladder, with 15 synthesized timeout rows.

**Fix:** key the long ceiling on "a llama.cpp server we run" rather than the two llama-swap hosts, so this endpoint gets it too.

## MINOR

### Mi1 — Constrained lane matched by exact equality, not containment
`src/blended/agent/loop.py:815` (CharmingPelican)

`uses_openai_protocol` matches by **substring** across `OPENAI_PROTOCOL_ENDPOINTS` (`loop.py:785`); `constrains_tool_calls` matches by **exact equality** against `LOCAL_LLAMA_SERVER_ENDPOINT` (`loop.py:815`). The two disagree for any non-byte-identical spelling of the same server (trailing slash, `localhost` vs `127.0.0.1`) — and one-sided in the dangerous direction: the config still takes the OpenAI wire but passes `constrains_tool_calls=False`, so it emits wire `tools` to a model that answers with a `<function_call>` tag llama.cpp will not parse. The endpoint is user-settable free text in the addon prefs (`blender_addon/__init__.py:2197-2200`) and via the host env var (`loop.py:754-758`).

**Fix:** match this endpoint with the same containment test the protocol check uses.

### Mi2 — No test pins the constrained lane
`tests/pure/test_openai_transport.py:267` (CharmingPelican)

Grep over `tests/` for `constrains_tool_calls`, `response_format`, `CONSTRAINED_ENVELOPE_NAME` and the two new ids returns only the seed assertions (`:252`, `:265`) — the ids appear solely as a vehicle for the seed tests. Nothing asserts: constrained ⇒ `response_format.json_schema` (name `blended_harness_turn`, strict `True`) with **no** `tools`; non-constrained ⇒ `tools` with **no** `response_format`; that the lane's envelope content becomes `tool_calls`; or that the lane is the **only** one with `constrains_tool_calls=True`. The file pins every other lane at that granularity — the new lane is the one transport behaviour shipping unpinned, and **two of the M1/M2 defects would each be caught by a single such test**.

**Fix:** add a payload + decode test for the constrained lane.

### Mi3 — Comment understates the experiment's op-vs-raw prompt delta
`scripts/run_3dcode_instance.py:51` (VariedPigeon)

The comment asserts "the raw-bpy arms … differ from this one in exactly the `run_python` bullet and nothing else." Strictly, `RAW_TASK_TEMPLATE == OPS_TASK_TEMPLATE` minus `CHUNK_RULE` (verified), **but no arm sends `OPS_TASK_TEMPLATE`**: the op arms send `SINGLE_SHOT_OPS_TASK_TEMPLATE` (`run_finetune_arm.py:164-169`), the raw arms send `RAW_TASK_TEMPLATE` (`raw_bpy_arm.py:63-64`). So the experiment's op-vs-raw text differs by `CHUNK_RULE` **and** the 5-line `SINGLE_SHOT_RULE`, not one bullet. The generated report does print the true diff (`finetune_decision_report.py:138-143` diffs `SINGLE_SHOT_OPS` against `RAW`), so the published artifact is honest — the defect is confined to the comment, whose purpose is the prompt-parity assurance a future reader trusts.

**Fix:** correct the comment to state the actual delta (chunk rule + single-shot rule).

### Mi4 — Budget report bullet split in two for every run, not just the empty case
`scripts/diagnose_3dcode.py:385` (VariedPigeon)

The divide-by-zero is genuinely fixed. But the unintended side effect is wider than the empty case the comment (`:382-385`) justifies: the list element that was **ONE** bullet (`- turns: mean X, max Y, turns>=20: Z`) is now **TWO** for **every run** (`- turns: mean X` at `:385-386`, `- max turns: Y, turns>=20: Z` at `:387-388`). Every `outputs/bench/diagnose_*.md` produced by `bench_chain.sh:97-98` and `score_finetune_arm.py:144-152` changes shape. Nothing parses the markdown (all downstream consumers read `--json` only), so no consumer breaks. Secondary nit: in the empty case the two bullets read `- turns: — (no meta)` then `- max turns: —, turns>=20: 0`, which prints a measured-looking `0` for a model dir with no meta.

**Fix (cosmetic):** if the intent was to change the report for the empty case only, restore the single-bullet form for non-empty runs; otherwise document the new shape.

## INFO

### I0 — Change request and disk disagree on the lane's constants; disk is canonical
`src/blended/agent/loop.py:520` (CharmingPelican)

The change request's diff introduces a `LOCAL_MODEL_ENDPOINTS` **dict** and `LOCAL_LLAMA_SERVER_ENDPOINT="http://localhost:8081"`. **Neither ships.** Disk has `LOCAL_LLAMA_SERVER_ENDPOINT="http://127.0.0.1:8091"` (`loop.py:85`) and `LOCAL_LLAMA_SERVER_MODEL_IDS=("qwen2.5-coder-7b-instruct","blenderllm")` (`loop.py:520`), wired through `OPENAI_PROTOCOL_ENDPOINTS`, `_implied_endpoint`, `_implied_api_key`. The disk form is the right one and is reviewed here: the id tuple matches the `BMB_MODEL_IDS`/`BIG_MODEL_IDS` convention; literal `127.0.0.1` avoids the macOS `localhost`-resolves-to-`::1`-first trap; port 8091 keeps the endpoint string distinct from `BIG_ENDPOINT`'s `:8081` (which matters because `uses_openai_protocol` matches by substring). **This is why the two reviewers' "diff" and "file" differ — treat the disk code as canonical.**

### I1 — `--json` payload omits the summary means the help text implies
`scripts/shape_error_decompose.py:94` (VariedPigeon)

The payload is well-formed and correctly scoped, but its help text says "the way `diagnose_3dcode.py --json` does," and that document carries both `per_instance` **and** a `means` block; this one stops at `per_instance`. The three summary means printed at `:378-380` (mean `cd_pca`, mean Δ_orient, mean oracle) remain markdown-only — the same "markdown is not a data path" problem the flag was added to solve. No current consumer needs them.

**Fix:** add a `means` block to the JSON (or trim the help text to match).

### I2 — New graph edges gate OT-12, which the backlog records as closed
`BACKLOG.md:351` (VariedPigeon)

The dependency graph gains `OT43 --> OT12` (`:351`) and `OT41 --> OT12` (`:352`), and OT-41's prose says "Settle it BEFORE the candidate-op miner (OT-12/OT-13)." But OT-12 is **not open**: `BACKLOG.md:79` says all Phase 4 items (OT-12, OT-13, OT-14) are closed (see `BACKLOG_DONE.md`), and `BACKLOG_DONE.md:221-233` records OT-12 Missing-op mining closed (commit `2e7e2ac`). The new edges assert a shipped item depends on two unstarted ones and contradict the pre-existing `OT8 --> OT12 --> OT13` edge (`:335`). Everything else in the new Phase 11 checks out: `OT43 --> OT40` present; OT-42's "Superseded in part by OT-43" line present; OT-39 references resolve; every number grounded; no `26×` remains.

**Fix:** correct the OT-41/OT-43 edge targets to reflect OT-12's closed status.

### I3 — No design row records the one-definition task-text contract
`docs/harness_design.md:41` (VariedPigeon)

The single added row is #31 (grammar-constrained tool calls), **not** the prompt-contract rule. Row 31's own claims all verify (no over-statement). The under-statement is what's absent: this patch also introduces a design decision of the same weight as rows 14/15 — one definition of the bench task text in `src/blended/evaluate/bench_task_prompt.py`, with OPS/RAW/SINGLE_SHOT composed from shared constants (`:81-87`) so an op-vs-raw experiment diffs real strings, and the report carrying the unified diff — and the table records no row for it.

**Fix (optional):** add a design row for the single-definition task-text contract.

### I (seed) — Seed coverage correct on disk (brief expectation superseded)
`tests/pure/test_openai_transport.py:243` (CharmingPelican)

The brief expected `test_seed_omitted_when_unset` + a sibling and an Ollama-side gap. **Neither matches disk.** One test covers all four cases and asserts **absence** (not falsiness) on both wires; production matches. The two seed expressions are semantically identical (one a statement, one an inline dict member). No defect. (Also notes the non-streamed OpenAI decoder doesn't copy `finish_reason` onto the returned message, unlike the streamed assembler — **predates** this change.)

## Summary of action items (before merge)
| # | Severity | File | Action |
|---|----------|------|--------|
| M1 | major | `loop.py` | Decode envelope in `_chat_streamed` (streamed/one-shot parity) |
| M2 | major | `loop.py` | Decode only if dict carries envelope's two required keys |
| M3 | major | `loop.py` | Key the long timeout ceiling on the llama.cpp server, not just llama-swap hosts |
| Mi1 | minor | `loop.py` | Match constrained lane by containment, not exact equality |
| Mi2 | minor | `test_openai_transport.py` | Add a payload + decode test pinning the constrained lane |
| Mi3 | minor | `run_3dcode_instance.py:51` | Correct the op-vs-raw delta comment |
| Mi4 | minor | `diagnose_3dcode.py` | Decide if the split bullet is intended; restore single-bullet for non-empty or document |
| I1 | info | `shape_error_decompose.py` | Add `means` to `--json` or trim help text |
| I2 | info | `BACKLOG.md` | Fix OT-41/OT-43 edge targets (OT-12 closed) |
| I3 | info | `harness_design.md` | (optional) add design row for the task-text contract |

M1, M2, M3 are the must-fix items; Mi1–Mi4 are cheap follow-ups; I1–I3 are documentation/consistency cleanups.
