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
**Commit:** `709dc33`.

---

## OT-20 The bench bridge carries op calls

**What:** `scripts/run_3dcode_instance.py` MUST emit the standalone script from the recorded call SEQUENCE — every executed `run_python` chunk AND every successful op-tool call, in order, the op calls as `from blended.ops import <op>` plus the call with its validated arguments (the encoding `evaluate.replay.calls_from` already reads) — so the bench re-bakes what the agent built. A chunk or op call whose result was not OK is excluded, as today.
**Why:** the bridge predates the op tools; a roll that drops 37 op calls from a script measures a different program than the one the gates passed. Found by reading OT-9's roll 1 before scoring it.
**Amends:** BEN-1 (the bridge), CNV-11 (replay and the bridge read one encoding).
**Done means:** `tests/blender/test_bench_bridge.py` builds a brief with op calls only, runs the bridge's script assembly, executes the emitted script in a fresh scene, and the form gate passes on the re-baked object; a run with zero op calls emits byte-identical output to today's.

**Closed:** 2026-09-10.
**Gating tests:** `tests/blender/test_bench_bridge.py::test_an_op_built_brief_re_bakes_from_the_standalone_script` (the planter through the real dispatcher: 13 calls, 9 op calls and 1 chunk included, 1 raising boolean excluded, the emitted script re-executed in an empty scene passes the form gate; `plan_step` absent from the script); `tests/pure/test_bench_bridge.py` (inclusion by stage, not text; op calls emitted in order through the binder; a chunks-only record keeps the chunk format byte for byte; nothing ran means no epilogue).
**Spec:** BEN-1 amended; CNV-11 notes the shared rule.
**Shape of the change:** `blended.evaluate.bench_bridge` owns the rule and the assembly: `RecordedCall(tool_name, validated arguments, stage_reached)`; a call is included iff its stage is past `execute` — the same fact for a chunk and an op call, replacing the text-prefix heuristic `chunk_executed`; an op call is emitted as `_op(name, {validated arguments})` and bound at bake time through `bind_arguments`, so a `tuple[BoneSpec, ...]` or an `EdgeSelector` is rebuilt by the one converter the loop used. The runner records every dispatched call and reports `n_op_calls_included`. The chunk body and the epilogue are byte-identical to the previous assembly; the prelude grew the helper.
**Not byte-identical, stated:** the Done means asked for identical output on a record with zero op calls; the prelude now carries the `_op` helper on every script, so identity holds for the chunk section and the epilogue, not the prelude.
**Layers:** pure 694 passed / 1 skipped / 1 xfailed; Blender 329 passed / 3 skipped.
**Commit:** `de44184`.

---

## OT-21 The bench chain bakes before it scores

**What:** the sweep chain MUST run the bench's own bake (`/Users/ladvien/3dcodebench/.venv/bin/python core/render.py --model <dir> --results-root <root> --blender <Blender>`) between the sweep and the scorers, and MUST refuse to score a model dir whose instances lack `renders/render_log.json`.
**Why:** `executability.py` and `shape_chamfer.py` read what the bake wrote; without it they report 0/20 with a fingerprint that reads like a model failure.
**Done means:** `outputs/bench/logs/*_chain.sh` carry the step; a dry run on roll 1's existing scripts produces 20 render logs; the scorer step is guarded.

