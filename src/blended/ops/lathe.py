"""Lathe (surface of revolution) built ring-by-ring with bmesh.

The general op behind barrels, bottles, columns, wheels: give it a 2D
profile of (radius_m, z_m) points and it revolves them around Z. Ends
with radius > 0 are capped with triangle fans so the result is closed.
Deterministic, context-free, idempotent by name.
"""

from __future__ import annotations

import math

MINIMUM_PROFILE_POINTS = 2
MINIMUM_SEGMENTS = 3


def add_lathe(
    name: str,
    profile: list[tuple[float, float]],
    segment_count: int = 24,
):
    """Revolve `profile` [(radius_m, z_m), ...] around Z into a closed mesh."""
    import bmesh
    import bpy

    from blended.ops.primitives import remove_object_and_mesh

    if len(profile) < MINIMUM_PROFILE_POINTS:
        raise ValueError("Lathe profile needs at least two points.")
    if segment_count < MINIMUM_SEGMENTS:
        raise ValueError("Lathe needs at least three segments.")
    if any(radius_m <= 0.0 for radius_m, _ in profile):
        raise ValueError(
            "Profile radii must be positive; poles are added automatically."
        )

    remove_object_and_mesh(name)
    mesh_data = bpy.data.meshes.new(name)
    lathe_object = bpy.data.objects.new(name, mesh_data)

    working_mesh = bmesh.new()
    try:
        rings = []
        for radius_m, height_z_m in profile:
            ring_vertices = []
            for segment_index in range(segment_count):
                angle_rad = (segment_index / segment_count) * math.tau
                ring_vertices.append(
                    working_mesh.verts.new(
                        (
                            radius_m * math.cos(angle_rad),
                            radius_m * math.sin(angle_rad),
                            height_z_m,
                        )
                    )
                )
            rings.append(ring_vertices)

        # Side wall quads between consecutive rings.
        for lower_ring, upper_ring in zip(rings, rings[1:]):
            for segment_index in range(segment_count):
                next_index = (segment_index + 1) % segment_count
                working_mesh.faces.new(
                    (
                        lower_ring[segment_index],
                        lower_ring[next_index],
                        upper_ring[next_index],
                        upper_ring[segment_index],
                    )
                )

        # Cap both ends with triangle fans to a pole vertex.
        for ring_vertices, is_bottom in ((rings[0], True), (rings[-1], False)):
            pole_vertex = working_mesh.verts.new((0.0, 0.0, ring_vertices[0].co.z))
            for segment_index in range(segment_count):
                next_index = (segment_index + 1) % segment_count
                if is_bottom:
                    triangle = (
                        pole_vertex,
                        ring_vertices[next_index],
                        ring_vertices[segment_index],
                    )
                else:
                    triangle = (
                        pole_vertex,
                        ring_vertices[segment_index],
                        ring_vertices[next_index],
                    )
                working_mesh.faces.new(triangle)

        bmesh.ops.recalc_face_normals(working_mesh, faces=working_mesh.faces)
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()

    return lathe_object
