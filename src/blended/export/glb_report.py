"""Read a shipped ``.glb`` and report what is actually in it — without Blender.

Tier 1 (pure). This module imports ``json``, ``math``, ``struct`` and
``dataclasses`` and nothing else. No ``bpy``, no ``numpy``. That is the
point: the exported file is the artifact the game loads, and checking
it should not require launching Blender.

MEASURE THE FILE, NOT THE SCENE
-------------------------------
The exporter runs with ``export_apply=True``, which bakes modifiers, so
scene polygon counts describe geometry that never shipped. scp measured
a "5k" tier that shipped 9,488 triangles, and a scene report and a raw
bmesh disagreed 0 vs 6,196 boundary edges because one welded by
position and one counted UV seams. Every count here is read out of the
file's own bytes.

TWO MEASUREMENT DECISIONS, BOTH PAID FOR
----------------------------------------
1. **Edges are counted after welding vertices by POSITION.** glTF
   splits a vertex wherever its normal or UV differs, so the raw index
   buffer reports seams as holes. Welded answers "does this surface
   have a hole", which is the question `blended`'s drift catalog asks
   ("judge shipped GLBs on POSITION-WELDED topology").
2. **An inverted facet is a face that disagrees with ITSELF** —
   ``dot(face_normal_from_winding, mean(stored_corner_normals)) < 0``.
   Not edge contiguity: contiguity asks whether two adjacent faces
   agree, so an island wound inside-out passes it.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

# glTF 2.0 binary container layout (little-endian, 12-byte header then chunks).
GLB_MAGIC = 0x46546C67  # 'glTF'
GLB_HEADER_SIZE_BYTES = 12
GLB_CHUNK_HEADER_SIZE_BYTES = 8

# Round positions to this many decimals before welding. 1e-6 m = 1
# micron: far below any prop feature, far above float32 round-trip
# noise.
POSITION_WELD_DECIMALS = 6
# glTF core primitives are triangles in every file this harness ships.
GLTF_MODE_TRIANGLES = 4

_COMPONENT_FORMATS = {
    5120: ("b", 1),  # BYTE
    5121: ("B", 1),  # UNSIGNED_BYTE
    5122: ("h", 2),  # SHORT
    5123: ("H", 2),  # UNSIGNED_SHORT
    5125: ("I", 4),  # UNSIGNED_INT
    5126: ("f", 4),  # FLOAT
}
_COMPONENT_MAXIMA = {5121: 255.0, 5123: 65535.0}
_TYPE_COMPONENT_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


@dataclass(frozen=True)
class GlbMeshReport:
    """Per-mesh geometry facts, all read out of the file."""

    name: str
    triangle_count: int
    welded_boundary_edge_count: int
    non_manifold_edge_count: int
    inverted_facet_count: int
    has_normals: bool
    has_tangents: bool
    # Count of TEXCOORD_* attributes. `blended` gates UVs, so the file
    # must report them: an unwrapped scene that ships without its UV
    # layer is exactly the export-time drift this module exists to see.
    uv_set_count: int


@dataclass(frozen=True)
class GlbAssetReport:
    """Everything a rig-less prop contract asks about a shipped file."""

    path: str
    size_bytes: int
    mesh_names: list
    meshes: dict = field(default_factory=dict)  # name -> GlbMeshReport
    material_count: int = 0
    image_count: int = 0
    root_node_names: list = field(default_factory=list)
    node_names: list = field(default_factory=list)
    # From the POSITION accessors' min/max, which glTF requires.
    minimum_corner_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    maximum_corner_m: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @property
    def triangle_count(self) -> int:
        return sum(m.triangle_count for m in self.meshes.values())

    @property
    def welded_boundary_edge_count(self) -> int:
        return sum(m.welded_boundary_edge_count for m in self.meshes.values())

    @property
    def non_manifold_edge_count(self) -> int:
        return sum(m.non_manifold_edge_count for m in self.meshes.values())

    @property
    def inverted_facet_count(self) -> int:
        return sum(m.inverted_facet_count for m in self.meshes.values())

    @property
    def dimensions_m(self) -> tuple[float, float, float]:
        """glTF-space extents, max - min."""
        return tuple(
            self.maximum_corner_m[axis] - self.minimum_corner_m[axis]
            for axis in range(3)
        )


def parse_glb(path: Path) -> tuple[dict, bytes]:
    """Split a ``.glb`` into ``(gltf_json_dict, binary_chunk_bytes)``.

    Fails loudly on anything unexpected rather than returning a
    half-parsed file — a silently misread accessor becomes a confident
    wrong number, which is the failure mode this whole module exists to
    stop.
    """
    data = Path(path).read_bytes()
    if len(data) < GLB_HEADER_SIZE_BYTES:
        raise ValueError(f"parse_glb({path!r}): file is too short to be a .glb")
    magic, _version, declared_length = struct.unpack(
        "<III", data[:GLB_HEADER_SIZE_BYTES]
    )
    if magic != GLB_MAGIC:
        raise ValueError(f"parse_glb({path!r}): not a .glb — bad magic {magic:#x}")
    if declared_length != len(data):
        raise ValueError(
            f"parse_glb({path!r}): header declares {declared_length} bytes, "
            f"file is {len(data)}"
        )

    json_length = struct.unpack("<I", data[12:16])[0]
    json_start = GLB_HEADER_SIZE_BYTES + GLB_CHUNK_HEADER_SIZE_BYTES
    gltf = json.loads(data[json_start : json_start + json_length])

    binary_header = json_start + json_length
    binary_length = struct.unpack("<I", data[binary_header : binary_header + 4])[0]
    binary_start = binary_header + GLB_CHUNK_HEADER_SIZE_BYTES
    return gltf, data[binary_start : binary_start + binary_length]


def read_accessor(gltf: dict, binary: bytes, index: int) -> list[tuple[float, ...]]:
    """Decode accessor ``index`` into a list of component tuples,
    honouring byteStride and the ``normalized`` flag."""
    accessor = gltf["accessors"][index]
    if "sparse" in accessor:
        raise NotImplementedError(
            f"read_accessor({index}): sparse accessors are not decoded here. "
            f"Blender's exporter does not emit them, so encountering one means "
            f"the file came from elsewhere and every count below would be wrong."
        )
    if "bufferView" not in accessor:
        raise ValueError(
            f"read_accessor({index}): no bufferView (implicit-zero accessor)"
        )

    buffer_view = gltf["bufferViews"][accessor["bufferView"]]
    component_format, component_size = _COMPONENT_FORMATS[accessor["componentType"]]
    component_count = _TYPE_COMPONENT_COUNTS[accessor["type"]]
    start = buffer_view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = buffer_view.get("byteStride") or component_size * component_count
    layout = "<" + component_format * component_count
    divisor = (
        _COMPONENT_MAXIMA.get(accessor["componentType"])
        if accessor.get("normalized")
        else None
    )

    values = []
    for element in range(accessor["count"]):
        raw = struct.unpack_from(layout, binary, start + element * stride)
        values.append(tuple(v / divisor for v in raw) if divisor else raw)
    return values


def _weld(positions: list) -> list:
    """Map each vertex index to a POSITION-welded index. See the module
    docstring — this is what makes a boundary-edge count mean "hole in
    the surface" rather than "UV seam"."""
    welded, remap = {}, []
    for position in positions:
        key = tuple(round(component, POSITION_WELD_DECIMALS) for component in position)
        remap.append(welded.setdefault(key, len(welded)))
    return remap


