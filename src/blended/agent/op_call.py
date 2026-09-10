"""A facade op called as a tool (OT-4, AGT-21).

`dispatch_tool` routes a generated op tool here. The arguments the model
sent are JSON; the op wants Python — a `tuple[float, float, float]`, a
`SplayedLegSpec`, a `Path`. Binding converts one to the other against
the signature's own type hints, the same hints the schema was generated
from (`agent.tool_schemas`), and fails loud on an unknown, missing or
mistyped parameter (NFR-13): a call the schema would have rejected is
rejected here too, so a lane without constrained decoding gets the
same door.

Execution goes through `run.executor.execute_captured`, the one capture
path a Python chunk also takes, and the result speaks the stage
vocabulary of `blended.stages` (EXE-6): an op call that raised FAILED at
`execute`; one that returned reached `done`. Gating a returned object
(locate, gate) is OT-5.

Pure: the binding and the result are testable without Blender; only the
op body reaches bpy.
"""

from __future__ import annotations

import dataclasses
import inspect
import pathlib
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass, field

from blended.run.executor import RunResult, execute_captured
from blended.stages import STAGE_DONE, STAGE_EXECUTE
from blended.version import TARGET_BLENDER_SERIES


class ArgumentError(TypeError):
    """The model's arguments do not fit the op's signature."""


# The version an op call reports. `assert_supported_blender` has already
# refused any other series by the time a tool runs, so the pinned series
# is the running one at the precision the harness pins.
PINNED_SERIES_TEXT = f"{TARGET_BLENDER_SERIES[0]}.{TARGET_BLENDER_SERIES[1]}"


# --- binding: JSON arguments -> the signature's Python types -------------


def bind_arguments(op_name: str, function: Callable, arguments: dict) -> dict:
    """Keyword arguments for `function`, converted and complete, or ArgumentError."""
    if not isinstance(arguments, dict):
        raise ArgumentError(
            f"{op_name}: arguments must be an object, got {type(arguments).__name__}"
        )
    signature = inspect.signature(function)
    hints = typing.get_type_hints(function)
    unknown = sorted(set(arguments) - set(signature.parameters))
    if unknown:
        raise ArgumentError(
            f"{op_name}: unknown parameter(s) {unknown}; it takes "
            f"{list(signature.parameters)}"
        )
    missing = [
        name
        for name, parameter in signature.parameters.items()
        if parameter.default is inspect.Parameter.empty and name not in arguments
    ]
    if missing:
        raise ArgumentError(f"{op_name}: missing required parameter(s) {missing}")
    return {
        name: convert_argument(hints[name], value, f"{op_name}.{name}")
        for name, value in arguments.items()
    }


