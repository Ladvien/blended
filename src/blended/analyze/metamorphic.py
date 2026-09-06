"""Metamorphic relations: the gate that needs no reference.

Every other gate in this repository needs a specification that already
exists. `evaluate.acceptance` needs a brief with numbers in it;
`evaluate.visual_diff` needs a pinned golden render. Both are useless
the moment the thing being built has no spec — which is exactly the
hole `scripts/photo_to_model.py` declares: a photograph carries no
dimensions.

A metamorphic relation needs neither. It changes the INPUT in a known
way and asserts a relation between the two OUTPUTS. Double every length
and every extent must double. Refine the segment count and the triangle
count must rise while the extents stay put. Neither claim needs to know
what the object is, so both survive having no brief.

THE ONE AUTHORING RULE, learned the expensive way: a relation must be
anchored in the SEMANTICS of what is being built, never in the
implementation's own arithmetic. A relation whose invariant set is read
off the artefact under test is VACUOUS. scp measured it: a
"these vertices must not move" relation defined its must-not-move set
as "the vertices with zero weight on this bone" — read from the same
weights the relation was testing — and deliberately bleeding weight
onto 200 vertices produced ZERO violations. The set moved with the
defect. Anchor the invariant outside the artefact: in the parameters,
in the constant, in the arithmetic a human can do on paper.

Which is why `Relation.justification` is a required field. A relation
nobody can justify is a relation nobody can falsify, and `probe`
refuses to run one.

MAIN THREAD ONLY: `measure_build` and `probe` touch bpy.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Comparisons that should be exact arithmetic get float-noise room and
# nothing more: a relation with a generous tolerance is a relation that
# passes on a build it should have caught.
EXACT_REL_TOL = 1.0e-9

# `strictly_increased` deliberately predicts no magnitude, so it needs a
# floor that a float wobble cannot climb.
STRICT_MARGIN = 1.0e-6


@dataclass(frozen=True)
class RelationOutcome:
    """One checked quantity: what was compared, and what was measured."""

    label: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Relation:
    """One (transform, relation) pair, with the reason it must hold.

    `transform` maps parameters to parameters — the follow-up input.
    `relation` receives the source and follow-up measurement dicts and
    returns every outcome it checked.
    """

    name: str
    transform: Callable[[Any], Any]
    relation: Callable[[dict, dict], tuple[RelationOutcome, ...]]
    justification: str


@dataclass(frozen=True)
class MetamorphicReport:
    outcomes: dict[str, tuple[RelationOutcome, ...]]
    errors: dict[str, str]

    @property
    def ok(self) -> bool:
        """A relation that RAISED is not a relation that passed."""
        if self.errors:
            return False
        return all(
            outcome.ok
            for outcomes in self.outcomes.values()
            for outcome in outcomes
        )

    def failures(self) -> list[str]:
        """Every failed outcome and every error, named."""
        found: list[str] = []
        for name, outcomes in sorted(self.outcomes.items()):
            for outcome in outcomes:
                if not outcome.ok:
                    found.append(f"{name}: {outcome.label}: {outcome.detail}")
        for name, error in sorted(self.errors.items()):
            found.append(f"{name}: raised {error}")
        return found


def _outcome(label: str, ok: bool, detail: str) -> RelationOutcome:
    return RelationOutcome(label=label, ok=ok, detail=detail)


def unchanged(label, before, after, rel_tol=EXACT_REL_TOL) -> RelationOutcome:
    """`after` must equal `before`."""
    ok = math.isclose(after, before, rel_tol=rel_tol, abs_tol=rel_tol)
    return _outcome(label, ok, f"{before} -> {after}, expected unchanged")


def scaled_by(label, before, after, factor, rel_tol=EXACT_REL_TOL) -> RelationOutcome:
    """`after` must equal `before * factor`."""
    expected = before * factor
    ok = math.isclose(after, expected, rel_tol=rel_tol, abs_tol=rel_tol)
    return _outcome(
        label, ok, f"{before} -> {after}, expected {expected} (x{factor})"
    )


def grew_by(label, before, after, delta, rel_tol=EXACT_REL_TOL) -> RelationOutcome:
    """`after` must equal `before + delta`.

    This is the predicate for a quantity whose transform leaves a known
    ABSOLUTE residue behind — a fixed epsilon that does not scale with
    the parameters. Naming the residue is how the relation stays exact
    instead of being loosened until it stops measuring.
    """
    expected = before + delta
    ok = math.isclose(after, expected, rel_tol=rel_tol, abs_tol=rel_tol)
    return _outcome(
        label, ok, f"{before} -> {after}, expected {expected} (+{delta})"
    )


def strictly_increased(label, before, after, margin=STRICT_MARGIN) -> RelationOutcome:
    """`after` must exceed `before`, by more than float noise.

    Deliberately predicts no magnitude: how many triangles a finer
    segment count adds is an implementation detail, and a relation that
    predicted it would be asserting the implementation back at itself.
    """
    ok = after > before + margin
    return _outcome(
        label, ok, f"{before} -> {after}, expected a strict increase"
    )


def all_of(*outcomes: RelationOutcome) -> tuple[RelationOutcome, ...]:
    """Every outcome, evaluated. NEVER short-circuits.

    Stopping at the first failure hides whether one quantity is wrong
    or all of them are — which is the difference between a typo and a
    wrong formula.
    """
    return tuple(outcomes)


def measure_build(blender_object) -> dict:
    """The quantities a relation may speak about.

    Everything here comes from `analyze_object` or the object's world
    dimensions. There is no second measurement path on purpose: a gate
    measuring with its own private probe is a gate whose disagreements
    with the rest of the harness cannot be adjudicated.
    """
    import bpy

    from blended.analyze.mesh_checks import analyze_object

    bpy.context.view_layer.update()
    report = analyze_object(blender_object)
    dimensions = blender_object.dimensions
    return {
        "triangle_count": report.triangle_count,
        "connected_component_count": report.connected_component_count,
        "non_manifold_edge_count": report.non_manifold_edge_count,
        "boundary_edge_count": report.boundary_edge_count,
        "self_intersecting_face_pair_count": (
            report.self_intersecting_face_pair_count
        ),
        "inverted_facet_count": report.inverted_facet_count,
        "dimension_x_m": dimensions[0],
        "dimension_y_m": dimensions[1],
        "dimension_z_m": dimensions[2],
    }


def probe(build, parameters, relations) -> MetamorphicReport:
    """Build the source case, then each follow-up case, and check R.

    `build` takes parameters and returns the built object. The scene is
    reset before EVERY build, source and follow-up alike, so no
    follow-up measures residue from the case before it.

    A relation that raises is recorded in `errors`, which makes the
    report not-ok. Nothing is swallowed: a relation that could not be
    evaluated is a relation that did not pass.
    """
    from blended.reset import reset_scene

    for relation in relations:
        if not relation.justification.strip():
            raise ValueError(
                f"relation {relation.name!r} carries no justification: a "
                f"relation nobody can justify is a relation nobody can "
                f"falsify"
            )

    reset_scene()
    source_measurements = measure_build(build(parameters))

    outcomes: dict[str, tuple[RelationOutcome, ...]] = {}
    errors: dict[str, str] = {}
    for relation in relations:
        try:
            reset_scene()
            follow_up_parameters = relation.transform(parameters)
            follow_up_measurements = measure_build(build(follow_up_parameters))
            outcomes[relation.name] = relation.relation(
                source_measurements, follow_up_measurements
            )
        except Exception as error:  # noqa: BLE001 — reported, not raised
            errors[relation.name] = f"{type(error).__name__}: {error}"
    return MetamorphicReport(outcomes=outcomes, errors=errors)
