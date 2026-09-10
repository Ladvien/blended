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
**Commit:** recorded in the follow-up commit.
