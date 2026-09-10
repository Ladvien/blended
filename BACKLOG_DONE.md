# blended — Backlog: done

Items move here from `BACKLOG.md` verbatim when they satisfy the closing rule
(`BACKLOG.md` § Closing rule): **Done means** test in the tree and green in both
layers (`make test`), spec rows amended in the same change, and — for OT-9
through OT-11 — the pre-registered hypothesis filled with a measured outcome.

Each entry records: the item block as written, the closing commit, the test(s)
that gate it, and the date closed. Nothing here is edited after it lands; a
regression reopens the item in `BACKLOG.md` with a pointer back to this entry.

---

## OT-1 Complete the ops facade

**What:** `blended.ops.__init__` MUST re-export every public op, including `legs`, `canonical_orientation`, and `add_lathe`. The barrel builder MUST import `add_lathe` from the facade.
**Why:** OT-3 generates schemas by introspecting the facade. Anything not on the facade is invisible to the agent and to the tests that check the whitelist. Closes spec §7.3 row 5.
**Amends:** OPS-1.
**Done means:** `tests/pure/test_one_path_ops.py` asserts that every public callable under `src/blended/ops/*.py` is reachable from the facade, and no builder imports an ops submodule directly.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_one_path_ops.py::test_every_public_op_is_reachable_from_the_facade`, `::test_facade_exports_nothing_it_does_not_define`, `::test_builders_import_only_the_facade`, `::test_every_ops_submodule_is_in_the_manifest`.
**Spec:** OPS-1 row amended; §7.3 facade gap row removed.
**Side effect, measured:** adding `canonical_orientation` to `OP_MODULE_NAMES` put its ops into the manifest the model reads; assembled prompt fingerprint moved `a10:f13911deb826` → `a10:315c684fd7f6` (pin updated in the same commit). `PromptRevision.identity` did not move.
**Layers:** pure 432 passed / 1 skipped / 1 xfailed; Blender 308 passed / 3 skipped.
**Commit:** `7226f01`.

---

## OT-2 Op signature contract

**What:** Every op on the facade MUST satisfy a machine-checkable contract: type-annotated parameters; unit-suffixed names for quantities (`_m`, `_deg`, `_px`) per NFR-8; a docstring whose first line is the one-sentence description; an explicit return annotation naming the object(s) created or modified; no `bpy` types in the signature (object references are names, `str`).
**Why:** The schema generator can only emit what the signature carries. This is the same discipline OPS-16 already applies to `Parameters`; it extends it to ops.
**Amends:** adds `OPS-21`.
**Done means:** `tests/pure/test_ops_signature_contract.py` fails on any facade op that violates the contract. A seeded-defect fixture op (NFR-15) trips it.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_ops_signature_contract.py::test_facade_op_satisfies_the_signature_contract` (parametrized over every facade op), `::test_the_contract_trips_on_a_seeded_defect` (NFR-15 fixture), `::test_unitless_allowlist_is_all_in_use`, `::test_typing_is_not_needed_at_import`.
**Spec:** OPS-21 row added; §5.5 gains the contract constants; §6.3 OPS 20 → 21.
**Shape of the change:** every op takes object NAMES (`str`) and returns the name(s) it created or modified; `blended.ops._objects.object_by_name` is the one resolver and raises `UnknownObject` / `WrongObjectType`. Callers converted: three builders, harness, agent tools, export, ingest cleanup, `examples/harness_demo.py`, `scripts/calibrate_examiner.py`, `scripts/chat_e2e.py`, 25 Blender test modules.
**Side effects, measured:** the manifest renders the new signatures, so the assembled prompt fingerprint moved `a10:315c684fd7f6` → `a10:2933f0ebd234` (pin updated); `PromptRevision.identity` (`v10:b6627b38f4c1`) did not move. Goldens 48 (planter_box) and 50 (ribbed_column) stopped replaying — their recorded model sources passed bpy objects into ops — and were replaced by iterations 66 and 67, run on the same v10 text on `claude-code:sonnet` (8 and 6 turns, 0 name-vs-object errors, identical form numbers). Pixel gate against the old views: planter shading RMSE 0.075 vs 0.010 limit, column silhouette IoU 0.9948 vs 0.998 floor — a fresh run beside a replay. The three untouched goldens re-minted pixel-identical (0.00 % differing) and were reverted. Mechanism recorded in `mistake_memory.py` as `a-signature-change-invalidates-recorded-model-code-not-just-callers`.
**Signed off:** 2026-09-10, by the user on the 66/67 contact sheets (the banner this line replaces said it would come off with the sign-off).
**Layers:** pure 477 passed / 1 skipped / 1 xfailed; Blender 308 passed / 3 skipped.
**Commit:** `22fdc8c`.

---

## OT-3 Generate tool schemas from the facade

**What:** `build_tool_schemas()` MUST produce one JSON-schema tool entry per facade op from introspection, using the same machinery `build_manifest` uses for prose. `TOOL_SCHEMAS` MUST become the union of the hand-written service tools and the generated op tools.
**Why:** PRM-2 already forbids hand-written manifest prose; the same rule should apply to schemas, or the two will drift.
**Amends:** AGT-1 ("exactly eight tools" becomes "the service tools plus every facade op, generated"), PRM-2.
**Done means:** `tests/pure/test_tool_schemas.py` checks that adding an op to the facade adds a tool, that the parameter set of each generated tool equals the op's signature, and that unit suffixes appear in every quantity parameter name. Fingerprint the generated schema set the way the prompt is fingerprinted (PRM-7) so a schema change is visible in the iteration log.

