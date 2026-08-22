"""Run ONE brief through the agent, inside a real Blender, and score it.

    make converge BRIEF=planter_box REVISION=1 ITERATION=1

This is the RUN + RENDER + deterministic half of EXAMINE. It does not
judge the render — that is the visual pass, done by a human or a
supervising agent reading the contact sheet this writes. It ends by
appending one IterationRecord with everything measured.

Runs inside `blender --background`, so bpy is on the main thread and
`dispatch_here` is the correct dispatcher. Ordering is not negotiable:
the structural gate and the form gate BOTH run and are BOTH recorded
before anything renders, because a visual critique of a scene that
already failed a measurement is wasted tokens.
"""

import argparse
import datetime as _datetime
import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def venv_site_packages() -> Path:
    candidates = sorted(
        (REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages")
    )
    if not candidates:
        raise SystemExit(f"No .venv under {REPOSITORY_ROOT}.")
    return candidates[-1]


sys.path.insert(0, str(venv_site_packages()))
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT))
os.chdir(REPOSITORY_ROOT)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", required=True)
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--iteration", type=int, required=True)
    parser.add_argument("--log", default="_evaluate/iterations.jsonl")
    parser.add_argument("--renders", default="_evaluate/renders")
    parser.add_argument("--model", default="")
    parser.add_argument("--vision-model", default="")
    # Measured, not guessed. three_leg_stool needs 17 calls to build and
    # verify itself (iteration 10, a run that passed both deterministic
    # gates) and then has nothing left to answer with — three consecutive
    # runs ended in the exhaustion string holding a finished asset. 24
    # leaves room to report and to absorb one failed chunk, while still
    # capping a runaway loop: planter_box answers in 3.
    parser.add_argument("--max-tool-calls", type=int, default=24)
    return parser.parse_args(argv)


