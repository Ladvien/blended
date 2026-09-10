# blended — Backlog: ops vocabulary as the agent tool surface

**Date:** 2026-09-10
**Baseline:** `main` @ `5764504`, per `docs/2026-09-10-specification-and-requirements.md`
**Problem being solved:** OPS-1 says all sanctioned construction goes through `blended.ops` and callers are never handed raw `bpy`. AGT-1 hands the agent `run_python(source)`. The verified construction vocabulary is not the agent's ACI; the escape hatch is. This backlog closes that gap.

## How to read this document

- One item per row block. `MUST` / `SHOULD` / `MAY` are RFC 2119.
- Every item names the requirement rows it amends or adds so the spec can be updated in the same change (§8.1 of the spec).
- **Done means** is the acceptance test. An item with no automated check is marked `(unverified)` and must not be closed as shipped.
- Phases are ordered by dependency, not by size. Phase 1 must land before any measurement in Phase 3 is meaningful.
- Item IDs are `OT-n` (ops-as-tools). They are stable.
- **When an item closes, move its block verbatim from this file to `BACKLOG_DONE.md`** in the same change, with the closing commit, gating tests, and date. This file lists only open work.

## Measured starting point

| Fact | Value | Source |
|---|---|---|
| Agent tools | 8 hand-written service tools + 42 generated op tools = 50 in `TOOL_SCHEMAS`, fingerprint `t:1fe7f62007ef` pinned (OT-3, closed) | `src/blended/agent/tools.py`, `tests/pure/test_tool_schemas.py` |
| Construction path in the ACI | 42 generated op tools, bound, gated, plan-required; `run_python(source, reason)` is the escape hatch (OT-3–OT-7, closed) | AGT-1, AGT-3, AGT-21 |
| Ops facade completeness | whole — every public op re-exported, builders import the facade only (OT-1, closed) | `tests/pure/test_one_path_ops.py` |
| Op signature contract | enforced — names in, names out, units on quantities, no bpy types (OT-2, closed) | `tests/pure/test_ops_signature_contract.py` |
| Shipped builders | 3 (crate, barrel, pallet) | OPS-15 |
| Manifest generation | introspects ops modules for prose AND for tool schemas (OT-3, closed) | PRM-2, `src/blended/manifest.py`, `src/blended/agent/tool_schemas.py` |
| Bench incumbent | `deepseek-v4-pro:cloud`, 6 rolls, 120/120 exec, `cd_pca` 0.0252 | `docs/2026-09-06-bench-panel-preregistration.md` |
| Transcript schema | `TRANSCRIPT_SCHEMA_VERSION` 2: structured `tool_event` per call, `IterationRecord.tool_events` (OT-8, closed) | AGT-17, `src/blended/agent/tool_event.py` |
| Retry / turn caps in the loop | gate-failure cap per object, 3 consecutive (OT-16); 1.7M-token budget per turn at the seam (OT-17, re-derived on the 50-tool lane); both closed | AGT-20, AGT-9 |

---

## Phase 1 — Prerequisites (the vocabulary has to be one thing before it can be a surface)

All Phase 1 items (OT-1, OT-2, OT-3) are closed — see `BACKLOG_DONE.md`.

---

## Phase 2 — The surface

All Phase 2 items (OT-4 through OT-8) are closed — see `BACKLOG_DONE.md`.

---

## Phase 3 — Measurement (no claim without a paired roll)

### OT-9 Pre-register the ops-lane benchmark roll

