.PHONY: test test-pure test-blender test-blender-app converge converge-local \
	replay calibrate-eye calibrate-visual-gate pin-golden-views converge-auto \
	pin bench-3dcode chat-e2e photo-to-model provider-smoke test-repro
PY ?= .venv/bin/python
BLENDER ?= /Applications/Blender.app/Contents/MacOS/Blender


# Both layers: the pure suite in the dev venv, the Blender suite inside
# the installed Blender (the environment the addon ships into). A bare
# `pytest tests/blender` with no bpy wheel collects nothing and exits 5,
# which is not a pass.
test: test-pure test-blender-app

# Pure-Python layer: must pass on any machine, no Blender required.
test-pure:
	$(PY) -m pytest tests/pure -q

# Blender layer: requires `import bpy` to work (pip-installed bpy wheel,
# or Blender's own Python). Skips cleanly if bpy is absent.
test-blender:
	$(PY) -m pytest tests/blender -q

# Blender layer inside the INSTALLED Blender — the environment the
# addon actually ships into (bundled numpy, no Pillow, no pip).
test-blender-app:
	$(BLENDER) --background --factory-startup \
		--python scripts/run_tests_in_blender.py -- $(ARGS)

# Build twice in two fresh Blenders under different PYTHONHASHSEED and
# require identical semantic digests. Slow: two full Blender launches,
# which is why it is not part of `test` — it is a gate you run before a
# pin, not on every change.
#   make test-repro ARGS="--builder barrel"
#   make test-repro ARGS="--iteration 10"
test-repro:
	$(PY) scripts/rebuild_twice.py $(ARGS)

# One convergence iteration: run a brief through the agent inside a real
# Blender, gate it structurally and by form, render it, log the record.
#   make converge BRIEF=planter_box REVISION=1 ITERATION=1
BRIEF ?= planter_box
REVISION ?= 1
ITERATION ?= 1
converge:
	$(BLENDER) --background --factory-startup \
		--python scripts/run_agent_task.py -- \
		--brief $(BRIEF) --revision $(REVISION) --iteration $(ITERATION) $(ARGS)

# One convergence iteration on the FULLY LOCAL pair: writer
# qwen3.8-27b on bmb's llama-swap, eye qwen3-vl on big's llama-swap.
# Two hosts on purpose — big is strict-swap, so a local writer there
# would evict the eye every turn. Artifacts land under outputs/ so a
# local-model run never mixes into _evaluate/iterations.jsonl, which
# the convergence tests read as source.
#   make converge-local BRIEF=planter_box
LOCAL_WRITER ?= qwen3.8-27b
LOCAL_EYE    ?= qwen3-vl
LOCAL_OUT    ?= outputs/local_pair
converge-local:
	$(BLENDER) --background --factory-startup \
		--python scripts/run_agent_task.py -- \
		--brief $(BRIEF) --revision $(REVISION) --iteration $(ITERATION) \
		--model $(LOCAL_WRITER) --vision-model $(LOCAL_EYE) \
		--log $(LOCAL_OUT)/iterations.jsonl \
		--verdicts $(LOCAL_OUT)/verdicts.jsonl \
		--renders $(LOCAL_OUT)/renders $(ARGS)

# Rebuild a scored iteration from its own log and export a .glb.
#   make replay ITERATION=10
replay:
	$(BLENDER) --background --factory-startup \
		--python scripts/replay_iteration.py -- --iteration $(ITERATION) $(ARGS)

# Calibrate the examiner against the fixture zoo: 5 defects + 5 controls,
# each examined the way the loop examines a run (5 views x 2 orders).
# Writes _evaluate/eye_calibration.json, which licenses machine verdicts.
#   make calibrate-eye
#   make calibrate-eye ARGS="--only missing_leg"
#   make calibrate-eye ARGS="--cross-run-only"   (the regime the loop uses)
calibrate-eye:
	$(BLENDER) --background --factory-startup \
		--python scripts/calibrate_examiner.py -- $(ARGS)
