"""Runs INSIDE `blender --background --python`; must not import blended.

Reads:  argv after "--" -> [script_path, result_json_path]
Writes: result JSON {ok, blender_version, error_type, error_message,
        traceback_text, stdout_text}
"""

import contextlib
import io
import json
import sys
import traceback


def main() -> None:
    import bpy

    argument_separator_index = sys.argv.index("--")
    script_path, result_json_path = sys.argv[argument_separator_index + 1 :][:2]

    result = {
        "ok": True,
        "blender_version": bpy.app.version_string,
        "error_type": "",
        "error_message": "",
        "traceback_text": "",
        "stdout_text": "",
    }
    stdout_buffer = io.StringIO()
    try:
        with open(script_path, "r", encoding="utf-8") as script_file:
            source_code = script_file.read()
        compiled = compile(source_code, script_path, "exec")
        # Executing agent-authored source is the whole point of the executor.
        with contextlib.redirect_stdout(stdout_buffer):
            exec(compiled, {"__name__": "__main__"})  # noqa: S102
    except Exception as error:  # noqa: BLE001
        result.update(
            ok=False,
            error_type=type(error).__name__,
            error_message=str(error),
            traceback_text=traceback.format_exc(),
        )
    result["stdout_text"] = stdout_buffer.getvalue()
    with open(result_json_path, "w", encoding="utf-8") as result_file:
        json.dump(result, result_file)


main()