**Decision recorded here, to be measured in OT-13:** one tool per op, not a single `call_op(name, arguments)` tool. Rationale: per-op tools carry typed arguments into the transport's constrained decoding (the Claude Code lane already builds a `oneOf`-per-tool envelope, AGT-14). Fallback if tool count breaks a local lane: a single `call_op` with `name` as an enum and per-op argument schemas surfaced through `search_ops`.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_tool_schemas.py` — `::test_adding_an_op_to_the_facade_adds_a_tool`, `::test_the_parameter_set_equals_the_signature` (parametrized over every facade op), `::test_every_numeric_parameter_carries_a_unit_in_its_name`, `::test_a_contract_violation_refuses_the_whole_set`, `::test_the_tool_set_has_not_drifted` (pin), plus the type-mapping cases (fixed tuple, optional, config dataclass, tuple of dataclasses, unmappable annotation is loud); `tests/pure/test_prompt_citations.py::test_every_other_registered_tool_is_a_facade_op`.
**Spec:** AGT-1 amended (service tools + every facade op, fingerprinted and pinned); PRM-2 amended (schemas generated like prose); §2.2 rewritten; §5.4 gains `TOOL_SCHEMAS_FINGERPRINT_PREFIX` / `JSON_TYPE_FOR_SCALAR`.
**Shape of the change:** the OPS-21 contract moved from the test into `blended.ops._contract` so the generator and the test read one definition; `blended.agent.tool_schemas` maps resolved type hints to JSON schema (scalars, `Path`, unions with `None`, fixed and variadic tuples, lists, config dataclasses as objects with required fields; anything else raises `UnsupportedAnnotation`) and refuses an op that violates the contract; `tools.py` splits `SERVICE_TOOL_SCHEMAS` (8, hand-written) from `OP_TOOL_SCHEMAS` (generated) and asserts the names are disjoint; `IterationRecord.tool_schemas_fingerprint` is written by `run_agent_task.py`.
**Measured:** 42 op tools generated; `TOOL_SCHEMAS` is 50 entries; fingerprint `t:1fe7f62007ef` pinned in `_evaluate/golden/pinned_tool_schemas_fingerprint.txt`. The assembled prompt fingerprint did not move (tools travel in the API `tools` field / the Claude Code envelope, not the prompt text). `envelope_schema(TOOL_SCHEMAS)` builds 50 `oneOf` variants (existing `test_claude_code_lane` assertion).
**Recorded, to be measured in OT-13:** one tool per op is a hypothesis. Tam et al. (DOI 10.18653/v1/2024.emnlp-industry.91) measured that a schema constraint raises prompt sensitivity and lowers average performance on reasoning tasks while helping classification; the generator docstring carries the citation next to the decision.
**Known gap, closed by OT-4:** `dispatch_tool` does not yet route an op tool; a call to one returns the existing `Unknown tool` result until OT-4 lands. No live lane ran in between.
**Layers:** pure 616 passed / 1 skipped / 1 xfailed; Blender 308 passed / 3 skipped.
**Commit:** `5275dc2`.

---

## OT-4 Op-call dispatch

