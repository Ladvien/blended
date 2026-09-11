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

---

## Disclosed-surface rolls — 2026-09-10 (OT-27)

Written BEFORE any benchmark roll on the disclosed surface. The rolls stopped earlier
today (OT-9 roll 1, OT-10 roll 1) measured a bridge that dropped op calls and a chain
that never baked; nothing from them ranks. This section names what runs now; only the
outcome line is filled afterwards, from `scripts/bench_panel.py`, never by hand.

**Candidate.** The harness at the OT-25/OT-26 closing commit, frozen as the worktree
`/Users/ladvien/blended-bench-v2`: 29 of 56 tools offered per call, the rest reachable
by name after `search_ops` (OT-25); `run_python` offered as the escape hatch with a
`reason` (OT-7); working agreement v14, no operations section in the prompt (OT-24);
the bridge carries op calls and the chain bakes before it scores (OT-20, OT-21); the
context preflight and the 2,000 s llama-swap request ceiling (OT-22).

**Incumbents.** Cloud lane: group `deepseek-v10` above — six existing `run_python`-only
rolls (120/120 executable, `cd_pca` 0.0252, SE 0.0007); nothing is re-run. Local lane:
the `run_python`-only tree at `4277aa3` (the OT-1 close, the same incumbent OT-10 named)
with exactly one change, `LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS` 900 → 2000, so both ACIs
meet the same request ceiling — the 900 s ceiling was measured to cut a local turn
(AquariumTank) before either surface could finish it. Branch `incumbent-ot27`, worktree
`/Users/ladvien/blended-bench-incumbent`. The incumbent's own bridge (chunks only) is
complete for a lane that emits chunks only; the bake and the diagnose come from the
candidate tree's scripts, which read bench result directories and import nothing from
either harness.

**Writers.** Cloud: `deepseek-v4-pro:cloud`, eye `kimi-k2.7-code:cloud`, as the
incumbent rolls. Local: `qwen3.8-27b` on bmb's llama-swap as writer and as its own eye;
big's GPU is under a foreign claim and is not touched. No paid lane (NFR-27).

**Instance set and rolls.** `bench_sets/instances_holdout.txt` (20). Cloud: three rolls,
`blended-deepseek-v4-pro-disclosed-roll{1,2,3}`, per-instance timeout 1,500 s. Local:
three paired rolls, `blended-local-qwen38-disclosed-roll{1,2,3}` alternating with
`blended-local-qwen38-hatch-roll{1,2,3}`, per-instance timeout 3,000 s. Every roll runs
`scripts/bench_chain.sh`: sweep → bake → `executability.py` → `shape_chamfer.py` →
`diagnose_3dcode.py`; an incomplete bake leaves the roll unscored.

**Ranking rule and target.** As the OT-9 section: executability first, then `cd_pca`;
`TARGET_RELATIVE_IMPROVEMENT` 0.15 on the incumbent's mean (0.0252 → 0.0214);
regression = a one-sided move beyond `REGRESSION_SIGMA` (2.0) on the paired SE.

**Hypotheses, stated before the roll.**

- H1' (executability, cloud writer): 60/60 over three rolls against 120/120 — the surface
  loses nothing on a writer that already executes everything.
- H2' (`cd_pca`, cloud writer): within the 0.0021 detectable effect; a loss beyond 2σ
  falsifies the surface on this writer.
- H3'/H4 (executability, local lane): the disclosed rolls beat the hatch rolls by more
  than the hatch rolls' own per-roll band, read off the panel. This is the claim the
  whole phase was built for.
- H6 (hatch calls per gate-passing instance, hatch offered): recorded from the v2
  transcripts of the disclosed rolls and reported beside the panel; the OT-25
  pre-registration's H6 is read here because these are the first hatch-offered runs
  on the disclosed surface.
- Recorded, not ranked: `search_ops` calls per instance; the local lane's per-request
  wall time (the 2,000 s ceiling is a measured derivation and a hit on it is a finding).

