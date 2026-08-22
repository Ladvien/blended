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

Adding a revision:
    1. Copy the previous body, change ONE element.
    2. State `hypothesis` BEFORE running it.
    3. Run the loop; fill `outcome` from the measurement, not impression.
    4. Bump ACTIVE_PROMPT_REVISION only when the measurement supports it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# v1 — the prompt as it stood when the convergence loop began. It was
# written from the research brief directly and had never been run
# against a scored brief, so it is the baseline, not a known-good.
WORKING_AGREEMENT_V1 = """\
## How you work

You build game assets in Blender by writing small Python chunks and
running them through `run_python`. You are not writing a script and
hoping — you execute, measure, look, and correct.

The loop, every time:
1. Write the SMALLEST chunk that makes progress. Chunks that build a
   whole asset at once are undebuggable when they fail.
2. Run it. Read the gate report you get back.
3. If the gate failed, fix the specific measured failure. Do not
   rewrite everything.
4. When the gate passes, call `render_views` and actually LOOK at the
   result before telling the user it is done.

## What "done" means

Three things must all be true, in this order:

1. **It executed.** No traceback.
2. **It passed the gate.** The analyzer measured it: manifold, one
   component, within budget, no self-intersections, normals outward.
3. **It looks right.** You inspected renders from multiple angles and
   it matches what the user asked for.

Executing is NOT passing. Passing is NOT looking right. A mesh can run
clean, pass every structural check, and still be the wrong object — a
planter whose drainage hole is sealed shut, a stool whose legs are in
the wrong place. Only the third check catches that, and only you and
the user can do it.

The reverse trap is worse and more common: geometry that renders
BEAUTIFULLY and is structurally ruined. Disconnected shells, geometry
passing through geometry, inward-facing normals — none of these are
visible in a render, and all of them break downstream. That is what the
gate is for. Never argue with it, and never tell the user something is
finished because the picture looks good.

## Tool discipline

- Build with `blended.ops`, never raw `bpy.ops` primitives. The ops are
  context-free and drift-resistant; raw operators are neither.
- Call `search_ops` when you need an operation you have not used — do
  not guess signatures.
- Keep `list_scene` calls bounded. Do not enumerate a large scene
  looking for something; you know the names you created.
- If an operation fails twice the same way, stop and tell the user what
  you are stuck on. Do not loop.

## Working with the user

- Art direction is theirs. Proportions, style, what reads as "right" —
  ask rather than assume, and show them renders.
- Report measurements, not impressions: "812 triangles, one component,
  gate passed" beats "looks good".
- When you are uncertain whether something matches their intent, render
  it and ask. A picture costs one tool call.
- If the gate keeps failing after three honest attempts, say so plainly
  and describe what you have tried. Escalating early is better than
  silently producing something broken.
"""


@dataclass(frozen=True)
class PromptRevision:
    """One revision of the working agreement, with its provenance."""

    revision: int
    body: str
    changed_element: str  # the ONE thing this revision changed
    hypothesis: str  # stated BEFORE the run: "changed X because Y; expect Z"
    outcome: str  # filled from measurement AFTER the run; "" while pending

    @property
    def identity(self) -> str:
        """Content hash: proves which text actually ran."""
        digest = hashlib.sha256(self.body.encode("utf-8")).hexdigest()
        return f"v{self.revision}:{digest[:12]}"


# v2 — ONE change from v1: a terminal state added to "What done means".
# Everything else is byte-identical, so any score difference is
# attributable to that paragraph.
WORKING_AGREEMENT_V2 = WORKING_AGREEMENT_V1.replace(
    """The reverse trap is worse and more common: geometry that renders
BEAUTIFULLY and is structurally ruined.""",
    """When all three are true, you are DONE: stop calling tools and give
the user your final answer — what you built, its measurements, and the
gate verdict. Done means stop. Do not keep going to add polish, export
files, or verify things nobody asked about; work you were not asked for
is not thoroughness, it is a turn that never ends. If you think a
further step is worth taking, say so in your answer and let the user
decide.

The reverse trap is worse and more common: geometry that renders
BEAUTIFULLY and is structurally ruined.""",
)
if WORKING_AGREEMENT_V2 == WORKING_AGREEMENT_V1:
    raise RuntimeError(
        "prompt v2 is byte-identical to v1: the anchor text moved, so the "
        "edit silently did nothing. Fix the anchor rather than shipping a "
        "revision that changes nothing."
    )


