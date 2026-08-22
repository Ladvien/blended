"""The Experience Library: mistakes that must never recur.

3DCodeBench's curated Experience Library is the model — a durable
record consulted BEFORE acting, not a postmortem written after. The
drift catalog next door holds API-level lessons (a symbol moved, a call
lies). This holds LOOP-level lessons: what the harness, the prompt, or
the acceptance spec got wrong, and the assertion that now guards it.

A record is not complete until `guarded_by` names something executable.
"Be careful about X" is not a guard; a test that fails when X recurs is.
"""

from __future__ import annotations

from dataclasses import dataclass

SCOPE_PROMPT = "prompt"
SCOPE_HARNESS_CODE = "harness_code"
SCOPE_BRIEF = "brief"
SCOPE_PROCESS = "process"
SCOPES = (SCOPE_PROMPT, SCOPE_HARNESS_CODE, SCOPE_BRIEF, SCOPE_PROCESS)


@dataclass(frozen=True)
class MistakeRecord:
    """One (failure -> cause -> fix -> guard) chain."""

    identifier: str
    scope: str
    failure: str  # what was observed, in measurements
    cause: str  # why it happened
    fix: str  # what was changed
    guarded_by: str  # the executable assertion that catches a recurrence
    recorded_on: str  # ISO date