**Outcome.** Not measured (filled 2026-09-11 from the panel): H1' 50/60, rolls 18, 18 and
13 of 20; under §P8a no roll ranks, so H2' has no reading. The launch record's 01:47 entry
carries the mechanism (a frozen tree that predated the gateway retry) and the
"Outcome (first set)" line the numbers. Re-run as the second set below.

**Launch record (appended, not edited).** 15:23 CDT: both chains launched from
`/Users/ladvien/blended-bench-v2` (`89583ce`). 15:26: the cloud chain's first two
instances died `ERR_NO_SCRIPT` at their third call — the OT-22 preflight compared the
prompt against `context_length` = 32,768, the harness's own Ollama-lane constant sent as
`num_ctx`, on a model whose window the daemon reports as 1,048,576; the chain was stopped
and its results directory removed unscored. Fix `8d05411`: the Ollama lane reads the
window from `/api/show` at `check_connection` (writer 1,048,576; eye 262,144) and sends
`num_predict` = the reserved completion. 15:32 CDT: the cloud chain relaunched from
`/Users/ladvien/blended-bench-v3` (`8d05411`), same model directories. The local chain
kept running from v2: its lane is llama-swap, whose window is table-driven and unaffected;
the two candidate trees differ only in the Ollama lane's window discovery.
15:33: the relaunch's first instance died `ERR_MODEL_CALL` — the fix had also sent
`max_completion_tokens` (16,384) as `num_predict`, and deepseek-v4-pro's planning turn
was cut there after 87 s (`done_reason=length`); stopped, directory removed. Fix
`c6e4bfc`: the number is headroom under the window on this wire, never a cap. 15:35: the
cloud chain relaunched from `/Users/ladvien/blended-bench-v4` (`c6e4bfc`), same model
directories; the local chain still runs from v2 (unaffected: llama-swap sends
`max_tokens` as before, and its window is table-driven).
15:52: local disclosed roll 1, instance 1 (AquariumTank): `ERR_MODEL_CALL` after 1,732 s
with zero turns completed — the writer's planning turn hit the lane's 16,384-token
completion ceiling (`finish_reason=length`, the OT-22 rule: a cut reply is an error, not
an answer). At the measured 10.5 tok/s that is ≈ 26 min of generation on one turn. This
is the local writer's thinking budget on a bench brief, not the surface; the same ceiling
applies to the incumbent, and the roll continues as pre-registered. Recorded as the
per-request finding this section said it would record.
16:23: **the local arm is dropped by decision** — the user's words, "I don't really want a
local arm right now; I want to iterate on our harness." Instance 2 (Beetle) had just
repeated instance 1 exactly: `ERR_MODEL_CALL`, zero turns, 1,714 s against 1,736 s. Two of
two instances measured the writer's own thinking budget against the harness's 16,384-token
completion ceiling, not the tool surface, and six pre-registered sweeps at ~25 min per
instance are ~2 days of wall clock against the cloud arm's ~5 min. The local chain was
stopped mid-sweep; `blended-local-qwen38-disclosed-roll1` holds two ERR rows and nothing
scorable, and it stays on disk as the record. **H3'/H4 (executability on a local lane) is
therefore unmeasured, and no local claim may be made from anything in this document.** The
cloud arm continues as pre-registered and is unaffected: it ranks against the six-roll
`deepseek-v10` incumbent group, which is what OT-9 needs.

18:37: **cloud roll 1 complete and scored** — 20 instances swept, 19 baked (one produced
no script), 18 GLBs loaded. Executability 18/20; `cd_pca` 0.02700 over n=18 against the
incumbent group's 0.0252. One roll ranks nothing (BEN-10); rolls 2 and 3 follow.