**What:** `dispatch_tool` MUST route a generated op tool to the facade function, on the main thread (AGT-2), with argument validation failing loud on unknown or missing parameters (NFR-13). The result MUST carry the same `stage_reached` vocabulary as `run_chunk` (EXE-6).
**Why:** The op tool must be at least as observable as `run_python`, or the agent will prefer the hatch.
**Amends:** adds `AGT-21`.
**Done means:** `tests/pure/test_agent_dispatch.py` covers valid call, unknown op, bad argument type, off-main-thread refusal. `tests/blender/test_agent_loop.py` runs a brief to gate-pass using only op tools.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_agent_dispatch.py::test_an_op_tool_call_binds_runs_and_reports_done`, `::test_an_unregistered_tool_is_refused_at_the_door_without_bpy`, `::test_a_mistyped_argument_fails_at_execute_with_the_cause_and_no_traceback`, `::test_unknown_and_missing_parameters_are_named`, `::test_arguments_are_converted_to_the_signature_types`, `::test_binding_is_strict_about_json_types`, `::test_an_op_that_raises_is_a_failed_call_with_its_type_and_traceback`, `::test_an_op_tool_off_the_main_thread_is_refused_like_any_tool`; `tests/blender/test_agent_loop.py::test_a_brief_reaches_gate_pass_with_op_tools_only` (planter_box, nine op calls, zero `run_python`, form gate PASS), `::test_an_op_tool_failure_names_the_op_error_to_the_model`; `tests/pure/test_import_integrity.py::test_the_harness_imports_first_in_a_fresh_interpreter`.
**Spec:** AGT-21 added; EXE-6 amended (vocabulary defined once in `blended.stages`, shared by `run_chunk` and op calls); §2.2 updated; §6.3 AGT 20 → 21.
**Shape of the change:** `blended.agent.op_call` binds JSON arguments against the op's type hints (the hints the schema came from) — unknown, missing and mistyped parameters fail loud, nested config dataclasses and paths convert — runs the op through `run.executor.execute_captured`, the one capture path `run_source_in_process` now also uses, and reports `stage_reached` (`execute` on failure, `done` on return). `dispatch_tool` routes op tools and refuses unregistered names before `import bpy`; a service tool with a schema but no branch is an assertion, not a fallthrough. `blended.stages` replaces five inline stage literals in `harness.py`.
**Measured:** pure op `middle_extent_m` runs end to end in the pure layer (door, binding, capture, stage). A binding failure reports no traceback (its frames are the harness's); an op's own exception keeps its traceback, bounded to `MAXIMUM_TRACEBACK_CHARACTERS`.
**Mistake recorded:** `a-pure-helper-under-a-package-whose-init-imports-the-harness-is-a-cycle` — the first placement of the stage module under `blended.run` made `harness → run.stages → run/__init__ → run.batch → harness` a cycle that the pure suite could not see (executor already imported) and six Blender agent-loop tests did; guarded by a fresh-interpreter import test.
**Pre-registration (OT-9):** appended before this shipped, as the backlog required.
**Layers:** pure 626 passed / 1 skipped / 1 xfailed; Blender 310 passed / 3 skipped.
**Commit:** `ace7618`.

---

## OT-5 Gate every scene-changing op call

**What:** An op tool whose return names an object MUST run the scene-state gate and the analyzer on that object and return the verdict, exactly as `run_python` does when `object_name` is given (AGT-3). An op that creates an intermediate (an operand about to be consumed by a boolean) MAY be marked `@op(gated=False)` in the signature contract, and the marker MUST appear in the schema description.
**Why:** OPS-20 already requires re-analysis after every CSG result. This makes the rule uniform and automatic.
**Amends:** AGT-3, OPS-20.
**Done means:** `tests/blender/test_agent_loop.py` asserts a gate verdict on every gated op result, and that an ungated intermediate is followed by a gated consumer before the turn can end with an answer.

**Closed:** 2026-09-10.
**Gating tests:** `tests/blender/test_agent_loop.py::test_a_brief_reaches_gate_pass_with_op_tools_only` (a gate verdict on every gated op result, none on the ungated constructor or the material op), `::test_an_unresolved_intermediate_blocks_the_answer_until_resolved`, `::test_a_gate_failure_on_an_op_result_is_reported_at_gate` (two disjoint boxes unioned: `FAILED at gate`, 2 components), `::test_an_armature_is_gated_on_scene_state_only`, `::test_a_gated_op_on_a_missing_object_fails_at_locate`; `tests/pure/test_intermediates.py` (ledger debits before credits; refusal names creator; loop refuses then accepts; refusal counts against the budget); `tests/pure/test_ops_signature_contract.py` (marker rules: `@op(gated=False)` on a text-returning op is a violation, an ungated constructor must take `name`); `tests/pure/test_tool_schemas.py::test_the_three_unlinked_constructors_are_the_only_ungated_object_returners`, `::test_the_description_is_the_summary_and_the_return` (marker in the description).
**Spec:** AGT-3 amended (op tools gated through the same `gate_named_object`; marker; ledger refusal); OPS-20 amended (booleans return `ObjectName`, gated automatically); OPS-4 amended (`link_into_scene` idempotent); §2.2, §5.4.
**Shape of the change:** "whose return names an object" is machine-checkable: `blended.ops._objects.ObjectName = NewType("ObjectName", str)` is the return type of the 22 ops that create or modify an object (material and weight ops return datablock names and stay `-> str`). `@op(gated=False)` marks `add_box`, `add_cylinder`, `add_lathe` — the three constructors that return an unlinked object, where a gate would say "not linked" on every call. `blended.harness.GateVerdict` / `gate_object` is the ONE gate: scene state, then the analyzer for a mesh, scene state alone for an armature; `run_chunk` and `op_call` both read it, and `gate_summary_lines` renders it for both. `ToolOutcome` replaces the `(text, images)` tuple across the dispatch seam so the loop's `IntermediateLedger` learns what each call created and resolved without parsing text; an answer while the ledger is non-empty is refused with the pending objects named and counts against the budget.
**Measured:** planter_box via nine op calls: the two `link_into_scene` and two `boolean_difference` results carry `gate: PASS` and an `orient:` line, the four constructors and `assign_material` carry none. Contact sheets are NOT captured per op call (a sheet per call would be N renders per turn; `render_views` and `run_python` keep theirs). Tool-set fingerprint `t:959b39398cda`; assembled prompt `a10:673809a9e687` (the manifest now shows `-> ObjectName`).
**Observation for OT-13, not acted on:** in the recorded goldens the model forgot `link_into_scene` on the first attempt in three of five briefs; a constructor that links would remove that failure class and the ungated set with it.
**Mistake recorded:** `a-typing-object-compared-by-identity-breaks-under-dev-reload`.
**Layers:** pure 634 passed / 1 skipped / 1 xfailed; Blender 314 passed / 3 skipped.
**Commit:** `ab97d36`.

---

## OT-6 Plan integration

**What:** Generated op tools MUST be members of `PLAN_REQUIRED_TOOLS` (AGT-5) and MUST accept `plan_step`, so a scene-changing op without a declared plan is refused with the same text as `run_python`.
**Amends:** AGT-5, AGT-7.
**Done means:** `tests/pure/test_turn_plan.py` covers refusal and progress reporting for an op tool.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_turn_plan.py::test_plan_required_tools_are_run_python_and_every_scene_changing_op`, `::test_an_op_tool_without_a_plan_is_refused_with_the_same_text` (refusal text identical to `run_python`'s; dispatch never reached), `::test_a_reader_op_needs_no_plan`, `::test_an_op_tool_call_with_plan_step_reports_progress` (step event), `::test_dispatch_strips_plan_step_before_binding`; `tests/pure/test_tool_schemas.py::test_the_readers_are_the_only_plan_free_op_tools`, `::test_the_parameter_set_equals_the_signature` (plan_step on every action op tool, never required, never on a reader); `tests/pure/test_ops_signature_contract.py::test_a_reader_that_returns_an_object_name_is_a_violation`; `tests/blender/test_agent_loop.py::test_an_action_op_accepts_plan_step_and_the_op_never_sees_it`.
**Spec:** AGT-5 amended (`PLAN_REQUIRED_TOOLS` derived from the facade: `run_python` + every op not `@op(reads_only=True)`); AGT-7 amended (`PLAN_STEP_SCHEMA` defined once, carried by every plan-requiring tool, stripped before binding); §5.4.
**Shape of the change:** `@op(reads_only=True)` marks the ten inspection ops (four `*_report`, `deforming_bone_names`, `orientation_reading`, four pure orientation computations); the contract refuses a reader that returns an `ObjectName`. `PLAN_REQUIRED_TOOLS` is computed, not listed: 33 entries. The generator adds `plan_step` to every scene-changing op tool's schema; `dispatch_tool` removes it before `call_op` binds, so the op signature stays the only source of the op's arguments. The four identical hand-written `plan_step` schemas in the service tools now reference `PLAN_STEP_SCHEMA`.
**Measured:** tool-set fingerprint `t:8e3f56aff46c` (plan_step on 32 op tools). The assembled prompt fingerprint did not move.
**Layers:** pure 641 passed / 1 skipped / 1 xfailed; Blender 315 passed / 3 skipped.
**Commit:** `65bb719`.

---

## OT-7 Demote `run_python` to an escape hatch

**What:** `run_python` MUST require a non-blank `reason` parameter naming what the ops vocabulary could not express. The working agreement MUST gain a revision (one hunk, PRM-5) stating that construction goes through op tools and `run_python` is for what they cannot do. Each `run_python` call MUST be transcribed as a `candidate_op` record (see OT-8).
**Why:** The hatch has to stay (a vocabulary that cannot be exceeded cannot grow), but every use must be a measured signal, not a silent default.
**Amends:** AGT-3; adds `PRM-15` (prompt revision registered with hypothesis before the run, PRM-4).
**Done means:** `tests/pure/test_agent_dispatch.py` refuses `run_python` without `reason`. `validate_revisions()` passes with the new revision. The revision's hypothesis: *escape-hatch calls per gate-passing brief fall below 1.0 on the five briefs within three paired rolls.*

**Closed:** 2026-09-10 — with the hypothesis PENDING measurement (recorded on revision 12 with `outcome=""`; the closing rule's outcome requirement applies to OT-9–OT-11, and OT-7's Done means is the refusal test plus a healthy registry).
**Gating tests:** `tests/pure/test_agent_dispatch.py::test_run_python_without_a_reason_is_refused_before_bpy` (missing, blank, whitespace and non-string reasons), `::test_run_python_with_a_reason_reaches_bpy`, `::test_the_run_python_schema_requires_the_reason`; `tests/pure/test_prompt_templates.py::test_the_revision_history_is_disciplined` (`validate_revisions() == []` with v12), `::test_each_revision_changes_exactly_one_place[12]`.
**Spec:** AGT-3 amended (`run_python` is the escape hatch; `reason` required, refused at the door; outcome carries reason and source hash); PRM-15 added; §2.2 run_python row; §5.4; §6.3 PRM 14 → 15.
**Shape of the change:** the `run_python` schema requires `reason` and its description opens with ESCAPE HATCH; `dispatch_tool` refuses a blank reason before `import bpy` with `RUN_PYTHON_REASON_REFUSAL`; a reasoned call's `ToolOutcome` carries `hatch_reason` and `source_sha256` (12 hex) — the candidate_op record's inputs, written into the transcript by OT-8. Working agreement v12 differs from v11 by exactly one hunk (the opening paragraph: a step is an op-tool call, or a chunk only when no op fits; the hatch must name what was missing) and is registered with the backlog's hypothesis; `ACTIVE_PROMPT_REVISION` stays at the pin (10) until measured.
**Measured:** hunks v11 → v12: `['replace lines 2-5 -> 2-11']`. A first draft that also reworded the loop's step 1 measured two hunks (the blank line between them is an equal line to difflib) and was cut back per PRM-5. Tool-set fingerprint `t:cc2df4bef820`; assembled prompt fingerprint unchanged (v10 is still active).
**Not done here, by design:** the candidate_op record itself is OT-8's transcript schema; the hypothesis outcome is OT-12's mining over v2 transcripts.
**Layers:** pure 645 passed / 1 skipped / 1 xfailed; Blender 315 passed / 3 skipped.
**Commit:** `70d80d8`.

---

## OT-8 Structured transcript

**What:** `TRANSCRIPT_SCHEMA_VERSION` MUST bump to 2. Every tool event MUST record: tool name, validated arguments, `plan_step`, gate verdict and analyzer fields when gated, `stage_reached`, wall time, and for `run_python` the `reason` and source hash. `IterationRecord` MUST carry the op-call sequence, not only the `run_python` sources (CNV-11 replay must still work from it).
**Why:** This is what turns normal use into a dataset. Free-text transcripts are not trainable and not minable.
**Amends:** AGT-17, CNV-11.
**Done means:** `tests/pure/test_transcript.py` round-trips a v2 record; `scripts/replay_iteration.py` rebuilds a scored iteration from an op-call sequence with no `run_python` present.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_tool_event.py::test_a_tool_event_round_trips_through_json`, `::test_a_v1_payload_is_refused_not_misread`, `::test_the_loop_emits_one_structured_event_per_dispatched_call` (validated arguments, plan step, stage, gates, wall time; ordered after the text the model reads), `::test_a_refused_call_is_recorded_as_refused`, `::test_the_hatch_record_carries_reason_and_hash`; `tests/pure/test_transcript.py::test_schema_two_stores_the_tool_event_under_data`; `tests/blender/test_replay_op_calls.py::test_an_op_call_sequence_replays_to_a_scored_pass` (twelve recorded calls, no `run_python`, three non-changing service calls skipped, form gate PASS), `::test_a_replay_that_builds_nothing_is_loud`; the five golden replays still pass through the same `replay_record`.
**Spec:** AGT-17 amended (schema 2, `tool_event`, `data`, `IterationRecord.tool_events`); CNV-11 amended (replay from the recorded call sequence, op calls through `call_op`); §2.5 iteration-log row; §5.4.
**Shape of the change:** `agent.tool_event.ToolEvent` (schema 2) is emitted by the loop on the `tool_event` channel after every dispatched or refused call, with the wall time measured around the dispatch. `ToolOutcome` now carries `ok`, `stage_reached`, `validated_arguments` and `gates`, and every service-tool branch returns one (the `(text, images)` tuple is gone from the service layer too); `harness.gate_verdict_json` / `harness_result_gate_json` give `run_chunk`'s gate and an op call's gate the same JSON shape. `ChatTranscript` schema 2 stores the event decoded under `data` and keeps it out of the Markdown; the addon lists `tool_event` as state-only. `run_agent_task.py` collects the sequence into `IterationRecord.tool_events`. `replay.calls_from` reads every recorded call; `replay_record` re-executes `run_python` sources and re-binds op calls through `call_op` — one read path over `tool_calls` for pre-OT-8 records and new ones alike, so the goldens needed no migration.
**Decision:** `tool_calls` (the raw call text the loop emitted) stays the replay source; `tool_events` is the measured record. A migration of the 67 historical records into `tool_events` was considered and rejected: it would have manufactured stage, gate and timing fields that were never measured.
**Layers:** pure 651 passed / 1 skipped / 1 xfailed; Blender 317 passed / 3 skipped.
**Commit:** `9a60a55`.

---

## OT-15 Schema-driven `search_ops`

**What:** `search_ops` MUST return the generated schema for each hit, not only the signature string, capped at `MAXIMUM_SEARCH_RESULTS`.
**Why:** Small models need the argument shape at the moment of use, not in the system prompt.
**Amends:** AGT-18.
**Done means:** `tests/pure/test_agent_dispatch.py` asserts schema presence in results.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_agent_dispatch.py::test_search_ops_returns_each_hit_with_its_generated_schema` (schema JSON present per hit; cap honoured), `::test_search_ops_spans_the_underscore_and_word_order` (three spellings of one op; a miss and an empty query are not ok); `tests/blender/test_transform_ops.py` search tests (the iteration-4 queries, narrowing by `schema:` line count).
**Spec:** AGT-18 amended.
**Shape of the change:** `search_ops` is a pure function over `OP_TOOL_SCHEMAS` (name, module, generated description) dispatched above `import bpy`; each hit prints the tool's description and its parameters schema as compact JSON; hits are ranked name-match first, shorter name first, facade order after — measured need: with facade order alone, "assign material" returned `assign_image_texture_material` first. The manifest-text search path is gone.
**Layers:** pure 653 passed / 1 skipped / 1 xfailed; Blender 317 passed / 3 skipped.
**Commit:** `0967110`.

---

## OT-16 Enforce retry and turn caps in the loop

**What:** The loop MUST enforce a named per-turn cap on consecutive gate failures on the same object (`MAXIMUM_GATE_FAILURES_PER_OBJECT`) and stop the turn with a contact sheet and a message, making the working agreement's "three honest attempts" code rather than prose.
**Why:** Closes AGT-20 / spec §7.2. With op tools, a retry is cheap and precise, so a cap no longer costs capability.
**Amends:** AGT-20 becomes verified.
**Done means:** `tests/blender/test_agent_loop.py` trips the cap with a builder that always fails the gate.

**Closed:** 2026-09-10.
**Gating tests:** `tests/blender/test_agent_loop.py::test_a_builder_that_always_fails_the_gate_trips_the_cap` (a chunk whose applied array leaves two islands fails the gate every time; the turn stops after three with `Bad_sheet.png` rendered and three tool results, not six); `tests/pure/test_turn_caps.py::test_three_consecutive_gate_failures_stop_the_turn_with_a_sheet`, `::test_a_passing_verdict_resets_the_count`, `::test_queued_calls_after_the_cap_get_a_not_run_result`.
**Spec:** AGT-20 rewritten from gap to requirement (verified); §7.2 gap row removed; §5.4 `MAXIMUM_GATE_FAILURES_PER_OBJECT`; §6.3 AGT unverified 2 → 1.
**Shape of the change:** the loop keeps a per-turn count of consecutive non-`done` gate verdicts per object, read from `ToolOutcome.gates` (so `run_python` with `object_name` and every gated op tool count alike); at `MAXIMUM_GATE_FAILURES_PER_OBJECT` it renders the object through the same dispatch seam (`render_views`), answers the model's queued calls with `GATE_CAP_TOOL_RESULT`, and returns `GATE_CAP_ANSWER` naming the object, the count and the last verdict. `_answer_pending_tool_calls` is now shared by cancel and the cap, and positional rather than id-based — measured: a scripted call with no id was answered twice under the id-based rule.
**Layers:** pure 656 passed / 1 skipped / 1 xfailed; Blender 318 passed / 3 skipped.
**Commit:** `be4c33f`.

---

## OT-17 Token budget per turn

**What:** `TurnCost` MUST be compared against a named `MAXIMUM_TURN_TOKENS` and the turn MUST stop at the next seam when exceeded, reported as text (same shape as the tool-call budget exhaustion, AGT-9).
**Why:** Cost is measured, not bounded (spec §7.2). Op tools shrink per-call tokens, which makes a budget that used to be unreachable reachable.
**Done means:** `tests/pure/test_agent_cancel.py` covers the seam.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_agent_cancel.py::test_the_turn_stops_at_the_seam_when_the_token_budget_is_exceeded` (reply 1 runs, reply 2 takes the turn over budget: its calls answered `TOKEN_CAP_TOOL_RESULT`, the turn ends with the exhaustion text), `::test_an_answer_over_budget_is_still_returned`, `::test_the_budget_is_per_turn_not_per_session`.
**Spec:** AGT-9 amended; §7.2 gap row removed (both §7.2 loop-limit rows are now closed); §5.4 `MAXIMUM_TURN_TOKENS`.
**Shape of the change:** `MAXIMUM_TURN_TOKENS` = 750,000, derived from measurement (24 calls × 25,851 tokens measured per call on the Claude Code lane ≈ 620k, plus a fifth). The loop snapshots `client.spent` at turn start and, at the seam after every reply, compares tokens billed since (input including cache reads and writes, plus output); a reply that wants more tool calls over budget has them answered `TOKEN_CAP_TOOL_RESULT` and the turn ends with `TOKEN_CAP_ANSWER`, the same shape as the tool-call exhaustion; a reply that already answers ends the turn whatever it cost. Every scripted client in the pure tests now carries `spent` like the real ones. `_answer_pending_tool_calls` finds the reply being closed as the LATEST occurrence in history — measured: a scripted client replaying one dict object twice made the first-occurrence search skip the pending calls.
**Layers:** pure 659 passed / 1 skipped / 1 xfailed; Blender 318 passed / 3 skipped.
**Commit:** `2922411`.

---

## OT-14 Selection as a first-class parameter type

**What:** Ops that act on a subset of geometry MUST accept a typed `EdgeSelector` / `FaceSelector` (by dihedral angle, by material slot, by axis-aligned face normal, by name pattern) rather than indices.
**Why:** Vertex indices are not something a model can reason about from a manifest; selectors are. This is the difference between an op vocabulary a 7B model can drive and one it cannot.
**Done means:** selector round-trips through the schema generator (OT-3) with an enum of selector kinds; `tests/blender/test_selectors.py` covers each kind against a fixture mesh.

**Closed:** 2026-09-10.
**Gating tests:** `tests/blender/test_selectors.py` — `::test_edge_selectors_resolve_each_kind`, `::test_face_selectors_resolve_each_kind`, `::test_vertex_selectors_resolve_each_kind` (every kind against one fixture box: 12 edges / 6 faces / 8 vertices with a marked top face and a `top_ring` group), `::test_weights_take_a_selector_not_indices`, `::test_a_selector_dispatches_as_a_tool_argument` (JSON in, enum validated, indices out; an unknown kind is an `ArgumentError`); `tests/pure/test_tool_schemas.py::test_a_selector_round_trips_as_an_object_with_an_enum_of_kinds`, `::test_the_select_ops_are_readers_with_selector_parameters`.
**Spec:** OPS-22 added; §5.5 selector constants; §6.3 OPS 21 → 22.
**Shape of the change:** `blended.ops.selectors` defines `EdgeSelector` (dihedral angle, material slot, vertex-group name pattern, all), `FaceSelector` (axis-aligned normal, material slot, vertex-group pattern, all) and `VertexSelector` (vertex-group pattern, height range, all) as frozen dataclasses whose `kind` is a `Literal`; `__post_init__` refuses a nonsensical selector. The schema generator maps `Literal` to an enum and a dataclass default to its fields; the binder checks enum membership. `select_edges` / `select_faces` / `select_vertices` are reader ops on the facade; `assign_vertex_group_weights` takes a `VertexSelector` instead of indices (the only subset op that took indices). "By name pattern" is read as a full-match regex over vertex-group names, stated once in the module docstring.
**Measured:** 45 op tools; tool-set fingerprint `t:2614a1448ba7`; assembled prompt `a10:107d5c63f0b0` (the manifest gained the selectors module and three config objects).
**Layers:** pure 678 passed / 1 skipped / 1 xfailed; Blender 323 passed / 3 skipped.
**Commit:** `36afbd7`.

---

## OT-12 Missing-op mining

**What:** `scripts/mine_candidate_ops.py` MUST read v2 transcripts and iteration logs, group `run_python` events by `reason` and by normalized source shape, and emit a dated markdown report ranking candidate ops by frequency × gate-pass rate.
**Why:** Vocabulary growth should be driven by measured demand, not guessed. Every hatch use is a vote.
**Done means:** the script is self-checking (fails on a v1 transcript rather than silently reading nothing) and produces a report on the existing five-brief runs after OT-8 lands.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_candidate_ops.py::test_a_record_without_tool_events_is_refused_not_read_as_empty` (v1 records and schema-1 transcripts refused by name), `::test_a_reason_is_one_spelling_and_a_shape_ignores_literals`, `::test_the_ranking_is_frequency_times_gate_pass_rate`, `::test_a_refused_hatch_call_is_not_a_vote`; the script refuses the un-filtered log (`iteration 1 ... predates OT-8`) and produced the report on the post-OT-8 runs.
**Spec:** CNV-14 added; §2.4 `make mine-ops`; §6.3 CNV 13 → 14.
**Shape of the change:** `blended.evaluate.candidate_ops` (pure) groups hatch events by normalized reason and by source shape (the dotted API the chunk called, facade imports included, literals and builtins excluded), ranks by frequency × gate-pass rate, and reports hatch calls per gate-passing brief — the v12 hypothesis metric. `scripts/mine_candidate_ops.py` / `make mine-ops FROM=68` write a dated Markdown report under `docs/candidate_ops/`.
**Measured (the report):** iterations 68–73, five gate-passing briefs' worth of runs on v12: 10 hatch calls on 68–71 plus 0 on 73; 3.00 hatch calls per gate-passing brief (hypothesis < 1.0: NOT met on this roll — one roll, no claim). Ranked candidates: rename an object (4 calls, 4/4 gate-passing), world-bounds reader (5 chunks, 4/4), mark UV seams by selector, lathe profile from rib parameters; two "placeholder" reasons show the reason field is gameable. The strongest finding is not a missing op: `location_m` was read as a center in both planter runs because the base convention never reaches the model (summary line only). All recorded on OT-13.
**Layers:** pure 678 passed / 1 skipped / 1 xfailed; Blender 323 passed / 3 skipped.
**Commit:** `2e7e2ac`.

---

## OT-11 Chat E2E on op tools

**What:** `make chat-e2e` scenarios MUST pass with `run_python` disabled entirely, for every scenario the vocabulary claims to cover (object, material, iterative edit at minimum; rig, weights, animation as the facade covers them).
**Why:** The E2E suite is the only headless proof that the surface is usable from the UI (NFR-18).
**Done means:** a `--no-hatch` flag on `scripts/chat_e2e.py`; scenarios that require the hatch are listed by name in the output as missing-op evidence for OT-12.

**Closed:** 2026-09-10.
**Gating tests:** `make chat-e2e ARGS="--no-hatch"` on 2026-09-10 (v12, Claude Code lane): 6/6 scenarios passed — object 8 tool calls, rig 10, weights 9, animation 8, material 8, iterative 12 — zero hatch attempts, no disabled-tool refusal, `MISSING-OP EVIDENCE (for OT-12): none`; transcripts under `outputs/chat_e2e/20260910-165504/`. `tests/pure/test_turn_caps.py::test_a_disabled_tool_is_neither_offered_nor_dispatched` covers the mechanism.
**Spec:** AGT-22 added (session `disabled_tools`, the loop refusal, the E2E flag and its listing); §2.4 `make chat-e2e ARGS="--no-hatch"`.
**Shape of the change:** `AgentSession.disabled_tools` withholds a tool from the schemas offered to the model and refuses a call to it with `DISABLED_TOOL_REFUSAL` (counted, recorded as a refused tool event). `scripts/chat_e2e.py --no-hatch` sets it for `run_python`, counts hatch attempts per scenario, and prints the scenarios that failed or reached for the hatch as missing-op evidence; its default revision is now v12.
**Measured beside it:** v12's outcome is recorded on the revision as measured once — the E2E passes without the hatch, while the five-brief roll sits at 3.00 hatch calls per gate-passing brief and the planter fails the form gate on the `location_m` convention (OT-13's first evidence).
**Layers:** pure passing with the revision outcome filled (below); Blender 323 passed / 3 skipped (unchanged since OT-14).
**Commit:** `485917e`.

