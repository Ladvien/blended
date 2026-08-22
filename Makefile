PY ?= python3
BLENDER ?= /Applications/Blender.app/Contents/MacOS/Blender

.PHONY: test test-pure test-blender test-blender-app converge replay

test: test-pure test-blender

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

# Rebuild a scored iteration from its own log and export a .glb.
#   make replay ITERATION=10
replay:
	$(BLENDER) --background --factory-startup \
		--python scripts/replay_iteration.py -- --iteration $(ITERATION) $(ARGS)
