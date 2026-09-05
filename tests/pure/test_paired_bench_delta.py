"""The bench regression test's own statistics.

`scripts/paired_bench_delta.py` is what decides whether a 3DCodeBench
candidate regressed against the roll that set the guard, and whether the
contract's target is resolvable at all. Those numbers are load-bearing —
they are the difference between "this change helped" and "this change
landed inside a coin flip" — so the arithmetic is pinned here on data
whose answers can be checked by hand.

The tool lives in `scripts/` and is deliberately stdlib-only (it runs
under the benchmark's own venv and under a bare `python3`), so it is
imported by path rather than as a `blended.*` module.
"""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import paired_bench_delta as tool


def write_roll(path: Path, model_dir: str, values: dict) -> Path:
    """A diagnose JSON with `{instance: (cd_yawmin, cd_pca, delta_orient)}`."""
    path.write_text(
        json.dumps(
            {
                "model_dir": model_dir,
                "per_instance": [
                    {
                        "instance": instance,
                        "cd_yawmin": yawmin,
                        "cd_pca": pca,
                        "delta_orient": orient,
                    }
                    for instance, (yawmin, pca, orient) in values.items()
                ],
            }
        )
    )
    return path


def load(path: Path) -> list[dict]:
    return tool.load_rolls([path])


def test_a_consistent_worsening_is_a_regression(tmp_path):
    """Four instances, each 0.05 worse: zero paired spread, so the
    difference is real however small it is."""
    baseline = load(
        write_roll(
            tmp_path / "base.json",
            "base",
            {
                "A": (0.10, 0.10, 0.0),
                "B": (0.20, 0.20, 0.0),
                "C": (0.30, 0.30, 0.0),
                "D": (0.40, 0.40, 0.0),
            },
        )
    )
    candidate = load(
        write_roll(
            tmp_path / "cand.json",
            "cand",
            {
                "A": (0.15, 0.10, 0.0),
                "B": (0.25, 0.20, 0.0),
                "C": (0.35, 0.30, 0.0),
                "D": (0.45, 0.40, 0.0),
            },
        )
    )
    instances = ["A", "B", "C", "D"]
    result = tool.paired_delta(baseline, candidate, instances, "cd_yawmin")
    assert result["mean_delta"] == pytest.approx(0.05)
    assert result["paired_stdev"] == pytest.approx(0.0)
    assert result["worse_count"] == 4
    assert result["better_count"] == 0
    assert result["regression"] is True
    # Shape did not move: that is what separates orientation from geometry.
    shape = tool.paired_delta(baseline, candidate, instances, "cd_pca")
    assert shape["mean_delta"] == pytest.approx(0.0)
    assert shape["regression"] is False


def test_a_reshuffle_of_coin_flips_is_not_a_regression(tmp_path):
    """Two instances broken, two fixed, by the same amount: the mean is
    zero and the paired SD is large — the exact shape of this benchmark's
    orientation flips."""
    baseline = load(
        write_roll(
            tmp_path / "base.json",
            "base",
            {
                "A": (0.01, 0.01, 0.00),
                "B": (0.01, 0.01, 0.00),
                "C": (0.21, 0.01, 0.20),
                "D": (0.21, 0.01, 0.20),
            },
        )
    )
    candidate = load(
        write_roll(
            tmp_path / "cand.json",
            "cand",
            {
                "A": (0.21, 0.01, 0.20),
                "B": (0.21, 0.01, 0.20),
                "C": (0.01, 0.01, 0.00),
                "D": (0.01, 0.01, 0.00),
            },
        )
    )
    instances = ["A", "B", "C", "D"]
    result = tool.paired_delta(baseline, candidate, instances, "cd_yawmin")
    assert result["mean_delta"] == pytest.approx(0.0)
    assert result["paired_stdev"] > 0.2
    assert result["worse_count"] == 2 and result["better_count"] == 2
    assert result["regression"] is False
    # And the movers table must name the baseline's own orientation error,
    # which is how "the candidate broke it" is told apart from "the
    # baseline got lucky".
    rows = tool.movers(baseline, candidate, instances, "cd_yawmin")
    by_instance = {row["instance"]: row for row in rows}
    assert by_instance["A"]["baseline_delta_orient"] == pytest.approx(0.0)
    assert by_instance["C"]["baseline_delta_orient"] == pytest.approx(0.20)


def test_several_candidate_rolls_average_per_instance(tmp_path):
    """A multi-roll candidate is the per-instance mean, not a pooled
    mean of means over different instances."""
    baseline = load(
        write_roll(
            tmp_path / "base.json",
            "base",
            {"A": (0.10, 0.05, 0.05), "B": (0.10, 0.05, 0.05)},
        )
    )
    first = write_roll(
        tmp_path / "c1.json", "c1", {"A": (0.20, 0.05, 0.15), "B": (0.10, 0.05, 0.05)}
    )
    second = write_roll(
        tmp_path / "c2.json", "c2", {"A": (0.40, 0.05, 0.35), "B": (0.10, 0.05, 0.05)}
    )
    candidate = tool.load_rolls([first, second])
    assert tool.instance_mean(candidate, "A", "cd_yawmin") == pytest.approx(0.30)
    result = tool.paired_delta(baseline, candidate, ["A", "B"], "cd_yawmin")
    assert result["mean_delta"] == pytest.approx(0.10)
    assert result["worse_count"] == 1 and result["better_count"] == 0


def test_one_instance_is_refused_rather_than_reported(tmp_path):
    """A mean delta with no standard error is the mistake this tool
    exists to prevent."""
    roll = load(write_roll(tmp_path / "one.json", "one", {"A": (0.1, 0.1, 0.0)}))
    with pytest.raises(ValueError, match="at least"):
        tool.paired_delta(roll, roll, ["A"], "cd_yawmin")


def test_disagreeing_instance_sets_fail_loudly(tmp_path):
    """A mean over different instance sets is not a comparison."""
    from compare_3dcode_rolls import shared_instances

    baseline = load(
        write_roll(
            tmp_path / "base.json", "base", {"A": (0.1, 0.1, 0.0), "B": (0.2, 0.2, 0.0)}
        )
    )
    candidate = load(
        write_roll(
            tmp_path / "cand.json", "cand", {"A": (0.1, 0.1, 0.0), "C": (0.2, 0.2, 0.0)}
        )
    )
    with pytest.raises(SystemExit):
        shared_instances(baseline + candidate, None)


def test_a_missing_diagnose_file_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        tool.load_rolls([tmp_path / "absent.json"])


def test_the_contract_defaults_are_the_goals_numbers():
    """The guard and target this repository is measured against."""
    assert tool.CONTRACT_GUARD_CD_YAWMIN == 0.0706
    assert tool.CONTRACT_TARGET_CD_YAWMIN == 0.060
    arguments = tool.parse_arguments(
        ["--baseline", "b.json", "--candidate", "c.json", "--label", "x"]
    )
    assert arguments.guard == tool.CONTRACT_GUARD_CD_YAWMIN
    assert arguments.target == tool.CONTRACT_TARGET_CD_YAWMIN
