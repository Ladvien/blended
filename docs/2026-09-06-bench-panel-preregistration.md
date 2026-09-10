# Bench panel pre-registration — 2026-09-06

This rule is written BEFORE the next experiment, which is what the iter3
post-mortem asked for and did not get. Three change classes — the harness/prompt
iterations 1-3, the chat harness, and the writer swap — were each judged on a single
roll of `cd_yawmin`, and each measured flat. That was not three null results; it was
one instrument being read past its resolution three times. The six surviving
20-instance rolls put `cd_yawmin` at mean 0.0769 with a between-roll SD of 0.0072,
so the 0.0706 that has been quoted as a no-regression guard is the MINIMUM of six
draws, not an expected value, and the apparent iter1 regression to 0.0903 was
orientation alone: `cd_pca` stayed inside 0.023-0.028 in every roll.

**No candidate may be ranked on a single roll again.** A candidate is a mean over at
least three paired rolls of the same 20 instances, ranked on `cd_pca` with
executability lexicographically first; `cd_yawmin` and `delta_orient` stay on every
panel and rank nothing. The detectable effect below is quoted at that three-roll
floor rather than at the six rolls this incumbent happens to have, because the floor
is what binds the next candidate. Two numbers to carry forward, including the one
that was wrong: the plan for this panel predicted `cd_yawmin`'s 15% target would
read "below the instrument's resolution" at 0.0115 against 0.0180, but 0.0180 is the
ONE-roll detectable effect; at the three-roll floor the same target clears by 1.11x
and reads visible — marginally. The mechanism worth remembering is that a power
verdict is a function of the roll count you quote it at, and quoting it at a
different N than the rule enforces is how an axis gets promoted or retired by
arithmetic instead of by measurement. `cd_pca` clears by 1.84x and `delta_orient`
does not clear at all (0.82x).

Regenerate with:

```
python3 scripts/bench_panel.py \
  --group "deepseek-v10=outputs/bench/diagnose_blended-deepseek-v4-pro.json,\
outputs/bench/diagnose_blended-deepseek-v4-pro-iter1.json,\
outputs/bench/diagnose_blended-deepseek-v4-pro-iter2.json,\
outputs/bench/diagnose_blended-deepseek-v4-pro-iter3.json,\
outputs/bench/diagnose_blended-deepseek-v4-pro-chat1.json,\
outputs/bench/diagnose_blended-deepseek-v4-pro-chat1-roll2.json" \
  --reported-roll outputs/bench/diagnose_blended-deepseek-v4-pro-iter1-roll2.json \
  --reported-roll outputs/bench/diagnose_blended-deepseek-v4-pro-iter1-roll3.json \
  --reported-roll outputs/bench/diagnose_claude_code_sonnet_dev.json \
  --instances-file bench_sets/instances_holdout.txt
```

## Pre-registered rule

Ranking is on **`cd_pca`** alone. `cd_yawmin`, `delta_orient` are reported on every panel and rank nothing.

**Executability is lexicographically first.** A group whose executability is below another's cannot rank better, however good its `cd_pca` is: a configuration that declines to produce a mesh scores nothing on the instances it skipped, so a shape mean is only comparable between groups that attempted the same work.

A candidate is a mean over at least **3 paired rolls** of the same instance set, each covering at least **20 instances**. A roll below that instance count is reported and never ranked. The frozen set named in `bench_sets/instances_holdout.txt` holds 20 instances.

The target is **relative**: 15% better than the incumbent's own measured mean, so it moves with the incumbent instead of being a literal that goes stale. A regression is a one-sided move of more than **2 sigma** on the ranking metric's standard error.

## Rolls

| roll | n | exec_ok | cd_pca | cd_yawmin (reported) | delta_orient (reported) | turns | sec/inst |
|---|---|---|---|---|---|---|---|
| blended-deepseek-v4-pro | 20 | 20/20 | 0.0235 | 0.0706 | 0.0471 | 13.2 | 426 |
| blended-deepseek-v4-pro-iter1 | 20 | 20/20 | 0.0265 | 0.0903 | 0.0637 | 11.1 | 263 |
| blended-deepseek-v4-pro-iter2 | 20 | 20/20 | 0.0231 | 0.0714 | 0.0483 | 13.6 | 339 |
| blended-deepseek-v4-pro-iter3 | 20 | 20/20 | 0.0273 | 0.0761 | 0.0488 | 15.2 | 408 |
| blended-deepseek-v4-pro-chat1 | 20 | 20/20 | 0.0234 | 0.0745 | 0.0511 | 14.5 | 306 |
| blended-deepseek-v4-pro-chat1-roll2 | 20 | 20/20 | 0.0277 | 0.0788 | 0.0511 | 12.1 | 312 |
| blended-deepseek-v4-pro-iter1-roll2 (not ranked) | 3 | 3/3 | 0.0390 | 0.1309 | 0.0920 | 9.3 | 402 |
| blended-deepseek-v4-pro-iter1-roll3 (not ranked) | 3 | 3/3 | 0.0431 | 0.1290 | 0.0859 | 9.0 | 361 |
| blended-claude-code-sonnet-dev (not ranked) | 12 | 12/12 | 0.0477 | 0.0708 | 0.0231 | 14.8 | 526 |

