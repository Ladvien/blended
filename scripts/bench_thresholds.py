"""Benchmark analysis thresholds shared by the 3DCodeBench scripts.

Stdlib-only on purpose: `scripts/compare_3dcode_rolls.py` runs under a bare
`python3` (no numpy, no trimesh), while `scripts/diagnose_3dcode.py` and
`scripts/shape_error_decompose.py` run under the benchmark's own venv. A
threshold quoted by both must therefore live in a module neither venv can
break, and be defined exactly once.
"""

ORIENT_ARTIFACT_THRESHOLD = 0.02    # Δ_orient at/above which an instance's
                                    # score is an orientation artifact rather
                                    # than shape error; also the per-instance
                                    # across-roll range above which a roll
                                    # delta is indistinguishable from noise

# --- The pre-registered ranking rule -------------------------------------
#
# Ranking is on the POSE-NORMALIZED axis. Measured over the six surviving
# 20-instance rolls: cd_pca mean 0.0252, between-roll SD 0.0022, SE of a
# 20-mean 0.0018; cd_yawmin mean 0.0769, SD 0.0072, SE 0.0090.
# delta_orient = cd_yawmin - cd_pca carries 89% of the headline variance,
# so ranking on cd_yawmin ranks a per-instance orientation coin flip.
RANKING_METRIC = "cd_pca"
# Reported on every panel, never ranked on. cd_yawmin is the scorer's own
# number and stays visible; delta_orient is the pose axis and is owned by
# the orientation work, not by a shape candidate.
REPORTED_METRICS = ("cd_yawmin", "delta_orient")
# A candidate is a MEAN over at least this many paired rolls of the same
# instance set: 3 rolls take the SE of the 20-mean from 0.0018 to 0.0010.
MINIMUM_PAIRED_ROLLS = 3
# A roll with fewer instances is reported but cannot be ranked: the frozen
# set is 20 and an unpaired subset is not comparable.
MINIMUM_INSTANCES_FOR_RANKING = 20
# The target is RELATIVE, so it moves with the incumbent instead of being
# a literal below the instrument's resolution. 15% of a 0.0252 incumbent
# is 0.0038 = 2.1 sigma at one roll, 3.7 at three.
TARGET_RELATIVE_IMPROVEMENT = 0.15
# One-sided, on the ranking metric's paired standard error.
REGRESSION_SIGMA = 2.0
