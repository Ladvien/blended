"""Reference-free relations over the three builders.

Every number in this file was measured before it was asserted (Blender
5.2.0, hash fbe6228777e7, 2026-09-06). The two that matter, because
they are the ones that would otherwise have been "obviously" wrong:

* PALLET, doubled: x and y double exactly, z overshoots by
  0.0004999935 m. That is `BOOLEAN_EMBED_M` (0.0005 m), an ABSOLUTE
  overlap the builder subtracts from its stack height so no boolean
  ever sees coplanar faces. It does not scale with the parameters, so
  the honest relation is `2 * before + BOOLEAN_EMBED_M`, not
  `2 * before`. Loosening the tolerance to 3e-3 to cover it would have
  hidden a real 0.5 mm of non-scale-invariance behind a round number.
* PALLET at 0.01x raises `ValueError: Deck boards thinner than the
  boolean embed` from `PalletParameters.validate` — 0.022 m x 0.01 is
  0.22 mm against a 0.5 mm embed. A builder refusing invalid
  parameters is correct, so the small-scale relation runs at the
  smallest factor its own validation accepts (0.05x, measured clean:
  0 non-manifold, 0 boundary, 0 self-intersecting).

Pallet triangle counts are NOT scale-invariant (334 at 1x, 344 at 0.1x,
348 at 0.05x): the EXACT boolean solver retriangulates differently when
the fixed 0.5 mm embed is relatively larger. That is why the
small-scale relation asserts topology and not triangle count.
"""

import dataclasses

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

# Doubling is exact arithmetic on the parameters, so the tolerance is
# float32 storage noise only (measured: 0.0 error at 2x on all three
# builders).
SCALE_REL_TOL = 1.0e-6

# Refinement must not resize the object. Measured: exactly 0.0 relative
# change on all three builders, so 1e-3 is three orders of slack, kept
# because a retriangulating boolean is entitled to move a vertex by
# less than a millimetre of a metre.
REFINEMENT_DIMENSION_REL_TOL = 1.0e-3

DOUBLE_FACTOR = 2.0
SMALL_SCALE_FACTOR = 0.01
# See the module docstring: 0.01x is refused by PalletParameters.validate.
PALLET_SMALL_SCALE_FACTOR = 0.05

# The count field each builder refines, and the refined value.
REFINED_COUNTS = {
    "barrel": ("segment_count", 32),
    "crate": ("bevel_segment_count", 4),
    "pallet": ("deck_board_count", 6),
}


def _builders():
    from blended.builders import (
        BarrelBuilder,
        BarrelParameters,
        CrateBuilder,
        CrateParameters,
        PalletBuilder,
        PalletParameters,
    )

    return {
        "barrel": (BarrelBuilder, BarrelParameters()),
        "crate": (CrateBuilder, CrateParameters()),
        "pallet": (PalletBuilder, PalletParameters()),
    }


def _length_field_names(parameters) -> tuple[str, ...]:
    """Every `_m` field: the units-in-names convention is what makes a
    uniform-scale transform expressible without a per-builder list."""
    return tuple(
        field.name
        for field in dataclasses.fields(parameters)
        if field.name.endswith("_m")
    )


def _scale_lengths(parameters, factor):
    return dataclasses.replace(
        parameters,
        **{
            name: getattr(parameters, name) * factor
            for name in _length_field_names(parameters)
        },
    )


def _uniform_scale_relation(factor, z_absolute_residue_m):
    """Every extent scales; topology does not move."""
    from blended.analyze import all_of, grew_by, scaled_by, unchanged

    def relation(before, after):
        return all_of(
            scaled_by(
                "dimension_x_m",
                before["dimension_x_m"],
                after["dimension_x_m"],
                factor,
                rel_tol=SCALE_REL_TOL,
            ),
            scaled_by(
                "dimension_y_m",
                before["dimension_y_m"],
                after["dimension_y_m"],
                factor,
                rel_tol=SCALE_REL_TOL,
            ),
            # z carries the builder's absolute boolean embed, if it has
            # one: expected = before * factor + residue.
            grew_by(
                "dimension_z_m",
                before["dimension_z_m"] * factor,
                after["dimension_z_m"],
                z_absolute_residue_m,
                rel_tol=SCALE_REL_TOL,
            ),
            unchanged(
                "triangle_count",
                before["triangle_count"],
                after["triangle_count"],
            ),
            unchanged(
                "connected_component_count",
                before["connected_component_count"],
                after["connected_component_count"],
            ),
            unchanged(
                "inverted_facet_count",
                before["inverted_facet_count"],
                after["inverted_facet_count"],
            ),
        )

    return relation


def _refinement_relation(before, after):
    """More segments: more triangles, same size."""
    from blended.analyze import all_of, strictly_increased, unchanged

    return all_of(
        strictly_increased(
            "triangle_count", before["triangle_count"], after["triangle_count"]
        ),
        *[
            unchanged(
                axis,
                before[axis],
                after[axis],
                rel_tol=REFINEMENT_DIMENSION_REL_TOL,
            )
            for axis in ("dimension_x_m", "dimension_y_m", "dimension_z_m")
        ],
    )


