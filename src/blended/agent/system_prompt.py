"""Renders the conversational agent's system prompt.

Distinct from `manifest.build_manifest()`, which is a one-shot brief for
"write this script". This is for a modeling PARTNER the user chats with
inside Blender across many turns: it establishes the working
relationship, the tool discipline, and — most importantly — what
counts as done.

The core instruction is the one the whole harness exists to enforce:
running without an error is not success, and a render that looks right
is not success. The analyzer gate decides.

This module is the ASSEMBLER. It gathers what only code can know — the
version pin, the conventions, the live ops manifest and its drift traps
— and hands them to `prompts/system_prompt.md.j2`. The prose lives in
`prompts/`; the tunable working agreement is an addressable revision in
`prompt_versions.py`, so a convergence run can cite exactly which text
it scored and roll back to its predecessor.
"""

from __future__ import annotations

SYSTEM_PROMPT_TEMPLATE = "system_prompt"
# Everything from the operations heading up to the one-shot output
# contract, which tells a script writer to "return only Python" and is
# wrong in a chat where the agent also talks to the user.
OPERATIONS_HEADING = "## Available operations"
OUTPUT_CONTRACT_HEADING = "## Your output"


def build_system_prompt(
    include_operations: bool = True,
    revision: int | None = None,
    lane: str | None = None,
) -> str:
    """Render the system prompt for an interactive modeling session.

    `revision` selects the working-agreement revision; `None` uses the
    active one. Unknown revisions raise rather than defaulting — see
    `prompt_versions.get_revision`.

    `lane` selects which capability modules load, and defaults to NONE.
    That default is deliberate: with no lane this renders exactly the
    text the convergence loop scored, so every existing measurement
    keeps meaning what it meant. Skills are opt-in per turn until a run
    has scored them — see `skill_modules`, and the -1.3 pp that
    self-authored skills measured there. Unknown lanes raise.
    """
    from blended.agent.prompt_templates import render
    from blended.agent.prompt_versions import get_revision
    from blended.version import TARGET_BLENDER_SERIES

    skills_text = ""
    if lane is not None:
        from blended.agent.skill_modules import render_modules

        skills_text = render_modules(lane)

    conventions_text = ""
    operations_text = ""
    if include_operations:
        from blended.manifest import CONVENTIONS, build_manifest

        conventions_text = "\n".join(
            f"{index}. {rule}" for index, rule in enumerate(CONVENTIONS, 1)
        )
        manifest_text = build_manifest()
        operations_text = manifest_text[
            manifest_text.find(OPERATIONS_HEADING) : manifest_text.find(
                OUTPUT_CONTRACT_HEADING
            )
        ]

    return render(
        SYSTEM_PROMPT_TEMPLATE,
        blender_series=(
            f"{TARGET_BLENDER_SERIES[0]}.{TARGET_BLENDER_SERIES[1]}"
        ),
        working_agreement=get_revision(revision).body,
        skills=skills_text,
        conventions=conventions_text,
        operations=operations_text,
    )
