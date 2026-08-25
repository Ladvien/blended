"""Pure layer: the convergence rule, executed against the real logs.

The predecessor of `converged_suite_cycles` was never executable: it
grouped briefs by iteration NUMBER while the protocol runs one brief
per iteration, so on iterations 47-51 — the cycle that earned the v10
pin — it returned 0, and nothing in the repo ever called it to notice.
These tests read the in-repo logs, which are the evidence the pin rests
on, so the rule is measured against the history it describes.
"""

from pathlib import Path

from blended.evaluate.briefs import BRIEFS
from blended.evaluate.iteration_log import (
    IterationLog,
    IterationRecord,
    IterationVerdict,
    VerdictLog,
    converged_suite_cycles,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ITERATION_LOG = REPOSITORY_ROOT / "_evaluate" / "iterations.jsonl"
VERDICT_LOG = REPOSITORY_ROOT / "_evaluate" / "verdicts.jsonl"
PINNED_IDENTITY = "v10:b6627b38f4c1"


def test_the_v10_cycle_is_one_converged_cycle():
    """Iterations 47-51: one clean run per brief, consecutive, no prompt
    change between them. That IS the rule the v10 pin claims to have
    met, so the rule must say so."""
    records = IterationLog(ITERATION_LOG).records()
    verdicts = VerdictLog(VERDICT_LOG).verdicts()

    cycles, identity = converged_suite_cycles(
        records, tuple(sorted(BRIEFS)), verdicts
    )

    assert cycles >= 1, (
        "the recorded v10 cycle (iterations 47-51) must count as converged"
    )
    assert identity == PINNED_IDENTITY


def _clean_record(iteration: int, brief_name: str, identity: str) -> IterationRecord:
    return IterationRecord(
        iteration=iteration,
        brief_name=brief_name,
        prompt_identity=identity,
        prompt_revision=10,
        started_at="2026-08-22T00:00:00+00:00",
        structural_gate_passed=True,
        form_gate_passed=True,
        refinement_gate_passed=True,
    )


def _clean_verdict(iteration: int, brief_name: str) -> IterationVerdict:
    return IterationVerdict(
        iteration=iteration,
        brief_name=brief_name,
        visual_inspected=True,
    )


def test_a_cycle_that_mixes_prompt_identities_is_not_a_cycle():
    """A cycle spanning two identities would attribute one claim to two
    texts."""
    names = ("alpha", "beta", "gamma")
    identities = (
        "v10:b6627b38f4c1",
        "v10:b6627b38f4c1",
        "v11:0000deadbeef",
    )
    records = [
        _clean_record(iteration, name, identity)
        for iteration, (name, identity) in enumerate(zip(names, identities), start=1)
    ]
    verdicts = [
        _clean_verdict(iteration, name)
        for iteration, name in enumerate(names, start=1)
    ]

    assert converged_suite_cycles(records, names, verdicts) == (0, "")


def test_an_abstention_is_not_a_clean_cycle():
    """An instrument that could not answer has not signed anything off."""
    names = ("alpha", "beta")
    records = [_clean_record(1, "alpha", "v10:x"), _clean_record(2, "beta", "v10:x")]
    verdicts = [
        IterationVerdict(
            iteration=1,
            brief_name="alpha",
            visual_inspected=True,
            examiner="m+examiner:abc",
            abstained=True,
            calibration_identity="0123456789ab",
        ),
        _clean_verdict(2, "beta"),
    ]

    cycles, _ = converged_suite_cycles(records, names, verdicts)
    assert cycles == 0


def test_a_deviation_is_not_a_clean_cycle():
    names = ("alpha", "beta")
    records = [_clean_record(1, "alpha", "v10:x"), _clean_record(2, "beta", "v10:x")]
    verdicts = [
        IterationVerdict(
            iteration=1,
            brief_name="alpha",
            visual_inspected=True,
            visual_deviations=("missing_part",),
        ),
        _clean_verdict(2, "beta"),
    ]

    # A cycle that is not converged reports no identity: the count is
    # the claim, and there is no converged cycle to name.
    assert converged_suite_cycles(records, names, verdicts) == (0, "")


def test_an_unexamined_run_is_not_a_clean_cycle():
    """A run nobody examined is a pass with no evidence, not a pass."""
    names = ("alpha", "beta")
    records = [_clean_record(1, "alpha", "v10:x"), _clean_record(2, "beta", "v10:x")]
    verdicts = [_clean_verdict(1, "alpha")]

    assert converged_suite_cycles(records, names, verdicts) == (0, "")


def test_a_prompt_change_ends_the_cycle_it_appears_in():
    names = ("alpha", "beta")
    records = [_clean_record(1, "alpha", "v10:x"), _clean_record(2, "beta", "v10:x")]
    verdicts = [
        IterationVerdict(
            iteration=1,
            brief_name="alpha",
            visual_inspected=True,
            prompt_change="v10 -> v11: one sentence",
        ),
        _clean_verdict(2, "beta"),
    ]

    cycles, _ = converged_suite_cycles(records, names, verdicts)
    assert cycles == 0


def test_two_clean_cycles_count_as_two():
    names = ("alpha", "beta")
    records = [
        _clean_record(1, "alpha", "v10:x"),
        _clean_record(2, "beta", "v10:x"),
        _clean_record(3, "alpha", "v10:x"),
        _clean_record(4, "beta", "v10:x"),
    ]
    verdicts = [
        _clean_verdict(1, "alpha"),
        _clean_verdict(2, "beta"),
        _clean_verdict(3, "alpha"),
        _clean_verdict(4, "beta"),
    ]

    assert converged_suite_cycles(records, names, verdicts) == (2, "v10:x")


def test_an_incomplete_trailing_cycle_does_not_count():
    """Four of five briefs run is not a suite cycle."""
    names = ("alpha", "beta")
    records = [
        _clean_record(1, "alpha", "v10:x"),
        _clean_record(2, "beta", "v10:x"),
        _clean_record(3, "alpha", "v10:x"),
    ]
    verdicts = [
        _clean_verdict(1, "alpha"),
        _clean_verdict(2, "beta"),
        _clean_verdict(3, "alpha"),
    ]

    # The newest complete cycle is (3:alpha, 2:beta) — the partial
    # trailing run of alpha is absorbed into it, and 1:alpha is left
    # over as an incomplete cycle that is never counted.
    assert converged_suite_cycles(records, names, verdicts) == (1, "v10:x")