MISTAKES: tuple[MistakeRecord, ...] = (
    MistakeRecord(
        identifier="stale-version-pin-lies-to-the-model",
        scope="harness_code",
        failure=(
            "make test-blender-app: 1 failed, 72 passed — "
            "BlenderVersionError, running (5, 2) against pin (5, 0)."
        ),
        cause=(
            "TARGET_BLENDER_SERIES is interpolated into the first line of "
            "the system prompt, so a stale pin is not only a red test: "
            "every session opened by telling the agent it was coding "
            "against Blender 5.0 while running 5.2."
        ),
        fix=(
            "Bumped the pin to (5, 2) after confirming all 72 other blender "
            "tests pass unchanged on 5.2 (so no ops drift exists between "
            "the series), and recorded the lesson in drift/catalog.py in "
            "the same commit."
        ),
        guarded_by="tests/blender/test_walking_skeleton.py::test_pinned_blender_series",
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="material-slot-is-not-a-material",
        scope="harness_code",
        failure=(
            "The acceptance gate passed a planter built with NO material: "
            "material_slot_count == 1 while nothing was assigned."
        ),
        cause=(
            "Applying a boolean modifier appends an empty material slot to "
            "the target (measured: len(mesh.materials) 0 -> 1, contents "
            "[None]). len() counts slots, not materials, so every mesh "
            "that had ever been through a boolean read as textured."
        ),
        fix=(
            "The gate reports two numbers — slots and assigned — and "
            "requires assigned_material_count > 0."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_missing_material_trips_the_material_check"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="unlinked-object-crashed-the-gate",
        scope="harness_code",
        failure=(
            "evaluate_brief raised RuntimeError('Object has no evaluated "
            "mesh data') instead of returning a failing report."
        ),
        cause=(
            "Construction and linking are separate ops, so an object can "
            "exist in bpy.data with no depsgraph instance. The probe cast "
            "rays at it and Blender raised."
        ),
        fix=(
            "linked_into_scene is measured first and reported as an "
            "ordinary acceptance failure naming the missing "
            "link_into_scene call."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_unlinked_object_reports_a_measurement_not_a_crash"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="no-observation-channel-so-the-agent-raised-to-print",
        scope="harness_code",
        failure=(
            "Iteration 1, planter_box, prompt v1: both deterministic gates "
            "passed, but the run burned all 16 tool calls and ended with "
            "'Stopped after 16 tool calls without reaching an answer'. "
            "Three of those calls came back as FAILED tracebacks reading "
            "'RuntimeError: ring_verts=24 radii=[0.015]', "
            "'RuntimeError: material_slots_non_none=1', "
            "'RuntimeError: base_color=(0.72, 0.35, 0.22, 1.0)'."
        ),
        cause=(
            "run_source_in_process never captured stdout and RunResult had "
            "no field for it, so print() went to Blender's console where "
            "the model cannot see it, and an ungated run_python returned "
            "only 'Executed OK in 0.02s.'. With no way to read a value out "
            "of the scene, raising an exception was the agent's only "
            "channel — and every observation therefore arrived in its "
            "context labelled as a failure."
        ),
        fix=(
            "RunResult carries stdout_text, captured via "
            "contextlib.redirect_stdout in both the in-process and "
            "subprocess paths, bounded to MAXIMUM_STDOUT_CHARACTERS "
            "keeping the tail. Both run_python branches return it, and the "
            "tool description tells the agent print() is how it asks the "
            "scene a question. Silence is reported explicitly as "
            "'(nothing printed)'."
        ),
        guarded_by=(
            "tests/blender/test_observation_channel.py (6 assertions, "
            "including test_run_python_tool_returns_printed_output)"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="parity-probe-passed-a-sealed-drain-hole",
        scope="brief",
        failure=(
            "Iteration 1, planter_box: the acceptance gate reported FORM "
            "PASS with 'drain_hole_is_open: expected empty, measured empty "
            "(0 surface crossings)', while the top-down render showed "
            "opaque material on the drain axis (centre pixel 0.604 grey, "
            "alpha 1.0, against a transparent background). The gate "
            "certified the exact wrong-object failure the brief existed "
            "to catch."
        ),
        cause=(
            "SolidityProbe answers 'is there material at this point' by "
            "counting crossings along ONE ray. A drain cut from the cavity "
            "down into the floor but not out the bottom leaves the probe "
            "point in open air with the open top above it — zero "
            "crossings, indistinguishable from a real through-hole. Parity "
            "says nothing about the half-space behind the ray."
        ),
        fix=(
            "Added ClearAxisProbe: sweeps the entire axis from beyond one "
            "side and requires no hit at all, reporting the blocking "
            "coordinate when there is one. planter_box asserts a clear "
            "z-axis at (0, 0)."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_blind_recess_trips_the_clear_axis_probe — which also "
            "asserts the parity probes still CANNOT see it, so the "
            "fixture keeps reproducing the original failure"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="workbench-renders-grey-so-the-eye-invented-a-defect",
        scope="harness_code",
        failure=(
            "Iteration 1: the agent assigned a terracotta material, the "
            "contact sheet came back grey (measured 0.604, 0.608, 0.612), "
            "the vision model reported 'gray, not terracotta', and the "
            "agent spent tool calls investigating a defect that did not "
            "exist. It ran out of its tool budget mid-investigation."
        ),
        cause=(
            "Workbench shades from material.diffuse_color and never reads "
            "the shader graph, so setting only the Principled BSDF base "
            "colour renders as default grey. Compounding it, there was no "
            "whitelisted material op at all — the gate required a "
            "material the ops vocabulary could not make — so the agent "
            "used raw bpy and hit the trap unaided."
        ),
        fix=(
            "Added ops/materials.assign_material, which sets the shader "
            "base colour AND diffuse_color together and is idempotent by "
            "name; registered it in OP_MODULE_NAMES so it appears in the "
            "manifest and in search_ops."
        ),
        guarded_by=(
            "tests/blender/test_material_op.py::"
            "test_the_render_actually_shows_the_colour — asserts on "
            "rendered PIXELS, not on properties"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="no-rotate-op-in-the-whitelisted-vocabulary",
        scope="harness_code",
        failure=(
            "Iteration 3, three_leg_stool: the agent spent 3 search_ops "
            "calls plus a dir() probe — 4 of its 16 — before its own "
            "reasoning recorded 'There's no rotate op', then improvised "
            "with raw attribute writes. It exhausted the budget without "
            "finishing."
        ),
        cause=(
            "blended.ops exposed primitives, booleans, arrays, bevel, "
            "heal, uv and three transforms, but nothing that rotates or "
            "places an object. The architecture claims the ops are the "
            "only sanctioned way to build, and a splayed-leg assembly is "
            "not buildable through it."
        ),
        fix=(
            "Added transforms.rotate_object_euler and "
            "transforms.move_object_to. Both SET rather than accumulate "
            "(idempotent chunks) and refresh the depsgraph, so the "
            "stale-matrix_world trap cannot bite through them."
        ),
        guarded_by=(
            "tests/blender/test_transform_ops.py (6 assertions, including "
            "test_rotation_survives_apply_object_transform and "
            "test_both_ops_are_discoverable_through_search)"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="object-dimensions-ignores-rotation",
        scope="harness_code",
        failure=(
            "A 0.1 x 0.1 x 1.0 m box rotated a quarter turn about Y still "
            "reported object.dimensions (0.1, 0.1, 1.0) while occupying "
            "1.0 m on world X."
        ),
        cause=(
            "object.dimensions is the local bounding box times scale and "
            "ignores rotation entirely. Found while writing the test for "
            "the new rotate op — the assertion was written the obvious "
            "way and failed."
        ),
        fix=(
            "Catalogued as drift, so it reaches the agent through the "
            "manifest's API-traps section. This matters directly for "
            "prompt v3, which tells the agent to verify stated sizes by "
            "measuring: without the trap catalogued, that instruction "
            "would have sent it to the wrong property. The acceptance "
            "gate already measured world extents via matrix_world."
        ),
        guarded_by=(
            "tests/blender/test_transform_ops.py::"
            "test_rotation_reaches_matrix_world_immediately — asserts "
            "dimensions STILL ignores rotation, so the catalogued trap "
            "cannot go stale silently"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="base-z-certified-a-stool-that-rocks",
        scope="brief",
        failure=(
            "Iteration 4, three_leg_stool: FORM PASS with base_z +0.0000 m "
            "and total_height_z 0.4500 m — both exact — while a foot's sole "
            "was angled, so the stool stood on three edges. The human "
            "answered No to 'do all three feet sit flat on the ground' "
            "against a render the gate had already certified."
        ),
        cause=(
            "Grounding was one number: the minimum z of the whole object. "
            "A tilted end cap touching the floor at a single point drives "
            "that number to exactly 0.0000, indistinguishable from a flat "
            "sole. Contact is an AREA and was being measured as a HEIGHT. "
            "Rays cannot fix it either — from above they hit the seat, and "
            "from below they hit one point of an angled cap and report "
            "z=0 just as a flat one would."
        ),
        fix=(
            "Added GroundContactProbe: sums the world-space area of faces "
            "that reach the floor, face downward, and lie within "
            "SOLE_PLANARITY_TOLERANCE_M of z=0 near each expected foot, "
            "and requires MINIMUM_SOLE_CONTACT_AREA_M2. Zero area with "
            "rejected faces reports the tilt; zero with none reports a "
            "missing leg — different repairs, so they read differently. "
            "The reference stool in the tests had the same defect and now "
            "cuts its soles flat BEFORE snapping to ground; snapping "
            "first leaves nothing below the plane to cut."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_angled_sole_trips_the_ground_contact_probe — which also "
            "asserts base_z, the parity probes and the dimensions ALL "
            "still pass, so the fixture keeps reproducing the blindness"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-critique-explained-away-its-own-evidence",
        scope="process",
        failure=(
            "Iteration 4: the harness's visual critique answered Yes to "
            "'do all three feet sit flat on the ground', citing 63 "
            "vertices below z=0.005 in three clusters. Its own pixel scan "
            "of the front render had already measured the right-hand foot "
            "narrowing from 42 to 24 pixels over its last 3 rows while "
            "the left held 41 — and that measurement was dismissed in "
            "one clause as anti-aliasing. The human answered No."
        ),
        cause=(
            "The critique held both the evidence and the verdict, so it "
            "could rationalise the evidence to fit. A 5 mm threshold was "
            "chosen loose enough to admit a tilted cap, then the vertex "
            "count under it was read as proof of flatness. Neither step "
            "was wrong on its own; nothing forced them to disagree."
        ),
        fix=(
            "Moved the question out of the critique entirely. Flat-sole "
            "contact is now a deterministic gate (GroundContactProbe) "
            "that runs before any render is looked at, so this can never "
            "again be a judgement call about a picture. The general "
            "lesson is recorded here: when the visual pass measures "
            "something numerically and then argues with the number, the "
            "measurement belongs in the deterministic gate."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_angled_sole_is_reported_as_a_tilt_not_a_missing_leg — "
            "the tilt now arrives as a reported span in metres, not as "
            "something to interpret"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="search-matched-the-whole-query-as-one-string",
        scope="harness_code",
        failure=(
            "Iteration 4, three_leg_stool: 3 of 16 turns returned 'No "
            "operation matches' for 'boolean union', 'material assign' "
            "and 'assign material'. boolean_union and assign_material "
            "both existed; single-word retries found them immediately. "
            "19 percent of the turn budget was lost to word count, and "
            "the run then exhausted that budget without answering."
        ),
        cause=(
            "search_ops tested `query in haystack` — the raw query as one "
            "contiguous substring. That can never span the underscore in "
            "`boolean_union`, and it cannot survive reversed word order. "
            "The tool's own description only ever showed single-word "
            "examples, so the failure looked like an absent op rather "
            "than an unlucky phrasing — the same wrong conclusion as the "
            "no-rotate-op record below, reached without a missing op."
        ),
        fix=(
            "Both sides are split on non-alphanumerics and every query "
            "word must appear, so underscores and spaces are the same "
            "character to a searcher and word order stops mattering. A "
            "query with no words left is refused rather than matching "
            "everything, because all() of an empty list is True."
        ),
        guarded_by=(
            "tests/blender/test_transform_ops.py::"
            "test_multi_word_search_finds_the_op — parametrised over the "
            "three exact queries iteration 4 sent"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="budget-counted-messages-and-reported-calls",
        scope="harness_code",
        failure=(
            "Iteration 4 executed 20 tool calls and ended with 'Stopped "
            "after 16 tool calls in one turn without reaching an answer'. "
            "The iteration record therefore carried a tool_calls list of "
            "20 beside a message claiming 16."
        ),
        cause=(
            "The loop iterated `range(maximum_tool_calls_per_turn)` over "
            "assistant MESSAGES, and one message can carry several tool "
            "calls. The field name, the driver's --max-tool-calls flag "
            "and the exhaustion text all said calls; only the loop said "
            "messages, and it was the one enforcing the limit."
        ),
        fix=(
            "The budget counts calls as they are dispatched, charged "
            "before dispatch so a raising call still costs its turn. A "
            "message's calls are never half-answered, so the final count "
            "can overshoot the budget — it is reported as measured, with "
            "the configured budget beside it."
        ),
        guarded_by=(
            "tests/blender/test_agent_loop.py::"
            "test_the_budget_counts_calls_not_messages — three calls per "
            "message against a budget of four"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-healer-freed-the-faces-it-was-iterating",
        scope="harness_code",
        failure=(
            "Iteration 5, three_leg_stool: boolean_union raised "
            "'ReferenceError: BMesh data of type BMFace has been removed' "
            "at heal.py:57, inside its own healing step. The union had "
            "already applied and the addend had already been consumed, so "
            "the next call reported KeyError 'Stool_leg_0' not found. The "
            "agent spent 10 of its 16 calls rebuilding legs into a scene "
            "it could no longer describe, and shipped a mesh with 6 "
            "non-manifold edges, 57 boundary edges and no material."
        ),
        cause=(
            "weld_and_dissolve collected every zero-area face, then called "
            "bmesh.ops.collapse once per face while still holding that "
            "list. Collapsing an edge frees neighbouring faces, so reading "
            "`sliver_face.edges` off a later entry touched dead BMesh "
            "data. It only fires when two zero-area faces are adjacent, "
            "which is why unions had run clean until a splayed-leg seam "
            "produced a pair."
        ),
        fix=(
            "Every shortest edge is chosen BEFORE anything is collapsed, "
            "deduplicated by index (adjacent slivers can nominate the same "
            "edge), and collapsed in one bmesh.ops.collapse call."
        ),
        guarded_by=(
            "tests/blender/test_heal_ops.py::"
            "test_adjacent_slivers_do_not_kill_the_healer — two bow-tie "
            "quads sharing vertices. Zero-area QUADS are the fixture that "
            "works: dissolve_degenerate removes every collinear triangle "
            "before the collapse branch is reached, so a triangle fixture "
            "silently tests nothing (it was tried first and passed "
            "against the buggy code)."
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-log-kept-a-preview-of-the-call-that-crashed",
        scope="harness_code",
        failure=(
            "Diagnosing iteration 5 needed the run_python source that "
            "raised. Both the iteration log and the transcript held its "
            "first 200 characters — 'import bpy\\nfrom blended.ops.booleans "
            "import boolean_union\\n\\nseat = bpy.data.objects[...' — and "
            "the rest was gone. The crash had to be re-derived from the "
            "traceback and reproduced by experiment instead."
        ),
        cause=(
            "AgentSession.send truncated at the point of RECORDING rather "
            "than the point of display: emit('tool', ...[:200]). The "
            "driver that consumes those events already previews them at "
            "400 characters for the console, so the clipping bought "
            "nothing and cost the ability to replay a run from its own "
            "record."
        ),
        fix=(
            "The event carries the whole call; display layers keep their "
            "own previews."
        ),
        guarded_by=(
            "tests/blender/test_agent_loop.py::"
            "test_the_recorded_call_is_replayable — asserts the LAST line "
            "of a >400-character source survives into the event"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="a-boolean-on-unlinked-objects-lied-and-ate-the-operand",
        scope="harness_code",
        failure=(
            "Iteration 8, three_leg_stool: the run ended with NO OBJECT AT "
            "ALL — 'no object named Stool in the scene'. Measured "
            "directly: boolean_union on two unlinked boxes returns "
            "normally, leaves the target at 8 vertices (no union "
            "happened), and destroys the addend anyway."
        ),
        cause=(
            "Construction and linking are separate ops, so add_box hands "
            "back an unlinked object. The boolean modifier cannot "
            "evaluate an operand the depsgraph has no instance of, so it "
            "applies as a no-op — and _apply_boolean then removed the "
            "operand regardless. The op reported success for a result it "
            "had not produced. The agent correctly concluded something "
            "was wrong, wiped every mesh in the scene to A/B-test the op "
            "in isolation, and destroyed its own finished stool doing it: "
            "5 of 16 calls on the experiment, plus the asset."
        ),
        fix=(
            "_apply_boolean checks both operands are in the scene BEFORE "
            "touching anything and raises UnlinkedOperand naming "
            "link_into_scene. Checked before mutation, so a refusal "
            "leaves the scene exactly as the agent left it."
        ),
        guarded_by=(
            "tests/blender/test_heal_ops.py::"
            "test_boolean_on_unlinked_objects_refuses_instead_of_lying — "
            "asserts the addend SURVIVES the refusal, then that the same "
            "call succeeds once both objects are linked"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="preflight-was-shorter-than-a-cold-start",
        scope="harness_code",
        failure=(
            "Iteration 6 refused to run: 'Model unreachable, refusing to "
            "score a run: http://localhost:11434: timed out'. The backend "
            "was healthy — the same one-token ping by curl answered in "
            "23.3 s."
        ),
        cause=(
            "PREFLIGHT_TIMEOUT_SECONDS was 10 while the preflight sends a "
            "real chat completion, so it paid the cloud model's cold "
            "start and called a working backend dead."
        ),
        fix=(
            "PREFLIGHT_TIMEOUT_SECONDS 10 -> 90: generous against a "
            "measured 23.3 s cold start, still far below "
            "REQUEST_TIMEOUT_SECONDS (300) so a genuinely dead endpoint "
            "is still reported rather than waited on."
        ),
        guarded_by=(
            "tests/blender/test_agent_loop.py::"
            "test_preflight_timeout_allows_a_cold_start"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-front-view-cannot-show-three-fold-symmetry",
        scope="process",
        failure=(
            "Iteration 10: the harness answered Yes to 'are the legs "
            "evenly spaced, first one on +X'. The human answered "
            "Unclear — 'the top left image looks off' — and was right. "
            "Measured from the render afterwards: the two visible feet "
            "sit at world x -0.0700 and +0.1392, which matches perfect "
            "0/120/240 spacing (predicted -0.0700 and +0.1400) to 0.8 "
            "mm. The geometry was correct and the view still could not "
            "show it."
        ),
        cause=(
            "In the front orthographic view the 120 and 240 degree legs "
            "project to the SAME world x and overlap into what reads as "
            "one leg, leaving an asymmetric two-leg silhouette. The "
            "contact sheet does not contain the information the question "
            "needs, so any confident answer from it — Yes or No — is "
            "luck. This is the second time a placement question was "
            "answered from a view that could not support it (see "
            "the-critique-explained-away-its-own-evidence)."
        ),
        fix=(
            "Two changes. GroundContactProbe now carries expected_radius_m "
            "and expected_angle_deg, and the measurement reports the flat "
            "sole's area-weighted centroid as a radius and a bearing — so "
            "placement is a number, not a look. And every scored run now "
            "exports a verified .glb beside its contact sheet, because a "
            "reviewer can turn a .glb and cannot turn a render."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_uneven_leg_spacing_trips_the_placement_check (gaps of "
            "105/120/135 deg) and ::"
            "test_correct_spacing_measures_the_specified_bearings"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-reference-stool-put-its-soles-inboard",
        scope="harness_code",
        failure=(
            "The new placement probe rejected the test suite's own "
            "reference stool: sole centre r=0.1281 m against a specified "
            "0.1400 +/- 0.0100. The agent's build (iteration 10) measured "
            "0.1400 exactly on all three feet."
        ),
        cause=(
            "The fixture stood each leg's base on z=0 and tilted it "
            "there, so the tilted end cap crossed the cut plane — high on "
            "the outer side, low on the inner. Cutting at z=0 then left a "
            "crescent rather than the full ellipse, and its centroid sat "
            "12 mm inboard of the axis. The agent's build was more "
            "correct than the reference it was being checked against."
        ),
        fix=(
            "The fixture drops each leg by leg_radius/cos(splay) plus a "
            "margin so the whole cap clears the plane, starts the base "
            "further out by overhang*tan(splay) so the axis crosses z=0 "
            "exactly on the foot circle, and lengthens the leg by exactly "
            "the drop. The tolerance was NOT loosened — that would have "
            "tuned the gate until the fixture passed."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_correct_spacing_measures_the_specified_bearings — "
            "asserts the measured bearings are exactly [0, 120, 240] and "
            "every radius is in tolerance"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-contact-sheet-could-not-see-the-legs",
        scope="harness_code",
        failure=(
            "Iterations 10 and 11: the human answered 'Unclear' then "
            "'the top left image still seems weird' to whether the legs "
            "were evenly spaced — twice, on stools whose spacing was "
            "later measured correct to 0.3 degrees. No amount of "
            "explaining fixed it, because the reviewer was right."
        ),
        cause=(
            "Of the four views, `top` is blind to a stool's legs (the "
            "0.16 m seat covers feet at 0.14 m) and `front` projects the "
            "120 and 240 degree legs to the SAME world x, overlapping "
            "them into what reads as one leg and leaving an asymmetric "
            "two-leg silhouette. Only `right` and `three_quarter` carried "
            "the information — the two views the human said looked "
            "right. The sheet did not contain the answer, so a confident "
            "verdict from it was luck either way."
        ),
        fix=(
            "Added a `bottom` view (0, 0, -1). From below nothing "
            "occludes the legs and the spacing is direct: measured off "
            "the new render's pixels, the three feet sit at 0.3, 120.0 "
            "and 240.2 degrees. Every scored run also exports a "
            "round-trip-verified .glb, which a reviewer can turn."
        ),
        guarded_by=(
            "tests/blender/test_capture_v2.py::"
            "test_the_sheet_can_see_underneath and ::"
            "test_every_named_view_is_actually_rendered"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="a-golden-snapshot-cannot-be-checked-by-re-import",
        scope="harness_code",
        failure=(
            "The first golden-snapshot suite re-imported the signed-off "
            ".glb and every assertion failed: the form gate, the "
            "dimensions and all three foot placements, on assets that had "
            "just passed those exact checks."
        ),
        cause=(
            "ingest.import_glb is the GENERATED-asset lane. It "
            "deliberately normalizes what it reads — joins the parts, "
            "recentres on the vertex CENTROID and re-grounds — which is "
            "correct for an arbitrary generated mesh and destructive for "
            "evidence. A stool's vertex centroid is not its axis, so the "
            "round trip moved the feet off the 0.14 m circle the "
            "snapshot existed to pin."
        ),
        fix=(
            "Golden tests REPLAY the run's own recorded chunks instead "
            "(evaluate/replay.py), which needs no model and no network "
            "and reproduces the acceptance report number for number. The "
            ".glb files remain as evidence for a human to turn; they are "
            "not the measurement."
        ),
        guarded_by=(
            "tests/blender/test_golden_convergence.py (9 assertions "
            "including test_golden_stool_feet_are_where_they_were_"
            "signed_off, which pins contact area, radius and all three "
            "bearings)"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="convergence-was-blocked-by-the-harness-not-the-prompt",
        scope="process",
        failure=(
            "The loop ran 9 iterations without converging and hit its "
            "abort cap. Every prompt edit had been CONFIRMED on its "
            "stated target (v2 terminal state: 17 calls -> 3; v3 measure "
            "your numbers: base_z -0.0043 -> +0.0000; v4 stop searching "
            "for listed ops: 16 calls -> 5; v5 contact not height: sole "
            "area 0.000000 -> 0.001459 m2) and the suite still would not "
            "produce three clean runs."
        ),
        cause=(
            "Three of the six stool runs failed on harness defects, not "
            "prompt wording — a healer that freed the faces it was "
            "iterating, a boolean that silently no-opped on unlinked "
            "objects and ate the addend, a preflight shorter than a cold "
            "start. Each iteration surfaced a NEW latent defect, so the "
            "three-consecutive-clean count could never start. The final "
            "two blockers were not the prompt either: a writer too weak "
            "to place geometry (deepseek-v4-flash) and a 16-call budget "
            "too small to build, verify AND report — iteration 10 built "
            "a flawless asset in 17 calls and had nothing left to say it "
            "with."
        ),
        fix=(
            "Fixed 15 harness defects with a guard each, swapped the "
            "writer to deepseek-v4-pro (the eye was never the "
            "bottleneck: it correctly flagged the broken mesh in "
            "iteration 5 and the empty scene in iteration 8), and raised "
            "the budget to 24 from the measured 17. Convergence followed "
            "immediately: iterations 11, 12 and 13, at 7, 10 and 9 "
            "calls. The process lesson is that a prompt cannot be tuned "
            "through an unstable harness, and the classification "
            "discipline — only a prompt failure may edit the prompt — is "
            "what kept that visible instead of hiding it in reworded "
            "instructions."
        ),
        guarded_by=(
            "tests/blender/test_golden_convergence.py::"
            "test_the_pinned_prompt_is_the_one_that_converged — asserts "
            "the pinned revision's content hash, so the signed-off TEXT "
            "cannot drift after the fact"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="a-runtime-dependency-the-addon-could-not-install",
        scope="harness_code",
        failure=(
            "Moving the prompts into Jinja templates added jinja2 as a "
            "RUNTIME dependency of blended.agent.system_prompt. "
            "AgentSession.__post_init__ builds the system prompt and "
            "blender_addon/__init__.py builds an AgentSession, so the "
            "addon reaches that import on its first turn — and measured "
            "2026-08-22, jinja2 is absent from Blender's bundled Python, "
            "which has no pip. Shipped unguarded, the addon would have "
            "installed cleanly and then failed in someone else's Blender."
        ),
        cause=(
            "The driver scripts prepend the venv's site-packages to "
            "sys.path, so a venv-only dependency works there and hides "
            "the problem completely. The addon lane gets no venv. Two "
            "lanes into the same code, one of which is never exercised "
            "by `make test-blender-app`, because that runs from the repo."
        ),
        fix=(
            "package_addon.py vendors jinja2 and markupsafe into the zip "
            "beside the library, and refuses to build with a named error "
            "if either is missing from the venv rather than producing a "
            "zip that is broken in a way nobody sees until install. The "
            "prompt templates are vendored the same way — package data "
            "is the classic thing to leave behind, where the code "
            "imports fine and then cannot find its own text."
        ),
        guarded_by=(
            "tests/pure/test_addon_packaging.py (5 assertions: the "
            "library, every registered template, each vendored "
            "dependency, and no __pycache__). Verified end to end by "
            "unpacking the zip and rendering the prompt inside Blender "
            "with ONLY the addon on sys.path."
        ),
        recorded_on="2026-08-22",
    ),
)


class DuplicateMistake(ValueError):
    """Raised when two records share an identifier."""


def validate_memory() -> list[str]:
    """Schema problems (empty list = healthy memory)."""
    problems: list[str] = []
    seen: set[str] = set()
    for record in MISTAKES:
        if record.scope not in SCOPES:
            problems.append(f"{record.identifier}: scope {record.scope!r} not in SCOPES")
        if not record.guarded_by.strip():
            problems.append(f"{record.identifier}: no guard — the record is not done")
        if record.identifier in seen:
            problems.append(f"duplicate identifier: {record.identifier}")
        seen.add(record.identifier)
    return problems


def consult(scope: str = "") -> str:
    """Render the memory for reading BEFORE an adjustment.

    Called at the top of every iteration. If this returns text nobody
    reads, the memory is decoration.
    """
    selected = [
        record for record in MISTAKES if not scope or record.scope == scope
    ]
    if not selected:
        return f"(no recorded mistakes for scope {scope!r})"
    lines: list[str] = []
    for record in selected:
        lines.append(f"[{record.scope}] {record.identifier} ({record.recorded_on})")
        lines.append(f"  failure: {record.failure}")
        lines.append(f"  cause:   {record.cause}")
        lines.append(f"  fix:     {record.fix}")
        lines.append(f"  guard:   {record.guarded_by}")
    return "\n".join(lines)
