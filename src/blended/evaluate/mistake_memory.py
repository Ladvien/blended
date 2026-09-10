"""The Experience Library: mistakes that must never recur.

3DCodeBench's curated Experience Library is the model — a durable
record consulted BEFORE acting, not a postmortem written after. The
drift catalog next door holds API-level lessons (a symbol moved, a call
lies). This holds LOOP-level lessons: what the harness, the prompt, or
the acceptance spec got wrong, and the assertion that now guards it.

A record is not complete until `guarded_by` names something executable.
"Be careful about X" is not a guard; a test that fails when X recurs is.

Shape per CoALA's procedural memory — reflect experience into knowledge,
then into a code library (DOI 10.48550/arXiv.2309.02427); the open
problem is stale memory dominating (memory-mechanism survey,
DOI 10.48550/arXiv.2404.13501), which is why `recorded_on` is a field.
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
    MistakeRecord(
        identifier="the-critique-called-a-clean-rebuild-a-failure",
        scope="process",
        failure=(
            "Iteration 14: every gate passed and the human confirmed "
            "the render, but the examiner raised a deviation anyway — "
            "the taller_stool follow-up re-ran add_cylinder / "
            "boolean_union / ground-cut at 0.55 m instead of editing "
            "the existing stool, which v6 forbids in words. It was "
            "classified harness_code, on the reasoning that the "
            "refinement gate was blind to it. The human ruled the "
            "rebuild ACCEPTABLE: it preserved 2 dimensions and 3 foot "
            "placements exactly, 0 disturbed. The finding was a FALSE "
            "POSITIVE, and a run that had passed was nearly recorded "
            "as a failure in an append-only log."
        ),
        cause=(
            "The examiner scored the run against the prompt's wording "
            "rather than against the result, and treated a rule the "
            "harness states as a rule the harness has verified is "
            "wanted. 'The gate cannot see X' is a statement about the "
            "gate; whether X should fail a run is a question for the "
            "human, and it was answered by assumption instead. Note "
            "the direction: the earlier critique failure "
            "(the-critique-explained-away-its-own-evidence) was a MISS, "
            "this one is a FALSE ALARM. Both are harness_critique "
            "failures, which is why that classification exists."
        ),
        fix=(
            "Object identity is stamped and READ BACK after every "
            "follow-up (evaluate/object_identity.py), so edit-versus-"
            "rebuild is measured rather than argued — and recorded as "
            "evidence in `IterationRecord.refinement_locality`, never "
            "consulted by `passed`. v7 softens the prompt to match what "
            "is actually enforced: editing is preferred for its cost, "
            "preserving settled detail is the binding requirement. The "
            "general lesson: when the critique wants to fail a run on a "
            "rule no gate enforces, that is a question for the human, "
            "not a finding."
        ),
        guarded_by=(
            "tests/pure/test_object_identity.py::"
            "test_a_rebuild_is_recorded_as_evidence_and_never_gated — "
            "asserts a rebuilt object reads as not edited_in_place AND "
            "that IterationRecord.passed stays True with that evidence "
            "present, so wiring locality into the gate breaks the test "
            "rather than silently reversing the ruling."
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="multi-step-refinement-was-scored-against-the-original-brief",
        scope="harness_code",
        failure=(
            "Iteration 23, the first run with three refinement steps: "
            "the FIRST build passed both gates, but all three "
            "REFINEMENT steps failed — wider_seat failed for still "
            "having a 0.40 m seat (expected 0.32), thicker_legs failed "
            "for having the 0.40 m seat and 0.55 m height the previous "
            "steps had correctly produced. The agent's build was "
            "right; the scorer was wrong."
        ),
        cause=(
            "The driver scored every step against "
            "refine_brief(ORIGINAL_brief, step) instead of the brief "
            "refined by its predecessors. A multi-step sequence is "
            "cumulative: step N's spec is the original brief with steps "
            "1..N applied, and scoring step N against the original "
            "reports every earlier step's change as a failure."
        ),
        fix=(
            "The driver accumulates step_brief = refine_brief(step_brief, "
            "step) per step and scores each outcome against it; replay "
            "and the golden tests apply exactly the steps the record "
            "carries in refinement_locality (evaluate/replay.py::"
            "steps_applied), so records from before the suite gained "
            "steps are not graded against steps they never ran."
        ),
        guarded_by=(
            "tests/blender/test_golden_convergence.py::"
            "test_golden_stool_measures_the_signed_off_numbers — the "
            "v10 stool snapshot pins the 0.40 m seat, which only "
            "measures correctly when all three steps are composed"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="a-boolean-that-changed-nothing-returned-normally",
        scope="harness_code",
        failure=(
            "Iteration 33, planter_box: the agent's cavity sat 0.01 m "
            "short of the box top, boolean_difference RETURNED NORMALLY "
            "with the mesh unchanged, the gate caught 2 disconnected "
            "components, and the agent spent 21 tool calls debugging an "
            "op that was never wrong — reading its source, trying "
            "FAST/MANIFOLD solvers, wiping the scene — before "
            "exhausting its budget with no object at all."
        ),
        cause=(
            "_apply_boolean verified the operands were linked (the "
            "iteration-8 lesson) but never verified the boolean had "
            "DONE anything. A cutter that does not intersect the target "
            "applies as a silent no-op, and the agent cannot tell 'the "
            "op failed' from 'my geometry was wrong' — so it "
            "investigated the op."
        ),
        fix=(
            "BooleanNoOp: after applying, the op compares vertex "
            "positions (rounded to 1e-6) before and after and raises "
            "when nothing moved. Counts are NOT compared — the EXACT "
            "solver cuts a tilted cap flat while preserving counts "
            "exactly (measured: 136 verts / 76 polys before and after "
            "trim_soles_flat, z range -0.0269 -> 0.0000), so a "
            "count-based guard fires falsely on legitimate trims."
        ),
        guarded_by=(
            "tests/blender/test_csg_ops.py::"
            "test_non_intersecting_cutter_raises_instead_of_silently_"
            "no_oping — a cutter outside the target must raise and "
            "leave both objects intact. Plus the full Blender suite: "
            "every trim_soles_flat call exercises the guard against "
            "false positives."
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="assign-material-destroyed-a-shared-datablock",
        scope="harness_code",
        failure=(
            "Iteration 46, crate_with_lid: the agent assigned "
            "'CrateWood' to the crate body, then assigned the same "
            "name to the lid. The assembly failed the material gate "
            "with CrateBody 0 assigned in 1 slot — everything else "
            "passed. The agent used the documented op correctly."
        ),
        cause=(
            "assign_material was idempotent by REMOVING the existing "
            "datablock and creating a fresh one. A material name is a "
            "shared resource across parts: removing it dangles every "
            "other object's slot to None. Single-object briefs never "
            "hit it; the assembly brief exposed it on its first run."
        ),
        fix=(
            "assign_material reuses the existing datablock in place — "
            "updates the colours, reassigns to the caller — so "
            "references from other objects survive. Idempotency is "
            "preserved (one datablock, one slot per object), only the "
            "destruction is gone."
        ),
        guarded_by=(
            "tests/blender/test_material_op.py::"
            "test_a_shared_material_name_survives_reassignment — two "
            "objects sharing a name must both keep their assignment "
            "and reference the SAME datablock"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-vision-model-cannot-yet-guard-visible-defects",
        scope="process",
        failure=(
            "Stage-7 measurement, 2026-08-22, scripts/measure_eye.py: "
            "7 fixtures x 2 conditions against minimax-m3:cloud. NoRef "
            "recall 3/5 (0.60) with 2/2 false positives; Ref recall 2/5 "
            "(0.40) with 2/2 false positives. The defect class that "
            "started the loop — sealed_drain — was missed in BOTH "
            "conditions: the eye noticed the hole difference and "
            "dismissed it as 'rendering/opacity'. floating_seat was "
            "caught WITHOUT the reference and missed WITH it: the eye "
            "wrote 'I cannot identify any meaningful visual "
            "differences... they appear essentially identical' — the "
            "reference invited rationalization. The controls drew "
            "false-positive defect language in every condition."
        ),
        cause=(
            "An unmeasured instrument was assumed to be a gate. The "
            "TikZ study's finding held: a VLM critic is biased toward "
            "accepting, and a reference image does not fix the bias — "
            "it reframes the task as 'explain why these match' and the "
            "eye complies. The sealed_drain miss matters most: it is "
            "the exact wrong-object failure the whole loop exists to "
            "catch, and no render-based instrument caught it."
        ),
        fix=(
            "None. The pre-decided branch applied: Ref recall (0.40) "
            "did not beat NoRef (0.60) by >= 0.2, so no reference "
            "wiring was added to VisionDescriber and no critique code "
            "changed. The measurement is the outcome: the human gate "
            "stays, and the eye stays advisory. The deterministic "
            "gates are the only pass/fail authority until a future "
            "measurement beats this one."
        ),
        guarded_by=(
            "_evaluate/eye_measurement.jsonl holds the raw replies, but "
            "its NUMBERS are void: the scorer that produced them "
            "counted denials as sightings (see "
            "the-eye-scorer-counted-a-denial-as-a-sighting). The live "
            "guard is now `make calibrate-eye`, whose "
            "_evaluate/eye_calibration.json must license a machine "
            "verdict before the loop will accept one — "
            "tests/pure/test_examiner.py::"
            "test_calibration_problems_are_loud asserts an examiner "
            "under threshold is refused."
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-eye-scorer-counted-a-denial-as-a-sighting",
        scope="harness_code",
        failure=(
            "In _evaluate/eye_measurement.jsonl both clean controls "
            "scored false_positive=true in BOTH conditions, and "
            "floating_seat/NoRef scored hit=true, off replies that "
            "said the opposite: \"I don't see any missing, misplaced, "
            'floating, or duplicated parts" and "no floating, '
            'intersecting, or duplicated parts". The recorded numbers '
            "(NoRef 3/5 hits with 2/2 false positives, Ref 2/5 with "
            "2/2) were instrument artifacts, not measurements of the "
            "eye."
        ),
        cause=(
            "scripts/measure_eye.py::is_hit did case-insensitive "
            "SUBSTRING matching over a flat defect vocabulary, so a "
            "denial containing the defect word matched as a sighting — "
            "negation was invisible to the scorer. Worse, control "
            'scoring called it with part_words=("",), and '
            'any("" in text) is always true, so any defect word '
            "anywhere in a reply was a false positive by construction."
        ),
        fix=(
            "The eye now answers in a CLOSED TAG VOCABULARY "
            "(evaluate/examiner.py: DEVIATION_TAGS + no_deviation + "
            "cannot_tell) inside a JSON contract, and scoring is exact "
            "tag comparison — so negation is not a scoring surface at "
            "all. A reply that is not the contract raises rather than "
            "being pattern-matched, and every view is examined in both "
            "image orders with only order-consistent tags surviving. "
            "scripts/measure_eye.py is gone; scripts/calibrate_examiner.py "
            "replaces it and writes _evaluate/eye_calibration.json, "
            "which must license a machine verdict before the loop will "
            "accept one."
        ),
        guarded_by=(
            "tests/pure/test_examiner.py::"
            "test_a_denial_is_not_a_deviation — the exact denial string "
            "from the bad measurement, which must yield zero deviations"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-convergence-rule-was-never-executable",
        scope="process",
        failure=(
            "evaluate/iteration_log.py::consecutive_clean_runs had no "
            "caller anywhere in the repository (repo-wide grep: the "
            "definition only), and it required every brief to appear "
            "under the SAME iteration number. On iterations 47-51 — "
            "the very cycle that earned the v10 pin, one brief per "
            "iteration — it returns 0. The convergence claim was "
            "verified by hand while the executable rule disagreed with "
            "it."
        ),
        cause=(
            "The rule was written against a two-brief suite where one "
            "iteration held every brief. The five-brief protocol runs "
            "ONE brief per iteration, and because nothing ever called "
            "the function, no test and no run noticed the shape change."
        ),
        fix=(
            "converged_suite_cycles builds a cycle from the NEWEST "
            "record per brief, walking iterations downwards, and "
            "returns (trailing clean cycles, the one prompt identity "
            "they ran). The orchestrator calls it every round, so the "
            "rule is executed on the same evidence a person would "
            "read."
        ),
        guarded_by=(
            "tests/pure/test_convergence_rule.py::"
            "test_the_v10_cycle_is_one_converged_cycle — reads the real "
            "_evaluate logs and requires the recorded v10 cycle to "
            "count, plus cases for mixed identities, abstention, "
            "deviations and an unexamined run"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="two-same-size-images-fused-so-the-examiner-was-blind",
        scope="harness_code",
        failure=(
            "The first live examiner call, 2026-08-22 against "
            "qwen3-vl:8b on native ollama 0.32.14, answered "
            "'The reference image (first image) is not provided' and "
            "tagged cannot_tell. Probing the wire: two 512x512 renders "
            "in one /api/chat message cost 1055 prompt tokens — the "
            "same as ONE image (1047) — the model answered '1' to 'how "
            "many distinct images did you receive?', and sending "
            "[planter, stool] made it describe the planter and ignore "
            "the stool. The examiner had never been shown the render "
            "under review; it was comparing the reference to itself."
        ),
        cause=(
            "Two layers compounding. Ollama's renderer prepends "
            "[img-0][img-1]... back to back for a message that carries "
            "images and no explicit placeholders "
            "(model/renderers/image_tags.go), and llama.cpp's mtmd "
            "tokenizer merges CONSECUTIVE same-size bitmaps into video "
            "frames for the qwen-vl family "
            "(clip_model_n_temporal_merge == 2). Reported as "
            "ollama/ollama#17321 and ggml-org/llama.cpp#24303, both "
            "open. Every render this harness makes comes out of the "
            "same CaptureSettings, so every examiner pair is the same "
            "size: the merge case was not an edge case, it was the "
            "only case. Nothing logged a warning at any layer."
        ),
        fix=(
            "loop.py::_image_placeholders emits one labelled `[img]` "
            "per image with text between them, so the renderer "
            "substitutes them in order and no two bitmaps are "
            "consecutive parts. Prompt tokens for the same pair went "
            "1055 -> 2089; the identical pair then scored "
            "no_deviation and stool-vs-planter scored missing_part. "
            "VisionDescriber.describe is the only place images are "
            "built for the eye, and it is now unconditional: the "
            "writer's path sends ONE contact sheet (render_views "
            "composites five views into a single PNG) so it was never "
            "bitten, but it carries a placeholder too, so a caller that "
            "ever attaches several images cannot silently lose them."
        ),
        guarded_by=(
            "tests/pure/test_vision_transport.py::"
            "test_no_two_placeholders_are_adjacent and "
            "::test_every_image_gets_its_own_placeholder — asserted on "
            "the payload at the _request boundary, because describe() "
            "builds its own client and the wire is the only honest "
            "place to see what the model will be shown"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="a-local-8b-eye-scored-0.20-and-may-not-judge",
        scope="process",
        failure=(
            "First real calibration, 2026-08-22: `make calibrate-eye` "
            "against qwen3-vl:8b-instruct on big (native ollama "
            "0.32.14, one RTX 3090), 100 eye calls over 10 fixtures x "
            "5 views x 2 orders in 228 s. sensitivity 0.20 (1/5), "
            "control specificity 1.00 (5/5). Only lid_offset was "
            "caught. missing_leg scored detected=True in a --only run "
            "four minutes earlier and detected=False in the zoo — at "
            "temperature 0.2 the bottom view's two orders disagreed, "
            "and order-consistency correctly dropped it. sealed_drain "
            "drew material_missing where missing_feature was expected: "
            "a sighting under the wrong name, which the tag "
            "intersection does not credit. The thinking sibling "
            "qwen3-vl:8b could not be used at all — on a "
            "stool-vs-planter pair it emitted 30387 tokens into "
            "`thinking`, hit done_reason=length against a 32k context "
            "and returned EMPTY content after 331 s."
        ),
        cause=(
            "An 8B eye at 512x512 is simply under-sensitive to the "
            "defect classes this suite cares about, and the controls "
            "prove it is not the opposite failure: 5/5 clean assets "
            "drew zero deviations, so it is not trigger-happy, it does "
            "not see. RESP's +0.49 recall from a reference is a delta, "
            "not a floor — the absolute level is the model's."
        ),
        fix=(
            "None, deliberately. MINIMUM_FIXTURE_SENSITIVITY (0.6) and "
            "REQUIRED_CONTROL_SPECIFICITY (1.0) were NOT moved and "
            "prompts/examiner.md.j2 was NOT softened; either would have "
            "bought a licence by lowering the bar the licence exists to "
            "certify. _evaluate/eye_calibration.json records the "
            "measurement under identity "
            "qwen3-vl:8b-instruct+examiner:60a9920cb938, machine "
            "verdicts stay unlicensed, and --examiner none remains the "
            "driver default. The next lever is a stronger eye, not more "
            "prompt engineering — BlenderGym's finding that verifier "
            "quality is the compute worth buying."
        ),
        guarded_by=(
            "The driver itself: `run_agent_task.py --examiner auto` "
            "against this calibration exits 1 in 0.7 s with "
            "'sensitivity 0.20 < 0.6: not distinguishable from the "
            "no-reference rubber stamp' and writes NO iteration row and "
            "NO verdict row (run with --log/--verdicts under "
            "_evaluate/local_eye/, both absent afterwards). "
            "tests/pure/test_examiner.py::"
            "test_calibration_problems_are_loud pins the refusal."
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="installing-over-an-enabled-addon-ran-a-stale-build",
        scope="harness_code",
        failure=(
            "Live session 2026-08-22 20:18, Blender 5.2: 'Make a low poly "
            "human' SIGSEGV'd about 20 s into the fifth tool call, which "
            "never produced a result row. TWO faults, both in the "
            "depsgraph: a TBB worker in BKE_object_sync_to_original "
            "(Blender's own blender.crash.txt) and the main thread in "
            "DepsgraphRelationBuilder::build_copy_on_write_relations under "
            "wm_event_do_notifiers (the OS .ips report). No Python frame in "
            "either. The crash is STILL UNEXPLAINED, and it cannot be "
            "replayed from the record: every tool event in that transcript "
            "is exactly 212 characters = 'run_python(' + 200 + ')', the old "
            "emit's [:200] slice — a line that does not exist on disk — so "
            "the script that was running when it died was never written "
            "down. Replaying the reconstructable part (six unlinked parts, "
            "link all, union five) survives headless, live, and live with "
            "the same emptied scene."
        ),
        cause=(
            "`blended` is a TOP-LEVEL package on sys.path, not a submodule "
            "of the addon. Installing dist/blended_agent.zip over an "
            "ENABLED addon rewrites every file and reloads only "
            "blended_agent/__init__.py ('module changed on disk ... "
            "reloading'), while sys.modules keeps every blended.* module "
            "from the previous install. Measured by installing a zip whose "
            "REQUEST_TIMEOUT_SECONDS was 12345: on disk 12345, in memory "
            "300, same module object. So the session was executing code "
            "nobody had installed, and its own log described a build that "
            "was no longer there."
        ),
        fix=(
            "blender_addon::_stale_library_refusal compares the fingerprint "
            "taken at register() against the library files on disk and "
            "REFUSES the turn when they differ — before a model call is "
            "spent — naming the count and telling the user to restart "
            "Blender (or, in developer mode, to click Reload). It does NOT "
            "silently purge and re-import: an automatic mid-session swap of "
            "the code under a running conversation is the magic-result path, "
            "and developer_mode already owns that behaviour explicitly."
        ),
        guarded_by=(
            "tests/blender/test_addon_registration.py::"
            "test_a_library_that_changed_on_disk_refuses_the_turn, plus the "
            "matching-library, developer-mode and empty-baseline cases. "
            "Proven live: after installing a different build over the "
            "enabled addon, bpy.ops.blended.send_message() cancelled with "
            "'58 library file(s) on disk no longer match'."
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="open-meshes-were-never-normal-checked",
        scope="harness_code",
        failure=(
            "Every open prop shipped with zero normals checking: the "
            "parity-ray flipped-normal test only runs on closed manifold "
            "meshes, and the analyzer recorded 0 flipped triangles for "
            "every open mesh. scp measured the distinction: edge "
            "contiguity passes an island wound inside-out, and decimation "
            "and boolean work create inverted facets on open meshes too "
            "(backpack 0 -> 15/164 facets, body 0 -> 5/749). Recalculating "
            "normals does not fix them — the geometry has folded."
        ),
        cause=(
            "The inverted-facet test asks whether a face agrees with "
            "ITSELF (winding normal against its own stored corner "
            "normals), which needs no closed solid, but the old code "
            "gated every normals check on the closed-manifold branch."
        ),
        fix=(
            "Added facet_disagrees_with_its_normals (pure arithmetic) and "
            "_count_inverted_facets, called UNCONDITIONALLY in "
            "analyze_object; MeshReport.inverted_facet_count and "
            "MeshBudget.allow_inverted_facets gate it. Per-corner normals "
            "match what glTF ships, so the file-level report reads the "
            "same numbers back out of the .glb."
        ),
        guarded_by=(
            "tests/blender/test_flipped_normals.py::"
            "test_open_mesh_inverted_facet_is_counted"
        ),
        recorded_on="2026-08-23",
    ),
    MistakeRecord(
        identifier="the-scene-is-not-the-shipped-file",
        scope="harness_code",
        failure=(
            "Export verification re-imported the .glb into Blender, so "
            "scene counts described geometry that never shipped: scp's "
            "'5k' tier shipped 9,488 triangles, and a file report and a "
            "raw bmesh disagreed 0 vs 6,196 boundary edges because one "
            "welded by position and one counted UV seams."
        ),
        cause=(
            "export_apply=True bakes modifiers, so scene polygon counts "
            "drift from the artifact; the re-import is not the artifact."
        ),
        fix=(
            "Added src/blended/export/glb_report.py (stdlib only): parses "
            "the file's own bytes, counts POSITION-welded topology, "
            "inverted facets from the stored NORMAL accessor, and root "
            "node names. ExportReport.round_trip_failures now also gates "
            "file triangle count vs pre-export, file boundary edges vs "
            "the welded re-import, file inverted facets, root node names, "
            "and file extents under the exporter's axis permutation."
        ),
        guarded_by=(
            "tests/blender/test_glb_file_report.py::"
            "test_file_and_welded_reimport_agree"
        ),
        recorded_on="2026-08-23",
    ),
    MistakeRecord(
        identifier="nearest-vertex-is-not-the-surface",
        scope="harness_code",
        failure=(
            "scp's palm-to-weapon distance read 60 mm against mesh "
            "VERTICES and 6.5 mm against the mesh SURFACE: on box "
            "geometry the nearest vertex is a far corner. Two wrong root "
            "causes were announced off the vertex artifact."
        ),
        cause=(
            "closest_point_on_mesh was measured against vertices; a "
            "nearest-vertex implementation answers 'how far is a corner', "
            "not 'how far is the surface'."
        ),
        fix=(
            "Added src/blended/analyze/pair_checks.py: analyze_pair "
            "measures interpenetration via BVH overlap with the narrow "
            "phase _count_self_intersecting_pairs uses, and separation "
            "via closest_point_on_mesh in the other object's local "
            "space. NoInterpenetrationSpec is scored in "
            "_measure_relations; crate_with_lid now asserts the lid does "
            "not sink into the body."
        ),
        guarded_by=(
            "tests/blender/test_pair_checks.py::"
            "test_separation_is_measured_on_the_surface"
        ),
        recorded_on="2026-08-23",
    ),
    MistakeRecord(
        identifier="a-hole-fill-can-cost-more-than-it-buys",
        scope="harness_code",
        failure=(
            "scp measured hole filling on valkyrie_body and REJECTED it: "
            "every ordering traded open edges for non-manifold edges and "
            "inverted facets — 241 boundary / 0 non-manifold / 5 "
            "inverted became 36 / 18 / 21. An inverted facet is a "
            "wrongly-lit patch visible in normal gameplay; an open "
            "boundary costs only gib caps."
        ),
        cause=(
            "Filling a boundary shared by two shells creates non-manifold "
            "edges; filling a folded boundary creates inverted facets."
        ),
        fix=(
            "cleanup_mesh keeps the fill (props are closed solids) but "
            "copies the mesh before the pass and reverts when "
            "non_manifold_edge_count or inverted_facet_count rises — "
            "CleanupReport.reverted_hole_fills reports the reversal and "
            "the holes stay open, reported as remaining failures."
        ),
        guarded_by=(
            "tests/blender/test_ingest_cleanup.py::"
            "test_a_regressing_fill_is_reverted"
        ),
        recorded_on="2026-08-23",
    ),
    MistakeRecord(
        identifier="a-guessed-visual-threshold-fails-good-assets",
        scope="process",
        failure=(
            "scp's pre-calibration visual-gate guesses (IoU >= 0.980, "
            "RMSE <= 0.030) failed all twelve views of a good asset. A "
            "threshold is a measurement of the harness's own render "
            "noise, not a number to copy."
        ),
        cause=(
            "Thresholds copied from a different harness (a clothed "
            "humanoid at 512x768 EEVEE with film_transparent alpha) do "
            "not transfer to opaque 512x512 Workbench captures."
        ),
        fix=(
            "scripts/calibrate_visual_gate.py measures: golden-vs-itself "
            "control must read exactly IoU 1.0 / RMSE 0.0, clean replays "
            "of the pinned iterations bound the thresholds with margins, "
            "and a Decimate mutation must land outside them or the "
            "calibration refuses to write. The gate refuses to run "
            "without the calibration file."
        ),
        guarded_by=(
            "tests/pure/test_visual_gate_verdict.py::"
            "test_gate_refuses_to_run_uncalibrated"
        ),
        recorded_on="2026-08-23",
    ),
    MistakeRecord(
        identifier="the-developer-lane-could-not-import-jinja2",
        scope="harness_code",
        failure=(
            "Live session 2026-08-23: the first turn died with `No "
            "module named 'jinja2'` the moment the prompt was set "
            "(bpy.context.scene.blended_chat.prompt = ...). The addon "
            "had installed cleanly and registered cleanly; only the "
            "first real render of the system prompt reached the "
            "dependency."
        ),
        cause=(
            "The addon's dev lanes put <repo>/src on sys.path and "
            "nothing else. jinja2 lives ONLY in the repo venv — "
            "Blender's bundled Python has none and no pip, and the "
            "packaged zip's vendored copy sits on a different path than "
            "the repo sources. The driver scripts mask the hole by "
            "prepending venv site-packages, and `make test-blender-app` "
            "runs from the repo where that preamble is exactly what "
            "makes the suite pass — so the lane that actually ships was "
            "never exercised."
        ),
        fix=(
            "_ensure_blended_importable's dev lanes now expose the "
            "repository venv's site-packages via _dev_venv_site_packages "
            "(the same glob the driver scripts use) with the repo "
            "sources kept ahead, and the packaged lane is untouched."
        ),
        guarded_by=(
            "tests/blender/test_addon_registration.py::"
            "test_developer_mode_resolves_jinja2_from_the_repo_venv, "
            "plus the non-developer repository lane in "
            "test_repository_lane_without_developer_mode_also_"
            "resolves_jinja2"
        ),
        recorded_on="2026-08-23",
    ),
    MistakeRecord(
        identifier="extent-rank-tie-break-cannot-canonicalise-a-cube",
        scope="harness_code",
        failure=(
            "The first canonical_orientation draft ranked the three world "
            "extents by POSITION (stable argsort, ties broken by axis "
            "index) and asserted afterwards that the depth axis held rank "
            "1. On an isotropic object — extents (1, 1, 1) — the rule "
            "selected X as the source axis, applied a quarter turn about "
            "Z, and then its own post-condition read rank 0, so "
            "apply_canonical_depth_axis raised RuntimeError on a perfect "
            "cube. Every 3DCodeBench script ends with that call, so it "
            "would have converted a scoring question into ERR_EXEC."
        ),
        cause=(
            "'Middle extent' is a VALUE, not a position. With two equal "
            "extents the middle axis is ambiguous while the middle number "
            "never is, and a position-based rule both picks an arbitrary "
            "axis and then fails to recognise its own output as correct — "
            "the rule was not idempotent, which is the one property a "
            "re-baked epilogue must have."
        ),
        fix=(
            "canonical_depth_axis_rotation_euler_rad now compares against "
            "middle_extent_m (sorted(extents)[1]) and returns identity "
            "whenever depth_axis_holds_middle_extent is already true; the "
            "post-condition asserts that same value invariant with a "
            "relative tolerance instead of a rank equality. Reported rank "
            "is kept as a diagnostic and never asserted on. The GLB audit "
            "in scripts/orientation_policy_sim.py carries the matching "
            "tie tolerance, so a radially symmetric object is not "
            "reported as off-policy (measured: Bottle, Jar, Pillar, "
            "Auger, Lid, Wineglass all tie within 0.2% of max extent)."
        ),
        guarded_by=(
            "tests/pure/test_canonical_orientation.py::"
            "test_a_cube_needs_no_rotation, plus "
            "test_ties_are_deterministic_and_settle_after_one_call and "
            "tests/blender/test_canonical_orientation_op.py::"
            "test_a_second_call_is_a_no_op"
        ),
        recorded_on="2026-09-03",
    ),
    MistakeRecord(
        identifier="a-tool-schema-without-descriptions-is-a-list-of-names",
        scope="harness_code",
        failure=(
            "First live turn on the Claude Code lane: the writer answered "
            "\"I'm unable to create the Crate cube right now\" and made "
            "ZERO tool calls, with a valid schema in the request."
        ),
        cause=(
            "envelope_schema built each oneOf variant from a tool's NAME "
            "and parameters and dropped its description. On the HTTP lanes "
            "descriptions ride the API's own `tools` field, so nothing "
            "else had ever needed them explicitly — this lane has no such "
            "field, so the model was handed seven names it knew nothing "
            "about."
        ),
        fix=(
            "Each variant carries `description` from the same "
            "TOOL_SCHEMAS entry as its arguments schema. Verified live: "
            "the same prompt then called run_python on the first turn."
        ),
        guarded_by=(
            "tests/pure/test_claude_code_lane.py::"
            "test_the_envelope_pins_each_tool_to_its_own_arguments"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="an-agent-cli-reaches-for-its-own-tools",
        scope="harness_code",
        failure=(
            "chat_e2e --only object on claude-code:sonnet: 0 tool calls, "
            "FAIL, and the answer read \"Every tool call I make "
            "(run_python, list_scene, search_ops) is being rejected with "
            "'No such tool available'\"."
        ),
        cause=(
            "The harness system prompt describes the six tools as "
            "callable, which is true on every lane that hands them over "
            "natively. Claude Code is itself an agent harness, so the "
            "model emitted native tool_use blocks — and `--tools \"\"` "
            "correctly refused them. The structured envelope was "
            "available and simply never used."
        ),
        fix=(
            "TOOL_PROTOCOL_NOTE is appended to the system prompt in the "
            "same `if tools:` branch that adds --json-schema, so the "
            "schema and the instruction for using it can never ship "
            "apart. The scenario then passed with one run_python call, "
            "gate PASS, dims 0.600x0.400x0.500."
        ),
        guarded_by=(
            "tests/pure/test_claude_code_lane.py::"
            "test_the_command_disables_every_built_in_capability"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="an-empty-enum-identifier-is-not-an-option",
        scope="harness_code",
        failure=(
            "In a live GUI session, setting the Eye preference to \"no "
            "eye\" raised TypeError: bpy_struct: item.attr = val: enum "
            "\"\" not found in ('kimi-k2.7-code:cloud', "
            "'qwen3.5:397b-cloud', 'kimi-k3:cloud', 'qwen3-vl', "
            "'qwen3.8-27b', 'claude-code:haiku') — the "
            "\"None - writer sees for itself\" row was absent from the "
            "RNA item list entirely."
        ),
        cause=(
            "That row spelled \"off\" as the empty identifier, which "
            "Blender DROPS from an EnumProperty. Registration still "
            "succeeded and the panel still drew, so nothing failed "
            "loudly: the option was simply unreachable, and the eye "
            "could not be switched off from the UI at all. It became "
            "load-bearing with the Claude Code lane, whose recommended "
            "setup is a vision-capable writer looking at its own "
            "renders."
        ),
        fix=(
            "The row carries a real token (_EYE_NONE_IDENTIFIER = "
            "\"none\") and one function, _eye_model_id, turns it back "
            "into the library's empty `vision_model` at the two places "
            "that build a ModelConfig and in the routing hint — so the "
            "token never reaches the library and \"\" never reaches an "
            "enum."
        ),
        guarded_by=(
            "tests/blender/test_addon_registration.py::"
            "test_no_dropdown_row_carries_an_empty_identifier and "
            "test_the_eye_can_be_switched_off_and_that_means_no_eye"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="a-gate-that-cannot-see-the-scene",
        scope="harness_code",
        failure=(
            "A live GUI turn built `Barrel` with 192 faces and a "
            "WoodMaterial; run_python reported GATE PASS, inspect_object "
            "reported GATE PASS, render_views returned a contact sheet — "
            "and bpy.context.scene.objects held only Camera, Cube and "
            "Light. The viewport never changed and the object would have "
            "been absent from any export."
        ),
        cause=(
            "run_chunk located the gated object with "
            "bpy.data.objects.get() and never asked whether it was "
            "LINKED. Every downstream check works on the datablock: the "
            "mesh analyzer reads the mesh, and the capture path links a "
            "copy into a temporary scene of its own to render it — so a "
            "chunk that forgot link_into_scene passed every gate while "
            "changing nothing the user can see. The failure message even "
            "said 'not found in scene' while reading bpy.data."
        ),
        fix=(
            "_gate_capture_export refuses before it analyzes, through "
            "harness.invisibility_failure(): one ordered walk that names "
            "the cause (unlinked / excluded collection / hidden / "
            "hide_render) so the writer can fix it from the tool result. "
            "inspect_object calls the SAME function, so the writer's own "
            "check cannot contradict the gate, and the "
            "missing-datablock message no longer claims to be about the "
            "scene."
        ),
        guarded_by=(
            "tests/blender/test_harness.py::"
            "test_an_unlinked_object_fails_the_gate, "
            "test_a_linked_object_passes_the_same_gate and "
            "test_every_invisibility_cause_is_named_not_just_detected"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="visible_get-covers-four-causes-hide_render-covers-none",
        scope="harness_code",
        failure=(
            "Probing the gate for siblings of the unlinked-object hole "
            "found three more, all reporting GATE PASS: hide_viewport = "
            "True, hide_set(True), and membership of a collection "
            "excluded from the view layer. A fourth, hide_render = True, "
            "passed while halving the harness's own contact sheet "
            "(634280 bytes with the object, 318310 without) — the eye "
            "was reviewing a render the asset was absent from."
        ),
        cause=(
            "The first fix tested exactly one symptom "
            "(name in scene.objects) instead of the property that "
            "matters: can this be seen. Object.visible_get() is False "
            "for all four visibility causes INCLUDING the unlinked one, "
            "so the narrow test was both incomplete and redundant. "
            "hide_render is the exception in the other direction: "
            "visible_get() stays True, so a visibility-only rule would "
            "have missed the one cause that breaks the render the model "
            "is judged by."
        ),
        fix=(
            "invisibility_failure() walks scene membership, view-layer "
            "membership, visible_get() and hide_render in that order, "
            "returning the cause-specific instruction. Both run_chunk "
            "and inspect_object call it."
        ),
        guarded_by=(
            "tests/blender/test_harness.py::"
            "test_every_invisibility_cause_is_named_not_just_detected, "
            "test_an_unrenderable_object_fails_even_though_it_is_visible "
            "and test_inspect_object_agrees_with_the_gate"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="view-layer-membership-lags-the-link",
        scope="harness_code",
        failure=(
            "The first draft of the visibility gate turned 9 green "
            "Blender tests red, accusing every freshly built object of "
            "sitting in an excluded collection. The SAME trap then bit "
            "in the other direction: the transform gate let a "
            "`scale = (1, 1, 0)` chunk through with GATE PASS, because "
            "matrix_world still held the pre-assignment value."
        ),
        cause=(
            "Evaluated scene state lags an assignment. An object linked "
            "by the chunk that just ran appears in "
            "bpy.context.scene.objects immediately but NOT in "
            "bpy.context.view_layer.objects, and a scale assigned by "
            "that chunk is NOT yet in matrix_world, until the depsgraph "
            "catches up. Both probes that designed the rules had called "
            "view_layer.update() by hand, so both rules looked correct "
            "in isolation and read the previous frame in the gate."
        ),
        fix=(
            "One helper, harness._synchronise_view_layer(), called at "
            "the top of BOTH invisibility_failure() and "
            "degenerate_transform_failure(). Rule: any scene-state "
            "assertion made immediately after a chunk runs syncs first "
            "— view-layer membership, matrix_world, dimensions and "
            "visible_get() are all evaluated state."
        ),
        guarded_by=(
            "tests/blender/test_harness.py::"
            "test_a_linked_object_passes_the_same_gate, "
            "test_the_gate_reports_a_broken_transform_through_run_chunk "
            "and tests/blender/test_task_loop.py::"
            "test_task_succeeds_first_round"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="the-object-matrix-is-outside-the-mesh-analyzer",
        scope="harness_code",
        failure=(
            "Four broken transforms all reported GATE PASS with a "
            "perfect mesh report: scale.x = 0 (world extent 0, 1, 1), "
            "scale.x = 1e-9, location.x = NaN (world extent nan, 1, 1), "
            "and scale.x = inf — the last of which makes the glTF "
            "export raise RuntimeError on geometry the gate had just "
            "called clean."
        ),
        cause=(
            "analyze_object measures the EVALUATED mesh (so modifiers "
            "are covered) but in the object's LOCAL space, which puts "
            "the object matrix outside everything it can see. A NaN "
            "transform is the worst case: the mesh measures perfect, "
            "the gate passes, and every world-space number the model "
            "prints back to itself is NaN."
        ),
        fix=(
            "degenerate_transform_failure() refuses non-finite matrix "
            "elements and collapsed axes, testing the SCALE LENGTHS' "
            "anisotropy (min/max < 1e-6) rather than the determinant — "
            "a legitimately tiny object scaled 0.001 uniformly has "
            "determinant 1e-9, so a determinant threshold would have "
            "refused real work. A 10x stretch, a 0.001 uniform scale "
            "and a 0.01-thin panel all still pass."
        ),
        guarded_by=(
            "tests/blender/test_harness.py::"
            "test_a_collapsed_or_non_finite_transform_fails_the_gate and "
            "test_legitimate_scales_are_left_alone"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="the-domain-reports-had-the-same-hole-as-the-gate",
        scope="harness_code",
        failure=(
            "Auditing the rig/weight/animation reports for the gate's "
            "own blind spot found three: rig_report counted a mesh as "
            "BOUND while its Armature modifier was switched off in "
            "viewport or render; weight_report reported non-zero "
            "weights for a vertex group whose name matched no bone (one "
            "typo away, and it deforms nothing); animation_report "
            "counted keyframes on MUTED fcurves and keyframes outside "
            "the scene's frame range as animation."
        ),
        cause=(
            "Each report measured the presence of a thing rather than "
            "its effect: a modifier exists, a weight is non-zero, a "
            "keyframe is stored. Every one of those can be true while "
            "the mesh never deforms and the object never moves — the "
            "same mistake the mesh gate made by measuring the mesh and "
            "not what the user could see."
        ),
        fix=(
            "bound_mesh_names now means DEFORMING (enabled in viewport "
            "and render) with disabled_modifier_mesh_names reported "
            "beside it; weight_report cross-checks group names against "
            "the deforming armature's bones "
            "(groups_without_bones / bones_without_groups, both empty "
            "for an unrigged mesh so ordinary modelling is never "
            "accused); animation_report adds muted_fcurve_count and "
            "keyframes_outside_frame_range_count. chat_e2e asserts all "
            "of them are clean, so the criteria mean what they say."
        ),
        guarded_by=(
            "tests/blender/test_domain_report_blind_spots.py (8 tests, "
            "each pathology beside its control) and "
            "scripts/chat_e2e.py::check_rig / check_weights / "
            "check_animation"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="a-test-that-computed-an-answer-and-asserted-nothing",
        scope="harness_code",
        failure=(
            "test_copy_buttons_address_the_transcript_not_the_visible_"
            "slice built the list of copy-button indices and then "
            "ended. No assert. It passed for any behaviour at all, "
            "including the exact off-by-slice bug it was written to "
            "catch, and it sat green in the suite."
        ),
        cause=(
            "An earlier edit to the file dropped the final assertion "
            "along with the blank line before the next `def`, which is "
            "invisible to every check that matters: the module still "
            "parses, pytest still collects the test, and the test "
            "still passes. Nothing in a green suite distinguishes a "
            "test that verifies something from one that does not."
        ),
        fix=(
            "The assertion is restored with the absolute indices "
            "spelled out ([7, 8, 9, 10] for a 4-message window over an "
            "11-event transcript). The general guard: a range-based "
            "edit near a test boundary must be re-read afterwards, and "
            "any test whose body ends in an assignment is a defect."
        ),
        guarded_by=(
            "tests/blender/test_addon_draw.py::"
            "test_copy_buttons_address_the_transcript_not_the_visible_slice"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="the-panel-woke-the-viewport-forever",
        scope="harness_code",
        failure=(
            "The tool-drain timer called _redraw_sidebars() on every "
            "tick, so every VIEW_3D area in every window was tagged for "
            "redraw 6.7 times a second for the whole session — with no "
            "conversation, no agent running, and nothing on screen "
            "changing."
        ),
        cause=(
            "The redraw was written for the streaming case, where the "
            "panel genuinely has new text several times a second, and "
            "the timer is the only main-thread hook available. Nothing "
            "distinguished 'the transcript moved' from 'the timer "
            "fired', so the expensive case became the only case."
        ),
        fix=(
            "_SessionState.revision counts every change the panel can "
            "see (log(), busy transitions, reset, revert) and the timer "
            "redraws only when it moved. Streaming still repaints at "
            "the timer's cadence; an idle sidebar costs one integer "
            "comparison per tick."
        ),
        guarded_by=(
            "tests/blender/test_addon_registration.py::"
            "test_an_idle_session_does_not_ask_for_a_redraw"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="the-preview-cache-held-the-struct-not-the-icon-id",
        scope="harness_code",
        failure=(
            "Render thumbnails never appeared in the panel. "
            "RenderPreviews.icon_for returned what "
            "`bpy.utils.previews` collection.load() hands back — an "
            "ImagePreview STRUCT — instead of its integer icon_id. "
            "`template_icon(icon_value=<struct>)` raises, draw() "
            "swallows the exception to stay alive, and the picture is "
            "silently absent."
        ),
        cause=(
            "Headless Blender has no GPU context, so every icon id is 0 "
            "there. The test asserted the CACHE (that a second call did "
            "not reload the file) rather than the VALUE, and 0 is what a "
            "correct implementation returns headless too — so the wrong "
            "type passed every assertion the background suite could "
            "make. It took a live GUI session to see it."
        ),
        fix=(
            "icon_for returns int(preview.icon_id); measured 1128 in a "
            "GUI session. The general rule: when a value is degenerate "
            "headless, assert its TYPE headless and its value under "
            "skipif — a cache test proves caching, not correctness."
        ),
        guarded_by=(
            "tests/blender/test_render_previews.py::"
            "test_icon_for_returns_an_integer_id_not_the_preview_struct "
            "(type, background) and "
            "test_icon_for_real_png_returns_nonzero_in_gui (value, GUI)"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="the-sidebar-is-twenty-seven-rows-not-a-page",
        scope="harness_code",
        failure=(
            "Three times in a row the panel's working controls — plan, "
            "renders, prompt box, status — fell below the bottom edge of "
            "the sidebar in a live GUI session. Each fix was based on an "
            "ESTIMATE of how many rows the content cost, and each "
            "estimate was too low: first no cap at all, then a cap of 8 "
            "SOURCE LINES (one paragraph wraps to ten ROWS), then row "
            "reserves that forgot the panel header and the record "
            "panel's own header."
        ),
        cause=(
            "A Blender region cannot be scrolled from code (View2D is "
            "read-only through RNA; 5.2 has no scroll operator), so "
            "anything unbounded drawn above a control puts that control "
            "out of reach — and the region is far smaller than it looks: "
            "561 x 1104 px at ui_scale 2.0 is 27 ROWS, because "
            "UI_UNIT_Y is 20 px BEFORE ui_scale."
        ),
        fix=(
            "The record moved into its own DEFAULT_CLOSED panel "
            "(BLENDED_PT_history) so the working surface cannot grow "
            "with the conversation, and the plan collapses to header + "
            "progress bar once the turn ends. The row-budget half of "
            "this fix — _answer_row_budget(region.height, ui_scale, …) "
            "subtracting the cards above and the controls below — is "
            "GONE as of 2026-09-06: the replies left the sidebar "
            "entirely for a GPU overlay in the viewport, so there is no "
            "unbounded content left to budget. Final measurement: the "
            "whole 561 x 1104 px sidebar is 0 differing pixels between "
            "a one-line reply and a sixty-line reply, while the overlay "
            "column differs by 577,780 px (so the diff was sensitive)."
        ),
        guarded_by=(
            "tests/blender/test_addon_draw.py::"
            "test_the_working_surface_holds_the_prompt_and_no_reply_text "
            "(no reply text on the pinned surface at all) and "
            "tests/blender/test_chat_panel_heuristics.py::"
            "test_the_working_surface_does_not_grow_with_the_turn, "
            "::test_a_finished_plan_gives_its_rows_back_to_the_answer"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="a-hot-reload-dropped-the-turns-plan",
        scope="harness_code",
        failure=(
            "Editing the library mid-session made the plan card vanish "
            "from the panel while the transcript survived: the plan and "
            "the right to revert the turn were gone."
        ),
        cause=(
            "_hot_reload transplants a hand-listed set of _SessionState "
            "fields into the fresh module. New state added to the panel "
            "(plan, can_revert, undo_guard) was not on that list, so "
            "every dev-mode reload silently reset it. The list is a "
            "duplicate of the state's own definition — the kind that "
            "rots the moment the state grows."
        ),
        fix=(
            "plan, can_revert and undo_guard are carried across the "
            "reload with the transcript. Any field added to "
            "_SessionState that the panel reads must be added there too."
        ),
        guarded_by=(
            "tests/blender/test_addon_registration.py::"
            "test_hot_reload_swaps_the_loaded_module_and_keeps_the_session"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="a-while-loop-around-an-operator-froze-blender",
        scope="harness_code",
        failure=(
            "Clicking the workspace button hung Blender completely — no "
            "traceback, no log line after 'Workspace blended ready', and "
            "the main thread stopped servicing timers, so the whole "
            "session had to be killed. The workspace layout builder "
            "collapsed areas with `while len(screen.areas) > 1: "
            "bpy.ops.screen.area_join(...)`."
        ),
        cause=(
            "`area_join` can return without joining (it declines "
            "geometry it cannot merge), and the loop's exit condition "
            "depended on the operator making progress. An operator that "
            "no-ops is not an error, so nothing raised — the loop simply "
            "never ended, on the thread that draws the UI."
        ),
        fix=(
            "The layout now splits the LARGEST area exactly once and "
            "never joins: one operator call, no loop, and the user's "
            "other editors survive (a better outcome anyway, since the "
            "workspace is a copy of the layout they were using). The "
            "general rule: never write a `while` whose exit depends on a "
            "bpy operator making progress — bound the attempts and "
            "report the failure."
        ),
        guarded_by=(
            "src/blended/ui/workspace.py::arrange_workspace has no loop "
            "and returns False when the split refuses; "
            "tests/blender/test_workspace.py asserts the background "
            "refusal and idempotence"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="an-area-was-chosen-by-position-not-identity",
        scope="harness_code",
        failure=(
            "The blended workspace built a 91-pixel Image Editor and "
            "left a stray second 3D viewport behind. `area_split` had "
            "worked; the code then picked which area to retype by "
            "POSITION — 'the lowest area sharing this x' — and the "
            "lowest area in that column was the source layout's own "
            "91 px timeline strip, not the half the split had just "
            "created."
        ),
        cause=(
            "A screen column can already hold areas the caller knows "
            "nothing about, so geometry does not identify the operator's "
            "product. Nothing failed loudly: every type assignment "
            "succeeded, `_has_chat_layout` saw a VIEW_3D and an "
            "IMAGE_EDITOR, and the function returned True on a layout "
            "that was useless for looking at a render."
        ),
        fix=(
            "Diff `{area.as_pointer() for area in screen.areas}` across "
            "the split to find the CREATED area, and re-fetch the "
            "survivor by its own pointer (the operator rebuilds the area "
            "list). Only those two are retyped. Verified by geometry, "
            "not by eye: VIEW_3D 2096x722 above IMAGE_EDITOR 2096x479 in "
            "the same column, one viewport, the user's other editors "
            "untouched."
        ),
        guarded_by=(
            "src/blended/ui/workspace.py::arrange_workspace (pointer "
            "diff + `return False` when the split creates nothing); "
            "tests/blender/test_workspace.py asserts idempotence and the "
            "background refusal"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="an-experiment-displaced-the-pins-own-evidence",
        scope="process",
        failure=(
            "test_the_v10_cycle_is_one_converged_cycle went red with "
            "'the recorded v10 cycle (iterations 47-51) must count as "
            "converged: assert 0 >= 1' — without anyone touching those "
            "records, the convergence rule, or the prompt. Five runs "
            "qualifying a new WRITER had been appended to "
            "_evaluate/iterations.jsonl."
        ),
        cause=(
            "`converged_suite_cycles` counts TRAILING cycles, walking "
            "iterations downwards and taking the newest record per "
            "brief. Appending a newer sweep therefore makes the newest "
            "cycle the sweep, and the pin's own evidence is no longer "
            "trailing. The sweep was not a convergence cycle at all: it "
            "was a lane qualification against goldens minted from a "
            "DIFFERENT writer, so its examiner verdicts carried "
            "deviations by construction and the count fell to zero."
        ),
        fix=(
            "A lane qualification gets its own artifact: "
            "_evaluate/writer_qualification_iterations.jsonl (and the "
            "matching verdicts file), leaving the protocol's log to the "
            "protocol. The general rule, already learned once for the "
            "3DCodeBench runs: never write an experiment into a "
            "canonical log that a rule reads positionally — appending "
            "is not harmless when 'newest' is part of the meaning."
        ),
        guarded_by=(
            "tests/pure/test_convergence_rule.py::"
            "test_the_v10_cycle_is_one_converged_cycle (goes red the "
            "moment a foreign cycle is appended); "
            "tests/pure/test_prompt_templates.py::"
            "test_the_shipped_configuration_is_the_converged_configuration "
            "reads the qualification artifact instead"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="a-vision-read-inverted-a-profile",
        scope="process",
        failure=(
            "A verification pass nearly reported a false defect. The "
            "writer described its own render as 'narrower flat rims at "
            "top and bottom, bulging out to its widest point at "
            "mid-height — the classic barrel belly'. An independent "
            "vision read of the SAME contact sheet said the opposite: "
            "'the mid-height is the NARROWEST point ... the inverse of "
            "a barrel (hourglass/spool profile)', with specific "
            "supporting evidence ('horizontal crease where the "
            "silhouette is narrowest'). Measuring the mesh settled it: "
            "max radius 0.1500 at both rims and 0.1900 across "
            "z 0.15-0.25, i.e. widest at mid-height. The writer was "
            "right and the vision read was wrong."
        ),
        cause=(
            "A single vision read of a shaded render is a MEASUREMENT "
            "with an error rate, not ground truth. The shading crease "
            "along the widest ring of a lathed solid reads as a waist "
            "when the lighting puts a dark band there — and the reading "
            "arrived with confident, specific-sounding evidence for the "
            "inverted profile, which is exactly what makes it "
            "dangerous."
        ),
        fix=(
            "Never escalate a visual discrepancy without the "
            "deterministic measurement, when geometry can answer: here, "
            "eight radius bands from the mesh vertices took one command "
            "and were unambiguous. This is the harness's founding order "
            "(deterministic gate first, visual critique second; tool "
            "feedback outranks model feedback, "
            "10.48550/arXiv.2409.02977) applied to the REVIEWER rather "
            "than to the writer — the reviewer's eye is the same kind "
            "of instrument as the examiner's."
        ),
        guarded_by=(
            "src/blended/evaluate/examiner.py thresholds and "
            "_evaluate/eye_calibration.json bound how far ANY eye is "
            "trusted (sensitivity 0.80, control specificity 1.00); "
            "tests/pure/test_examiner.py::"
            "test_the_shipped_eye_holds_the_licence_in_the_repository"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="the-pin-loop-could-not-advance-a-revision",
        scope="harness_code",
        failure=(
            "Every door to pinning a candidate revision refused, in a "
            "cycle: `converge_auto --revision 11` refused because "
            "_evaluate/golden/<brief>_v11 did not exist; "
            "`make pin-golden-views REVISION=11` refused with 'iteration "
            "51 ran v10:b6627b38f4c1, not v11:d90e5ee9e59d — refusing to "
            "pin the wrong text'; and `make pin` refuses a proposal "
            "'composed by hand'. The loop could not advance past the "
            "revision it had already pinned."
        ),
        cause=(
            "pin_golden_views sourced its runs from "
            "prompt_versions.CONVERGENCE_RUNS — the runs of the "
            "CURRENTLY PINNED revision, which by definition executed the "
            "old text — and then asserted the recorded identity equals "
            "the revision being stamped. Those two rules can only both "
            "hold for the revision already pinned. CONVERGENCE_RUNS is "
            "rewritten by `make pin`, which needs the proposal, which "
            "needs the reference: a genuine deadlock, introduced by "
            "tightening the identity guard (correct) while leaving the "
            "run SOURCE as the previous pin (wrong)."
        ),
        fix=(
            "The source is now the log, scoped to the identity being "
            "stamped: `clean_cycle_for_identity` takes the newest run "
            "per brief that EXECUTED that revision with all three "
            "deterministic gates green, and pin_golden_views refuses "
            "loudly, naming the briefs, when the suite has not been run "
            "at that revision yet. The identity guard is kept — it was "
            "always the right check, just applied to the wrong "
            "candidates. Bootstrap order for a new revision: run the "
            "suite at it, mint from those runs, then converge."
        ),
        guarded_by=(
            "tests/pure/test_convergence_rule.py::"
            "test_only_runs_that_executed_a_revision_may_mint_its_reference"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="every-number-was-right-and-the-lid-was-invisible",
        scope="brief",
        failure=(
            "crate_with_lid passed every deterministic check — CrateLid "
            "0.5000 x 0.5000 x 0.0600 at base_z 0.4000, resting on the "
            "body, centred, not sunk — and the render showed ONE "
            "CONTINUOUS BOX. No lid, no seam, no ledge. The examiner "
            "reported `missing_feature` and no measurement could, which "
            "halted the v11 convergence attempt as harness_critique."
        ),
        cause=(
            "The brief specified a lid with the body's EXACT footprint "
            "resting flush on the rim, so nothing about the geometry "
            "distinguishes the two parts from outside. What made the "
            "signed-off reference readable was never geometry but "
            "COLOUR: body (0.6, 0.4, 0.2) against lid (0.5, 0.3, 0.15), "
            "a distance of 0.15. The run that vanished gave both parts "
            "(0.45, 0.30, 0.15) — distance 0 — which no check forbade."
        ),
        fix=(
            "DistinctMaterialSpec: two named parts must differ in base "
            "colour by at least CRATE_LID_MINIMUM_COLOUR_DISTANCE_RGB "
            "(0.10, set below the reference's measured 0.15 so the "
            "artifact that earned the pin still conforms), and the brief "
            "text now says so. Deliberately contrast, NOT a required "
            "hue or luminance: pinning those would bake one writer's "
            "taste into the acceptance spec. Verified across two later "
            "cycles — `missing_feature` never returned."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_a_lid_the_same_colour_as_the_body_fails_even_though_it_"
            "measures_right (and ::test_a_contrasting_lid_passes, which "
            "keeps the probe from condemning the reference)"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="the-examiners-licence-did-not-cover-how-it-is-used",
        scope="harness_code",
        failure=(
            "Three convergence cycles on one unchanged configuration "
            "(15 runs, 14 of them green on every deterministic gate) "
            "never produced a clean examiner sweep, and the deviations "
            "MOVED: uv_crate came back `material_missing` in one cycle "
            "and clean in the next, ribbed_column the reverse, "
            "planter_box clean then flagged. A pin needs 5/5 clean at "
            "once, so the loop cannot close — and re-rolling cycles "
            "until one comes up clean would be selecting on the "
            "instrument's noise."
        ),
        cause=(
            "calibrate_examiner builds its five clean CONTROLS by "
            "replaying ONE recorded run and comparing it against the "
            "reference minted from THAT SAME run — pixel-identical "
            "inputs. Control specificity 1.00 therefore measures "
            "'does it stay quiet when shown the same image twice', "
            "while the loop uses it to compare a FRESH run against an "
            "exemplar. That regime was never measured, and the "
            "false-alarm rate in it is plainly not zero: planter_box "
            "iteration 62 was flagged against planter_box_v11, an "
            "exemplar minted from iteration 57 — same lane, same "
            "prompt, same brief, both gate-clean."
        ),
        fix=(
            "NOT YET FIXED, and deliberately not worked around. The "
            "measurement to make is cross-run control specificity: "
            "clean run B against an exemplar minted from clean run A. "
            "If that number is below REQUIRED_CONTROL_SPECIFICITY the "
            "examiner may not judge unattended at all, which is a "
            "decision about the loop, not a tuning knob. Until it is "
            "measured, treat a machine verdict on a fresh run as "
            "advisory and let the deterministic gates carry the "
            "qualification (which is the existing order: tool feedback "
            "outranks model feedback, 10.48550/arXiv.2409.02977)."
        ),
        guarded_by=(
            "_evaluate/verdicts.jsonl iterations 52-65 record the "
            "hopping deviations; scripts/calibrate_examiner.py is where "
            "the cross-run control class belongs"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="sixty-nine-iterations-with-no-idea-what-they-cost",
        scope="harness_code",
        failure=(
            "Asked whether the harness made good use of prompt caching, "
            "the answer was that NOBODY HAD EVER CHECKED. 69 logged "
            "iterations, three convergence cycles in one day, and not "
            "one token of accounting anywhere: no `usage` parsing on "
            "any lane, no cost in the iteration record, and the "
            "`rate_limit_event` frame the Claude Code transport already "
            "parsed was thrown away. Measured once accounting existed: "
            "ONE brief costs $1.4182 and 738,839 input tokens across 26 "
            "API calls, so a 5-brief cycle is ~$7 and 3.7M tokens."
        ),
        cause=(
            "Every gate in this harness measures the ARTIFACT. Nothing "
            "measured the harness itself, so the one quantity that "
            "scales with every experiment stayed invisible — and a "
            "harness whose whole thesis is 'measure, do not assume' was "
            "assuming. Two specifics only measurement could reveal: one "
            "harness turn is 2-3 API calls (the CLI runs the model again "
            "to conform to `--json-schema`), and 85% of the effective "
            "input cost is cache WRITES at 1.25x rather than reads at "
            "0.1x."
        ),
        fix=(
            "`TurnCost` + `parse_turn_cost` on the Claude Code lane, "
            "`_turn_cost_from_body` for the OpenAI/Ollama lanes, "
            "`OllamaClient.spent` accumulating across a run with the "
            "eye's client folded in, and six cost fields on "
            "`IterationRecord`. Also measured and worth keeping: prompt "
            "caching DOES survive our stateless one-process-per-turn "
            "design (12,241 tok cost $0.0507 cold, $0.0043 warm — "
            "11.8x) because the system prompt is byte-stable and "
            "history is append-only. Those two properties were "
            "accidental and are now tested."
        ),
        guarded_by=(
            "tests/pure/test_claude_code_lane.py::"
            "test_a_growing_transcript_keeps_the_previous_turn_as_its_"
            "prefix, ::test_the_system_prompt_is_byte_stable_across_"
            "builds, ::test_one_harness_turn_reports_every_api_call_it_"
            "made; docs/2026-09-06-token-budget-audit.md"
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="the-examiner-was-asked-the-wrong-question",
        scope="harness_code",
        failure=(
            "Three convergence cycles halted on examiner deviations, "
            "and the pending question was whether the examiner was "
            "noisy. Measured 2026-09-06 with a new cross-run control "
            "class: specificity 0.50 (2 of 4 gate-clean runs flagged), "
            "against a required 1.00. At a per-brief false-alarm rate "
            "of 0.5 a five-brief cycle comes up clean with probability "
            "0.5^5 = 3%, so re-rolling cycles would have cost ~32 "
            "cycles and ~$224 to reach a pin BY LUCK."
        ),
        cause=(
            "The deviations are not noise — they are TRUE. Measured "
            "from the meshes: planter_box's exemplar (iteration 57) is "
            "base colour (0.45, 0.28, 0.15) and the flagged candidate "
            "(62) is (0.35, 0.22, 0.12), a distance of 0.120, with "
            "IDENTICAL dimensions; three_leg_stool 59 vs 64 share a "
            "bbox but differ in internal proportion. The loop asks "
            "'does this match the exemplar?' and reads the answer as "
            "'does this satisfy the brief?'. Everything the brief "
            "leaves free differs between runs BY CONSTRUCTION, so an "
            "exemplar-matching question manufactures deviations at a "
            "rate set by how much the brief leaves unspecified."
        ),
        fix=(
            "PENDING a human decision (plan Phase B). What is already "
            "settled: my own first draft — count a deviation only if "
            "it reproduces across independent examinations — is "
            "REFUTED by this measurement, because a systematic true "
            "difference reproduces every time and the rule would have "
            "doubled examiner calls for nothing. The recommended "
            "branch is to stop asking the eye about properties a "
            "deterministic gate measures (`wrong_proportion` -> form "
            "gate, `material_missing` -> material gate) while keeping "
            "the reference paired, since pairing is worth +0.32 F1 "
            "(10.48550/arXiv.2604.11082) and tool feedback outranks "
            "model feedback (10.48550/arXiv.2409.02977)."
        ),
        guarded_by=(
            "make calibrate-eye ARGS=\"--cross-run-only\"; "
            "tests/pure/test_examiner.py::"
            "test_a_licence_measured_on_identical_images_does_not_"
            "cover_a_fresh_run; docs/2026-09-06-token-budget-plan.md"
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="the-workspace-pushed-its-own-composer-off-screen",
        scope="harness_code",
        failure=(
            "A live walkthrough of the shipped `blended` workspace, run "
            "for the user's sign-off, found the prompt box, the Send "
            "button and the Revert control BELOW the visible sidebar "
            "after one finished turn. Fourth time the composer has been "
            "lost, and the first time the harness's own workspace "
            "caused it."
        ),
        cause=(
            "Two faults compounding. (1) `arrange_workspace` split the "
            "viewport HORIZONTALLY to give the Image Editor a wide "
            "short home — and the chat sidebar is a REGION OF THAT "
            "VIEWPORT, so the split halved it: 561x618 px, 15 rows at "
            "ui_scale 2.0, measured live. (2) `_answer_row_budget` "
            "shrank only the ANSWER and drew the cards unconditionally, "
            "so the surface still wanted 12 composer + 6 renders + 2 "
            "plan + 3 answer = 23 rows in a 15-row region. The budget "
            "adapted to the region and still overflowed, because what "
            "it adapted was the one part that was already at its floor."
        ),
        fix=(
            "Split VERTICALLY (`IMAGE_EDITOR_WIDTH_FRACTION`), which "
            "leaves the viewport full height and the sidebar its "
            "measured 561x1104 px / 27 rows — and puts the enlarged "
            "render beside the thumbnails that open it. Assign the two "
            "products by WIDTH, not by `area.x`: read straight after "
            "the operator, x returned them in the opposite order to "
            "their final geometry. Two more ordering facts: "
            "assigning `area.type` swaps the area's active space, so a "
            "`show_region_ui` written right after the split lands on "
            "the replaced space (sidebar came back 1x1) — it is set in "
            "`activate_chat_tab`, which is already deferred a frame; "
            "and the tab needs one frame MORE than the layout, so the "
            "operator's timer re-arms until `active_panel_category` "
            "takes, bounded by `_WORKSPACE_TAB_ATTEMPTS`. The row "
            "budget this record originally added was later DELETED: "
            "see `the-composer-moved-because-it-was-drawn-last`, which "
            "replaced it with a draw-order guarantee."
        ),
        guarded_by=(
            "tests/blender/test_chat_panel_heuristics.py::"
            "test_the_composer_is_the_first_thing_the_surface_draws and "
            "tests/blender/test_chat_panel_heuristics.py::workspace "
            "coverage in tests/blender/test_workspace.py"
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="the-composer-moved-because-it-was-drawn-last",
        scope="harness_code",
        failure=(
            "The user reported it in one sentence: \"when you send a "
            "message, it moves the input box down every response "
            "message, so it forces the user to have to scroll down to "
            "type again\". Measured on the shipped panel: the prompt "
            "box was the LAST thing `BLENDED_PT_chat.draw` emitted, "
            "after the render card, the plan card and the reply, so "
            "its screen position was a function of the reply's length "
            "— a 1-line reply and a 22-line reply put it ~21 rows "
            "apart. Four live sessions had already lost the composer "
            "off the bottom for the same reason."
        ),
        cause=(
            "Every previous fix BUDGETED the composer instead of "
            "placing it: reserve 12 rows, shrink the answer, make the "
            "cards yield. A budget can only decide whether a control "
            "FITS; it cannot make it STAY, because a widget drawn "
            "after a variable-height widget has a variable position by "
            "construction. Three rounds of arithmetic defended the "
            "wrong property, and each round's test pinned the wrong "
            "property too — test_the_working_surface_holds_the_answer_"
            "and_the_prompt_but_not_the_record actually ASSERTED that "
            "the answer reads above the composer."
        ),
        fix=(
            "Draw the composer FIRST, unconditionally, then the "
            "session controls, then the newest reply, then the cards, "
            "then older replies. Replies stack ASCENDING: a new one "
            "goes on top and its predecessors recede downward, off the "
            "bottom, the one direction growth costs nothing. Position "
            "is now a property of draw ORDER, so `_SurfaceBudget`, "
            "`_pinned_surface_budget` and the four row constants were "
            "DELETED rather than corrected — there is nothing left to "
            "compute wrongly. The newest reply sits ABOVE the render "
            "and plan cards for a second measured reason: with the "
            "cards above it, a 22-line reply was clipped by the bottom "
            "of the 1104 px sidebar, and the cards lose nothing (the "
            "same renders are open in the Image Editor beside the "
            "chat, every plan step is in the record). Proof: two live "
            "turns, replies of 1 and 22 lines, screenshots diffed — "
            "the composer strip is 0 differing pixels of 94,350, the "
            "only change being a 6 px scrollbar stripe at x 1402-1407 "
            "that spans 1101 of 1104 rows; a control band lower down "
            "differed by 13.2 percent, so the diff was sensitive."
        ),
        guarded_by=(
            "tests/blender/test_chat_panel_heuristics.py::"
            "test_the_composer_is_the_first_thing_the_surface_draws "
            "(the prompt box is at draw index 0 across empty, short, "
            "long, and answer-plus-plan-plus-renders states), "
            "::test_the_working_surface_does_not_grow_with_the_turn, "
            "::test_the_record_keeps_every_message, and "
            "tests/blender/test_addon_draw.py::"
            "test_the_working_surface_holds_the_prompt_and_no_reply_text"
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="ui-scale-is-zero-when-preferences-are-not-ready",
        scope="harness_code",
        failure=(
            "The GPU transcript's column came out 56 px wide instead of "
            "640 and the wheel hit test answered False for a point the "
            "column visibly contained: "
            "bpy.context.preferences.system.ui_scale reads 0.0 in "
            "--background (measured 2026-09-06; pixel_size reads 1.0 in "
            "the same call)."
        ),
        cause=(
            "TranscriptStyle.scaled clamped with max(ui_scale, 0.1), "
            "copying the addon's own _characters_per_line idiom. That "
            "clamp treats 0.0 as a very small SCALE rather than as "
            "'not told yet', so every _px field was multiplied by a "
            "tenth: a 320 px minimum column became 32 px."
        ),
        fix=(
            "A non-positive ui_scale is read as DEFAULT_UI_SCALE = 1.0. "
            "The clamp constant was deleted rather than lowered — there "
            "is no legitimate sub-unity scale to defend, and Blender's "
            "own preference floor is 0.5."
        ),
        guarded_by=(
            "tests/pure/test_transcript_layout.py::"
            "test_an_uninitialised_ui_scale_is_read_as_one"
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-purged-module-cannot-remove-its-own-draw-handler",
        scope="harness_code",
        failure=(
            "After one hot reload, sys.modules held a DIFFERENT "
            "blended.ui.transcript_overlay object than the earlier "
            "import, with the live RNA_HANDLE capsule in the stale one "
            "and _HANDLER None in the fresh one (measured 2026-09-06). "
            "Every reload would therefore have added a second draw "
            "handler, painting the pre-reload session's state from the "
            "pre-reload code, forever."
        ),
        cause=(
            "devreload.purge_library_modules() drops every blended.* "
            "entry so the next import reads disk. The draw handler's "
            "handle lived in the module's globals, which is exactly "
            "what the purge throws away — so register_overlay's "
            "'remove the previous handler first' rule could never see "
            "a handler installed before the purge."
        ),
        fix=(
            "The addon owns the lifetime, not the library: "
            "_remove_overlay() runs immediately before BOTH purge "
            "sites (_reload_library and _hot_reload_unlocked) while the "
            "owning module is still importable, and _install_overlay() "
            "runs after the re-import — including on the import-failure "
            "path, so a failed reload reports itself in the panel's "
            "alert row instead of silently leaving the viewport blank."
        ),
        guarded_by=(
            "tests/blender/test_transcript_overlay.py::"
            "test_a_library_reload_never_orphans_the_overlay "
            "(asserts the pre-reload module's _HANDLER is None AND the "
            "post-reload module's is not)"
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="an-absolute-colour-cannot-contrast-with-a-themed-one",
        scope="harness_code",
        failure=(
            "The code band behind a fenced block was invisible in the "
            "live screenshot. Blender's own dark theme reported "
            "wcol_box.inner at 0.1137 and the band was pinned at 0.11 "
            "— a 0.004 step (measured 2026-09-06, confirmed by a vision "
            "read of the capture: 'no distinctly darker band')."
        ),
        cause=(
            "Half the palette was theme-derived and half was pinned. A "
            "pinned colour can be checked against the OTHER pinned "
            "colours at authoring time, and against nothing at all once "
            "a theme moves the value it was supposed to contrast with."
        ),
        fix=(
            "shifted_for_contrast() derives the band from the agent "
            "bubble by CODE_BAND_CONTRAST = 0.10, darkening by default "
            "and lightening only when there is no room to darken, so a "
            "light theme is not a second code path. The default "
            "CODE_BAND_RGBA is now computed from AGENT_BUBBLE_RGBA "
            "through the same function — one source of truth."
        ),
        guarded_by=(
            "tests/blender/test_transcript_overlay.py::"
            "test_the_code_band_contrasts_with_the_themed_bubble "
            "(against the REAL theme, because that is the value that "
            "was wrong) and tests/pure/test_transcript_layout.py::"
            "test_the_code_band_always_contrasts_with_the_bubble"
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-stream-capped-by-lines-loses-its-own-cursor",
        scope="harness_code",
        failure=(
            "A 31-row streaming reply in a 28-row column rendered rows "
            "0-27 and put the block cursor below the fold — the one "
            "thing a stream exists to show was the one thing off-screen "
            "(measured by screenshot, 2026-09-06; bubble height 1165 px "
            "in a 1144 px column, bottom edge at y=-21)."
        ),
        cause=(
            "prefer_tail was implemented as a TRUNCATION rule only: it "
            "chose which end to keep once a body exceeded "
            "maximum_lines_newest (40). Below that budget nothing was "
            "capped at all, so the bubble was free to grow taller than "
            "the column while its top stayed pinned to the column's "
            "top edge. The replaced native panel had applied "
            "_tail_lines unconditionally, so this was a regression the "
            "line budget hid."
        ),
        fix=(
            "_tail_row_budget(column, style) caps a tail-kept message "
            "by what the COLUMN can show — min(line budget, rows that "
            "fit) — holding TRUNCATION_NOTE_ROWS = 1 back because the "
            "note is itself a row (forgetting it overflowed by exactly "
            "one line). The note also moved ABOVE a tail-kept message, "
            "since a note at the bottom of a stream points down at "
            "rows that are actually above it. A FINISHED reply is "
            "deliberately not capped this way: it keeps its full line "
            "budget and is reached by scrolling, so nothing the model "
            "said is dropped at a small window size."
        ),
        guarded_by=(
            "tests/pure/test_transcript_layout.py::"
            "test_a_streaming_reply_is_capped_to_what_the_column_can_show "
            "(the cursor row is last AND the bubble fits the column), "
            "::test_a_finished_reply_is_not_capped_by_the_column, and "
            "::test_prefer_tail_keeps_the_last_lines"
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-screenshot-lags-the-state-that-produced-it",
        scope="process",
        failure=(
            "Three GUI verification rounds read the WRONG frame: a "
            "screenshot taken in the same probe command that mutated "
            "_STATE showed the PREVIOUS command's transcript, and a "
            "vision read of it reported a missing code band that the "
            "in-session layout dump proved was present."
        ),
        cause=(
            "bpy.ops.screen.screenshot captures the swap chain, and one "
            "bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP') pass inside "
            "the mutating command is not enough to land the new frame "
            "in the buffer that gets read."
        ),
        fix=(
            "Capture TWICE in the command — redraw_timer + screenshot, "
            "then redraw_timer + screenshot to the same path — and keep "
            "the second. Always cross-check a vision read against an "
            "in-session dump of the laid-out runs; the numbers are "
            "ground truth and the picture is the confirmation, never "
            "the other way round."
        ),
        guarded_by=(
            "No test can guard a screenshot harness, so the guard is "
            "procedural and pinned here: every GUI verification in this "
            "repository double-captures and asserts against an "
            "in-session numeric dump (the layout dump that caught this "
            "is layout_transcript(...).texts, printed through "
            "outputs/gui_cmd.py)."
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="writing-the-prompt-property-sends-a-real-turn",
        scope="process",
        failure=(
            "A GUI check of the new reference-photo row set "
            "scene.blended_chat.reference_image and then .prompt from "
            "Python to stage a screenshot. The screenshot came back "
            "with BOTH fields already empty, the operator the script "
            "then called returned CANCELLED, and the stub session had "
            "recorded nothing — because a turn had already run against "
            "the configured writer and consumed the photo."
        ),
        cause=(
            "`prompt` carries update=_on_prompt_confirmed, which is how "
            "'Enter sends' reaches out of a Blender text field (a "
            "focused field swallows keystrokes, so no keymap entry can "
            "see them). An RNA write from Python is indistinguishable "
            "from a user confirming the field, so it queued "
            "bpy.ops.blended.send_message() on a 0 s timer — and "
            "_STATE.session was still None at that moment, so the "
            "operator built a REAL session from preferences."
        ),
        fix=(
            "Install the stub session BEFORE writing any chat property, "
            "and let the auto-send fire THROUGH it: the check then "
            "exercises the real Enter-sends path instead of a "
            "hand-called operator. Code that must fill the field "
            "without sending sets _STATE.suppress_prompt_send first, "
            "which is what prompt-history recall already does."
        ),
        guarded_by=(
            "Partly procedural, and deliberately so: the auto-send "
            "cannot fire headlessly (_on_prompt_confirmed returns early "
            "when context.preferences.addons[__name__] raises KeyError, "
            "which is every test that loads the addon as a plain "
            "module), so no headless test can catch a GUI script doing "
            "this. The executable part is that the surface is now "
            "asserted WITHOUT writing `prompt` at all — "
            "tests/blender/test_chat_panel_heuristics.py::"
            "test_the_photo_picker_is_one_fixed_height_row_under_the_"
            "composer and ::test_a_reference_photo_is_drawn_as_its_own_"
            "picture_in_the_record set reference_image, show_details "
            "and the transcript only. Any future GUI probe stubs "
            "_STATE.session before touching a chat property."
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="vertex-penetration-is-not-surface-penetration",
        scope="harness_code",
        failure=(
            "scp measured 28-vertex shoulder straps at 0 deep pokes and "
            "1.6 mm max depth — green — while triangle-vs-triangle "
            "counted 1,200 pairs with their centroid inside the "
            "shoulder. Palm-to-weapon read 60 mm against vertices "
            "and 6.5 mm against the surface. The gap widens as "
            "geometry gets coarser."
        ),

        cause=(
            "A vertex-penetration probe samples the query object's "
            "vertices against the target's closest surface point. "
            "When the query mesh is sparse (28 vertices on a strap), "
            "no vertex falls inside the target, so the probe reads "
            "zero penetration even though the surfaces fully "
            "intersect. The triangle-vs-triangle broad phase sees "
            "the real overlap but is gated behind an AABB depth "
            "threshold (CONTACT_DEPTH_TOLERANCE_M, 2 mm) that a "
            "shallow overlap never reaches, so it reports zero too."
        ),
        fix=(
            "PairReport reports aabb_penetration_depth_m (the "
            "world-AABB minimum translation depth) alongside "
            "intersecting_face_pair_count. NoInterpenetrationSpec "
            "gates on maximum_aabb_penetration_depth_m, and "
            "evaluate.acceptance compares it — so a caller sees the "
            "shallow overlap that the vertex probe misses and the "
            "face-pair count gates. The surface-distance probe "
            "remains for separation, not penetration."
        ),
        guarded_by="blended.evaluate.acceptance (NoInterpenetrationSpec.maximum_aabb_penetration_depth_m) and tests/blender/test_pair_checks.py",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-separation-measure-must-be-symmetric",
        scope="harness_code",
        failure=(
            "scp measured analyze_pair sampling only the first "
            "argument's vertices as query points, so the same pair "
            "measured differently depending on argument order. On the "
            "local fixture (24-segment cylinder vs 8-vertex cube, "
            "overlapping) the one-directional readings were "
            "0.0224 m one way and 0.3274 m the other — a 14.6x "
            "spread on the same pair."
        ),
        cause=(
            "When the two meshes differ in vertex density, the "
            "sparse object's vertices miss the close approach that "
            "the dense object's vertices find. Sampling only one "
            "direction picks whichever density the argument order "
            "happened to give, so the measure is not a function of "
            "the pair but of the call."
        ),
        fix=(
            "analyze_pair now samples BOTH objects' vertices via "
            "_sampled_minimum_distance_m (the extracted helper) and "
            "reports the minimum of the two directional readings. "
            "It also reports aabb_penetration_depth_m, the "
            "world-AABB minimum translation depth that gates the "
            "face-pair count."
        ),
        guarded_by="tests/blender/test_pair_checks.py::test_separation_does_not_depend_on_argument_order",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-gate-sharing-a-derivation-cannot-fail",
        scope="process",
        failure=(
            "scp measured read_hand_frame's palm_out at ~150 degrees "
            "from the real palm normal; every grip gate measured "
            "against that same vector and all passed (1.8 mm, "
            "0.0 mm, 'palm faces up') while a render showed the "
            "weapon gripped from the wrong side. The same pattern "
            "recurred in this repo: every shipped Provenance passed "
            "value=<the constant itself>, so validate_briefs read the "
            "constant back through the Provenance and compared it to "
            "itself — a tautology that passed until the values became "
            "literals and a constant edit reddened it ('claims value "
            "0.32, constant holds 0.36')."
        ),
        cause=(
            "The gate and the pose reader shared the same "
            "derivation: palm_out was computed once and then every "
            "check compared against it. A derivation that is wrong "
            "in the same way as the thing it validates produces "
            "self-consistent green readings on a wrong result. "
            "Defining the 'must not move' set by reading it off the "
            "artefact under test (zero weight on a bone) was "
            "vacuous — 200 deliberately bled vertices produced "
            "zero violations."
        ),
        fix=(
            "A relation must be anchored in the semantics of what "
            "is being built, never in the implementation's own "
            "arithmetic. The metamorphic gate transforms the input "
            "and asserts a relation between the two outputs, "
            "reaching outside the artefact's own derivation."
        ),
        guarded_by="tests/blender/test_metamorphic.py (a relation anchored outside the artefact)",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="hashing-raw-floats-cries-wolf",
        scope="harness_code",
        failure=(
            "Inherited doctrine, not a local measurement: blended "
            "never had a byte or float hash to fail. scp measured "
            "that .blend bytes carry a version stamp and floats "
            "carry last-bit noise, so a byte or float hash reports "
            "drift on an unchanged build; bmesh emits geometry in "
            "pointer-hash order, so face order is not signal. The "
            "lesson is why blended.evaluate.digest was designed to "
            "hash quantized semantic tuples from the start."
        ),
        cause=(
            "Hashing raw floats or .blend bytes treats last-bit "
            "noise and Blender version stamps as semantic drift. "
            "The hash fires on every rebuild even when the shipped "
            "geometry is identical, so it is switched off inside a "
            "week — and the real drift it was meant to catch goes "
            "unguarded."
        ),
        fix=(
            "blended.evaluate.digest hashes quantized semantic "
            "tuples (positions to 0.1 mm, UVs to 1e-5, matrices to "
            "1e-5, weights to 1e-4), with faces canonicalized by "
            "rotating each face's index cycle to start at its "
            "lowest index before sorting. Winding direction is "
            "preserved so a flipped face still changes the digest."
        ),
        guarded_by="scripts/rebuild_twice.py / make test-repro (two fresh Blenders, PYTHONHASHSEED 0 vs 1) and tests/blender/test_rebuild_in_session.py",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="undo-is-not-a-reset",
        scope="harness_code",
        failure=(
            "Inherited doctrine, not a local measurement: blended "
            "never had a rebuild that trusted the undo stack. scp "
            "measured Blender's undo stack as unreliable from "
            "script-driven operators, so a rebuild that trusts it "
            "measures residue from the previous build. The lesson is "
            "why blended.reset.reset_scene wipes every collection in "
            "dependency order and asserts the wipe took, rather than "
            "relying on undo."
        ),
        cause=(
            "bpy.ops.wm.read_factory_settings(use_empty=True) "
            "wipes the scene but does not assert the wipe took, and "
            "Blender's undo stack does not reliably unwind "
            "script-driven operators. A rebuild that assumes the "
            "scene is clean measures the previous build's orphaned "
            "datablocks alongside the new one."
        ),
        fix=(
            "blended.reset.reset_scene wipes every collection in "
            "dependency order (objects before meshes before "
            "materials), calls orphans_purge, sets the canonical "
            "FPS, and finishes with assert_clean_scene, which "
            "raises SceneNotClean listing every non-empty "
            "MUST_BE_EMPTY collection and a non-canonical FPS at "
            "once."
        ),
        guarded_by="tests/blender/test_reset.py::test_a_leftover_object_is_not_a_clean_scene and ::test_a_rewritten_fps_is_not_a_clean_scene and ::test_every_problem_is_reported_in_one_raise",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-purged-module-is-still-patchable-and-still-dead",
        scope="harness_code",
        failure=(
            "test_the_assembled_fingerprint_covers_the_drift_catalog "
            "passed alone (pytest tests/pure/test_prompt_templates.py: "
            "20 passed) and failed in the full suite (1 failed, 402 "
            "passed) with 'a new drift row did not move the assembled "
            "fingerprint' — asserting a10:ff1ac8f0e73c != "
            "a10:ff1ac8f0e73c. Bisecting one file at a time against the "
            "single test named exactly one interferer: "
            "tests/pure/test_devreload.py."
        ),
        cause=(
            "test_devreload calls devreload.purge_library_modules(), "
            "which drops every blended.* entry from sys.modules. A "
            "module-scope `import blended.drift.catalog` binding in "
            "another test file survives the purge as a DEAD object, so "
            "monkeypatch.setattr lands on a module nobody imports "
            "again, while the deferred `from blended.drift.catalog "
            "import DRIFT_ENTRIES` inside build_manifest re-imports a "
            "fresh one. monkeypatch reported success: the attribute was "
            "really set, on the wrong module. Same defect class as "
            "a-purged-module-cannot-remove-its-own-draw-handler — a "
            "purge orphans every reference held outside sys.modules."
        ),
        fix=(
            "Tests resolve the module under test at CALL time through "
            "_live(name) -> importlib.import_module(name), which "
            "returns the live sys.modules entry and re-imports after a "
            "purge, so the patch and the reader agree. The test also "
            "asserts the probe is VISIBLE (the synthetic row's fix text "
            "appears in build_manifest()) before interpreting its "
            "effect: a patch that silently missed would otherwise read "
            "as 'the drift catalog does not reach the prompt', which is "
            "the opposite lesson."
        ),
        guarded_by="tests/pure/test_prompt_templates.py::test_the_assembled_fingerprint_covers_the_drift_catalog, which asserts the synthetic row reached build_manifest before comparing fingerprints, and is green in file order, after test_devreload, and in the full suite",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="git-checkout-reverts-to-the-index-not-to-your-snapshot",
        scope="process",
        failure=(
            "Running a negative control on "
            "src/blended/ops/canonical_orientation.py — reorder "
            "AXIS_NAMES, confirm 3 of 21 tests redden, revert — "
            "DELETED the uncommitted orientation_reading function the "
            "control was proving. The revert step was `git checkout -- "
            "<file>`; the assertion that the file matched its "
            "pre-probe bytes then failed, which is the only reason the "
            "loss was noticed at all."
        ),
        cause=(
            "`git checkout -- <path>` restores from the INDEX (or HEAD), "
            "not from the working-tree state that was snapshotted a "
            "moment earlier. The same command was safe on "
            "src/blended/drift/catalog.py in the same session, because "
            "that file had already been committed and its index copy WAS "
            "the snapshot — so the habit reads as correct right up until "
            "it is applied to a file with uncommitted work."
        ),
        fix=(
            "A probe on a file with uncommitted work snapshots BYTES and "
            "restores BYTES: read the file, write the probe, measure, "
            "write the saved bytes back, then assert byte equality. "
            "`git checkout` is for reverting to a commit, never for "
            "undoing a scratch edit. Assert the restore, always — the "
            "assertion is what turned a silent deletion into a caught "
            "one."
        ),
        guarded_by="No test can guard a shell habit; the guard is the byte-equality assertion at the end of every negative control, and this record. tests/pure/test_canonical_orientation.py::test_the_reading_names_the_axis_holding_the_middle_extent is what reddened under the probe and what proved the restore.",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-digest-is-mesh-identity-not-solid-identity",
        scope="harness_code",
        failure=(
            "The permutative metamorphic relation, written to assert "
            "semantic_digest and triangle_count unchanged when the "
            "boolean union order is reversed, FAILED on both multi-part "
            "builders on its first run: 2 failed, 4 passed. Measured — "
            "barrel 816 -> 816 triangles with a BIT-IDENTICAL volume "
            "(0.31573285487001135 both) but digest 665a17f1 -> "
            "4f927c63; pallet 334 -> 336 triangles, volume rel 1.7e-8, "
            "area rel 8.5e-9, digest 7213b524 -> 0284e97f."
        ),
        cause=(
            "Union is commutative on SOLIDS, not on TESSELLATIONS. "
            "Blender's EXACT boolean retriangulates from whatever "
            "intermediate mesh it was handed, so operand order decides "
            "the triangulation and the vertex order — which is all a "
            "digest sees. The relation asserted mesh identity while its "
            "own justification claimed to be about geometry, so it would "
            "have failed forever on correct builders: a gate that cannot "
            "pass is as useless as one that cannot fail."
        ),
        fix=(
            "MeshReport gained volume_m3 and surface_area_m2 (computed "
            "first, off the mesh as loaded, in the bmesh analyze_object "
            "already opens — one measurement path), measure_build "
            "carries them, and the relation asserts the SOLID: volume "
            "and area within a MEASURED CONSTRUCTION_ORDER_REL_TOL of "
            "1e-6 (~60x the worst observed noise), plus extents and the "
            "four topology counts exactly. triangle_count and the digest "
            "are deliberately not asserted, and the falsification is "
            "recorded in the module docstring WITH the numbers so the "
            "vacuous version is not retried. The semantic_digest key "
            "added for the dead assertion was removed with it."
        ),
        guarded_by="tests/blender/test_metamorphic.py::test_builders_satisfy_their_metamorphic_relations[barrel] and [pallet] carry construction_order_does_not_change_the_mesh. Negative control, run and reverted: making hoop z depend on sequence_position rather than hoop_index reddens it on surface_area_m2 (2.59578341525048 -> 2.5958127349149436, rel 1.1e-5, 11x the tolerance) while volume_m3 stays inside tolerance, because HOOP_POSITION_FRACTIONS 0.2 and 0.8 sit at equal radii on a sine-bulged barrel and the two shifts cancel in volume. Asserting both quantities is what catches it; either one alone would have missed it.",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-file-loaded-addon-draws-nothing-and-every-pixel-diff-is-zero",
        scope="process",
        failure=(
            "The live GUI check for shipping the transcript overlay "
            "reported the sidebar as 0 differing pixels out of 619,344 "
            "between a one-line and a sixty-line reply — the exact "
            "'the composer did not move' result wanted. It also "
            "reported 0 between an EMPTY session and a painted one, "
            "which cannot be true: the empty-state box disappears. A "
            "positive control (toggle _STATE.busy, which must change "
            "the status row) also read 0, and the FULL-WINDOW diff read "
            "0 as well."
        ),
        cause=(
            "The harness loaded blender_addon/__init__.py by file path "
            "(importlib.spec_from_file_location) and called register(). "
            "That registers the classes but creates no "
            "bpy.context.preferences.addons[<module>] entry, so "
            "BLENDED_PT_chat.draw raised KeyError "
            "('bpy_prop_collection[key]: key \"...\" not found') on "
            "EVERY frame. Blender swallows a panel draw exception, so "
            "the sidebar simply rendered no addon content and no "
            "sidebar pixel could ever change. The overlay's numbers in "
            "the same run were real — a draw handler does not read "
            "preferences — which is what made the mixed result "
            "believable."
        ),
        fix=(
            "A GUI check installs the addon the way a user does: "
            "package it, extract the zip into "
            "bpy.utils.user_resource('SCRIPTS', path='addons'), verify "
            "the installed __init__.py sha256 against the zip member "
            "(addon_install has been seen keeping a stale build), then "
            "bpy.ops.preferences.addon_enable(module=...). And every "
            "pixel-zero claim ships with a POSITIVE CONTROL measured in "
            "the same run: after the fix the control read 1,333 "
            "differing sidebar pixels, which is what licenses the 0."
        ),
        guarded_by="No unit test can catch this — it is a property of the GUI harness, not of the addon. The guard is the rule: a pixel diff of 0 is reported only alongside a control diff > 0 measured in the same session. Live numbers for the overlay flip: control 1333/619344 differing, composer strip 0/619344, overlay column 64467/732160 empty-vs-painted and 13647/732160 short-vs-long reply.",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-lane-with-no-acceptance-spec-cannot-fail",
        scope="harness_code",
        failure=(
            "scripts/photo_to_model.py returned 0 whenever ANY mesh "
            "existed. `error` was set from the turn's traceback and "
            "written into summary.json but never read for the exit code; "
            "`structural_failures` was printed and stored but never "
            "enforced; and an unreachable eye was swallowed upstream — "
            "deliver_images substituted EYE_UNREACHABLE_NOTE, so the "
            "writer got a prompt that deliberately names no shape and no "
            "pixels, invented an object, and the run exited 0. The "
            "no-mesh path returned 1 while writing NO summary.json at "
            "all, so the run with the most to explain explained nothing."
        ),
        cause=(
            "The module docstring's own sentence — 'there is no "
            "acceptance spec: a photograph carries no dimensions' — was "
            "read as 'therefore nothing can be gated'. But a photograph "
            "supports a COMPARATIVE spec even though it supports no "
            "dimensional one, and `examine_view` already existed and "
            "already takes two arbitrary images."
        ),
        fix=(
            "The photograph is the reference view and the three_quarter "
            "render is the candidate; examine_view runs both orders and "
            "only tags surviving the swap count, so a position-biased "
            "answer cannot decide the run. A surviving HALTING tag exits "
            "1, abstention is recorded and never a failure, a raised "
            "turn exits 1, and the gate needs an eye that is not the "
            "writer (--vision-model '' exits 2 BEFORE any Blender work) "
            "because a writer grading its own build against the picture "
            "it was handed holds both the evidence and the verdict. "
            "deliver_images gained eye_failure_is_fatal, True only at "
            "the reference-photo call site, raising a dedicated "
            "EyeUnreachable rather than a traceback the caller has to "
            "string-match. Every path past the turn now writes "
            "summary.json."
        ),
        guarded_by="tests/pure/test_reference_images.py::test_a_blind_eye_on_the_photo_path_raises_instead_of_guessing (the writer receives NO payload) and ::test_a_blind_eye_on_the_render_path_still_reports_a_note (the control that keeps the change from spreading). Live runs 2026-09-06, exit codes 2 / 1 / 0: --vision-model '' exits 2 naming the flag; --vision-model no-such-model-exists:v0 exits 1 with eye_reachable false, tool_calls 0 and objects []; a real run exits 0 with no surviving deviation. Gate sensitivity proven separately — a stool photograph against a crate render yields the surviving tag missing_part, so the exit 0 is not a gate that cannot fail.",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-signature-change-invalidates-recorded-model-code-not-just-callers",
        scope="harness_code",
        failure=(
            "OT-2 made every op take and return object NAMES. make "
            "test-blender-app: 3 failed, 305 passed — the golden replays "
            "of iteration 48 (planter: materials 0 assigned in 1 slot) and "
            "50 (column: exists but not linked; no dimension named "
            "'diameter_x'). Every hand-written caller and all 305 other "
            "tests had already been converted and were green."
        ),
        cause=(
            "The goldens replay what the MODEL wrote on 2026-08-22 against "
            "the object-returning API: planter chunk 7 fetched "
            "bpy.data.objects['PlanterBox'] and passed it to "
            "assign_material; column chunks 1-2 read `.name` off "
            "add_lathe's return and chunk 3 passed the bpy object to "
            "link_into_scene. Under the name contract those chunks raise "
            "and the rest of the chunk never runs. The other three goldens "
            "survived only because their sources never dereferenced an "
            "op's return — a behaviour-preserving API change still breaks "
            "recorded evidence, and grep over src/ and tests/ cannot see it."
        ),
        fix=(
            "Re-converged the two briefs on the new vocabulary at the SAME "
            "pinned v10 text (iterations 66 and 67, claude-code:sonnet, 8 and "
            "6 turns, 0 name-vs-object errors, identical form numbers) and "
            "re-minted their golden views, per the v9->v10 precedent in "
            "test_golden_convergence.py. The three untouched briefs were "
            "re-minted pixel-identical (0.00% differing) and reverted. "
            "Iterations 48 and 50 stay in the append-only log. Budget "
            "this: an ops API change costs one converge run per golden "
            "whose recorded source touches the changed surface."
        ),
        guarded_by=(
            "tests/blender/test_golden_convergence.py (replays the recorded "
            "sources: a signature change that breaks recorded model code "
            "fails here, not in the ops tests); "
            "tests/pure/test_ops_signature_contract.py (the contract itself)"
        ),
        recorded_on="2026-09-10",
    ),
    MistakeRecord(
        identifier="a-pure-helper-under-a-package-whose-init-imports-the-harness-is-a-cycle",
        scope="harness_code",
        failure=(
            "OT-4 put the EXE-6 stage vocabulary in blended/run/stages.py "
            "and imported it from harness.py. make test-pure: 625 passed. "
            "make test-blender-app -k agent_loop: 6 failed — every "
            "run_python tool call answered 'Tool raised ImportError: cannot "
            "import name HarnessResult from partially initialized module "
            "blended.harness', and the scene stayed empty."
        ),
        cause=(
            "blended/run/__init__.py eagerly imports run.batch, which "
            "imports blended.harness at module level. harness -> "
            "run.stages -> run/__init__ -> run.batch -> harness is a cycle "
            "whenever harness is the FIRST of the two imported. The pure "
            "suite never saw it because an earlier test had already "
            "imported blended.run.executor, so the package was initialised "
            "before harness loaded; a Blender probe that imported executor "
            "first passed for the same reason and was misleading."
        ),
        fix=(
            "Moved the vocabulary to blended/stages.py, a top-level module "
            "under the side-effect-free blended/__init__.py, and repointed "
            "harness.py, agent/op_call.py, the tests and the spec. Added a "
            "fresh-interpreter import test so import order is probed in a "
            "process that has imported nothing else."
        ),
        guarded_by=(
            "tests/pure/test_import_integrity.py::"
            "test_the_harness_imports_first_in_a_fresh_interpreter; "
            "tests/blender/test_agent_loop.py::test_loop_runs_a_tool_then_answers"
        ),
        recorded_on="2026-09-10",
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
