"""A structured, reference-guided visual examiner for rendered assets.

The human verdict is replaced, for loop purposes, by an instrument with
a closed answer space and a measured license to speak. The design rests
on three corpus findings, cited in the code below:

- Reference guidance lifts recall on defect spotting (RESP,
  10.48550/arXiv.2604.11082), and an *irrelevant* reference is worse
  than none — so the reference is pinned per brief and its integrity is
  verified before every use (`GoldenReferenceMismatch`).
- VLM critics are position-biased (BlenderGym, 10.48550/arXiv.2504.01786)
  and judge order matters (MT-bench, 10.48550/arXiv.2306.05685): every
  view is examined twice, reference-first and test-first, and only tags
  consistent across both orders count.
- Strict aggregation wins: permissive OR over single calls is dominated
  by false alarms (RESP aggregation; TikZ, 10.48550/arXiv.2606.15693),
  so the deviation set is the order-consistent intersection, and the
  instrument is trusted only after calibration licenses it
  (`Calibration.problems`).

This module imports no `bpy` — it reads PNGs and calls the eye through
the `describe(image_paths, prompt=...)` seam, so the whole instrument is
testable in the pure layer with a stub eye.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from blended.agent.prompt_templates import render

DEVIATION_TAGS: tuple[str, ...] = (
    "missing_part",
    "extra_part",
    "wrong_count",
    "floating_part",
    "intersecting_parts",
    "offset_part",
    "wrong_proportion",
    "missing_feature",
    "surface_artifact",
    "material_missing",
)
NO_DEVIATION_TAG = "no_deviation"
CANNOT_TELL_TAG = "cannot_tell"
VALID_TAGS = DEVIATION_TAGS + (NO_DEVIATION_TAG, CANNOT_TELL_TAG)
EXAMINER_TEMPLATE = "examiner"  # prompts/examiner.md.j2
EXAMINED_VIEW_NAMES = ("front", "right", "top", "bottom", "three_quarter")
# A defect is licensed when at least this fraction of the fixture zoo is
# detected. Justification: RESP measures oracle-reference recall 0.76
# and auto-reference recall 0.69 for the small open model, against 0.28
# for the no-reference rubber stamp; an examiner under 0.6 on a
# five-defect zoo is not distinguishable from that stamp, so its verdict
# is not allowed to replace the human's.
MINIMUM_FIXTURE_SENSITIVITY = 0.6
# A single false alarm on a known-clean control ends refinement early
# (TikZ §6.2: "False positives are harmful, as they prematurely
# terminate refinement"), so a control must be clean in every fixture.
REQUIRED_CONTROL_SPECIFICITY = 1.0
CALIBRATION_PATH = Path("_evaluate/eye_calibration.json")


class ExaminerError(Exception):
    """Base for every failure of the examiner instrument."""


class ExaminerReplyUnparseable(ExaminerError):
    """The eye's reply was not the contract JSON. There is no salvage."""


class UnknownDeviationTag(ExaminerError):
    """The eye returned a tag outside the closed vocabulary."""


class GoldenViewMissing(ExaminerError):
    """A view exists on one side but not the other; the pair cannot be compared."""


class GoldenReferenceMismatch(ExaminerError):
    """The golden reference is not the pinned one for this asset.

    RESP measured that an irrelevant reference is worse than no
    reference at all (−0.23 F1 for Qwen3-VL-8B), so a stale or
    wrong-brief golden is a correctness bug, not a cosmetic one.
    """


@dataclass(frozen=True)
class ViewVerdict:
    """One view, examined twice (both image orders), tags intersected."""

    view_name: str
    reference_first_tags: tuple[str, ...]
    test_first_tags: tuple[str, ...]
    order_consistent_tags: tuple[str, ...]
    reference_first_reasoning: str
    test_first_reasoning: str


@dataclass(frozen=True)
class AssetVerdict:
    """The examiner's verdict on one asset, across the examined views."""

    brief_name: str
    examiner_identity: str
    golden_identity: str
    views: tuple[ViewVerdict, ...]
    deviations: tuple[str, ...]
    abstained: bool

    def summary(self) -> str:
        lines = [
            f"EXAMINER {self.examiner_identity}: {self.brief_name} vs golden "
            f"{self.golden_identity}"
        ]
        for view in self.views:
            consistent = ", ".join(view.order_consistent_tags) or "(none)"
            lines.append(f"  {view.view_name:14s} consistent [{consistent}]")
        aggregate = (
            "ABSTAINED" if self.abstained else f"deviations {list(self.deviations)}"
        )
        lines.append(f"  aggregate: {aggregate}")
        return "\n".join(lines)


