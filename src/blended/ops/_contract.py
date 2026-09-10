"""OPS-21: the machine-checkable contract every facade op satisfies.

The schema generator (`blended.agent.tool_schemas`, OT-3) can only emit
what a signature carries, so the signature has to carry everything:
annotated parameters, a return annotation, unit suffixes on quantities
(NFR-8), a one-line description, and no bpy type anywhere — object
references are NAMES, resolved by `blended.ops._objects`. The manifest
renders these signatures into the prompt and the generator renders them
into tool schemas; a violation here is a violation the model reads.

One definition, two readers: `tests/pure/test_ops_signature_contract.py`
asserts it over the facade and proves it can fail on a seeded-defect
op; `build_tool_schemas()` refuses an op that violates it. Pure —
introspection only, no Blender.

Private (underscore module): shared plumbing, not an op, not in the
manifest, not a tool.
"""

from __future__ import annotations

import inspect
import re

# --- the contract -------------------------------------------------------

# Parameter names ending in one of these carry a unit and need no
# further justification. NFR-8.
UNIT_SUFFIXES = ("_m", "_deg", "_rad", "_px", "_s", "_m2", "_m3")

# Names that are QUANTITIES by contract but unitless by nature: counts,
# ratios, indices, frames, weights in [0, 1]. Anything numeric that is
# not in this list and does not carry a unit suffix is a violation.
UNITLESS_NUMERIC_NAMES = frozenset(
    {
        "count",
        "segment_count",
        "frame",
        "start_frame",
        "end_frame",
        "roughness",
        "scale",
        "weight",
        "island_margin",
        "vertex_indices",
        "base_color_rgb",
        "color_a_rgb",
        "color_b_rgb",
        "location_m",
    }
)

# Types that must never appear in a facade signature: an agent tool
# cannot pass an RNA struct. Object references travel as `str` names.
# Matched as whole tokens: `MaterialReport` is a frozen dataclass, not
# `bpy.types.Material`.
FORBIDDEN_TYPE_TOKENS = ("bpy", "Object", "Mesh", "Scene", "Material", "Any")
_FORBIDDEN_TYPE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(FORBIDDEN_TYPE_TOKENS) + r")(?![A-Za-z0-9_])"
)

NUMERIC_ANNOTATIONS = {"int", "float"}

# An object-name parameter is `str`, or `str | None` when the op has a
# scene-wide default (apply_canonical_depth_axis). Nothing else.
NAME_ANNOTATIONS = {"str", "str | None", "None | str", "Optional[str]"}

# Names for the object being acted on. Given so the rule "object refs are
# str" can be checked by NAME too: `blender_object`, `obj`, `mesh_object`
# were the pre-OT-2 spellings that carried bpy objects.
FORBIDDEN_PARAMETER_NAMES = frozenset(
    {"blender_object", "obj", "mesh_object", "armature_object", "scene"}
)
_OBJECT_NAME_PATTERN = re.compile(r"(^|_)name$|_names$")

MAXIMUM_SUMMARY_CHARACTERS = 120




class ContractViolation(TypeError):
    """An op reached the generator without satisfying OPS-21."""


# --- readers -------------------------------------------------------------


def facade_ops() -> list[tuple[str, object]]:
    """Every function the facade exports, as (name, function), in facade order."""
    import blended.ops as ops_facade

    return [
        (name, getattr(ops_facade, name))
        for name in ops_facade.__all__
        if inspect.isfunction(getattr(ops_facade, name))
    ]


def _annotation_text(annotation) -> str:
    if annotation is inspect.Parameter.empty:
        return ""
    if isinstance(annotation, str):
        return annotation
    return getattr(annotation, "__name__", None) or str(annotation)


def _numeric_scalar(annotation_text: str) -> bool:
    return annotation_text in NUMERIC_ANNOTATIONS


def contract_violations(function) -> list[str]:
    """Every way `function` fails OPS-21, as one line each."""
    violations: list[str] = []
    signature = inspect.signature(function)

    for parameter in signature.parameters.values():
        annotation_text = _annotation_text(parameter.annotation)
        if not annotation_text:
            violations.append(f"parameter {parameter.name!r} has no annotation")
        if parameter.name in FORBIDDEN_PARAMETER_NAMES:
            violations.append(
                f"parameter {parameter.name!r} names a bpy object; take a name (str)"
            )
        if _FORBIDDEN_TYPE_PATTERN.search(annotation_text):
            violations.append(
                f"parameter {parameter.name!r} is annotated {annotation_text!r}, a bpy type"
            )
        if _OBJECT_NAME_PATTERN.search(parameter.name) and annotation_text not in NAME_ANNOTATIONS:
            violations.append(
                f"parameter {parameter.name!r} looks like a name but is {annotation_text!r}"
            )
        if _numeric_scalar(annotation_text):
            has_unit = parameter.name.endswith(UNIT_SUFFIXES)
            if not has_unit and parameter.name not in UNITLESS_NUMERIC_NAMES:
                violations.append(
                    f"numeric parameter {parameter.name!r} carries no unit suffix "
                    f"{UNIT_SUFFIXES} and is not a declared unitless quantity"
                )

    return_text = _annotation_text(signature.return_annotation)
    if not return_text:
        violations.append("no return annotation")
    elif _FORBIDDEN_TYPE_PATTERN.search(return_text):
        violations.append(f"return annotation {return_text!r} is a bpy type")

    docstring = inspect.getdoc(function) or ""
    first_line, _, rest = docstring.partition("\n")
    if not first_line.strip():
        violations.append("no docstring")
    elif rest and rest.split("\n", 1)[0].strip():
        violations.append("docstring summary is not a single line followed by a blank")
    elif len(first_line) > MAXIMUM_SUMMARY_CHARACTERS:
        violations.append(f"docstring summary longer than {MAXIMUM_SUMMARY_CHARACTERS} chars")

    return violations



def assert_satisfies_contract(op_name: str, function) -> None:
    """Raise ContractViolation naming every way `function` fails OPS-21."""
    violations = contract_violations(function)
    if violations:
        raise ContractViolation(f"{op_name}: " + "; ".join(violations))
