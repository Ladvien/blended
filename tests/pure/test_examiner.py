"""Pure layer: the structured examiner, with a stub eye (no network).

The examiner is the instrument that replaces the human verdict in the
convergence loop, so its tests pin the three failure modes that would
silently corrupt the loop if they regressed:

- Defect 1's exact shape: a denial ("I don't see any missing...") must
  score as NO deviation, not as a sighting — the old scorer counted it
  as both (see mistake memory
  "the-eye-scorer-counted-a-denial-as-a-sighting").
- Order-consistency: a tag seen in only one image order is dropped
  (MT-bench position-bias mitigation, 10.48550/arXiv.2306.05685).
- The closed vocabulary: a tag outside the list, or prose instead of
  JSON, is a loud failure, never a best-effort guess.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from blended.evaluate.examiner import (
    CANNOT_TELL_TAG,
    Calibration,
    ExaminerReplyUnparseable,
    GoldenReferenceMismatch,
    GoldenViewMissing,
    UnknownDeviationTag,
    examine_asset,
    examiner_identity,
    parse_tags,
)

VIEWS = ("front", "right", "top", "bottom", "three_quarter")
NO_DEVIATION = '{"reasoning": "Same asset.", "tags": ["no_deviation"]}'


def _write_png(path: Path, payload: bytes = b"png-bytes") -> Path:
    path.write_bytes(payload)
    return path


def _golden_directory(base: Path, brief_name: str = "three_leg_stool") -> Path:
    golden = base / "golden"
    golden.mkdir()
    manifest = {
        "brief": brief_name,
        "iteration": 47,
        "revision": 10,
        "prompt_identity": "v10:b6627b38f4c1",
        "blender_series": "5.2",
        "captured_at": "2026-08-22T00:00:00+00:00",
    }
    (golden / "manifest.json").write_text(json.dumps(manifest))
    for view in VIEWS:
        _write_png(golden / f"{view}.png")
    manifest["view_sha256"] = {
        view: hashlib.sha256((golden / f"{view}.png").read_bytes()).hexdigest()
        for view in VIEWS
    }
    (golden / "manifest.json").write_text(json.dumps(manifest))
    return golden


def _render_directory(base: Path) -> Path:
    renders = base / "renders"
    renders.mkdir()
    for view in VIEWS:
        _write_png(renders / f"{view}.png")
    return renders


@dataclass
class StubEye:
    """One canned reply per describe call, in call order."""

    replies: list[str]

    def describe(self, image_paths, question="", prompt=""):
        return self.replies.pop(0)


class _Brief:
    name = "three_leg_stool"


def _clean_replies(extra: list[str]) -> list[str]:
    """The nine no_deviation replies for the other views, plus `extra`
    for the first view's two orders."""
    return extra + [NO_DEVIATION] * 8


def test_a_denial_is_not_a_deviation(tmp_path):
    """Defect 1's guard: 'I don't see any missing, misplaced, floating,
    or duplicated parts' scored as a false positive in the old scorer.
    The closed-vocabulary reply with no_deviation must yield zero
    deviations."""
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    replies = [
        (
            '{"reasoning": "I don\'t see any missing, misplaced, floating, or '
            'duplicated parts.", "tags": ["no_deviation"]}'
        ),
        NO_DEVIATION,
    ] + [NO_DEVIATION] * 8
    verdict = examine_asset(StubEye(replies), golden, renders, _Brief(), "stub-model")
    assert verdict.deviations == ()
    assert verdict.abstained is False
    assert not replies, "the stub must have answered every call"


def test_a_tag_seen_in_one_order_only_is_dropped(tmp_path):
    """Position-bias mitigation: offset_part seen in one order and
    no_deviation in the other must NOT survive the intersection."""
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    replies = [
        '{"reasoning": "seat shifted", "tags": ["offset_part"]}',
        NO_DEVIATION,
    ] + [NO_DEVIATION] * 8
    verdict = examine_asset(StubEye(replies), golden, renders, _Brief(), "stub-model")
    assert verdict.deviations == ()
    assert verdict.views[0].reference_first_tags == ("offset_part",)


