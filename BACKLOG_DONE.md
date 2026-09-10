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
**PENDING:** viewport sign-off of the 66/67 renders. Recorded here under this banner per the no-unmeasured-claim rule; the banner comes off with the sign-off, and a rejection reopens this item.
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
**Commit:** recorded in the follow-up commit.