@dataclass(frozen=True)
class Calibration:
    """The measurement that licenses machine verdicts for one examiner."""

    examiner_identity: str
    vision_model: str
    recorded_at: str
    view_names: tuple[str, ...]
    fixtures: tuple[dict, ...] = field(default_factory=tuple)
    sensitivity: float = 0.0
    control_specificity: float = 0.0
    absent: bool = False

    @classmethod
    def missing(cls) -> Calibration:
        return cls(
            examiner_identity="",
            vision_model="",
            recorded_at="",
            view_names=(),
            absent=True,
        )

    def problems(self, examiner_identity: str) -> list[str]:
        """Non-empty means this examiner may not be trusted with a verdict."""
        if self.absent:
            return [f"no calibration file at {CALIBRATION_PATH}"]
        problems: list[str] = []
        if self.examiner_identity != examiner_identity:
            problems.append(
                f"calibration is for {self.examiner_identity!r}, not the "
                f"requested {examiner_identity!r} — a prompt or model change "
                f"invalidates a calibration by construction"
            )
        if self.sensitivity < MINIMUM_FIXTURE_SENSITIVITY:
            problems.append(
                f"sensitivity {self.sensitivity:.2f} < "
                f"{MINIMUM_FIXTURE_SENSITIVITY}: not distinguishable from "
                f"the no-reference rubber stamp"
            )
        if self.control_specificity < REQUIRED_CONTROL_SPECIFICITY:
            problems.append(
                f"control specificity {self.control_specificity:.2f} < "
                f"{REQUIRED_CONTROL_SPECIFICITY}: one false alarm on a "
                f"clean control terminates refinement early"
            )
        return problems


def load_calibration(path: Path = CALIBRATION_PATH) -> Calibration:
    path = Path(path)
    if not path.exists():
        return Calibration.missing()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Calibration(
        examiner_identity=payload["examiner_identity"],
        vision_model=payload["vision_model"],
        recorded_at=payload["recorded_at"],
        view_names=tuple(payload["view_names"]),
        fixtures=tuple(payload["fixtures"]),
        sensitivity=float(payload["sensitivity"]),
        control_specificity=float(payload["control_specificity"]),
    )


class CalibrationMissing(ExaminerError):
    """A machine verdict was attempted with no calibration on disk."""


