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