## Groups

| rank | group | rolls | exec | cd_pca | cd_yawmin | delta_orient | SE(cd_pca) |
|---|---|---|---|---|---|---|---|
| 1 | deepseek-v10 | 6 | 120/120 | 0.0252 | 0.0769 | 0.0517 | 0.0007 |

## Power

The detectable effect is quoted at the RULE'S FLOOR of 3 rolls, not at the roll count an incumbent happens to have: a future candidate is bound by the floor, so a verdict computed on six accumulated rolls would promise resolution nobody has to buy. The group's own SE is printed beside it.

### deepseek-v10 — 6 ranking-eligible rolls

| axis | mean | median per-instance span | mean per-instance SD | SE of a 20-mean | SE of the 6-roll mean | SE at the 3-roll floor | target (15%) | detectable at 2σ | margin |
|---|---|---|---|---|---|---|---|---|---|
| cd_pca | 0.0252 | 0.0161 | 0.0080 | 0.0018 | 0.0007 | 0.0010 | 0.0038 | 0.0021 | 1.84x |
| cd_yawmin | 0.0769 | 0.0541 | 0.0402 | 0.0090 | 0.0037 | 0.0052 | 0.0115 | 0.0104 | 1.11x |
| delta_orient | 0.0517 | 0.0317 | 0.0366 | 0.0082 | 0.0033 | 0.0047 | 0.0078 | 0.0095 | 0.82x |

- `cd_pca`: **visible** — a 15% improvement is 0.0038, at or above the 2σ detectable effect of 0.0021 (1.84x).
- `cd_yawmin`: **visible** — a 15% improvement is 0.0115, at or above the 2σ detectable effect of 0.0104 (1.11x).
- `delta_orient`: **below the instrument's resolution** — a 15% improvement is 0.0078 against a 2σ detectable effect of 0.0095 (0.82x).

## Not measured

**Image similarity.** Absent for two independent reasons:

1. `3dcodebench/metrics/image_similarity.py` needs `torch` and `transformers`, and neither is installed in `/Users/ladvien/3dcodebench/.venv` or `/Users/ladvien/blended/.venv`.
2. No reference images exist to compare against: there is no `data/<instance>/images/` directory in the benchmark checkout, so the metric has no second operand even with the packages installed.

The generated meshes are NOT gone: every `model_dir` above resolves with its `glb/<instance>.glb` present, and the reference GLBs survive under `data/<instance>/glb/`. So the axis is missing its packages and its reference images, not its geometry.

**Requirement on the next roll:** retain `glb/` and `renders/`. With both kept, image similarity can be added to this panel without re-running a single instance; discard them and the axis costs a full sweep to recover.

---

## Ops-lane pre-registration — 2026-09-10 (OT-9)

Written BEFORE op-call dispatch (OT-4) shipped, as the backlog requires, so the first
ops-lane roll cannot be judged post hoc. Nothing in this section may be edited after
the first ops-lane roll's directory timestamp; the outcome line is the only line that
gets filled in, and it gets filled from `scripts/bench_panel.py` output, not by hand.

**Comparison.** Candidate: the agent whose ACI is the generated op tools (OT-3) with
`run_python` demoted to an escape hatch that requires a `reason` (OT-7) — "ops tools +
hatch". Incumbent: the `run_python`-only ACI, group `deepseek-v10` above (6 rolls,
120/120 executable, `cd_pca` 0.0252, SE 0.0007).

**Writer.** `deepseek-v4-pro:cloud`, unchanged; the same lane configuration the
incumbent rolls ran. A different writer is a different experiment and ranks nothing here.

**Instance set.** `bench_sets/instances_dev_sweep.txt` while the surface is being built; `bench_sets/instances_holdout.txt`
(20 instances) for any roll that is to be RANKED (BEN-8). A holdout roll made before the
surface is complete through OT-7 is reported and never ranked.

**Ranking rule.** Executability lexicographically first, then `cd_pca` (BEN-4/5;
`RANKING_METRIC` in `scripts/bench_thresholds.py`). `cd_yawmin` and `delta_orient` are
reported on every panel and rank nothing.

**Rolls.** At least `MINIMUM_PAIRED_ROLLS` (3) paired rolls of at least
`MINIMUM_INSTANCES_FOR_RANKING` (20) instances each, the same instances as the
incumbent's rolls.

