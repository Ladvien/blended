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