def _topology_relation(before, after):
    """Scale is not allowed to change what the mesh IS."""
    from blended.analyze import all_of, unchanged

    return all_of(
        *[
            unchanged(label, before[label], after[label])
            for label in (
                "non_manifold_edge_count",
                "boundary_edge_count",
                "self_intersecting_face_pair_count",
                "connected_component_count",
            )
        ]
    )


def _relations_for(builder_name, parameters):
    from blended.analyze import Relation
    from blended.builders.pallet import BOOLEAN_EMBED_M

    z_residue_m = BOOLEAN_EMBED_M if builder_name == "pallet" else 0.0
    small_factor = (
        PALLET_SMALL_SCALE_FACTOR
        if builder_name == "pallet"
        else SMALL_SCALE_FACTOR
    )
    field_name, refined_value = REFINED_COUNTS[builder_name]

    return (
        Relation(
            name="uniform_scale_doubles_every_extent",
            transform=lambda parameters: _scale_lengths(parameters, DOUBLE_FACTOR),
            relation=_uniform_scale_relation(DOUBLE_FACTOR, z_residue_m),
            justification=(
                "A build is a shape function of its parameters, so scaling "
                "every length must scale every extent and change no "
                "topology. This is the relation a parameter applied as an "
                "absolute rather than a proportion breaks — the barrel's "
                "bulge is a fraction of end_radius_m (barrel.py:43-47), and "
                "the pallet's 0.5 mm boolean embed is the one absolute that "
                "legitimately survives, which is why it is named in the "
                "relation instead of hidden in a tolerance."
            ),
        ),
        Relation(
            name="more_segments_adds_triangles_not_size",
            transform=lambda parameters: dataclasses.replace(
                parameters, **{field_name: refined_value}
            ),
            relation=_refinement_relation,
            justification=(
                "Refinement is a resolution change, not a shape change: a "
                "finer segment/bevel/board count must add triangles while "
                "leaving every extent where it was. A builder that resized "
                "when refined would be applying its count to a dimension."
            ),
        ),
        Relation(
            name="topology_is_scale_invariant",
            transform=lambda parameters: _scale_lengths(parameters, small_factor),
            relation=_topology_relation,
            justification=(
                "A mesh that only becomes non-manifold at some scales has "
                "an absolute epsilon buried in it. Nothing in a boolean "
                "union, a bevel or a lathe is entitled to depend on the "
                "object's size in metres."
            ),
        ),
    )


@pytest.mark.parametrize("builder_name", sorted(REFINED_COUNTS))
def test_builders_satisfy_their_metamorphic_relations(builder_name):
    from blended.analyze import probe

    builder_class, parameters = _builders()[builder_name]
    report = probe(
        lambda built_parameters: builder_class(built_parameters).build(),
        parameters,
        _relations_for(builder_name, parameters),
    )

    assert report.failures() == []
    assert report.ok


def test_a_relation_without_a_justification_is_refused():
    """A relation nobody can justify is a relation nobody can falsify."""
    from blended.analyze import Relation, all_of, probe, unchanged

    unjustified = Relation(
        name="unjustified",
        transform=lambda parameters: parameters,
        relation=lambda before, after: all_of(
            unchanged("triangle_count", before["triangle_count"], after["triangle_count"])
        ),
        justification="   ",
    )
    builder_class, parameters = _builders()["crate"]

    with pytest.raises(ValueError, match="justification"):
        probe(
            lambda built_parameters: builder_class(built_parameters).build(),
            parameters,
            (unjustified,),
        )


def test_a_broken_relation_fails_instead_of_being_swallowed():
    """A relation that raises is not a relation that passed."""
    from blended.analyze import Relation, probe

    def raise_instead(before, after):
        raise RuntimeError("the relation itself is broken")

    broken = Relation(
        name="broken",
        transform=lambda parameters: parameters,
        relation=raise_instead,
        justification="proves an unevaluable relation cannot report success",
    )
    builder_class, parameters = _builders()["crate"]

    report = probe(
        lambda built_parameters: builder_class(built_parameters).build(),
        parameters,
        (broken,),
    )

    assert not report.ok
    assert report.failures() == ["broken: raised RuntimeError: the relation itself is broken"]


def test_the_scale_relation_can_actually_fail():
    """A relation that cannot fail is not a gate.

    The proof runs against the same builder with a transform that
    scales only ONE axis' parameter, which is exactly the defect class
    the relation exists to catch (a length applied as an absolute).
    """
    from blended.analyze import Relation, probe

    builder_class, parameters = _builders()["crate"]
    half_scaled = Relation(
        name="only_width_doubled",
        transform=lambda p: dataclasses.replace(p, width_m=p.width_m * DOUBLE_FACTOR),
        relation=_uniform_scale_relation(DOUBLE_FACTOR, 0.0),
        justification="negative control: one axis scaled must break the relation",
    )

    report = probe(
        lambda built_parameters: builder_class(built_parameters).build(),
        parameters,
        (half_scaled,),
    )

    assert not report.ok
    failed_labels = [failure.split(": ")[1] for failure in report.failures()]
    assert "dimension_y_m" in failed_labels
    assert "dimension_z_m" in failed_labels
    assert "dimension_x_m" not in failed_labels
