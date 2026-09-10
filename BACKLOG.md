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
**Launched 2026-09-10 12:17 CDT (user: "launch now"):** three holdout rolls on the frozen candidate tree `/Users/ladvien/blended-bench` (worktree at `68a124f`), writer `deepseek-v4-pro:cloud`, eye `kimi-k2.7-code:cloud` (the incumbent's), model dirs `blended-deepseek-v4-pro-ops-roll{1,2,3}` under the bench's `results/text_to_3D_agent/`; each roll is scored by the bench's own `executability.py` and `shape_chamfer.py`, then `diagnose_3dcode.py` into `outputs/bench/diagnose_<dir>.json`. Chain: `outputs/bench/logs/ot9_cloud_chain.sh` (detached; progress in `outputs/bench/logs/ot9_chain.log`; resumable by re-running). Measured pace: instance 6/20 of roll 1 after 50 min (≈ 2.8 h per roll). To finish once `ot9_chain.log` says ALL DONE:

```
python3 scripts/bench_panel.py \
  --group "deepseek-v10=outputs/bench/diagnose_blended-deepseek-v4-pro.json,outputs/bench/diagnose_blended-deepseek-v4-pro-iter1.json,outputs/bench/diagnose_blended-deepseek-v4-pro-iter2.json,outputs/bench/diagnose_blended-deepseek-v4-pro-iter3.json,outputs/bench/diagnose_blended-deepseek-v4-pro-chat1.json,outputs/bench/diagnose_blended-deepseek-v4-pro-chat1-roll2.json" \
  --group "ops-v12=outputs/bench/diagnose_blended-deepseek-v4-pro-ops-roll1.json,outputs/bench/diagnose_blended-deepseek-v4-pro-ops-roll2.json,outputs/bench/diagnose_blended-deepseek-v4-pro-ops-roll3.json" \
  --instances-file bench_sets/instances_holdout.txt
```

Then fill the **Outcome** line of the ops-lane pre-registration (H1 executability, H2 `cd_pca` within 0.0021) from that panel, and move this item.
**Hypothesis to state:** executability stays at parity or better; `cd_pca` moves within noise on the cloud writer (the cloud writer already executes 120/120, so the gain there is expected to be small). The real gain is expected in OT-10.

### OT-10 Local-lane roll

**What:** Run the same paired roll on one local lane (`bmb` llama-swap or Ollama) for both ACIs.
**Why:** This is where the change is expected to pay: executability first (BEN-5) means a local model that emits valid op calls but poor `bpy` will rank differently under the two surfaces. It is also the readiness test for any future specialist model behind a tool call.
**Done means:** ≥ `MINIMUM_PAIRED_ROLLS` rolls of ≥ `MINIMUM_INSTANCES_FOR_RANKING` instances each, reported on the panel with executability and `cd_pca`; the hypothesis (executability on the local lane improves by more than the per-roll noise band) is filled with an outcome. No paid lane (NFR-27).
**Launched 2026-09-10 12:17 CDT:** paired holdout rolls on bmb's llama-swap, writer `qwen3.8-27b` as its own eye (big's GPU is under a `coding` claim and is not touched), alternating the ops surface (frozen `/Users/ladvien/blended-bench`, model dirs `blended-local-qwen38-ops-roll{1,2,3}`) and the `run_python`-only incumbent (worktree `/Users/ladvien/blended-bench-old` at `4277aa3`, the OT-1 close, model dirs `blended-local-qwen38-hatch-roll{1,2,3}`), per-instance timeout 3000 s, scored the same way. Chain: `outputs/bench/logs/ot10_local_chain.sh`; progress in `outputs/bench/logs/ot10_chain.log`. The incumbent's own local noise band comes from the `hatch` rolls.
Measured pace: instance 2/20 after 50 min (≈ 25 min per instance, ≈ 8 h per sweep, six sweeps ≈ 2 days). To finish: `bench_panel.py --group "local-hatch=<the three diagnose_blended-local-qwen38-hatch-roll*.json>" --group "local-ops=<the three ...ops-roll*.json>" --instances-file bench_sets/instances_holdout.txt`; H3 (executability on the local lane improves by more than the hatch rolls' own per-roll band) is read off that panel. If two days is too long, one paired roll each (`roll1` only) is reported, never ranked (BEN-6), and the chain can be stopped after `blended-local-qwen38-hatch-roll1 scored` appears in `ot10_chain.log`.

---

## Phase 4 — Growing the vocabulary (the hatch tells you what to build)

All Phase 4 items (OT-12, OT-13, OT-14) are closed — see `BACKLOG_DONE.md`.

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