def mesh_reports(gltf: dict, binary: bytes) -> dict[str, GlbMeshReport]:
    """``{mesh_name: GlbMeshReport}`` for every mesh in the file."""
    reports: dict[str, GlbMeshReport] = {}
    for mesh in gltf.get("meshes", []):
        triangles = inverted = boundary = nonmanifold = 0
        has_normals = has_tangents = False
        uv_set_count = 0
        edge_uses: dict = {}

        for primitive in mesh["primitives"]:
            attributes = primitive["attributes"]
            mode = primitive.get("mode", GLTF_MODE_TRIANGLES)
            if mode != GLTF_MODE_TRIANGLES:
                raise ValueError(
                    f"mesh {mesh.get('name', '<unnamed>')!r}: primitive mode "
                    f"{mode} is not triangles ({GLTF_MODE_TRIANGLES})"
                )
            has_tangents = has_tangents or "TANGENT" in attributes
            positions = read_accessor(gltf, binary, attributes["POSITION"])
            normals = (
                read_accessor(gltf, binary, attributes["NORMAL"])
                if "NORMAL" in attributes
                else None
            )
            has_normals = has_normals or normals is not None
            uv_set_count = max(
                uv_set_count,
                sum(1 for key in attributes if key.startswith("TEXCOORD_")),
            )

            indices = [i[0] for i in read_accessor(gltf, binary, primitive["indices"])]
            remap = _weld(positions)
            for corner in range(0, len(indices), 3):
                corner_indices = indices[corner : corner + 3]
                triangles += 1
                for first, second in ((0, 1), (1, 2), (2, 0)):
                    edge = tuple(
                        sorted(
                            (remap[corner_indices[first]], remap[corner_indices[second]])
                        )
                    )
                    edge_uses[edge] = edge_uses.get(edge, 0) + 1
                if normals is not None and _face_disagrees_with_itself(
                    positions, normals, corner_indices
                ):
                    inverted += 1

        boundary = sum(1 for uses in edge_uses.values() if uses == 1)
        nonmanifold = sum(1 for uses in edge_uses.values() if uses > 2)
        name = mesh.get("name", "<unnamed>")
        reports[name] = GlbMeshReport(
            name=name,
            triangle_count=triangles,
            welded_boundary_edge_count=boundary,
            non_manifold_edge_count=nonmanifold,
            inverted_facet_count=inverted,
            has_normals=has_normals,
            has_tangents=has_tangents,
            uv_set_count=uv_set_count,
        )
    return reports