**Target.** `TARGET_RELATIVE_IMPROVEMENT` (0.15) on the incumbent's own measured mean:
`cd_pca` 0.0252 → 0.0214. A regression is a one-sided move of more than
`REGRESSION_SIGMA` (2.0) on the paired standard error. At the 3-roll floor the 2σ
detectable effect on `cd_pca` is 0.0021 (table above).

**Hypotheses, stated before the roll.**

- H1 (executability, cloud writer): parity or better — 60/60 over three rolls against
  the incumbent's 120/120. The cloud writer already executes every instance under the
  hatch, so there is no room to gain here and the claim is that the surface loses nothing.
- H2 (`cd_pca`, cloud writer): moves within noise — |Δ| below the 0.0021 detectable
  effect. A gain on this writer is NOT expected; a loss beyond 2σ falsifies the surface.
- H3 (local lane, OT-10): executability on one local lane (`bmb` llama-swap) improves by
  more than that lane's own per-roll noise band. The band is measured from the incumbent
  ACI on the same local lane BEFORE the candidate runs, and quoted here when it exists.
- Recorded, not ranked: escape-hatch calls per gate-passing instance (from v2 transcripts,
  OT-8). The OT-7 prompt revision's own hypothesis — below 1.0 per brief on the five
  briefs within three paired rolls — is measured on the convergence suite, not here.

**Outcome.** *(pending — no ops-lane roll has run as of 2026-09-10)*

---

## Disclosed-surface pre-registration — 2026-09-10 (OT-25)

Written BEFORE progressive disclosure ships. Measured basis: a call carried all 48 op
schemas (7,904 tokens on bmb's tokenizer) while the five briefs that pass with the hatch
withheld used 4–8 distinct ops each; the derivation from the nine gate-passing v12 runs
with tool events puts 7 scene-changing ops in the core at the two-brief threshold, so a
call offers 8 service tools + 14 readers + 7 core ops = 29 tools, and reaches the other
27 through `search_ops`.

**Hypotheses, stated before the roll.**

- H4 (executability, local lane): rises against the `hatch` rolls' own band (OT-10's
  pairing, re-run as OT-27).
- H5 (tokens per call, Claude Code lane): falls below the 8-tool baseline of 25,851
  per harness call, from the 58,241 measured with the full 50-tool envelope.
- H6 (hatch calls per gate-passing brief, hatch offered, five briefs): unchanged
  within one call per brief of the v12 reading (3.00 on one roll).
- H7 (search cost): at most one `search_ops` call per undisclosed op a brief needs;
  the stool (splayed_leg_ring, trim_soles_flat, boolean_union) is the brief that
  pays it.

**Outcome (2026-09-10, closing commit of OT-25; the roll itself is OT-27).** The
surface shipped as pre-registered: 29 of 56 tools offered (fingerprint `t:6b6093efb569`
with the hatch, `t:38dae1b48ceb` with it withheld), static per call 8,646 / 9,626 tokens
on bmb's tokenizer (from 13,727 / 14,967).

- H4: *pending OT-27* — no local-lane roll has run on this surface.
- H5: **holds on the mean and on four of five briefs.** Claude Code lane, v14, hatch
  withheld, billed input per API call: planter 87 17,833; uv_crate 89 16,880; column 90
  17,073; crate_with_lid 91 17,410; stool 92 25,258 (mean 18,891; the whole-set v14 runs
  81–86 read 24,248–32,052). The multi-turn stool sits at the 25,851 baseline (26,541 on
  its first run 88, 25,258 on 92): its four turns of history, not the tool set, are what
  a call carries by then.
- H6: *pending* — every run here withheld the hatch; the hatch-offered reading comes
  with OT-27's five-brief chain.
- H7: **12 `search_ops` calls for 11 undisclosed ops needed (1.09 per op), not ≤ 1.**
  Stool 88: 4 for 4; stool 92: 3 for 3; uv_crate 89: 4 for 3 — the query "unwrap seams"
  matched nothing because `search_ops` requires every word (`add_bevel`, `mark_uv_seams`,
  `unwrap_uvs` were then found one word at a time); column 90: 1 for 1; planter 87 and
  crate_with_lid 91: 0 for 0. One AND-miss in six runs; recorded, not fixed here.
- Not hypothesised, observed: the stool's first run (88) failed its third refinement at
  the 24-call turn cap after two op gate failures (`boolean_union` on leg 1 and
  `trim_soles_flat`, both "2 triangles face inward") and two full tear-down rebuilds;
  that turn made no `search_ops` call. The second run (92) passed all three refinements
  in 38 API calls ($1.85; the whole-set run 86 took 44, $2.12). One failure in two runs
  of the one multi-turn brief: the cap, not the surface, is the mechanism on the record,
  and the roll (OT-27) is where a rate gets measured.