---

## OT-13 First vocabulary expansion, from the five briefs

**What:** Implement the ops the five briefs (`planter_box`, `three_leg_stool`, `uv_crate`, `ribbed_column`, `crate_with_lid`) need to reach gate-pass with zero hatch calls. Expected from the brief contents, to be confirmed by OT-12: hollow-out with named wall thickness, bevel by edge selector, radial array, inset faces, mirror across a named plane, edge-selector primitives (by angle, by material, by name pattern).
**Why:** These are the briefs the convergence loop and the goldens already exercise; closing them first means every downstream instrument keeps working.
**Amends:** adds one `OPS-n` row per op, each with a fixture that trips its validation (GATE-18 discipline applied to ops).
**Done means:** `make converge` on each brief reaches structural + form gate pass with `run_python` disabled.
**Evidence 2026-09-10 (v12, Claude Code lane, iterations 68–73; report `docs/candidate_ops/2026-09-10-candidate-ops.md`):**
- Hatch calls per gate-passing brief: 3.00 over 3 (stool 6, uv_crate 1, column 2); planter 0 on its re-run (73) but it failed the form gate.
- Top candidate by reason and by gate-pass rate: **rename an object** (4 calls, 4/4 gate-passing) — `boolean_union` keeps the target's name and the brief wants `Stool`. Cheapest op in the list.
- Top by source shape: **read world bounds** (5 measurement chunks, 4/4 gate-passing) — the writer wants both operands' world boxes when a boolean says "no overlap".
- **Mark UV seams by edge selector** (uv_crate), **compute a lathe profile from rib parameters** (ribbed_column, 2 calls: the tool call cannot take a computed list), and "placeholder" reasons (2 on the stool: the reason field is gameable; count them).
- **Measured twice, not a missing op: `location_m` read as a CENTER** (68 and 73 both built the planter at base z 0.125 and failed the floor probe). Mechanism: `add_box`'s base-at-z convention lives in the docstring BODY, and both the manifest and the generated tool description carry only the summary line. Fix belongs here: either the parameter name carries the convention (`base_center_m`, which breaks every recorded golden source and costs a re-converge) or the schema carries the convention sentence. Decide by measurement on the planter.
- Cost of the surface on this lane: 58k tokens per call with 50 tools vs 26k with 8 (OT-17 correction); run 72 (crate_with_lid) died on `error_max_structured_output_retries` with the 50-variant envelope — one occurrence, not yet a cause.
- **First fix, measured (commit `fa3b1e5`, iteration 74):** `add_box`'s summary line now states BASE at `location_m[2]` (no rename). The planter then passed both deterministic gates on op tools alone: 14 calls, 0 hatch calls, base_z +0.0000, $0.30. One run; the pixel gate reports "the render moved" against golden 66 as any fresh run does.

