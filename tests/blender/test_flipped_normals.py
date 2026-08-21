"""Flipped-normal detection: the fixtures and the clean control."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _box_with_flipped_faces(name, flip_face_indices=None, flip_all=False):
    import bmesh

    from blended.ops.primitives import remove_object_and_mesh

    remove_object_and_mesh(name)
    mesh_data = bpy.data.meshes.new(name)
    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_cube(working_mesh, size=1.0)
        working_mesh.faces.ensure_lookup_table()
        if flip_all:
            for face in working_mesh.faces:
                face.normal_flip()
        elif flip_face_indices:
            for face_index in flip_face_indices:
                working_mesh.faces[face_index].normal_flip()
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    box_object = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(box_object)
    return box_object


def test_clean_control_has_no_flipped_triangles(empty_scene):
    from blended.analyze import analyze_object
    from blended.builders import BarrelBuilder, BarrelParameters

    report = analyze_object(BarrelBuilder(BarrelParameters()).build())
    assert report.flipped_normal_triangle_count == 0


def test_single_flipped_face_is_detected(empty_scene):
    from blended.analyze import MeshBudget, analyze_object

    TRIANGLES_PER_QUAD = 2
    box_object = _box_with_flipped_faces("OneFlipped", flip_face_indices=[0])
    report = analyze_object(box_object)
    assert report.flipped_normal_triangle_count == TRIANGLES_PER_QUAD
    assert not report.passes(MeshBudget())


def test_inside_out_box_flags_every_triangle(empty_scene):
    from blended.analyze import analyze_object

    CUBE_TRIANGLE_COUNT = 12
    box_object = _box_with_flipped_faces("InsideOut", flip_all=True)
    report = analyze_object(box_object)
    assert report.flipped_normal_triangle_count == CUBE_TRIANGLE_COUNT