Read before scoring, as the rule requires, and **one of the two failures is the
instrument, not the surface**: Spoon_seed0 baked to `UnknownObject: no object named
'Spoon'`. Its first `run_python` chunk raised `TypeError: create_uvsphere: keyword
"diameter" is invalid` — but the very next `list_scene` shows `Spoon: 956 tris`, so the
chunk had already built the handle before it failed on the bowl. The bridge includes a
call only when its `stage_reached` is `locate`/`gate`/`export`/`done` (OT-20), so a chunk
that raised midway is dropped — even though the live scene kept everything it made and
every later call in the recorded conversation depended on it. The baked script therefore
cannot reproduce the run it replays. Scheduled as OT-31, **not fixed now**: changing the
instrument between rolls 1 and 3 would make them incomparable. The other failure
(Pillar_seed0, `ERR_MODEL_CALL`) was a transient connection reset on the Ollama cloud
lane. So roll 1's honest reading is 18/20 executable with 1 instance attributable to the
bridge and 1 to the network, and the outcome line below must say so when it is filled.

19:53: **cloud roll 2 complete and scored** — 18/20 the same way: `Tap_seed0` baked to no
GLB with the runner reporting `OK_AGENT_DONE` (the OT-31 bridge defect again, a chunk that
built then raised), and `AquariumTank_seed0` died `ERR_MODEL_CALL` on an HTTP 502 from the
Ollama cloud lane. `cd_pca` 0.02886 over n=18. Roll 3 follows.

2026-09-11 01:47: **cloud roll 3 complete, 13/20, and the set is void.** Seven instances —
Nautilus, Pillar, Plate, Rug, Sink, Spoon, Tap — died `ERR_MODEL_CALL`, every one
`HTTP 502 from http://localhost:11434` with the daemon's own body
`Post "https://ollama.com:443/api/chat": read tcp ... connection reset by peer`; zero
`[retry]` lines in any of the seven transcripts; five of the seven died on their first
call; the failures span 20:52–23:24 CDT. Nautilus died late, after its shell had passed
the gate and taken materials, mid-way through a final render loop. `cd_pca` 0.02754 over
n=13. **Mechanism, from the git graph and not from a guess:** this set ran from
`/Users/ladvien/blended-bench-v4` at `c6e4bfc`, and the bounded gateway retry
(`RETRYABLE_HTTP_STATUSES`, `RETRY_BACKOFF_SECONDS`, OT-32) landed in `179ab11`, after it.
The plan written on the 10th said the retry "already flows through `OllamaClient`" for
the bench lane; on `main` it does, and the frozen tree never had it. So the whole set
measured a missing fix. Under §P8a (executability 20/20 on every roll) rolls of 18, 18 and
13 rank nothing; **H1' and H2' are not measured**, and this section's outcome line is
written as such. The instrument is now guarded: `scripts/bench_chain.sh` refuses any
worktree that is not a freeze named by its commit (OT-37), and the set is re-run under
the "second set" pre-registration below, on F@0.05 as the OT-33 section registered.

**Outcome (first set).** Not measured: no roll reached 20/20 (18, 18, 13 — two bridge
losses now fixed by OT-31, nine gateway losses on a tree that predated the retry). The
first-set numbers, for the record and never for ranking: `cd_pca` 0.0270 / 0.0289 / 0.0275,
F@0.05 0.4066 / 0.4465 / 0.4001, all below the incumbent's 0.4528.

---

## F-score pre-registration — 2026-09-10 (OT-33)

Written AFTER rolls 1 and 2 were scored on `cd_pca` and BEFORE any roll is ranked on
F-score, which is the only order that keeps this honest.

**Why.** Tatarchenko, Richter, Ranftl, Li, Koltun & Brox, "What Do Single-View 3D
Reconstruction Networks Learn?", CVPR 2019 (DOI 10.1109/cvpr.2019.00352) show that Chamfer
distance and IoU are dominated by category-level priors — retrieval baselines are
statistically indistinguishable from reconstruction under them — and recommend F-score.
Three of this repo's own measurements fit that thesis: the proportion oracle is worth only
0.0043 of 0.0270; the orientation term sits at the holdout's documented floor; and the two
metrics rank our own rolls differently (below).

