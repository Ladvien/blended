"""The prompt is an artifact people read, so its file layer is tested.

Moving the bodies out of Python and into `prompts/*.md.j2` bought
reviewability and gave up a guard: the old chained-`.replace()` build
raised when an anchor moved, which made a silent rewrite impossible by
construction. These tests are what replaces it.
"""

import hashlib

import pytest

from blended.agent import prompt_templates, prompt_versions

# The revision the convergence loop signed off. Its hash is the claim
# that the pinned TEXT is the text that was measured; if extracting the
# templates had altered so much as a space, this is what would say so.
PINNED_IDENTITY = "v9:2e5d0dab1033"

# Jinja's delimiters. The bodies are prose and markdown, and the day one
# of these appears in a body is the day a prompt silently loses a
# section — so it is a red test, not a surprise in production.
JINJA_DELIMITERS = ("{{", "}}", "{%", "%}", "{#", "#}")


def test_every_registered_revision_has_a_template():
    on_disk = set(prompt_templates.available_revisions())
    registered = {entry.revision for entry in prompt_versions.PROMPT_REVISIONS}
    assert registered == on_disk, (
        f"registry and prompts/ disagree: registered={sorted(registered)}, "
        f"on disk={sorted(on_disk)}"
    )


def test_the_revision_history_is_disciplined():
    """One hypothesis, one hunk, one outcome per revision."""
    assert prompt_versions.validate_revisions() == []


@pytest.mark.parametrize(
    "revision", [entry.revision for entry in prompt_versions.PROMPT_REVISIONS]
)
def test_each_revision_changes_exactly_one_place(revision):
    if revision == 1:
        pytest.skip("the baseline has no predecessor to differ from")
    hunks = prompt_versions.changed_hunks(
        prompt_versions.get_revision(revision - 1).body,
        prompt_versions.get_revision(revision).body,
    )
    assert len(hunks) == prompt_versions.MAXIMUM_CHANGED_HUNKS_PER_REVISION, hunks


def test_the_pinned_revision_text_has_not_drifted():
    pinned = prompt_versions.get_revision(prompt_versions.PINNED_PROMPT_REVISION)
    assert pinned.identity == PINNED_IDENTITY


def test_the_template_file_is_the_body_byte_for_byte():
    """No preamble, no front matter, no normalization on the way in."""
    for entry in prompt_versions.PROMPT_REVISIONS:
        path = prompt_templates.template_path(
            f"{prompt_templates.WORKING_AGREEMENT_STEM}{entry.revision}"
        )
        raw = path.read_text(encoding="utf-8")
        assert raw == entry.body, path.name
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        assert entry.identity.endswith(digest)


def test_no_body_contains_a_jinja_delimiter():
    for entry in prompt_versions.PROMPT_REVISIONS:
        for delimiter in JINJA_DELIMITERS:
            assert delimiter not in entry.body, (
                f"v{entry.revision} contains {delimiter!r}: Jinja would try "
                f"to interpret it and the prompt would lose text"
            )


def test_an_unknown_template_raises_instead_of_rendering_nothing():
    with pytest.raises(prompt_templates.TemplateNotFound):
        prompt_templates.render("working_agreement_v999")


def test_a_missing_variable_is_an_error_not_a_blank():
    """A prompt with a silently empty section still runs, and the agent
    simply never learns the thing that section existed to tell it."""
    from jinja2 import UndefinedError

    with pytest.raises(UndefinedError):
        prompt_templates.render("system_prompt")


def test_the_assembled_prompt_carries_the_working_agreement():
    from blended.agent.system_prompt import build_system_prompt

    text = build_system_prompt(include_operations=False)
    assert prompt_versions.get_revision().body in text
    assert "Blender" in text.splitlines()[0]