**Closed:** 2026-09-10.
**Gating runs:** `scripts/bake_3dcode.py` on roll 1's 20 existing scripts: 20 render logs, render statuses `{OK: 13, ERR_EXEC: 7}`, GLBs for the 13 that executed, exit 0 "safe to score" — the 7 that did not execute are the benchmark's own executability number for the pre-OT-20 bridge, not a bake defect. One fresh instance (AquariumTank) through the OT-20 runner on the cloud lane, then baked: `OK_AGENT_DONE` in 690 s, one `_op(` line in the script, re-bake status OK, 1 mesh, 4 views, GLB 33.6 KB.
**Spec:** BEN-11 added; §2.4 `scripts/bench_chain.sh`; §6.3 BEN 10 → 11.
**Shape of the change:** `scripts/bake_3dcode.py` runs the bench's `core/render.py` and `core/export_glb.py` for a model dir and then refuses (exit 2, instances named) unless every scripted instance has its render log and, where the log says the script executed, its GLB. `scripts/bench_chain.sh` is the committed roll template: sweep → bake → executability → shape_chamfer → diagnose, the scorers gated on the bake's exit; the operational chains under `outputs/bench/logs/` are regenerated from it for OT-27.
**Found by the smoke, fixed here:** (1) the first guard demanded a GLB from a script that failed to execute — the benchmark's failure semantics, restored; (2) `--overwrite` had reached only the render orchestrator; (3) the emitted script's `blended` imports resolved against the installed `blended_agent` addon's bundled copy, because the bench bakes without `--factory-startup` — the prelude now evicts `blended*` from `sys.modules` first; recorded as `the-host-blender-already-holds-an-older-blended`.
**Layers:** pure 698 passed / 1 skipped / 1 xfailed; Blender 329 passed / 3 skipped.
**Commit:** `3c76b39`.

---

## OT-23 Measure the composition of a call, per lane