**What:** Before OT-4 ships, append a pre-registration to `docs/2026-09-06-bench-panel-preregistration.md` naming the comparison (ops tools + hatch vs incumbent `run_python`-only), the writer (`deepseek-v4-pro:cloud`, unchanged), the instance set (dev, then holdout only for ranking, BEN-8), the ranking rule (executability first, then `cd_pca`, BEN-4/5), the target (`TARGET_RELATIVE_IMPROVEMENT` on the incumbent's own mean, BEN-7), and the hypothesis.
**Why:** BEN-10 forbids single-roll claims; a pre-registration forbids post-hoc ones.
**Done means:** the pre-registration is committed with a date before the first ops-lane roll's directory timestamp.
**Status 2026-09-10:** pre-registration appended to `docs/2026-09-06-bench-panel-preregistration.md` (§ "Ops-lane pre-registration — 2026-09-10 (OT-9)") before OT-4 shipped, hypotheses H1–H3 stated; outcome line pending the first paired roll. Stays open until the outcome is filled from measurement (closing rule).
**Hypothesis to state:** executability stays at parity or better; `cd_pca` moves within noise on the cloud writer (the cloud writer already executes 120/120, so the gain there is expected to be small). The real gain is expected in OT-10.

### OT-10 Local-lane roll

**What:** Run the same paired roll on one local lane (`bmb` llama-swap or Ollama) for both ACIs.
**Why:** This is where the change is expected to pay: executability first (BEN-5) means a local model that emits valid op calls but poor `bpy` will rank differently under the two surfaces. It is also the readiness test for any future specialist model behind a tool call.
**Done means:** ≥ `MINIMUM_PAIRED_ROLLS` rolls of ≥ `MINIMUM_INSTANCES_FOR_RANKING` instances each, reported on the panel with executability and `cd_pca`; the hypothesis (executability on the local lane improves by more than the per-roll noise band) is filled with an outcome. No paid lane (NFR-27).

---

## Phase 4 — Growing the vocabulary (the hatch tells you what to build)

### OT-13 First vocabulary expansion, from the five briefs

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

---

## Phase 5 — Bounding cost (cheap, and the ops lane makes it safe to do)

Both Phase 5 items (OT-16, OT-17) are closed — see `BACKLOG_DONE.md`.

---

## Phase 6 — The flywheel (only after Phase 3 shows the surface is better on a local lane)

### OT-18 Dataset export

**What:** `scripts/export_traces.py` MUST emit, from v2 transcripts, one record per gate-passing turn: brief or user ask, scene context, op-call sequence with arguments, final analyzer report, `cd_pca` where a reference exists. Records MUST be filtered by a named pass threshold and MUST exclude any turn that used the hatch.
**Why:** This is the rejection-sampled corpus for a specialist model behind a tool call. It does not exist until OT-8 exists, and it is not worth building until OT-10 shows the surface helps a small model.
**Done means:** the exporter is self-checking (refuses to emit a record missing a gate verdict) and the record schema is versioned.

### OT-19 Specialist-model lane (deferred; not scheduled)

**What:** A transport lane whose model is a fine-tuned small coder trained on OT-18 output, wired behind one or more op tools, with the frontier writer as fallback on a failing gate.
**Why:** Recorded so the dependency chain is explicit. Not scheduled: the decision to build it MUST be made on OT-10 and OT-18 numbers, not on this document.
**Done means:** `(unverified)` — no acceptance test until the item is scheduled.

---

## Corrections to closed items

Entries in `BACKLOG_DONE.md` are never edited; a measured correction to a closed item is recorded here with the mechanism and the commit.

| Item | Correction | Measured | Commit |
|---|---|---|---|
| OT-17 (`2922411`) | `MAXIMUM_TURN_TOKENS` re-derived 750,000 → 1,700,000. The 750k figure came from the 8-tool lane (25,851 tokens per call); with 50 op tools the Claude Code lane bills 58,241 per call (91 % cache reads), and the budget stopped iteration 68 (planter_box, v12) at call 16 of 24. Mistake memory: `a-budget-derived-before-the-surface-changed-stops-honest-turns`. | iteration 68: 931,851 tokens / 16 calls | `6fdd91a` |

## Not in this backlog, and why

| Item | Why it is excluded |
|---|---|
| Examiner licence (spec §7.1) | Orthogonal to the tool surface; `--examiner none` keeps the loop usable. Worth its own backlog. |
| Lane skill-module selection (PRM-14) | Prompt tuning has the smallest ceiling of the levers here. Revisit after OT-9/OT-10 show what the prompt still needs to say. |
| Organic / character asset generation | Not a code-gen problem. Belongs to the ingest lane (ING-*) plus cleanup, not to this surface. |
| Retopology | Algorithmic or dedicated-model, not an op an LLM should author. May become a service tool later. |

## Dependency graph

```mermaid
flowchart LR
  OT1 --> OT2 --> OT3 --> OT4 --> OT5 --> OT6 --> OT7 --> OT8
  OT8 --> OT9 --> OT10
  OT8 --> OT11
  OT8 --> OT12 --> OT13
  OT3 --> OT14 --> OT13
  OT3 --> OT15
  OT4 --> OT16 --> OT17
  OT10 --> OT18 --> OT19
```

## Closing rule

An item closes only when its **Done means** test is in the tree and green in both layers (`make test`), the spec rows it amends are updated in the same change (§8.1), and — for OT-9 through OT-11 — the pre-registered hypothesis has an outcome filled from measurement. A single roll closes nothing.