def calibration_file_identity(path: Path = CALIBRATION_PATH) -> str:
    """Content hash of the calibration that licensed a machine verdict.

    Recorded in every machine verdict: a verdict whose licence cannot be
    identified afterwards is not auditable, and the pin rests on the
    verdict log. Raises rather than returning a blank — an unlicensed
    verdict must not be writable.
    """
    path = Path(path)
    if not path.exists():
        raise CalibrationMissing(
            f"no calibration file at {path}: run `make calibrate-eye` "
            f"before asking the examiner for a verdict"
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _first_json_object(reply_text: str) -> str:
    start = reply_text.find("{")
    if start == -1:
        raise ExaminerReplyUnparseable(
            f"reply contains no JSON object: {reply_text[:200]!r}"
        )
    depth = 0
    for index in range(start, len(reply_text)):
        if reply_text[index] == "{":
            depth += 1
        elif reply_text[index] == "}":
            depth -= 1
            if depth == 0:
                return reply_text[start : index + 1]
    raise ExaminerReplyUnparseable(
        f"reply opens a JSON object that never closes: {reply_text[:200]!r}"
    )


def parse_tags(reply_text: str) -> tuple[str, ...]:
    """The closed-vocabulary answer from the eye's reply.

    Requires exactly the contract shape — `reasoning` (str) and `tags`
    (list of str), every tag inside VALID_TAGS — and raises on anything
    else. No regex salvage, no best-effort path: a malformed reply is a
    loud failure, per the one-path rule.
    """
    try:
        payload = json.loads(_first_json_object(reply_text))
    except json.JSONDecodeError as error:
        raise ExaminerReplyUnparseable(
            f"reply is not valid JSON: {error}. Reply: {reply_text[:200]!r}"
        ) from error
    if not isinstance(payload, dict):
        raise ExaminerReplyUnparseable(
            f"reply JSON is not an object: {payload!r}"
        )
    reasoning = payload.get("reasoning")
    tags = payload.get("tags")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise ExaminerReplyUnparseable(
            f"reply lacks a non-empty string 'reasoning': {payload!r}"
        )
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ExaminerReplyUnparseable(
            f"reply lacks a list of string 'tags': {payload!r}"
        )
    unknown = sorted(set(tags) - set(VALID_TAGS))
    if unknown:
        raise UnknownDeviationTag(
            f"tags outside the closed vocabulary: {unknown}. "
            f"Valid tags: {VALID_TAGS}"
        )
    return tuple(tags)


def examiner_identity(vision_model: str) -> str:
    """The identity of this examiner: model + hash of the prompt body.

    Mirrors `PromptRevision.identity`, so a prompt or model change
    invalidates a stale calibration by construction.
    """
    body = render(EXAMINER_TEMPLATE, reference_position="first")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"{vision_model}+examiner:{digest[:12]}"


def _examiner_prompt(view_name: str, reference_position: str) -> str:
    return render(
        EXAMINER_TEMPLATE,
        view_name=view_name,
        reference_position=reference_position,
    )


def examine_view(eye, golden_view: Path, test_view: Path, view_name: str) -> ViewVerdict:
    """Compare one golden view against the render under review.

    Called twice with swapped image order (MT-bench position-bias
    mitigation, 10.48550/arXiv.2306.05685; BlenderGym measured judge
    position bias, 10.48550/arXiv.2504.01786) and only the
    order-consistent tags survive — the strictness that keeps false
    alarms out of the aggregate.
    """
    reference_first_reply = eye.describe(
        [golden_view, test_view],
        prompt=_examiner_prompt(view_name, reference_position="first"),
    )
    test_first_reply = eye.describe(
        [test_view, golden_view],
        prompt=_examiner_prompt(view_name, reference_position="second"),
    )
    reference_first_tags = parse_tags(reference_first_reply)
    test_first_tags = parse_tags(test_first_reply)
    consistent = tuple(sorted(set(reference_first_tags) & set(test_first_tags)))
    return ViewVerdict(
        view_name=view_name,
        reference_first_tags=reference_first_tags,
        test_first_tags=test_first_tags,
        order_consistent_tags=consistent,
        reference_first_reasoning=reference_first_reply,
        test_first_reasoning=test_first_reply,
    )


def verify_golden_manifest(golden_directory: Path, brief_name: str) -> str:
    """The golden must be the pinned one for THIS brief, byte for byte.

    RESP measured an irrelevant reference is worse than none
    (10.48550/arXiv.2604.11082, −0.23 F1), so a stale or wrong-brief
    golden is a correctness bug, not a cosmetic one.
    """
    manifest_path = Path(golden_directory) / "manifest.json"
    if not manifest_path.exists():
        raise GoldenReferenceMismatch(
            f"no manifest.json in golden directory {golden_directory}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("brief") != brief_name:
        raise GoldenReferenceMismatch(
            f"golden {golden_directory} is for {manifest.get('brief')!r}, "
            f"not {brief_name!r}"
        )
    recorded = manifest.get("view_sha256", {})
    if not recorded:
        raise GoldenReferenceMismatch(
            f"golden manifest {manifest_path} records no view hashes"
        )
    for view_name, expected in recorded.items():
        png = Path(golden_directory) / f"{view_name}.png"
        if not png.exists():
            # Absence is reported as GoldenViewMissing by examine_asset,
            # which pairs the views; a missing reference and a drifted
            # reference are different failures with different fixes.
            continue
        actual = hashlib.sha256(png.read_bytes()).hexdigest()
        if actual != expected:
            raise GoldenReferenceMismatch(
                f"golden view {png} hash {actual[:12]} does not match the "
                f"manifest's {expected[:12]} — the reference drifted"
            )
    return manifest.get("prompt_identity", "")


def examine_asset(
    eye,
    golden_directory: Path,
    render_directory: Path,
    brief,
    vision_model: str,
) -> AssetVerdict:
    """Examine every paired view of one asset against its golden reference.

    `deviations` is the sorted union of order-consistent tags across
    views, minus `no_deviation`; RESP's aggregation result — union over
    views is the detection rule, and order-consistency is the strictness
    that keeps false alarms out (10.48550/arXiv.2604.11082,
    10.48550/arXiv.2606.15693).
    """
    golden_directory = Path(golden_directory)
    render_directory = Path(render_directory)
    # Pair every view BEFORE spending a single eye call: a comparison
    # with one side missing would burn tokens to answer nothing.
    missing: list[str] = []
    for view_name in EXAMINED_VIEW_NAMES:
        golden_view = golden_directory / f"{view_name}.png"
        test_view = render_directory / f"{view_name}.png"
        if not golden_view.exists() or not test_view.exists():
            for path in (golden_view, test_view):
                if not path.exists():
                    missing.append(str(path))
    if missing:
        raise GoldenViewMissing(
            f"view(s) missing on one side of the comparison: {', '.join(missing)}"
        )
    golden_identity = verify_golden_manifest(golden_directory, brief.name)

    views: list[ViewVerdict] = []
    for view_name in EXAMINED_VIEW_NAMES:
        views.append(
            examine_view(
                eye,
                golden_directory / f"{view_name}.png",
                render_directory / f"{view_name}.png",
                view_name,
            )
        )

    deviation_tags = {
        tag
        for view in views
        for tag in view.order_consistent_tags
        if tag not in (NO_DEVIATION_TAG, CANNOT_TELL_TAG)
    }
    abstained = any(
        CANNOT_TELL_TAG in view.order_consistent_tags for view in views
    )
    return AssetVerdict(
        brief_name=brief.name,
        examiner_identity=examiner_identity(vision_model),
        golden_identity=golden_identity,
        views=tuple(views),
        deviations=tuple(sorted(deviation_tags)),
        abstained=abstained,
    )