**Measured, on rolls already in hand.** 18 instances each, the scorer's own sampling
(8,192 points, seed 0), orientation quotiented out the same way `diagnose_3dcode.py` does.

| roll | mean cd_pca (lower better) | mean F@0.05 (higher better) |
|---|---|---|
| disclosed-roll1 | **0.0270** | 0.4060 |
| disclosed-roll2 | 0.0289 | **0.4454** |

**The two metrics disagree about which roll is better.** Mean absolute rank shift between
them across roll 1's instances is 2.78 places of 18; `CabinetDoorIkea` moves 8 places better
under F-score and `Nautilus` 6, while `Bottle`, `FoodBox` and `DoorCasing` each move 5 worse.

**What is therefore registered, before any roll is ranked on it.** F-score at
τ = 0.05 of the unit-sphere radius, with precision and recall reported separately, becomes
the ranking axis **for the next roll set only** (OT-30 onward). Rolls 1–3 stay ranked on
`cd_pca` as originally pre-registered. Thresholds 0.01, 0.02, 0.05 and 0.10 were fixed in
`scripts/bench_fscore.py` before any of them was read, and τ = 0.05 was named primary in the
same commit; re-choosing it later would be selection on the test set.

**Reference audit, recorded as a limit on every number in this document.** All 19 baked
references are **not watertight**, while the harness gates its own output on manifold
geometry — the candidate is held to a standard the ground truth does not meet. Seven are
thin in their own frame (`Mirror` 0.006, `Rug` 0.007, `LeafBananaTree` 0.04, `Leaf` 0.047,
`Spoon` 0.051, `Nautilus` 0.074, `CabinetDoorIkea` 0.099) and several are very low-poly
(`Leaf` 31 faces, `FoodBox` 44, `Mirror` 108, `Rug` 508, `DoorCasing` 604). `Nautilus` is
posed off-axis and its proportion-oracle number is therefore invalid (see BEN-6c).

