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
