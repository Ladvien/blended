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
        outcome="",
    ),
)

# --- CONVERGED --------------------------------------------------------
# v5 is PINNED. The rule is three CONSECUTIVE runs passing both
# deterministic gates with zero visual deviations, confirmed by the
# human, with no prompt change between them. Met 2026-08-22:
#
#   iteration 11  three_leg_stool    7 calls  both gates PASS  0 deviations
#   iteration 12  planter_box       10 calls  both gates PASS  0 deviations
#   iteration 13  three_leg_stool    9 calls  both gates PASS  0 deviations
#
# All three terminated with a written report, all three exported a
# round-trip-verified .glb, and the human answered Yes to every derived
# verification question on all three. The prompt has been byte-identical
# since iteration 9.
#
# The evidence is MODEL-SPECIFIC and the log records it per run. v1-v4
# were scored against deepseek-v4-flash, which never converged this
# suite: the last two blockers were not prompt wording at all but a
# writer too weak to place geometry and a tool budget too small to
# build, verify AND report in one turn.
PINNED_PROMPT_REVISION = 5
CONVERGED_ON = "2026-08-22"
CONVERGENCE_RUNS = (
    (11, "three_leg_stool"),
    (12, "planter_box"),
    (13, "three_leg_stool"),
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