**Closed:** 2026-09-10.
**Gating runs (`make converge ... ARGS="--no-hatch"`, v12, Claude Code lane, `run_python` withheld):** planter_box 75 (14 calls), three_leg_stool 76 (51 calls, three turns), ribbed_column 78 (7 calls), crate_with_lid 79 (15 calls), uv_crate 80 (11 calls) — every one passed the structural AND form gates with zero hatch calls, by construction. uv_crate's first sample (77) failed: seams on every edge above 30° after the bevel gave 26 islands against the cap of 12, seven `select_edges` probes and three rebuilds spent the 24-call budget, and the last box was left unlinked. The second sample used seams then unwrap and passed with 6 islands and 0 overlaps.
**Gating tests:** `tests/blender/test_vocabulary_ot13.py` (each op and the fixture that trips it: `NameTaken`, an empty new name, `NoEdgesSelected`; all three dispatch as tools with a gate verdict on the object-returning ones); `tests/blender/test_selectors.py` (OT-14) for the selector kinds the seam op uses.
**Spec:** OPS-23 (`rename_object`), OPS-24 (`world_bounds`), OPS-25 (`mark_uv_seams`); §2.4 `--no-hatch`; §6.3 OPS 22 → 25.
**What was built, and why these and not the expected list:** the backlog expected hollow-out, bevel by selector, radial array, inset, mirror. The measured demand (OT-12) was different: the stool needed to rename a boolean's result (4/4 gate-passing hatch calls), the writer wanted world bounds when a boolean reported no overlap (5 chunks), and the crate set seams through bmesh. Those three became ops. The `location_m` misread (planter, twice) was fixed by stating the base convention in `add_box`'s summary line (`fa3b1e5`), which is all the manifest and schema carry — measured true on iteration 74 and again on 75. Nothing from the expected list was needed to pass the five briefs; each stays unbuilt until a run asks for it.
**Costs, measured:** the five passing no-hatch runs billed $0.3–2.3 each on this lane. 75 briefs' worth of runs today; the account's 7-day window was at 62% before them.
**Observations for the next roll, not acted on:** `select_edges` used as a probe loop (seven calls in 77) suggests the reader should return what the edges ARE (their dihedral angles, count) rather than indices; the structured-output failure on run 72 has one occurrence.
**Layers:** pure 690 passed / 1 skipped / 1 xfailed; Blender 328 passed / 3 skipped.
**Commit:** recorded in the follow-up commit.