def main(argv) -> int:
    import bpy

    from blended.agent.loop import AgentSession, ModelConfig, OllamaClient
    from blended.agent.prompt_versions import get_revision
    from blended.agent.system_prompt import build_system_prompt
    from blended.analyze import analyze_object
    from blended.capture import CaptureSettings, capture_contact_sheet
    from blended.evaluate.acceptance import (
        RefinementOutcome,
        evaluate_brief,
        refine_brief,
    )
    from blended.evaluate.briefs import get_brief
    from blended.evaluate.iteration_log import IterationLog, IterationRecord
    from blended.evaluate.object_identity import (
        measure_locality,
        new_identity,
        stamp_identity,
    )
    from blended.export.gltf import export_glb
    from blended.version import assert_supported_blender

    arguments = parse_arguments(argv)
    assert_supported_blender()

    brief = get_brief(arguments.brief)
    revision = get_revision(arguments.revision)
    render_directory = Path(arguments.renders) / (
        f"iteration{arguments.iteration:02d}_{brief.name}_v{revision.revision}"
    )
    render_directory.mkdir(parents=True, exist_ok=True)

    # A fresh scene per run. Convergence is about the prompt; leftover
    # geometry from a previous iteration would silently score for it.
    bpy.ops.wm.read_factory_settings(use_empty=True)

    configuration_overrides = {}
    if arguments.model:
        configuration_overrides["model"] = arguments.model
    if arguments.vision_model:
        configuration_overrides["vision_model"] = arguments.vision_model
    client = OllamaClient(ModelConfig.from_environment(**configuration_overrides))
    status = client.check_connection()
    print(f"[connection] {status.summary()}", flush=True)
    if not status.ok:
        raise SystemExit(f"Model unreachable, refusing to score a run: {status.detail}")

    system_prompt = build_system_prompt(revision=revision.revision)
    session = AgentSession(
        client=client,
        output_directory=render_directory / "agent",
        maximum_tool_calls_per_turn=arguments.max_tool_calls,
        messages=[{"role": "system", "content": system_prompt}],
    )

    tool_calls: list[str] = []
    transcript: list[str] = []

    def on_event(kind: str, text: str) -> None:
        transcript.append(f"--- {kind} ---\n{text}")
        if kind == "tool":
            tool_calls.append(text)
        preview = text if len(text) <= 400 else text[:400] + " ..."
        print(f"[{kind}] {preview}", flush=True)

    started_at = _datetime.datetime.now(_datetime.timezone.utc).isoformat()
    print(f"[brief] {brief.prompt_text}", flush=True)
    final_text = session.send(brief.prompt_text, on_event=on_event)

    # --- EXAMINE (a): deterministic gates, both, before any render ----
    bpy.context.view_layer.update()
    built_object = bpy.data.objects.get(brief.object_name)

    if built_object is None:
        structural_failures = (
            f"no object named {brief.object_name!r} — nothing to analyze",
        )
        structural_passed = False
    else:
        structural_report = analyze_object(built_object)
        structural_failures = tuple(structural_report.failures(brief.budget))
        structural_passed = not structural_failures

    form_report = evaluate_brief(brief)
    form_failures = tuple(form_report.failures(brief))

    # --- RENDER: on failure too. A failure you cannot review is one
    # you will repeat.
    render_path = ""
    glb_path = ""
    if built_object is not None and built_object.name in bpy.context.scene.objects:
        sheet = capture_contact_sheet(
            built_object,
            render_directory,
            settings=CaptureSettings(),
        )
        render_path = str(sheet)
        # AFTER both gates: export_glb re-imports to verify the file, and
        # a temporary re-import in the scene would read as a stray object.
        destination = render_directory / f"{brief.object_name}.glb"
        export_report = export_glb(built_object, destination)
        glb_path = str(destination)
        print(
            f"[export] {destination} ({export_report.file_size_bytes} bytes), "
            f"round trip "
            f"{'OK' if export_report.passes(brief.budget) else 'FAILED'}",
            flush=True,
        )
        for failure in export_report.round_trip_failures(brief.budget):
            print(f"   - {failure}", flush=True)

    # --- USER-GUIDED REFINEMENT: a second turn, gated exactly like the
    # first. The standard requires follow-up instructions to be applied
    # as LOCALIZED edits that preserve the rest of the asset, so the
    # measurement is not "does it still satisfy the brief" (a rebuild
    # does too) but "did anything the user did not name move".
    refinement_summaries: list[str] = []
    refinement_failures: list[str] = []
    refinement_locality: list[str] = []
    refinement_passed = True
    if brief.refinements and not form_failures and structural_passed:
        # Stamp AFTER the export, so the shipped .glb never carries it,
        # and BEFORE the first follow-up, so the stamp predates any edit
        # it is meant to survive. The primitives are idempotent by name,
        # so a rebuild under the same name destroys the datablock and
        # takes the stamp with it — which is the whole measurement.
        stamped_identity = stamp_identity(built_object, new_identity())
        for step in brief.refinements:
            print(f"\n[refine] {step.instruction_text}", flush=True)
            before_report = form_report
            session.send(step.instruction_text, on_event=on_event)
            bpy.context.view_layer.update()
            after_report = evaluate_brief(refine_brief(brief, step))
            outcome = RefinementOutcome(
                step=step, before=before_report, after=after_report
            )
            step_failures = outcome.failures(brief)
            refinement_failures.extend(step_failures)
            refinement_summaries.append(outcome.summary(brief))
            refinement_passed = refinement_passed and not step_failures
            print(outcome.summary(brief), flush=True)
            refined_object = bpy.data.objects.get(brief.object_name)
            locality = measure_locality(
                refined_object, step.name, stamped_identity
            )
            refinement_locality.append(locality.summary())
            print(locality.summary(), flush=True)
            if refined_object is not None and (
                refined_object.name in bpy.context.scene.objects
            ):
                capture_contact_sheet(
                    refined_object,
                    render_directory / f"refined_{step.name}",
                    settings=CaptureSettings(),
                )
            form_report = after_report
    elif brief.refinements:
        # Refining an asset that already failed measures nothing.
        refinement_summaries.append(
            "REFINEMENT SKIPPED: the first build did not pass both gates"
        )
        refinement_passed = False

    record = IterationRecord(
        iteration=arguments.iteration,
        brief_name=brief.name,
        prompt_identity=revision.identity,
        prompt_revision=revision.revision,
        started_at=started_at,
        writer_model=client.config.model,
        vision_model=client.config.vision_model,
        agent_turns=len([m for m in session.messages if m.get("role") == "assistant"]),
        tool_calls=tuple(tool_calls),
        agent_final_text=final_text,
        structural_gate_passed=structural_passed,
        structural_failures=structural_failures,
        form_gate_passed=not form_failures,
        form_failures=form_failures,
        form_summary=form_report.summary(brief),
        render_path=render_path,
        glb_path=glb_path,
        refinement_gate_passed=refinement_passed,
        refinement_failures=tuple(refinement_failures),
        refinement_summary="\n".join(refinement_summaries),
        refinement_locality=tuple(refinement_locality),
    )
    IterationLog(Path(arguments.log)).append(record)

    (render_directory / "transcript.txt").write_text(
        "\n\n".join(transcript), encoding="utf-8"
    )
    (render_directory / "system_prompt.txt").write_text(system_prompt, encoding="utf-8")

    print("\n================ ITERATION RESULT ================", flush=True)
    print(f"brief      : {brief.name}", flush=True)
    print(f"prompt     : {revision.identity}", flush=True)
    print(
        f"models     : writer {client.config.model} / eye "
        f"{client.config.vision_model}",
        flush=True,
    )
    print(f"tool calls : {len(tool_calls)}", flush=True)
    print(
        f"STRUCTURAL : {'PASS' if structural_passed else 'FAIL'}",
        flush=True,
    )
    for failure in structural_failures:
        print(f"   - {failure}", flush=True)
    print(form_report.summary(brief), flush=True)
    print(f"render     : {render_path or '(none — nothing to render)'}", flush=True)
    print(f"glb        : {glb_path or '(none)'}", flush=True)
    for summary in refinement_summaries:
        print(summary, flush=True)
    # Evidence, printed beside the gates but never folded into them:
    # the exit code below does not consult it.
    for summary in refinement_locality:
        print(summary, flush=True)
    print("=================================================", flush=True)
    return (
        0
        if (structural_passed and not form_failures and refinement_passed)
        else 1
    )


extra_arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
raise SystemExit(main(extra_arguments))
