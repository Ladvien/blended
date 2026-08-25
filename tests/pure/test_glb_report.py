"""Pure layer: the stdlib .glb parser, exercised on synthetic bytes.

No committed fixture: _evaluate/golden/*.glb are deliberately
untracked, so the test assembles its own JSON chunk + BIN chunk.

The chunk layout mirrors Blender's exporter (io_scene_gltf2
export.py): the JSON chunk's length field carries the PADDED length
(length_gltf += spaces_gltf), not the raw JSON byte count.
"""

import json
import struct

import pytest

from blended.export.glb_report import (
    GLB_HEADER_SIZE_BYTES,
    GLB_MAGIC,
    asset_report,
    format_glb_report,
    parse_glb,
    read_accessor,
)

# float32 encoding of (0,0,0), (1,0,0), (0,1,0) — two triangles sharing
# the edge (1,0,0)-(0,1,0).
SHARED_EDGE_POSITIONS = (
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (1.0, 1.0, 0.0),
)
UP_NORMALS = (
    (0.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
)
# glTF requires the NORMAL accessor to cover every POSITION; the
# 5-vertex fixtures need 5 normals.
UP_NORMALS_5 = UP_NORMALS + ((0.0, 0.0, 1.0),)


def _pack_components(values):
    return b"".join(struct.pack("<fff", *value) for value in values)


def _json_chunk(payload: bytes) -> bytes:
    """Blender-style JSON chunk: length field is the PADDED length."""
    padding = (4 - (len(payload) & 3)) & 3
    return (
        struct.pack("<I", len(payload) + padding)
        + b"JSON"
        + payload
        + b" " * padding
    )


def _bin_chunk(payload: bytes) -> bytes:
    padding = (4 - (len(payload) & 3)) & 3
    return (
        struct.pack("<I", len(payload) + padding)
        + b"BIN\x00"
        + payload
        + b"\x00" * padding
    )


def _build_glb(positions, indices, normals=None):
    """Assemble a minimal .glb: one mesh, one triangle primitive."""
    binary = bytearray()
    binary.extend(_pack_components(positions))
    if normals is not None:
        binary.extend(_pack_components(normals))
    binary.extend(struct.pack("<" + "I" * len(indices), *indices))
    while len(binary) % 4:
        binary.append(0)

    buffer_views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(binary)}
    ]
    accessors = [
        {
            "bufferView": 0,
            "byteOffset": 0,
            "componentType": 5126,
            "count": len(positions),
            "type": "VEC3",
            "min": [
                min(p[0] for p in positions),
                min(p[1] for p in positions),
                min(p[2] for p in positions),
            ],
            "max": [
                max(p[0] for p in positions),
                max(p[1] for p in positions),
                max(p[2] for p in positions),
            ],
        }
    ]
    attributes = {"POSITION": 0}

    offset = len(_pack_components(positions))
    if normals is not None:
        buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": offset,
                "byteLength": len(_pack_components(normals)),
            }
        )
        accessors.append(
            {
                "bufferView": len(buffer_views) - 1,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(normals),
                "type": "VEC3",
            }
        )
        attributes["NORMAL"] = len(accessors) - 1
        offset += len(_pack_components(normals))
    buffer_views.append(
        {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(indices) * 4,
        }
    )
    accessors.append(
        {
            "bufferView": len(buffer_views) - 1,
            "byteOffset": 0,
            "componentType": 5125,
            "count": len(indices),
            "type": "SCALAR",
        }
    )
    indices_accessor = len(accessors) - 1

    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "meshes": [
            {
                "name": "Tri",
                "primitives": [
                    {
                        "attributes": attributes,
                        "indices": indices_accessor,
                        "mode": 4,
                    }
                ],
            }
        ],
        "nodes": [{"name": "TriNode", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    json_chunk = _json_chunk(json.dumps(gltf).encode("utf-8"))
    bin_chunk = _bin_chunk(bytes(binary))
    declared = GLB_HEADER_SIZE_BYTES + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", GLB_MAGIC, 2, declared)
    return header + json_chunk + bin_chunk


def _write_glb(tmp_path, data, name="test.glb"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_two_triangles_sharing_an_edge(tmp_path):
    """Two triangles on one shared edge: 2 tris, 4 welded boundary
    edges, 0 non-manifold, 0 inverted."""
    indices = (0, 1, 2, 1, 3, 2)
    path = _write_glb(
        tmp_path, _build_glb(SHARED_EDGE_POSITIONS, indices, UP_NORMALS)
    )
    report = asset_report(path)
    mesh = report.meshes["Tri"]
    assert report.triangle_count == 2
    assert mesh.triangle_count == 2
    assert mesh.welded_boundary_edge_count == 4
    assert mesh.non_manifold_edge_count == 0
    assert mesh.inverted_facet_count == 0
    assert mesh.has_normals is True
    assert mesh.uv_set_count == 0


def test_duplicated_shared_vertices_do_not_weld(tmp_path):
    """The same two triangles with their shared vertices duplicated
    1 mm apart: the weld is load-bearing — 6 boundary edges, not 4."""
    positions = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (1.001, 0.0, 0.0),
        (0.001, 1.0, 0.0),
    )
    indices = (0, 1, 2, 1, 3, 4)
    path = _write_glb(tmp_path, _build_glb(positions, indices, UP_NORMALS_5))
    report = asset_report(path)
    assert report.meshes["Tri"].welded_boundary_edge_count == 6


def test_three_triangles_on_one_shared_edge(tmp_path):
    """Three triangles on one edge: that edge is used 3 times ->
    non-manifold."""
    positions = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (1.0, -1.0, 0.0),
    )
    indices = (0, 1, 2, 0, 1, 3, 0, 1, 4)
    path = _write_glb(tmp_path, _build_glb(positions, indices, UP_NORMALS_5))
    report = asset_report(path)
    assert report.meshes["Tri"].non_manifold_edge_count == 1


def test_reversed_winding_is_an_inverted_facet(tmp_path):
    """One triangle with reversed winding against unchanged normals."""
    indices = (0, 2, 1)
    path = _write_glb(
        tmp_path, _build_glb(SHARED_EDGE_POSITIONS[:3], indices, UP_NORMALS[:3])
    )
    report = asset_report(path)
    assert report.meshes["Tri"].inverted_facet_count == 1


def test_bad_magic_raises(tmp_path):
    path = tmp_path / "bad.glb"
    path.write_bytes(b"not a glb at all")
    with pytest.raises(ValueError, match="bad magic"):
        parse_glb(path)


def test_declared_length_disagrees_raises(tmp_path):
    data = _build_glb(SHARED_EDGE_POSITIONS[:3], (0, 1, 2))
    bad = bytearray(data)
    bad[8:12] = struct.pack("<I", len(data) + 100)
    path = tmp_path / "lying.glb"
    path.write_bytes(bad)
    with pytest.raises(ValueError, match="declares"):
        parse_glb(path)


def test_sparse_accessor_raises_not_implemented(tmp_path):
    data = _build_glb(SHARED_EDGE_POSITIONS[:3], (0, 1, 2))
    json_length = struct.unpack("<I", data[12:16])[0]
    json_start = GLB_HEADER_SIZE_BYTES + 8
    gltf = json.loads(data[json_start : json_start + json_length])
    gltf["accessors"][0]["sparse"] = {
        "count": 1,
        "indices": {"bufferView": 1, "byteOffset": 0, "componentType": 5123},
        "values": {"bufferView": 2},
    }
    gltf_bytes = json.dumps(gltf).encode("utf-8")
    binary = b"\x00" * 24
    json_chunk = _json_chunk(gltf_bytes)
    bin_chunk = _bin_chunk(binary)
    header = struct.pack(
        "<III", GLB_MAGIC, 2, GLB_HEADER_SIZE_BYTES + len(json_chunk) + len(bin_chunk)
    )
    path = tmp_path / "sparse.glb"
    path.write_bytes(header + json_chunk + bin_chunk)
    gltf_parsed, _ = parse_glb(path)
    with pytest.raises(NotImplementedError, match="sparse"):
        read_accessor(gltf_parsed, b"", 0)


def test_read_accessor_without_buffer_view_raises():
    gltf = {"accessors": [{"componentType": 5126, "count": 3, "type": "VEC3"}]}
    with pytest.raises(ValueError, match="no bufferView"):
        read_accessor(gltf, b"", 0)


def test_format_glb_report_baseline_hides_unchanged_meshes(tmp_path):
    indices = (0, 1, 2, 1, 3, 2)
    path = _write_glb(tmp_path, _build_glb(SHARED_EDGE_POSITIONS, indices))
    report = asset_report(path)
    baseline = asset_report(path)
    text = format_glb_report(report, baseline)
    assert "meshes removed: none" in text
    assert "meshes added:   none" in text
    # No per-mesh row when nothing changed: nothing after the
    # "per mesh" header names the mesh.
    assert "Tri" not in text.split("per mesh")[1]