def _face_disagrees_with_itself(positions, normals, corner_indices) -> bool:
    a, b, c = (positions[i] for i in corner_indices)
    edge_1 = [b[i] - a[i] for i in range(3)]
    edge_2 = [c[i] - a[i] for i in range(3)]
    winding_normal = (
        edge_1[1] * edge_2[2] - edge_1[2] * edge_2[1],
        edge_1[2] * edge_2[0] - edge_1[0] * edge_2[2],
        edge_1[0] * edge_2[1] - edge_1[1] * edge_2[0],
    )
    stored_normal = [sum(normals[i][axis] for i in corner_indices) / 3.0 for axis in range(3)]
    return sum(winding_normal[axis] * stored_normal[axis] for axis in range(3)) < 0.0


def asset_report(path: Path) -> GlbAssetReport:
    """Everything the prop pipeline asks about a shipped file, read out
    of ``path``."""
    gltf, binary = parse_glb(path)
    nodes = gltf.get("nodes", [])
    scene = gltf.get("scenes", [{}])[gltf.get("scene", 0)]

    minimum_corner = (math.inf, math.inf, math.inf)
    maximum_corner = (-math.inf, -math.inf, -math.inf)
    for mesh in gltf.get("meshes", []):
        for primitive in mesh["primitives"]:
            position_accessor = gltf["accessors"][primitive["attributes"]["POSITION"]]
            minimum = position_accessor.get("min")
            maximum = position_accessor.get("max")
            if minimum is None or maximum is None:
                raise ValueError(
                    f"mesh {mesh.get('name', '<unnamed>')!r}: POSITION accessor "
                    f"has no min/max — glTF requires them"
                )
            minimum_corner = tuple(
                min(existing, value)
                for existing, value in zip(minimum_corner, minimum)
            )
            maximum_corner = tuple(
                max(existing, value)
                for existing, value in zip(maximum_corner, maximum)
            )

    return GlbAssetReport(
        path=str(path),
        size_bytes=Path(path).stat().st_size,
        mesh_names=[mesh.get("name", "") for mesh in gltf.get("meshes", [])],
        meshes=mesh_reports(gltf, binary),
        material_count=len(gltf.get("materials", [])),
        image_count=len(gltf.get("images", [])),
        root_node_names=[nodes[i].get("name", "") for i in scene.get("nodes", [])],
        node_names=[node.get("name", "") for node in nodes],
        minimum_corner_m=minimum_corner,
        maximum_corner_m=maximum_corner,
    )


def format_glb_report(
    report: GlbAssetReport, baseline: GlbAssetReport | None = None
) -> str:
    """Human-readable report; with ``baseline``, only the meshes that
    CHANGED are listed, plus explicit added/removed mesh lines."""
    lines = [
        f"{report.path}",
        f"  bytes ................. {report.size_bytes:,}",
        f"  triangles ............. {report.triangle_count:,}",
        f"  boundary edges ........ {report.welded_boundary_edge_count}  "
        f"(welded by position)",
        f"  non-manifold edges .... {report.non_manifold_edge_count}",
        f"  inverted facets ....... {report.inverted_facet_count}",
        f"  materials / images .... {report.material_count} / {report.image_count}",
        f"  root node(s) .......... {report.root_node_names}",
        f"  extents (m) ........... "
        f"{', '.join(f'{value:.4f}' for value in report.dimensions_m)}",
        ]
    if baseline is not None:
        removed = sorted(set(baseline.mesh_names) - set(report.mesh_names))
        added = sorted(set(report.mesh_names) - set(baseline.mesh_names))
        lines += [
            "",
            f"  vs baseline {baseline.path}:",
            f"    meshes removed: {removed or 'none'}",
            f"    meshes added:   {added or 'none'}",
        ]

    lines += ["", "  per mesh (tris / boundary / non-manifold / inverted / UV sets):"]
    for name in sorted(report.meshes):
        mesh = report.meshes[name]
        if baseline is not None:
            was = baseline.meshes.get(name)
            if was is not None and (
                was.triangle_count,
                was.welded_boundary_edge_count,
                was.non_manifold_edge_count,
                was.inverted_facet_count,
            ) == (
                mesh.triangle_count,
                mesh.welded_boundary_edge_count,
                mesh.non_manifold_edge_count,
                mesh.inverted_facet_count,
            ):
                continue
        lines.append(
            f"    {name:28s} {mesh.triangle_count:6d} "
            f"{mesh.welded_boundary_edge_count:6d} {mesh.non_manifold_edge_count:5d} "
            f"{mesh.inverted_facet_count:5d}  {mesh.uv_set_count}"
        )
    return "\n".join(lines)
