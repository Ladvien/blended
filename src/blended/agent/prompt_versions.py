"""The system prompt as a VERSIONED artifact.

The prompt is the tunable part of this harness, so it is not a string
literal buried in a renderer — it is an addressable revision with an
identity the iteration log can cite and a predecessor it can be rolled
back to.

LL3M's finding is the reason each revision differs from its predecessor
by exactly ONE element: surgical edits to a working prompt outperform
rewrites, and a rewrite destroys the attribution that makes the next
edit informed. So `PROMPT_REVISIONS` reads as a diff history, and every
entry after v1 carries the hypothesis that motivated it and the outcome
that was measured — the record 3DCodeBench's Experience Library keeps,
in the artifact it is about.

This module is the REGISTRY, not the text. Each body lives in
`prompts/working_agreement_v{n}.md.j2` so it can be read and reviewed as
prose; what a file cannot carry — why the revision exists and what it
measured — lives here. `validate_revisions()` checks the two agree, and
enforces by measurement the discipline the old chained-`.replace()`
build enforced by construction.

Adding a revision: see `prompts/README.md`. In short — copy the previous
template, change ONE element, state `hypothesis` BEFORE running it, fill
`outcome` from the measurement rather than impression, and move
ACTIVE_PROMPT_REVISION only once the measurement supports it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptRevision:
    """One revision of the working agreement, with its provenance."""

    revision: int
    changed_element: str  # the ONE thing this revision changed
    hypothesis: str  # stated BEFORE the run: "changed X because Y; expect Z"
    outcome: str  # filled from measurement AFTER the run; "" while pending

    @property
    def body(self) -> str:
        """The prompt text, rendered from `prompts/`.

        Read from disk rather than stored here so the text is a file a
        person or an agent can open, diff and review on its own terms.
        This registry keeps what a file cannot: why the revision exists
        and what it measured.
        """
        from blended.agent.prompt_templates import render_working_agreement

        return render_working_agreement(self.revision)

    @property
    def identity(self) -> str:
        """Content hash: proves which text actually ran."""
        digest = hashlib.sha256(self.body.encode("utf-8")).hexdigest()
        return f"v{self.revision}:{digest[:12]}"


PROMPT_REVISIONS: tuple[PromptRevision, ...] = (
    PromptRevision(
        revision=1,
        changed_element="(baseline)",
        hypothesis="(baseline — written from the research brief, never scored)",
        outcome=(
            "Iteration 2: both briefs passed both deterministic gates with "
            "zero visual deviations, but planter_box never terminated — it "
            "met every done-condition, then exported unprompted and "
            "exhausted its 16-call budget, returning 'Stopped after 16 tool "
            "calls in one turn without reaching an answer'. three_leg_stool "
            "terminated cleanly at 12 calls. Classified: prompt failure, no "
            "terminal state defined."
        ),
    ),
    PromptRevision(
        revision=2,
        changed_element=(
            "Added a terminal state to 'What done means': when all three "
            "conditions hold, stop calling tools and report."
        ),
        hypothesis=(
            "Changed the done-definition to name an explicit STOP, because "
            "v1 listed three done-conditions but never said what to do once "
            "they held — so the agent treated 'done' as an internal "
            "checklist and kept working past it. Expect planter_box to end "
            "with a final report in fewer tool calls, and three_leg_stool, "
            "which already terminated, to be unaffected."
        ),
        outcome=(
            "CONFIRMED for planter_box: 17 tool calls -> 3, ending in a "
            "written report instead of 'Stopped after 16 tool calls'. Both "
            "gates passed. NOT sufficient for three_leg_stool: it still "
            "exhausted 16 calls and now FAILED the form gate "
            "(base_z -0.0043 m against a 0.002 m tolerance, total height "
            "0.4543 m). It spent 4 calls discovering there was no rotate "
            "op, and never re-checked grounding after its final union."
        ),
    ),
    PromptRevision(
        revision=3,
        changed_element=(
            "Added, before the terminal state: the gate measures structure "
            "not intent, so verify the user's stated numbers by measuring "
            "the finished object after the last operation."
        ),
        hypothesis=(
            "Changed the done-definition to require measuring the brief's "
            "own numbers, because three_leg_stool passed the structural "
            "gate with its feet 4.3 mm below z=0 and its height 4.3 mm "
            "over — drift introduced by the final boolean union, which "
            "nothing in the loop ever re-checked, and which the analyzer "
            "gate cannot see because it does not know the brief. Expect "
            "base_z and total_height_z inside tolerance, and planter_box "
            "(already passing in 3 calls) to stay passing."
        ),
        outcome=(
            "CONFIRMED on its target, iteration 4: base_z -0.0043 -> "
            "+0.0000 m and total_height_z 0.4543 -> 0.4500 m, both exact, "
            "and the agent printed its own measurements after the final "
            "boolean. NOT sufficient overall — the run still exhausted "
            "its budget (20 calls / 16 turns) without answering, and the "
            "human rejected the feet: one sole was angled, which base_z "
            "cannot see. Both were classified harness-code, not prompt, "
            "so v3 stands unchanged into iteration 5: search_ops now "
            "matches words (3 wasted turns returned), the budget counts "
            "and reports real calls, and GroundContactProbe measures "
            "sole contact as an area."
        ),
    ),
    PromptRevision(
        revision=4,
        changed_element=(
            "Tool discipline: replaced 'call search_ops when you need an "
            "operation you have not used' with a statement that the "
            "listed vocabulary is complete and must not be searched for."
        ),
        hypothesis=(
            "Changed the search instruction because the prompt contains "
            "all 20 operations with their exact signatures and then tells "
            "the agent to go and look operations up. Measured: "
            "three_leg_stool spent 6 of 16 calls on search_ops in "
            "iteration 4 and 5 of 16 in iteration 6, and every single op "
            "it searched for — boolean_union, add_cylinder, "
            "assign_material, boolean_difference, add_box, "
            "rotate_object_euler, move_object_to, add_bevel — was already "
            "printed in its own system prompt. That is 31-37 percent of "
            "the budget spent re-deriving what it was handed, on the one "
            "brief that has now failed to terminate three times running. "
            "Expect three_leg_stool to reach a written answer inside its "
            "budget, and planter_box (which already answers in 3 calls "
            "and searched for nothing) to be unaffected."
        ),
        outcome=(
            "CONFIRMED, iteration 7: 16 tool calls -> 5, and the run "
            "TERMINATED with a written report for the first time in four "
            "attempts on this brief. Zero search_ops calls. Structural "
            "PASS; base_z +0.0000 m and total_height_z 0.4500 m both "
            "exact; material assigned; and the agent correctly explained "
            "the +0.0048 m seat_diameter_x delta as the splayed foot "
            "protruding past the seat rim rather than treating it as a "
            "defect. One failure remains, unrelated to this edit: all "
            "three soles are angled (zero flat contact area)."
        ),
    ),
    PromptRevision(
        revision=5,
        changed_element=(
            "Added to the measure-your-own-numbers paragraph: resting on "
            "a surface is a contact, not a height — a part that stands on "
            "the floor must meet it with a flat face."
        ),
        hypothesis=(
            "Changed it because 'feet on the ground at z=0' is being read "
            "as a height and satisfied by the lowest point. Measured "
            "across iterations 4 and 7: base_z +0.0000 m exactly, every "
            "foot probe solid, and every sole still angled — 7 non-level "
            "faces per foot spanning 0.41-0.43 m in z, zero flat contact "
            "area. The agent verifies the number it was given and the "
            "number is not the requirement. Expect the three "
            "leg_N_sole_is_flat_on_the_ground probes to report contact "
            "area above the minimum, and the 5-call termination from v4 "
            "to survive."
        ),
        outcome=(
            "CONFIRMED on its target, iteration 9: all three soles went "
            "from 0.000000 m2 of flat contact to 0.001459 m2 each — 14.6x "
            "the required minimum — and base_z stayed at +0.0000 m. This "
            "is the defect the human caught by eye at iteration 4 and the "
            "gate could not see; it is now built correctly and measured. "
            "NOT a passing run overall, and the failures are new ones: "
            "the material was never assigned (0 in 1 slot), "
            "seat_diameter_x reached 0.3798 m (+0.0598, outside the "
            "0.0200 tolerance) as the legs splayed past the seat rim, and "
            "the run again used all 16 calls without answering — v4's "
            "5-call termination did NOT survive."
        ),
    ),
    PromptRevision(
        revision=6,
        changed_element=(
            "Added a 'Changing something they already have' section: "
            "follow-up instructions are localized edits that preserve the "
            "rest of the asset, the gate and a render are re-run after "
            "each one, and the turn ends on the user's approval."
        ),
        hypothesis=(
            "Added it because the harness code standards REQUIRE a "
            "user-guided refinement phase and v5 contains none — it says "
            "how to build an asset and stop, and nothing about changing "
            "one that exists, so a follow-up instruction invites a full "
            "rebuild that discards approved work. This is a compliance "
            "gap, not an observed run failure: v5 converged without it "
            "only because no brief exercised a second turn. The briefs "
            "now carry a RefinementStep, so it is measurable. Expect "
            "first-build behaviour unchanged (the section governs only "
            "follow-ups), so runs should stay near 7-10 calls with both "
            "gates clean, AND the taller_stool follow-up to reach 0.55 m "
            "while every other dimension, foot radius and leg bearing "
            "stays where it was."
        ),
        outcome=(
            "Iteration 14, the first run to exercise a RefinementStep: "
            "both deterministic gates PASS and the refinement gate PASS "
            "— total_height_z 0.4500 -> 0.5500 m exact, 2 dimensions "
            "and 3 foot placements preserved with 0 disturbed, soles "
            "0.001522 m2 flat contact each at bearings 0.0/120.0/240.0 "
            "deg, material 1-in-1, 21 tool calls of 24 (16 first build, "
            "5 refinement) ending in a written report. The human "
            "confirmed the render with zero visual deviations. The "
            "section's first-build prediction held. Its CENTRAL "
            "instruction did not: told to change one dimension, the "
            "agent re-ran add_cylinder / boolean_union / ground-cut "
            "from scratch at 0.55 m rather than editing the stool in "
            "front of it. No gate could see it — a rebuild from the "
            "same constants lands on the same numbers, which is exactly "
            "what preservation compares. The human ruled the rebuild "
            "ACCEPTABLE, which makes the examiner's finding a false "
            "positive (mistake memory: "
            "the-critique-called-a-clean-rebuild-a-failure) and makes "
            "v6's 'Do not rebuild it from scratch' a demand nothing "
            "enforces and nobody wants enforced. Superseded by v7."
        ),
    ),
    PromptRevision(
        revision=7,
        changed_element=(
            "Softened the opening of 'Changing something they already "
            "have' from an absolute prohibition on rebuilding to a "
            "preference for editing, with the preservation of settled "
            "detail as the binding requirement instead."
        ),
        hypothesis=(
            "Changed it because iteration 14 rebuilt the stool at "
            "0.55 m, preserved every unnamed measurement exactly, and "
            "the human ruled that acceptable. v6 forbids in words what "
            "the loop permits in measurement: an instruction that can "
            "be violated with no consequence and no signal teaches the "
            "reader which lines are decorative. v7 keeps the reason "
            "(seconds versus minutes) and the requirement that survives "
            "scrutiny (nothing settled may be lost), and drops the ban "
            "that does not. Expect iteration 15 to measure as 14 did — "
            "both gates clean, the refinement preserving every unnamed "
            "number — with the run no longer in conflict with its own "
            "instructions, and `refinement_locality` in the log "
            "recording which way the follow-up went."
        ),
        outcome=(
            "CONFIRMED on its own target across iterations 15-17. "
            "Iteration 15 (three_leg_stool): both gates PASS, "
            "refinement PASS with 0 unnamed measurements disturbed, 18 "
            "tool calls (down from 21 at v6), and LOCALITY recorded "
            "'rebuilt (stamped 9337507e4ccd, found no stamp)' — the "
            "follow-up replaced the datablock, which v7 permits and the "
            "gate correctly did not fail. The instruction and the "
            "measurement agree for the first time. Iteration 16 "
            "(planter_box): both gates PASS at 12 calls, every "
            "dimension exact. Human confirmed both renders, zero "
            "deviations. NOT a converging sequence: iteration 17 "
            "(three_leg_stool) FAILED the form gate at 10 calls — all "
            "three sole centres at r=0.1281 m against 0.1400 +/- "
            "0.0100. Unrelated to this edit: v7 changed only the "
            "follow-up paragraph, and 17 failed on its FIRST build, "
            "before any follow-up ran. Superseded by v8, which "
            "addresses that failure."
        ),
    ),
    PromptRevision(
        revision=8,
        changed_element=(
            "Extended the contact paragraph: a position the user "
            "specified belongs to the contact patch, not to the axis "
            "that produced it."
        ),
        hypothesis=(
            "Changed it because iteration 17 placed all three leg base "
            "centres at r=0.1400, cut them flat at z=0, and the "
            "surviving ellipse's centroid landed at r=0.1281 on every "
            "foot — 11.9 mm inboard, past the 0.0100 tolerance — while "
            "the run's own report claimed 'each foot's axis landing on "
            "radius 0.14'. It measured, and measured the wrong feature: "
            "v5 taught it that resting is a contact rather than a "
            "height, and it now produces a flat sole and then verifies "
            "the axis that made it. The number is not incidental: "
            "0.1281 is exactly what the harness's own reference fixture "
            "produced before it was fixed (mistake memory: "
            "the-reference-stool-put-its-soles-inboard), so this is a "
            "known geometric trap, not run-to-run noise, and the "
            "tolerance was deliberately not loosened when the fixture "
            "hit it. Expect all three sole centres inside 0.1400 +/- "
            "0.0100, with the flatness, spacing, termination and "
            "refinement behaviour of v5-v7 unchanged."
        ),
        outcome=(
            "CONFIRMED on its target, iteration 18: all three sole "
            "centres measured r=0.1400 m exactly (from 0.1281), "
            "bearings 0.0/120.0/240.0 deg, flat contact 0.001228 m2 "
            "each, both gates PASS, refinement PASS with 0 disturbed, "
            "and 7 tool calls — the shortest run the suite has "
            "produced. The sentence worked. SUPERSEDED ANYWAY, by "
            "decision rather than by measurement: the trap was "
            "reclassified harness_code and moved into the builder API "
            "(blended/ops/legs.py), because prose that asks the model "
            "to re-derive trigonometry has to be re-derived on every "
            "run, while an op that cannot be called wrongly does not. "
            "Iteration 18 was not human-verified; no convergence claim "
            "rests on it."
        ),
    ),
    PromptRevision(
        revision=9,
        changed_element=(
            "Reverted v8's contact-position sentence. The text is "
            "byte-identical to v7 again."
        ),
        hypothesis=(
            "Reverted because v8 was an edit made under a "
            "classification that was wrong. Iteration 17 was called a "
            "prompt failure; it is a harness_code failure, and the "
            "loop's own discipline says a harness_code failure is "
            "fixed by coding and permits no prompt edit. The fix now "
            "lives in blended.ops.legs, which owns the placement "
            "arithmetic and is exposed to the agent through the "
            "generated manifest, so the sentence is redundant — and "
            "keeping it would leave the loop unable to tell which of "
            "the two fixed the run. Expect iteration 19 to hold "
            "iteration 18's sole placement (r=0.1400 +/- 0.0100 on all "
            "three feet) with the sentence gone, because the op "
            "supplies it. If placement regresses, the op is present "
            "but unused, and the answer is to make it the obvious call "
            "in the manifest — not to restore the prose."
        ),
        outcome=(
            "CONFIRMED, and CONVERGED. Iteration 19 answered the "
            "question the revert was written to ask: with v8's sentence "
            "gone, the agent reached for add_splayed_leg unprompted (23 "
            "references in its transcript) and sole centres held at "
            "r=0.1400 m exactly on all three feet. The geometry came "
            "from the op, not the prose. Then three consecutive "
            "human-verified clean runs on the settled harness: "
            "iteration 20 planter_box (8 calls), 21 three_leg_stool (9 "
            "calls, refinement 0 disturbed), 22 planter_box (3 calls, "
            "the fewest any run has taken). Iterations 15, 16 and 19 "
            "ran this same TEXT and are NOT counted: 15 and 16 predate "
            "the leg ops, 19 predates the removal of the smart_unwrap "
            "shim, and 'no prompt change between them' has to mean the "
            "bytes the agent actually received."
        ),
    ),
)

# --- CONVERGED --------------------------------------------------------
# v9 is PINNED, superseding the v5 pin of earlier the same day. The rule is three CONSECUTIVE runs passing both
# deterministic gates with zero visual deviations, confirmed by the
# human, with no prompt change between them. Met 2026-08-22:
#
#   iteration 20  planter_box        8 calls  both gates PASS  0 deviations
#   iteration 21  three_leg_stool    9 calls  both gates PASS  0 deviations
#   iteration 22  planter_box        3 calls  both gates PASS  0 deviations
#
# All three terminated with a written report, all three exported a
# round-trip-verified .glb, and the human confirmed every render. The
# stool run also passed the refinement gate with 0 unnamed measurements
# disturbed, which v5 was never asked to do.
#
# WHAT "NO PROMPT CHANGE" MEANS HERE. v9's working agreement is
# byte-identical to v7's — same hash, 2e5d0dab1033 — because v9 reverts
# v8. But iterations 15, 16 and 19 ran that same text and are NOT
# counted toward this pin: 15 and 16 predate blended.ops.legs, and 19
# predates the removal of the uv.smart_unwrap shim. Both changed the
# generated manifest, and the manifest is part of the bytes the agent
# receives. Counting them would claim evidence from a system that no
# longer exists.
#
# The v5 pin was earned on its own harness and is not disowned: it is
# in the append-only log, and v5 still carries its outcome above. What
# it no longer has is a golden test, because its runs cannot be
# replayed against a harness that has since gained ops.
#
# The evidence is MODEL-SPECIFIC and the log records it per run. v1-v4
# were scored against deepseek-v4-flash, which never converged this
# suite: the last two blockers were not prompt wording at all but a
# writer too weak to place geometry and a tool budget too small to
# build, verify AND report in one turn.
PINNED_PROMPT_REVISION = 9
CONVERGED_ON = "2026-08-22"
CONVERGENCE_RUNS = (
    (20, "planter_box"),
    (21, "three_leg_stool"),
    (22, "planter_box"),
)
CONVERGENCE_WRITER_MODEL = "deepseek-v4-pro:cloud"
CONVERGENCE_VISION_MODEL = "minimax-m3:cloud"
CONVERGENCE_TOOL_CALL_BUDGET = 24

ACTIVE_PROMPT_REVISION = PINNED_PROMPT_REVISION


# LL3M's one-element rule used to be enforced by construction: each body
# was built by `.replace()` on its predecessor and raised if the anchor
# text had moved. Templates are far easier to read and review, and they
# lose that guard — nothing stops a file from being quietly rewritten.
# So the rule is enforced by MEASUREMENT instead, which is stricter: a
# revision must differ from its predecessor by exactly one contiguous
# run of changed lines.
MAXIMUM_CHANGED_HUNKS_PER_REVISION = 1


def changed_hunks(previous_body: str, body: str) -> list[str]:
    """The contiguous runs of changed lines between two revisions."""
    import difflib

    matcher = difflib.SequenceMatcher(
        None, previous_body.splitlines(), body.splitlines(), autojunk=False
    )
    hunks: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks.append(f"{tag} lines {i1}-{i2} -> {j1}-{j2}")
    return hunks


def validate_revisions() -> list[str]:
    """Schema and discipline problems (empty list = a healthy history).

    Checks what a reader would otherwise have to take on trust: the
    revisions are consecutive from 1, each has a template that renders,
    each differs from its predecessor by one hunk and by SOMETHING, and
    every revision before the active one has recorded what it measured.
    """
    problems: list[str] = []
    numbers = [entry.revision for entry in PROMPT_REVISIONS]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"revisions are not consecutive from 1: {numbers}")
    previous: PromptRevision | None = None
    for entry in PROMPT_REVISIONS:
        try:
            body = entry.body
        except Exception as error:  # noqa: BLE001 — reported, not raised
            problems.append(f"v{entry.revision}: template did not render: {error}")
            previous = None
            continue
        if not body.strip():
            problems.append(f"v{entry.revision}: template rendered empty")
        if previous is not None:
            hunks = changed_hunks(previous.body, body)
            if not hunks:
                problems.append(
                    f"v{entry.revision} is identical to v{previous.revision}: "
                    f"a revision that changes nothing cannot be attributed"
                )
            elif len(hunks) > MAXIMUM_CHANGED_HUNKS_PER_REVISION:
                problems.append(
                    f"v{entry.revision} changes {len(hunks)} separate places "
                    f"in v{previous.revision}, not one: {hunks}. Surgical "
                    f"edits beat rewrites (LL3M); split it into revisions."
                )
        if not entry.hypothesis.strip():
            problems.append(f"v{entry.revision}: no hypothesis recorded")
        if entry.revision < ACTIVE_PROMPT_REVISION and not entry.outcome.strip():
            problems.append(
                f"v{entry.revision} was superseded without recording what it "
                f"measured — the next edit would be uninformed"
            )
        previous = entry
    return problems


class UnknownPromptRevision(KeyError):
    """Raised when a revision number has no entry. There is no default."""


def get_revision(revision: int | None = None) -> PromptRevision:
    """Return one revision. `None` means the active one.

    Unknown revisions raise. A convergence loop that silently fell back
    to the active prompt when asked for v3 would attribute v3's score to
    text that never ran.
    """
    wanted = ACTIVE_PROMPT_REVISION if revision is None else revision
    for entry in PROMPT_REVISIONS:
        if entry.revision == wanted:
            return entry
    available = ", ".join(str(entry.revision) for entry in PROMPT_REVISIONS)
    raise UnknownPromptRevision(
        f"No prompt revision {wanted}. Available: {available}."
    )


def latest_revision() -> PromptRevision:
    return max(PROMPT_REVISIONS, key=lambda entry: entry.revision)