# Measure the visual gate's thresholds against the pinned goldens:
# control (golden vs itself), clean replays, and a Decimate mutation
# that must FAIL the derived thresholds. Writes
# _evaluate/visual_gate_calibration.json, which licenses the gate in
# run_agent_task.py.
#   make calibrate-visual-gate REVISION=10
calibrate-visual-gate:
	$(BLENDER) --background --factory-startup \
		--python scripts/calibrate_visual_gate.py -- --revision $(REVISION) $(ARGS)

# Pin the per-view golden references for a revision's converged runs.
# The examiner compares every render against these, so they are the
# reference a machine verdict rests on.
#   make pin-golden-views REVISION=10
pin-golden-views:
	$(BLENDER) --background --factory-startup \
		--python scripts/pin_golden_views.py -- --revision $(REVISION) $(ARGS)

# The unattended loop: RUN -> EXAMINE -> CLASSIFY -> ADJUST, over the
# whole brief suite, until it proposes a pin or halts with a reason.
# Ends in exactly one of two states: _evaluate/pin_proposal.json (exit 0)
# or _evaluate/halt_report.md (non-zero).
#   make converge-auto REVISION=10
#   make converge-auto REVISION=10 ARGS="--propose-only --from-iteration 31"
# The eye it names must be the eye that was calibrated: examiner_identity
# binds the licence to the model name AND the examiner prompt hash, so
# switching eyes means re-running calibrate-eye first. Measured
# 2026-08-22: qwen3-vl:8b-instruct scored sensitivity 0.20 and is
# refused, so this loop halts at preflight until a stronger eye is
# calibrated (or --examiner none keeps the human as the judge).
converge-auto:
	$(PY) scripts/converge_auto.py --revision $(REVISION) $(ARGS)

# Apply a pin proposal. The one human act the loop leaves behind: a
# machine verdict may run the loop, but it may not mint the golden
# reference every later examination is compared against.
#   make pin REVISION=11
pin:
	$(PY) scripts/pin_revision.py --revision $(REVISION) $(ARGS)

# External benchmark: run the frozen 3DCodeBench subset through the
# agent and emit one standalone script per instance for 3DCodeBench's
# own unmodified scorers to bake and measure. This is the only quality
# signal here that is comparable to something outside this repository.
#   make bench-3dcode
#   make bench-3dcode INSTANCES=/Users/ladvien/3dcodebench/instances_v1.txt
BENCH_ROOT ?= /Users/ladvien/3dcodebench
INSTANCES  ?= /Users/ladvien/3dcodebench/instances_smoke.txt
bench-3dcode:
	$(PY) scripts/sweep_3dcode.py --bench-root $(BENCH_ROOT) \
		--instances-file $(INSTANCES) $(ARGS)

# The chat's own gate: six user asks (object, rig, weights, animation,
# material, iterative edit) through AgentSession inside a real Blender,
# each measured with hard assertions. Exit 0 = all six pass.
#   make chat-e2e
#   make chat-e2e ARGS="--only rig,animation --revision 11"
#   make chat-e2e ARGS="--model claude-code:sonnet --vision-model ''"
#     (the CLI lane, writer as its own eye: 6/6 in 2m53s, 2026-09-05)
chat-e2e:
	$(BLENDER) --background --factory-startup --python scripts/chat_e2e.py -- $(ARGS)

# Photo in, model out: the agent reads a picture of a real object and
# builds it. The default prompt names no shape, so the picture is what
# drove the build; the proof is the contact sheet it prints.
#   make photo-to-model ARGS="--photo path/to/thing.jpg"
#   make photo-to-model ARGS="--photo thing.jpg --model deepseek-v4-pro:cloud \
#       --vision-model kimi-k2.7-code:cloud"   (text-only writer, eye reads it)
photo-to-model:
	$(BLENDER) --background --factory-startup --python scripts/photo_to_model.py -- $(ARGS)

# One text chat and one image call per model lane (OpenRouter, bmb, big,
# claude-code). The claude-code lane needs no key and no endpoint: it
# shells out to the signed-in Claude Code CLI on this machine.
#   make provider-smoke
#   make provider-smoke ARGS="--only big"
#   make provider-smoke ARGS="--only claude-code"
provider-smoke:
	.venv/bin/python scripts/provider_smoke.py $(ARGS)