**What:** `scripts/context_composition.py` MUST split one call's tokens into working agreement, manifest sections, tool schemas, scene block and history, per lane, using each lane's own tokenizer where one is reachable (bmb's `/tokenize`) and the transport's `usage` otherwise, and write the row into the spec's measured-state table.
**Why:** everything in this phase is sized by this number; `TurnCost` measures the total only.
**Done means:** the script is self-checking (the parts sum to the assembled whole within the tokenizer's join error) and its output is in the spec.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_context_budget.py::test_every_part_is_a_verbatim_substring_and_the_remainder_is_small`, `::test_the_composition_sums_and_names_both_lanes`, `::test_an_unreachable_tokenizer_refuses_instead_of_estimating`, `::test_the_spec_row_is_written_once_and_replaced_in_place`; the live run wrote the "Context per call" row into the spec's measured-state table.
**Spec:** the row; §2.4 `scripts/context_composition.py`.
**Measured (bmb `qwen3.8-27b` tokenizer, wire encoding, v12, 56 tools):** system prompt 7,569 — working agreement 1,770, conventions 228, manifest operations + config objects 3,074, gate fields + budget 291, drift catalog 2,148, scaffolding 58; tools 9,245 on the OpenAI/Ollama lanes (op tools 7,904, service 1,342) and 10,485 as the Claude Code envelope with its protocol note; **static per call 16,814 / 18,054** before scene and history. The earlier 15.0k figure used compact JSON; the wire uses the default separators, which cost 1.8k more.
**Shape of the change:** `blended.agent.context_budget` splits the assembled prompt into verbatim substrings plus a measured scaffolding remainder, renders the tool set the way each lane sends it, counts with an injected tokenizer (`bmb_tokenizer` binds to llama-server's `/tokenize` and raises `TokenizerUnreachable` rather than estimate), and writes one idempotent spec row.
**Layers:** as OT-21.
**Commit:** `cc28cf1` (OT-23 code landed with OT-21's commit `3c76b39`).

---

## OT-22 Context preflight and truncation as failures

**What:** every lane MUST know its model context (`ModelConfig.context_tokens`: 65,536 for bmb's `qwen3.8-27b`, `num_ctx` for Ollama-native, the CLI's for Claude Code) and the loop MUST refuse to send a request whose prompt tokens plus tool schema plus the reply ceiling exceed it, naming the sizes; a transport reply that reports truncation MUST be an error, never a result. The per-request ceiling on the llama-swap lane (`LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS` = 900) MUST be measured against a real 27B turn and re-derived the way the token budget was.
**Why:** the one place the fail-loud rule is missing. A 65k-context lane holding 15k of static prefix reaches its limit inside a long turn, and the OT-10 roll's first instance died at the request ceiling instead.
**Amends:** NFR-13; adds `AGT-23`.
**Done means:** `tests/pure/test_context_preflight.py` refuses an oversize prompt with the sizes named and passes one that fits; a fake transport reporting `truncated` is an error.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_context_preflight.py::test_context_tokens_come_from_each_lanes_own_number`, `::test_the_estimate_is_the_measured_ratio`, `::test_preflight_refuses_with_every_number_named`, `::test_a_cut_reply_is_an_error_on_every_wire` (finish_reason/done_reason length, `truncated`, prompt larger than the context), `::test_the_loop_refuses_before_calling_the_model` (a 32k lane with 16k reserved and ~20k of history: the model is never called, the answer names the sizes), `::test_an_unmeasured_lane_is_reported_once_and_still_runs`.
**Spec:** AGT-23 added; NFR-13 amended; §5.4 (`LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS`, `CONTEXT_TOKENS_BY_MODEL`, `CLAUDE_CODE_CONTEXT_TOKENS`, `CHARS_PER_TOKEN_ESTIMATE`); §6.3 AGT 22 → 23; §7.2 gains the unmeasured-lane row.
**Shape of the change:** `ModelConfig.context_tokens` reads the served `-c` per model from bmb's llama-swap config (65,536 for `qwen3.8-27b`, 32,768 for the 32B and smaller), `num_ctx` on the Ollama lanes, the documented 200k on the Claude Code lane, and `None` for a model with no measured entry. `blended.agent.context_preflight` estimates the request at the measured 3.8 characters per token, refuses at the seam before the model call when the estimate plus the reserved completion exceeds the context (every number in the message), reports an unmeasured lane once per turn on a `preflight` event, and turns a cut reply into an error on both wire protocols and both streamed paths (the assemblers now carry `finish_reason` / `done_reason`).
**Measured (bmb `qwen3.8-27b`, one real full-prefix request, 16,997 prompt tokens):** cold 226.1 s — prefill 142.9 s (119 tok/s), 711 completion tokens in 67.7 s (10.5 tok/s); warm 17.6 s with the prefix read from llama-server's cache in 0.3 s. The request ceiling is re-derived from that: cold load ~240 s + prefill 143 s + 16,384 completion tokens at 10.5 tok/s ≈ 1,943 s → `LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS` = 2000 (was 900, which killed OT-10's first instance mid-generation). The model's first move on that request was `declare_plan`.
**Layers:** pure 704 passed / 1 skipped / 1 xfailed; Blender 329 passed / 3 skipped.
**Commit:** `6ef543c`.

---

## OT-24 One description per op: drop the manifest's ops section

**What:** the manifest MUST stop rendering the operations section into the prompt (3,074 tokens); the generated schema is the one description of each op. Conventions, gate fields, budget knobs and the drift catalog stay. Register the prompt change with a hypothesis before the run.
**Why:** "nothing is written twice" applies to the context window as much as to source.
**Amends:** PRM-1, PRM-2; a new prompt revision is NOT needed (the `.j2` does not change) but the assembled fingerprint moves and is re-pinned.
**Done means:** the five briefs still pass with the hatch withheld; `tests/pure/test_manifest.py` asserts no op signature appears in the assembled prompt.

**Closed:** 2026-09-10.
**Gating runs and tests:** `make converge ... REVISION=14 ARGS="--no-hatch"`: planter 81 (13 calls), stool 86 (56 calls, three refinements pass), uv_crate 83 (10), column 84 (8), crate_with_lid 85 (21) — all FORM PASS, zero `search_ops` calls; `make chat-e2e ARGS="--no-hatch --revision 14"` 6/6 in 46 tool calls. `tests/pure/test_prompt_templates.py::test_the_prompt_describes_no_op_twice`; `::test_each_revision_changes_exactly_one_place[13]`, `[14]`; `tests/pure/test_refinement_missing_part.py`.
**Spec:** PRM-1 amended (the operations section leaves the prompt), PRM-2 verification; §5.4 pins row; the "Context per call" row re-measured on v14.
**Shape of the change:** `build_system_prompt` renders conventions plus the manifest's gate-fields and drift-catalog slice, never the operations section; `include_operations` is gone and the manifest headings are asserted, not searched for with a silent -1. Working agreement v13 (one hunk: "the rest of your tool list") and v14 (one hunk: the tool-discipline bullet now points at the tool list and `search_ops`) are registered with hypotheses and measured outcomes; `ACTIVE_PROMPT_REVISION` stays at the pin. The composition script measures the prompt without the section.
**Measured:** system prompt 7,569 → 4,482 tokens on bmb's tokenizer (−3,087); static per call 16,814 → 13,727 (OpenAI/Ollama) and 18,054 → 14,967 (Claude Code); assembled fingerprint moved to `a10:c68237772de1`.
**Found by the first stool run (82), fixed here:** the driver died in `RefinementOutcome._measured` when a refinement turn left the part named `Seat` — a missing dimension now reads "missing (part not found)" in the summary and counts as a failure instead of losing the record.
**Layers:** pure 713 passed / 1 skipped / 1 xfailed; Blender 329 passed / 3 skipped (both by exit code).
**Commit:** `75ec2c9`.

## OT-25 Progressive disclosure of op tools

**What:** the loop MUST offer the service tools, the readers and a CORE set of op tools on every call, and expose the rest through `search_ops` (which already returns the schema). The core set MUST be derived from `tool_events` frequency across gate-passing runs, never listed by hand, and the offered set MUST be fingerprinted per turn so the pin tests see a change.
**Why:** 15 of 48 ops carried all five briefs; the other 33 cost 4k+ tokens per call on every lane and a `oneOf` variant each on the CLI lane.
**Hypothesis to register before the roll:** executability on the local lane rises, per-call tokens fall below the 8-tool baseline (25,851 on the CLI lane), and hatch calls per gate-passing brief do not change.
**Done means:** `tests/pure/test_tool_disclosure.py` covers the derivation, the per-turn fingerprint and a search-then-call round trip; the five briefs pass no-hatch on the disclosed set.

**Closed:** 2026-09-10.
**Gating runs and tests:** `make converge ... REVISION=14 ARGS="--no-hatch"` on the disclosed surface: planter 87 (14 API calls), uv_crate 89 (15), column 90 (8), crate_with_lid 91 (9), stool 92 (38; three refinements pass) — all FORM PASS, zero hatch calls, 12 `search_ops` calls for 11 undisclosed ops; the stool's first run 88 FAILED its third refinement at the 24-call turn cap (recorded in the pre-registration outcome). `make chat-e2e ARGS="--no-hatch --revision 14"` 6/6 in 56 tool calls (46 on the whole set). `tests/pure/test_tool_disclosure.py` (8 tests: derivation; generated module equals the derivation from the real log; offered set seen by the client; a withheld tool leaves it; undisclosed op dispatches after `search_ops` with the fingerprint on every event; envelope catch-all; module round trip), `tests/blender/test_agent_loop.py::test_an_undisclosed_op_found_by_search_ops_runs_through_the_real_dispatcher`.
**Spec:** AGT-1 (the offered set, the generated module, the fingerprint on events and records), AGT-14 (envelope from the offered set + catch-all variant; preflight sends the same), §2.5 `src/blended/agent/core_tools.py`, §5.4 `MINIMUM_BRIEFS_USING_OP`, the scripts table (`scripts/derive_core_tools.py`), the "Context per call" row re-measured on the offered set.
**Shape of the change:** `tool_disclosure.py` derives the core (scene-changing ops used successfully in ≥ 2 gate-passing briefs) and writes it as the generated module `core_tools.py` (`CORE_OPS`: add_box, add_cylinder, assign_material, boolean_difference, link_into_scene, rename_object, snap_base_to_ground); `AgentSession.offered_tools()` = service + readers + core − withheld, fingerprinted per turn and stamped on every `ToolEvent` and the `IterationRecord`; the door and the binder are untouched, so any facade op runs by name once `search_ops` has shown it; the Claude Code envelope gains one catch-all variant (enum of the undisclosed names, free-form arguments). Hypotheses H4–H7 pre-registered before the runs; H5 holds (mean 18,891 tokens per call, four of five briefs under 25,851), H7 read 1.09 per op, H4/H6 wait for OT-27.
**Measured:** offered 29 of 56 (8 service + 14 readers + 7 core); static per call 13,727 → 8,646 (OpenAI/Ollama) and 14,967 → 9,626 (Claude Code) tokens on bmb's tokenizer; the Claude Code lane billed 16,880–17,833 tokens per API call on the four single-turn briefs (24,248–30,498 on the whole set at v14).
**Layers:** recorded in the closing commit message (both by exit code).
**Commit:** implementation `e7b6d5e`; closing commit recorded in the follow-up commit.

## OT-26 Cache-friendly prefix order

**What:** on lanes with prefix caching (Claude Code, OpenRouter) the static content — working agreement, conventions, tool set — MUST precede everything that changes per turn (scene block, history), and the cache-read fraction MUST be reported per run.
**Why:** measured today on the CLI lane: 89 % of input tokens were already cache reads (iteration 74: 331,796 of 372,080), so the remaining lever is the last 11 %; this item is ranked last for that reason and is closed by measurement, not by reordering on faith.
**Done means:** `TurnCost` cache-read fraction per run is in the record; a paired comparison shows the fraction did not fall.

**Closed:** 2026-09-10 — by measurement; no reordering was needed.
**Gating tests:** `tests/pure/test_cache_report.py` (the fraction is one function, `TurnCost.cache_read_fraction`, shown in the `spent` line; rows skip pre-accounting records; the paired comparison takes each brief's latest run on each side); the order itself was already pinned by `tests/pure/test_claude_code_lane.py::test_the_system_prompt_is_byte_stable_across_builds` and `::test_a_growing_transcript_keeps_the_previous_turn_as_its_prefix` — the system prompt (working agreement, conventions, protocol note) is static and travels as `--system-prompt`, the tool envelope as `--json-schema`, and the fold is append-only, so nothing per-turn precedes the static content on the Claude Code lane.
**Spec:** AGT-24 added; the "Prefix cache" row in the measured-state table; the scripts table (`scripts/cache_read_report.py`).
**Measured (`scripts/cache_read_report.py --before 81-86 --after 87-92`, whole set → disclosed set, both v14, hatch withheld):**

| brief | cache read before (iteration) | after (iteration) | delta | writes/call before | after | delta |
|---|---|---|---|---|---|---|
| crate_with_lid | 0.851 (85) | 0.812 (91) | -0.039 | 3,989 | 3,274 | -715 |
| planter_box | 0.829 (81) | 0.791 (87) | -0.039 | 4,259 | 3,733 | -527 |
| ribbed_column | 0.923 (84) | 0.885 (90) | -0.037 | 1,908 | 1,956 | +48 |
| three_leg_stool | 0.729 (86) | 0.647 (92) | -0.082 | 8,686 | 8,910 | +224 |
| uv_crate | 0.937 (83) | 0.883 (89) | -0.054 | 1,531 | 1,978 | +447 |

mean cache-read delta -0.050 over 5 paired brief(s); fell on 5; mean writes/call delta -104; rose on 3

The **Done means** as written ("the fraction did not fall") is NOT met: it fell on all five briefs. The mechanism is the ratio, not the order: the numerator is the static prefix, and OT-25 cut that prefix by ~5,300 tokens per call while each turn's new content (tool results, `search_ops` pages) stayed, so a smaller share of a smaller call is cached even though every call is cheaper (planter: 24,933 → 17,833 tokens per call). The number a volatile prefix would inflate — cache WRITES per call — moved −104 on average (rose on three briefs by 48–447 tokens, the extra `search_ops` result text; fell on two by 527–715). Recorded as the wrong number and the right one; the criterion for any future reorder is writes per call, and the fraction is reported per run as the item asked.
**Layers:** recorded in the closing commit message (both by exit code).
**Commit:** recorded in the follow-up commit.