**Outcome.** *(pending — to be filled from the first roll set ranked on F-score, which is
the "second set" registered below; the panel that fills it also fills that section's line)*

**Instrument note, 2026-09-11 (OT-36).** F-score moved from `bench_fscore.py`'s sidecar into
every diagnose row (`fscore_005`, `precision_005`, `recall_005`, one implementation in
`scripts/bench_surface_metrics.py`), and the nine rolls on disk were re-diagnosed with every
re-derived `cd_pca` asserted equal to its stored value (all 180 rows, tolerance 1e-9). The
per-roll F@0.05 the panel now carries differs from the table above in the fourth decimal —
roll 1 0.4066 against 0.4060, roll 2 0.4465 against 0.4454 — because the sidecar drew from
the scorer's RNG stream for every instance in the list while the diagnose skips an
instance with no GLB before sampling, so the two sample different points on the instances
after a failure. The panel's numbers are the ones that rank; the table above is the record
of what was read before the axis was chosen.

---

## Disclosed-surface rolls, second set — 2026-09-11 (OT-37)

Written BEFORE the set is launched and AFTER the first set (rolls 1–3 above) was read: it
finished 18/20, 18/20 and 13/20 and is void under §P8a, so nothing in it ranks and its
outcome line reads "not measured". Only the outcome line here is filled afterwards, from
`scripts/bench_panel.py`, never by hand.

**Candidate.** The harness at `main` after OT-34 and OT-36, frozen by
`scripts/freeze_worktree.sh HEAD` into `~/blended-worktrees/<commit>`; the commit is named in
the launch record below. Beyond the first set's candidate it carries: the bake replays a
chunk that raised after changing the scene (OT-31); the gateway retry on the bench lane
(`179ab11`, which the first set's tree `c6e4bfc` predated — the cause of roll 3's seven
`HTTP 502` losses); the `orient:` reading computed from world extents (OT-34); F-score in
every diagnose row (OT-36). Everything else is the first set's candidate unchanged.

**Incumbent.** Group `deepseek-v10`, the same six `run_python`-only rolls, re-diagnosed on
the same GLBs. Measured before launch: executability 120/120; **F@0.05 mean 0.4528, between-
roll SD 0.0200** (rolls 0.4578, 0.4708, 0.4613, 0.4140, 0.4516, 0.4615); precision 0.4943,
recall 0.4871; `cd_pca` 0.0252 unchanged. SE of a 20-mean 0.0192; at the three-roll floor
0.0111; the 15 % target is 0.0679 against a 2σ detectable effect of 0.0221 (margin 3.07×,
against 1.84× on `cd_pca`) — the registered axis is the more resolving of the two.

**Writer and eye.** `deepseek-v4-pro:cloud` and `kimi-k2.7-code:cloud`, unchanged; the
Ollama lane through the local daemon; per-instance timeout 1500 s.

**Instance set and rolls.** The frozen 20-instance holdout, three rolls, model directories
`blended-deepseek-v4-pro-disclosed2-roll{1,2,3}` — new names, because the sweep resumes any
directory that already holds a script. Every roll runs `scripts/bench_chain.sh` from the
freeze: sweep → bake → `executability.py` → `shape_chamfer.py` → `diagnose_3dcode.py`.

**Ranking rule and target.** Executability 20/20 on every roll (§P8a; the panel now refuses
any roll below it by name), then **F@0.05 as a mean over the three rolls, higher is better**,
per the F-score pre-registration above. Target: `TARGET_RELATIVE_IMPROVEMENT` (15 %) above
the incumbent's mean, i.e. 0.5207. Regression: a one-sided fall of more than
`REGRESSION_SIGMA` (2) paired standard errors. `cd_pca` is reported so H2' stays readable;
it ranks nothing.

**Hypotheses, stated before the roll.**
- H1'' (executability): 60/60 over three rolls against 120/120. A roll below 20/20 whose
  losses are the gateway's voids the set again; one whose losses are ours is a finding.
- H2'' (F@0.05): the disclosed surface is not below the incumbent by more than 2σ; a fall
  beyond that falsifies the surface on this writer. The first set's rolls, void as they are,
  read 0.4066, 0.4465 and 0.4001 — each below the incumbent's 0.4528, and roll 1 by more
  than the incumbent's between-roll SD — so this hypothesis is at real risk, which is the
  point of running it.
- Recorded, not ranked: `cd_pca` (H2' as originally stated), precision and recall, turns and
  seconds per instance.

**Outcome.** *(pending — launched per the launch record below; ≈ 3 h per roll)*

**Launch record (appended, not edited).** 2026-09-11 07:39:59 CDT: three cloud rolls
launched from the freeze `/Users/ladvien/blended-worktrees/bd81028` (commit `bd81028`,
`main` after OT-34, OT-36 and the OT-37 guard), chain `outputs/bench/logs/ot37_cloud_chain.sh`,
progress in `ot37_chain.log`; the chain log's first line records the frozen commit. Both
writer and eye answered a probe through the daemon one minute before launch. The old
`blended-bench-v4` worktree and the `incumbent-ot27` branch were removed beforehand (user
decision); `scripts/freeze_worktree.sh --list` shows this freeze alone.

2026-09-11 09:35:07 CDT: roll 1 scored, **20/20**, F@0.05 0.4614 (precision 0.5032, recall
0.4804, `cd_pca` 0.0252). 11:22:36 CDT: roll 2 scored, **16/20**, F@0.05 0.4815 on the
sixteen. The four losses — AquariumTank (347.6 s), Nautilus (302.3 s), Spoon (301.2 s),
Tap (303.1 s) — are one mechanism, read from each `.blender_stdout.txt`: the writer's
first call died in `urllib` with `TimeoutError: timed out`, the 300 s cloud read ceiling
(`REQUEST_TIMEOUT_SECONDS`), on a one-shot (non-streamed) request; the frozen tree's
retry catches `HTTPError` only, so a socket timeout is raised as it stands with zero
retries. That is ours, not the gateway's: the ceiling's own comment says cloud writers
answer "in well under 60 s", and four first calls in one roll did not. 13:30:53 CDT:
roll 3 scored, **20/20**, F@0.05 0.4440 (precision 0.4985, recall 0.4615, `cd_pca` 0.0253).

**Outcome of this set: void under §P8a** — roll 2 is below 20/20 by name, so the panel
refuses it and the set cannot rank. H1'' and H2'' are **not measured**. Recorded, not
ranked: the two 20/20 rolls read 0.4614 and 0.4440 against the incumbent's 0.4528
(SD 0.0200), both inside its band. The finding under H1'' is the retry's scope, fixed on
`main` after this record and carried by the next freeze; the third set is pre-registered
below as "Disclosed-surface rolls, third set".

## Disclosed-surface rolls, third set — 2026-09-11 (OT-37, after the transport fix)

Written BEFORE the set is launched and AFTER the second set was read (void: roll 2
16/20, four socket timeouts with zero retries). Only the outcome line here is filled
afterwards, from `scripts/bench_panel.py`, never by hand.

**Candidate.** The harness at `main` after the second set's finding, frozen by
`scripts/freeze_worktree.sh HEAD` into `~/blended-worktrees/<commit>`; the commit is named
in the launch record below. Beyond the second set's candidate it carries exactly one
change to what a roll runs: the one socket opener's bounded retry now covers the
transport saying "not now" (`RETRYABLE_TRANSPORT_ERRORS`: a read timeout, a refused or
reset connection, an unresolved name) with the same `RETRY_BACKOFF_SECONDS` and the same
`retried_calls` accounting. The 300 s cloud ceiling is unchanged: measured the same day,
a 7,328-token thinking reply returned whole in 37.9 s (~193 tok/s), so the worst legal
reply (16,384 tokens) generates in ~85 s; the second set's losses were stalled
connections, which is the retry's case. Everything else is the second set's candidate.

**Incumbent, writer, eye, instance set, rolls, ranking rule, target, regression.** As the
second set: group `deepseek-v10` (F@0.05 mean 0.4528, SD 0.0200, executability 120/120),
`deepseek-v4-pro:cloud` and `kimi-k2.7-code:cloud` through the local daemon, per-instance
timeout 1500 s, the frozen 20-instance holdout, three rolls in new directories
`blended-deepseek-v4-pro-disclosed3-roll{1,2,3}`, `scripts/bench_chain.sh` from the
freeze, executability 20/20 on every roll then F@0.05 mean over the three rolls, higher
is better, target 0.5207, regression a one-sided fall beyond `REGRESSION_SIGMA` paired
standard errors. `cd_pca` reported, never ranked.

**Hypotheses, stated before the roll.** H1''' and H2''' are H1'' and H2'' restated
unchanged: 60/60 against 120/120, and F@0.05 not below the incumbent by more than 2σ.
One addition, from the second set's two rankable rolls (0.4614, 0.4440): H3''' the
retried calls are visible in the record — every `[retry] TimeoutError` line in a
`.blender_stdout.txt` corresponds to a `retried_calls` increment, and no instance is
lost to a transport error that was not retried `len(RETRY_BACKOFF_SECONDS)` times.
A loss that IS retried that many times and still fails is the gateway's and voids the
set; a loss with fewer retries than that is ours and a finding.

**Outcome.** *(pending — launched per the launch record below; ≈ 2 h per roll measured
on the second set)*
