"""The cleanup pass against a synthetic generator-grade messy mesh."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _messy_sphere(name, punch_face_count=3):
    """An icosphere with seeded defects: a hole, duplicate vertices,
    a zero-length-edge degenerate face, and loose vertices — the defect
    profile of raw generated geometry."""
    import bmesh

    from blended.ops.primitives import remove_object_and_mesh

    remove_object_and_mesh(name)
    mesh_data = bpy.data.meshes.new(name)
    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_icosphere(working_mesh, subdivisions=5, radius=0.5)
        working_mesh.faces.ensure_lookup_table()
        for face in list(working_mesh.faces[:punch_face_count]):
            working_mesh.faces.remove(face)

        working_mesh.verts.ensure_lookup_table()
        for source_vertex in list(working_mesh.verts[:5]):
            working_mesh.verts.new(source_vertex.co)  # exact doubles, loose

        working_mesh.verts.new((2.0, 2.0, 2.0))  # a far loose vertex

        # Degenerate face: two coincident vertices -> zero-length edge.
        degenerate_anchor = working_mesh.verts.new((0.9, 0.0, 0.0))
        degenerate_twin = working_mesh.verts.new((0.9, 0.0, 0.0))
        degenerate_third = working_mesh.verts.new((0.95, 0.05, 0.0))
        working_mesh.faces.new((degenerate_anchor, degenerate_twin, degenerate_third))

        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    messy_object = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(messy_object)
    return messy_object


def test_cleanup_takes_messy_mesh_to_gate_pass(empty_scene):
    from blended.analyze import MeshBudget, analyze_object
    from blended.ingest import CleanupSettings, cleanup_mesh

    messy_object = _messy_sphere("MessySphere")
    before_report = analyze_object(messy_object)
    assert before_report.boundary_edge_count > 0
    assert before_report.duplicate_vertex_pair_count > 0
    assert before_report.triangle_count > MeshBudget().maximum_triangle_count

    cleanup_report = cleanup_mesh(messy_object, CleanupSettings())

    failures = cleanup_report.after.failures(MeshBudget())
    assert failures == [], (
        f"failures after cleanup: {failures}; actions: {cleanup_report.actions}"
    )
    assert cleanup_report.after.triangle_count <= MeshBudget().maximum_triangle_count
    assert any("welded" in action for action in cleanup_report.actions)
    assert any("filled hole" in action for action in cleanup_report.actions)
    assert any("decimated" in action for action in cleanup_report.actions)


def test_oversized_hole_is_left_open_and_reported(empty_scene):
    """The Attene rule: never blind-fill. A hole beyond the threshold
    survives cleanup and still fails the gate — honestly."""
    from blended.analyze import MeshBudget
    from blended.ingest import CleanupSettings, cleanup_mesh

    BIG_HOLE_FACE_COUNT = 200
    messy_object = _messy_sphere("BigHoleSphere", punch_face_count=BIG_HOLE_FACE_COUNT)
    tight_settings = CleanupSettings(maximum_hole_perimeter_m=0.05)
    cleanup_report = cleanup_mesh(messy_object, tight_settings)

    assert any("LEFT OPEN" in action for action in cleanup_report.actions)
    assert cleanup_report.after.boundary_edge_count > 0
    assert not cleanup_report.after.passes(MeshBudget())