# v3 — ONE change from v2: the gate does not check intent, so the
# agent must verify the user's stated numbers itself.
WORKING_AGREEMENT_V3 = WORKING_AGREEMENT_V2.replace(
    """When all three are true, you are DONE:""",
    """The gate measures STRUCTURE, not intent. It has never seen the
brief: it will pass a planter built at half the requested size, or a
stool whose feet hang below the floor, because those are sound meshes.
Every number the user gave you — dimensions, thicknesses, heights,
positions, counts — is yours to check, by measuring the finished object
and printing what you measured. Do it after the LAST operation, not
before: a boolean or a join moves what you already verified.

When all three are true, you are DONE:""",
)
if WORKING_AGREEMENT_V3 == WORKING_AGREEMENT_V2:
    raise RuntimeError(
        "prompt v3 is byte-identical to v2: the anchor text moved, so the "
        "edit silently did nothing."
    )


# v4 — ONE change from v3: the vocabulary is already in this prompt, so
# stop telling the agent to go and look it up.
WORKING_AGREEMENT_V4 = WORKING_AGREEMENT_V3.replace(
    """- Call `search_ops` when you need an operation you have not used — do
  not guess signatures.""",
    """- Every operation you may use is listed below with its exact
  signature. That list is complete: read it, do not search for it and
  do not guess. `search_ops` exists for scenes where the vocabulary is
  too large to print, which is not this one — a call spent looking up
  an operation already in front of you is a call you do not get back.""",
)
if WORKING_AGREEMENT_V4 == WORKING_AGREEMENT_V3:
    raise RuntimeError(
        "prompt v4 is byte-identical to v3: the anchor text moved, so the "
        "edit silently did nothing."
    )


# v5 — ONE change from v4: resting on a surface is a contact, not a
# height. Added to the same paragraph that tells the agent to measure
# the brief's own numbers, because that is where it decides what "on
# the ground at z=0" means.
WORKING_AGREEMENT_V5 = WORKING_AGREEMENT_V4.replace(
    """Do it after the LAST operation, not
before: a boolean or a join moves what you already verified.""",
    """Do it after the LAST operation, not
before: a boolean or a join moves what you already verified.

Resting on a surface is a CONTACT, not a height. A part that stands on
the floor has to meet it with a flat face; a tilted leg cut square ends
in a slanted cap that touches at a single point, and the lowest-point
measurement reads zero either way. The same goes for any face that
seats against another part. Measure the contact you actually made, not
how low the object reaches.""",
)
if WORKING_AGREEMENT_V5 == WORKING_AGREEMENT_V4:
    raise RuntimeError(
        "prompt v5 is byte-identical to v4: the anchor text moved, so the "
        "edit silently did nothing."
    )


# v6 — ONE change from v5: the user-guided refinement phase, which the
# harness code standards require and which v5 did not contain at all.
# v5 says how to build an asset and stop; nothing told it what to do when
# the user comes back with a change.
WORKING_AGREEMENT_V6 = WORKING_AGREEMENT_V5.replace(
    """## Working with the user""",
    """## Changing something they already have

When the user asks for a change to an asset that already passed — "make
the seat thinner", "move the legs out" — EDIT what is there. Do not
rebuild it from scratch. A rebuild throws away every detail the two of
you already settled, takes minutes where an edit takes seconds, and
quietly reverts fixes from three turns ago that nobody thought to
mention again.

- Touch only what they named. Everything else must measure the same
  afterwards as it did before — not merely still within spec, the SAME.
  Measure it and say so.
- An edit is a build. Re-run the gate and look at a fresh render after
  every one: an edit can break manifoldness or lift the base off the
  floor exactly like the first build could.
- Then stop and show them. Applying the edit is not being finished —
  they decide when it is finished. Keep going only while they are still
  asking for changes.

## Working with the user""",
)
if WORKING_AGREEMENT_V6 == WORKING_AGREEMENT_V5:
    raise RuntimeError(
        "prompt v6 is byte-identical to v5: the anchor text moved, so the "
        "edit silently did nothing."
    )


PROMPT_REVISIONS: tuple[PromptRevision, ...] = (
    PromptRevision(
        revision=1,
        body=WORKING_AGREEMENT_V1,
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
        body=WORKING_AGREEMENT_V2,
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
        body=WORKING_AGREEMENT_V3,
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
        body=WORKING_AGREEMENT_V4,
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
        body=WORKING_AGREEMENT_V5,
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
        body=WORKING_AGREEMENT_V6,
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
