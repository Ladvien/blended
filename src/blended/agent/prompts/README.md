# Prompts

The tunable text of the harness, one file per artifact, so it can be
read, diffed and reviewed as prose instead of as string surgery inside a
module.

| File | What it is |
|---|---|
| `system_prompt.md.j2` | The outer shell. Takes `blender_series`, `working_agreement`, `conventions`, `operations`. |
| `working_agreement_v{n}.md.j2` | Revision `n` of the working agreement — the part the convergence loop tunes. |

## The split

These files hold the **text**. `../prompt_versions.py` holds the
**provenance**: which revisions exist, the one element each changed, the
hypothesis stated before it ran, and the outcome measured after. A file
cannot carry why it exists; the registry cannot be read as prose. Both
are needed, so both exist, and `validate_revisions()` checks they agree.

`../prompt_templates.py` renders them. Nothing else opens these files.

## Adding a revision

1. Copy the current revision to `working_agreement_v{n+1}.md.j2` and
   change **exactly one element**. Surgical edits beat rewrites (LL3M),
   and a rewrite destroys the attribution that makes the next edit
   informed.
2. Add a `PromptRevision` to `PROMPT_REVISIONS` with `changed_element`
   and `hypothesis` — the hypothesis is written **before** the run, in
   the form "changed X because Y; expect Z".
3. Run it: `make converge BRIEF=... REVISION={n+1} ITERATION=...`.
   Fill `outcome` from the measurement, not from impression.
4. Move `ACTIVE_PROMPT_REVISION` only once the measurement supports it.

`validate_revisions()` enforces the parts of that a reader would
otherwise have to take on trust: revisions consecutive from 1, every
template rendering non-empty, every revision differing from its
predecessor by exactly one contiguous hunk and by *something*, every
revision carrying a hypothesis, and every superseded revision recording
what it measured.

## Constraints

- **No Jinja delimiters in a body.** `{{ }}`, `{% %}` and `{# #}` would
  be interpreted, and the prompt would quietly lose text. Asserted in
  `tests/pure/test_prompt_templates.py`.
- **Whitespace is content.** Bullet indentation, blank lines between
  paragraphs and the trailing newline are all part of the text, and the
  revision's identity is a hash of it. The environment is configured
  with `keep_trailing_newline=True` and no block trimming for exactly
  this reason.
- **Undefined variables raise.** A prompt with a silently blank section
  still runs — the agent just never learns the thing that section
  existed to tell it.
- **These files ship in the addon zip.** Blender has no pip, so
  `scripts/package_addon.py` vendors both the templates and jinja2.
  Guarded by `tests/pure/test_addon_packaging.py`.
