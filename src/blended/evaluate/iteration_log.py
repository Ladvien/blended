"""Append-only record of prompt-convergence iterations.

One JSON object per iteration, never rewritten. The log is the evidence
that a prompt revision earned its promotion: it carries the exact brief,
the prompt identity that ran, what the deterministic gates measured,
where the render landed, the visual deviations, the failure
classification, and the hypothesis behind the next edit.

Append-only matters. A convergence claim is "three consecutive clean
runs", which is a statement about HISTORY — a log that can be edited
after the fact cannot support it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

DEFAULT_LOG_PATH = Path("_evaluate/iterations.jsonl")
DEFAULT_VERDICT_PATH = Path("_evaluate/verdicts.jsonl")

# The four causes an iteration failure can have. Exactly one applies,
# and only the first permits a prompt edit — the discipline that keeps
# the loop from "fixing" a code bug by rewording the prompt until the
# bug is hidden.
#
# HARNESS_CRITIQUE is the fourth because the critique is itself a
# fallible instrument, and its failures look exactly like the other
# three from the outside. LL3M measured a critic VLM that missed
# spatial errors a human caught in 3-4 follow-ups; the TikZ study
# measured visual verification at imperfect precision AND recall. So a
# run can fail two ways that are not about the asset at all: the
# critique answered "Yes" to a question the render answers "No" (a
# missed deviation), or it reported a deviation that is not there (a
# false positive). Either way the artifact to fix is the critique — the
# eye's question set, the render that feeds it, or the gate that should
# have measured the thing instead of asking about it. Tuning the
# working agreement to satisfy a blind critic tunes the wrong artifact
# and bakes the blindness in. This project has already paid for the
# distinction once: see the mistake memory entry
# "the-critique-explained-away-its-own-evidence", where the critique
# held both the evidence and the verdict, answered Yes, and the human
# caught the angled sole by eye at iteration 4.
CLASSIFICATION_PROMPT = "prompt"
CLASSIFICATION_HARNESS_CODE = "harness_code"
CLASSIFICATION_HARNESS_CRITIQUE = "harness_critique"
CLASSIFICATION_BAD_BRIEF = "bad_brief"
CLASSIFICATIONS = (
    CLASSIFICATION_PROMPT,
    CLASSIFICATION_HARNESS_CODE,
    CLASSIFICATION_HARNESS_CRITIQUE,
    CLASSIFICATION_BAD_BRIEF,
)


class InvalidClassification(ValueError):
    """Raised for a classification outside the closed set."""


@dataclass(frozen=True)
class IterationRecord:
    """One RUN -> RENDER -> EXAMINE pass over one brief."""

    iteration: int
    brief_name: str
    prompt_identity: str  # e.g. "v2:9fa1c0d3e771"
    prompt_revision: int
    started_at: str  # ISO 8601, supplied by the caller
    # WHICH MODELS RAN. A prompt is tuned against a model, not in the
    # abstract: v1-v5 were all scored against deepseek-v4-flash, and a
    # log that does not say so would silently compare runs from
    # different baselines and attribute the difference to the prompt.
    writer_model: str = ""
    vision_model: str = ""
    # RUN
    agent_turns: int = 0
    tool_calls: tuple[str, ...] = field(default_factory=tuple)
    agent_final_text: str = ""
    # EXAMINE (a) — deterministic, in order
    structural_gate_passed: bool = False
    structural_failures: tuple[str, ...] = field(default_factory=tuple)
    form_gate_passed: bool = False
    form_failures: tuple[str, ...] = field(default_factory=tuple)
    form_summary: str = ""
    # RENDER
    render_path: str = ""
    # A contact sheet answers what one viewpoint can answer. Measured
    # 2026-08-22 (iteration 10): the front orthographic view projects a
    # stool's 120 and 240 degree legs to the same world x, so it cannot
    # show spacing at all and the human could only answer "Unclear".
    # The .glb can be turned.
    glb_path: str = ""
    # USER-GUIDED REFINEMENT: the follow-up turn, gated like the
    # first. A localized edit is only localized if what the user did
    # NOT name still measures what it measured before.
    refinement_gate_passed: bool = True
    refinement_failures: tuple[str, ...] = field(default_factory=tuple)
    refinement_summary: str = ""
    # HOW the follow-up reached its result: edited in place, or rebuilt.
    # Evidence, never a gate — see evaluate/object_identity.py. Kept in
    # the record because it is the only place the edit-vs-rebuild cost
    # is visible once the render is forgotten, and no measurement of the
    # finished mesh can recover it after the fact.
    refinement_locality: tuple[str, ...] = field(default_factory=tuple)
    # EXAMINE (b) — visual, only meaningful once (a) passed
    visual_deviations: tuple[str, ...] = field(default_factory=tuple)
    visual_inspected: bool = False
    # EXAMINE (c) + ADJUST
    classification: str = ""
    hypothesis: str = ""
    prompt_change: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.classification and self.classification not in CLASSIFICATIONS:
            raise InvalidClassification(
                f"classification {self.classification!r} not in {CLASSIFICATIONS}"
            )

    @property
    def passed(self) -> bool:
        """A clean iteration: both deterministic gates, zero deviations.

        Deliberately requires `visual_inspected`. An iteration where
        nobody looked is not a pass with no deviations — it is a pass
        with no evidence.
        """
        return (
            self.structural_gate_passed
            and self.form_gate_passed
            # The refinement turn is a gate, not a bonus: the standards
            # require a user-guided refinement phase, so a run whose
            # follow-up moved something the user did not name has not
            # passed, however clean the first build was.
            #
            # What this gate does NOT decide is whether the follow-up
            # edited the asset or rebuilt it. Ruled 2026-08-22, on
            # iteration 14: a rebuild that lands on every preserved
            # number is an acceptable way to satisfy a follow-up. That
            # is measured and recorded in `refinement_locality`, and
            # deliberately not consulted here.
            and self.refinement_gate_passed
            and self.visual_inspected
            and not self.visual_deviations
        )


@dataclass(frozen=True)
class IterationVerdict:
    """The examiner's judgement of one iteration, written separately.

    Measurements and judgements have different authors and different
    lifetimes: the driver measures, a human (or supervising agent)
    examines the render afterwards. Keeping them in one mutable row
    would mean rewriting a measured record hours after it was taken,
    which is exactly what an append-only log exists to prevent. So the
    verdict is its own append-only file, keyed to (iteration, brief).
    """

    iteration: int
    brief_name: str
    visual_inspected: bool
    visual_deviations: tuple[str, ...] = field(default_factory=tuple)
    classification: str = ""
    hypothesis: str = ""
    prompt_change: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.classification and self.classification not in CLASSIFICATIONS:
            raise InvalidClassification(
                f"classification {self.classification!r} not in {CLASSIFICATIONS}"
            )


class VerdictLog:
    """Append-only JSONL of examiner verdicts."""

    def __init__(self, path: Path = DEFAULT_VERDICT_PATH) -> None:
        self.path = Path(path)

    def append(self, verdict: IterationVerdict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(verdict), sort_keys=True) + "\n")

    def verdicts(self) -> list[IterationVerdict]:
        if not self.path.exists():
            return []
        loaded: list[IterationVerdict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                payload = json.loads(line)
                payload["visual_deviations"] = tuple(
                    payload.get("visual_deviations", ())
                )
                loaded.append(IterationVerdict(**payload))
        return loaded

    def latest_for(self, iteration: int, brief_name: str) -> IterationVerdict | None:
        """The most recent verdict for a run. Later lines supersede earlier
        ones, so a correction is an append, never an edit."""
        matching = [
            verdict
            for verdict in self.verdicts()
            if verdict.iteration == iteration and verdict.brief_name == brief_name
        ]
        return matching[-1] if matching else None


class IterationLog:
    """Append-only JSONL log of iterations."""

    def __init__(self, path: Path = DEFAULT_LOG_PATH) -> None:
        self.path = Path(path)

    def append(self, record: IterationRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")

    def records(self) -> list[IterationRecord]:
        if not self.path.exists():
            return []
        loaded: list[IterationRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                loaded.append(IterationRecord(**json.loads(line)))
        return loaded

    def next_iteration_number(self) -> int:
        existing = self.records()
        return 1 + max((record.iteration for record in existing), default=0)


def consecutive_clean_runs(
    records: list[IterationRecord],
    brief_names: tuple[str, ...],
    verdicts: list[IterationVerdict] | None = None,
) -> int:
    """How many trailing iterations were clean across EVERY brief.

    Convergence is a property of the suite, not of one brief: a prompt
    that fixes the planter by breaking the stool has not converged. So
    an iteration counts only when every brief in `brief_names` passed
    it, and any brief failing resets the streak to zero.
    """
    by_iteration: dict[int, dict[str, IterationRecord]] = {}
    for record in records:
        by_iteration.setdefault(record.iteration, {})[record.brief_name] = record

    verdict_by_key: dict[tuple[int, str], IterationVerdict] = {}
    for verdict in verdicts or []:
        verdict_by_key[(verdict.iteration, verdict.brief_name)] = verdict

    def judged(record: IterationRecord) -> IterationRecord:
        """Fold the examiner's verdict into the measured record."""
        verdict = verdict_by_key.get((record.iteration, record.brief_name))
        if verdict is None:
            return record
        return replace(
            record,
            visual_inspected=verdict.visual_inspected,
            visual_deviations=verdict.visual_deviations,
            classification=verdict.classification,
            prompt_change=verdict.prompt_change,
            hypothesis=verdict.hypothesis,
        )

    streak = 0
    for iteration in sorted(by_iteration, reverse=True):
        present = {
            name: judged(record) for name, record in by_iteration[iteration].items()
        }
        if not all(name in present for name in brief_names):
            break
        if not all(present[name].passed for name in brief_names):
            break
        if any(present[name].prompt_change for name in brief_names):
            # A run that also changed the prompt is not a run of the
            # converged prompt: the next iteration is the first that
            # exercises the new text.
            streak += 1
            break
        streak += 1
    return streak
