"""Renders the conversational agent's system prompt.

Distinct from `manifest.build_manifest()`, which is a one-shot brief for
"write this script". This is for a modeling PARTNER the user chats with
inside Blender across many turns: it establishes the working
relationship, the tool discipline, and — most importantly — what
counts as done.

The core instruction is the one the whole harness exists to enforce:
running without an error is not success, and a render that looks right
is not success. The analyzer gate decides.

This module is the RENDERER. The tunable text lives in
`prompt_versions.py` as addressable revisions, so a convergence run can
cite exactly which body it scored and roll back to its predecessor.
"""

from __future__ import annotations


def build_system_prompt(
    include_operations: bool = True, revision: int | None = None
) -> str:
    """Render the system prompt for an interactive modeling session.

    `revision` selects the working-agreement revision; `None` uses the
    active one. Unknown revisions raise rather than defaulting — see
    `prompt_versions.get_revision`.
    """
    from blended.agent.prompt_versions import get_revision
    from blended.version import TARGET_BLENDER_SERIES

    sections = [
        (
            f"You are a 3D modeling agent working inside Blender "
            f"{TARGET_BLENDER_SERIES[0]}.{TARGET_BLENDER_SERIES[1]}, "
            f"collaborating with a game artist on production assets.\n"
            f"\nYou have a live Blender session and a set of tools. The user "
            f"can see the viewport; you see what your tools return."
        ),
        get_revision(revision).body,
    ]
    if include_operations:
        from blended.manifest import CONVENTIONS, build_manifest

        sections.append("\n## Conventions\n")
        sections.append(
            "\n".join(f"{index}. {rule}" for index, rule in enumerate(CONVENTIONS, 1))
        )
        # The operation list and drift traps, minus the one-shot
        # "return only Python" contract, which does not apply in chat.
        manifest_text = build_manifest()
        operations_start = manifest_text.find("## Available operations")
        output_contract_start = manifest_text.find("## Your output")
        sections.append("\n" + manifest_text[operations_start:output_contract_start])
    return "\n".join(sections)