def convert_argument(hint, value, path: str):
    """`value` as the Python type `hint` names, recursively, or ArgumentError.

    Strict on purpose: a bool is not an int, a string is not a number.
    Every rule here mirrors one in `tool_schemas.json_schema_for_type`.
    """
    if hint is type(None):
        if value is not None:
            raise ArgumentError(f"{path}: expected null, got {value!r}")
        return None
    if hint is bool:
        if not isinstance(value, bool):
            raise ArgumentError(f"{path}: expected a boolean, got {value!r}")
        return value
    if hint is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ArgumentError(f"{path}: expected an integer, got {value!r}")
        return value
    if hint is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ArgumentError(f"{path}: expected a number, got {value!r}")
        return float(value)
    if hint is str:
        if not isinstance(value, str):
            raise ArgumentError(f"{path}: expected a string, got {value!r}")
        return value
    if hint is pathlib.Path:
        if not isinstance(value, str):
            raise ArgumentError(f"{path}: expected a path string, got {value!r}")
        return pathlib.Path(value)
    origin = typing.get_origin(hint)
    members = typing.get_args(hint)
    if origin in (types.UnionType, typing.Union):
        failures: list[str] = []
        for member in members:
            try:
                return convert_argument(member, value, path)
            except ArgumentError as error:
                failures.append(str(error))
        raise ArgumentError(f"{path}: none of the accepted types fit: " + " | ".join(failures))
    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise ArgumentError(f"{path}: expected an array, got {value!r}")
        if len(members) == 2 and members[1] is Ellipsis:
            return tuple(
                convert_argument(members[0], item, f"{path}[{index}]")
                for index, item in enumerate(value)
            )
        if len(value) != len(members):
            raise ArgumentError(
                f"{path}: expected exactly {len(members)} items, got {len(value)}"
            )
        return tuple(
            convert_argument(member, item, f"{path}[{index}]")
            for index, (member, item) in enumerate(zip(members, value))
        )
    if origin is list:
        if not isinstance(value, (list, tuple)):
            raise ArgumentError(f"{path}: expected an array, got {value!r}")
        return [
            convert_argument(members[0], item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if dataclasses.is_dataclass(hint) and isinstance(hint, type):
        if not isinstance(value, dict):
            raise ArgumentError(f"{path}: expected an object for {hint.__name__}, got {value!r}")
        field_hints = typing.get_type_hints(hint)
        field_names = [config_field.name for config_field in dataclasses.fields(hint)]
        unknown = sorted(set(value) - set(field_names))
        if unknown:
            raise ArgumentError(
                f"{path}: unknown field(s) {unknown} for {hint.__name__}; it takes {field_names}"
            )
        missing = [
            config_field.name
            for config_field in dataclasses.fields(hint)
            if config_field.default is dataclasses.MISSING
            and config_field.default_factory is dataclasses.MISSING
            and config_field.name not in value
        ]
        if missing:
            raise ArgumentError(f"{path}: missing required field(s) {missing} for {hint.__name__}")
        return hint(
            **{
                name: convert_argument(field_hints[name], item, f"{path}.{name}")
                for name, item in value.items()
            }
        )
    raise ArgumentError(f"{path}: the signature type {hint!r} has no binding rule")


# --- the result ----------------------------------------------------------------


def json_returned(value):
    """What an op returned, as JSON the model can read. Loud on anything else."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, pathlib.Path):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [json_returned(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_returned(item) for key, item in value.items()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return json_returned(dataclasses.asdict(value))
    raise TypeError(f"op returned {type(value).__name__}, which has no JSON form")


@dataclass(frozen=True)
class OpCallResult:
    ok: bool
    stage_reached: str  # one of blended.stages.STAGES (EXE-6)
    op_name: str
    arguments: dict
    execution: RunResult
    returned: object = None
    bound_arguments: dict = field(default_factory=dict)

    def summary(self, maximum_traceback_characters: int) -> str:
        """The text the model reads. Same first line shape as `HarnessResult`."""
        import json

        verdict = "OK" if self.ok else f"FAILED at {self.stage_reached}"
        lines = [f"{verdict}: {self.op_name}", f"  execute: {self.execution.summary()}"]
        if self.ok:
            lines.append(f"  returned: {json.dumps(self.returned)}")
        elif self.execution.error_type != ArgumentError.__name__:
            # A binding failure IS its message; the frames below it are
            # this module's, not the model's. An op's own traceback is
            # kept, bounded to the observation window like run_python's.
            lines.append(self.execution.traceback_text[:maximum_traceback_characters])
        return "\n".join(lines)


def call_op(op_name: str, function: Callable, arguments: dict) -> OpCallResult:
    """Bind, run, report. Never raises for the model's mistakes or the op's."""
    bound: dict = {}

    def bind_and_call():
        nonlocal bound
        bound = bind_arguments(op_name, function, arguments)
        return function(**bound)

    execution, returned = execute_captured(bind_and_call, op_name, PINNED_SERIES_TEXT)
    if not execution.ok:
        return OpCallResult(
            ok=False,
            stage_reached=STAGE_EXECUTE,
            op_name=op_name,
            arguments=arguments,
            execution=execution,
            bound_arguments=bound,
        )
    return OpCallResult(
        ok=True,
        stage_reached=STAGE_DONE,
        op_name=op_name,
        arguments=arguments,
        execution=execution,
        returned=json_returned(returned),
        bound_arguments=bound,
    )
