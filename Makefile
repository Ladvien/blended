PY ?= python3

.PHONY: test test-pure test-blender

test: test-pure test-blender

# Pure-Python layer: must pass on any machine, no Blender required.
test-pure:
	$(PY) -m pytest tests/pure -q

# Blender layer: requires `import bpy` to work (pip-installed bpy wheel,
# or Blender's own Python). Skips cleanly if bpy is absent.
test-blender:
	$(PY) -m pytest tests/blender -q