def test_a_tag_consistent_across_orders_is_reported(tmp_path):
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    replies = [
        '{"reasoning": "leg missing", "tags": ["missing_part"]}',
        '{"reasoning": "leg missing", "tags": ["missing_part"]}',
    ] + [NO_DEVIATION] * 8
    verdict = examine_asset(StubEye(replies), golden, renders, _Brief(), "stub-model")
    assert verdict.deviations == ("missing_part",)


def test_unknown_tag_raises():
    with pytest.raises(UnknownDeviationTag):
        parse_tags('{"reasoning": "r", "tags": ["invented_tag"]}')


def test_prose_reply_raises():
    with pytest.raises(ExaminerReplyUnparseable):
        parse_tags("The asset looks fine, no problems at all.")


def test_missing_reasoning_raises():
    with pytest.raises(ExaminerReplyUnparseable):
        parse_tags('{"tags": ["no_deviation"]}')


def test_cannot_tell_sets_abstained(tmp_path):
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    replies = [
        f'{{"reasoning": "cannot judge", "tags": ["{CANNOT_TELL_TAG}"]}}',
        f'{{"reasoning": "cannot judge", "tags": ["{CANNOT_TELL_TAG}"]}}',
    ] + [NO_DEVIATION] * 8
    verdict = examine_asset(StubEye(replies), golden, renders, _Brief(), "stub-model")
    assert verdict.abstained is True
    assert verdict.deviations == ()


def test_missing_golden_view_raises(tmp_path):
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    (golden / "bottom.png").unlink()
    with pytest.raises(GoldenViewMissing):
        examine_asset(StubEye([]), golden, renders, _Brief(), "stub-model")


def test_missing_test_view_raises(tmp_path):
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    (renders / "top.png").unlink()
    with pytest.raises(GoldenViewMissing):
        examine_asset(StubEye([]), golden, renders, _Brief(), "stub-model")


def test_wrong_brief_golden_raises(tmp_path):
    golden = _golden_directory(tmp_path, brief_name="planter_box")
    renders = _render_directory(tmp_path)
    with pytest.raises(GoldenReferenceMismatch):
        examine_asset(StubEye([]), golden, renders, _Brief(), "stub-model")


def test_drifted_golden_view_raises(tmp_path):
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    (golden / "front.png").write_bytes(b"different-bytes")
    with pytest.raises(GoldenReferenceMismatch):
        examine_asset(StubEye([]), golden, renders, _Brief(), "stub-model")


def test_missing_manifest_raises(tmp_path):
    golden = _golden_directory(tmp_path)
    (golden / "manifest.json").unlink()
    renders = _render_directory(tmp_path)
    with pytest.raises(GoldenReferenceMismatch):
        examine_asset(StubEye([]), golden, renders, _Brief(), "stub-model")


def test_examiner_identity_changes_with_the_model():
    assert examiner_identity("model-a") != examiner_identity("model-b")
    assert examiner_identity("minimax-m3:cloud").startswith("minimax-m3:cloud+examiner:")


def test_calibration_problems_are_loud():
    calibration = Calibration(
        examiner_identity="some-model+examiner:deadbeef",
        vision_model="some-model",
        recorded_at="2026-08-22T00:00:00+00:00",
        view_names=("front",),
        sensitivity=0.4,
        control_specificity=1.0,
    )
    problems = calibration.problems("other-model+examiner:cafebabe")
    assert any("calibration is for" in problem for problem in problems)
    assert any("sensitivity" in problem for problem in problems)

    clean = Calibration(
        examiner_identity="m+examiner:abc",
        vision_model="m",
        recorded_at="2026-08-22T00:00:00+00:00",
        view_names=("front",),
        sensitivity=1.0,
        control_specificity=1.0,
    )
    assert clean.problems("m+examiner:abc") == []


def test_missing_calibration_file_is_a_problem(tmp_path):
    calibration = Calibration.missing()
    assert calibration.problems("anything") != []
