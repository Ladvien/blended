"""What ships in the addon zip.

Blender's bundled Python has no pip, so a dependency that is merely
declared in pyproject.toml is not installed for the addon — it has to be
inside the zip. `AgentSession.__post_init__` builds the system prompt,
which renders a Jinja template, so the addon reaches both jinja2 and
`prompts/*.j2` on its very first turn. A packaging miss here does not
fail at install time; it fails later, in someone else's Blender.
"""

import zipfile

import pytest

from scripts.package_addon import VENDORED_DEPENDENCIES, package_addon


@pytest.fixture(scope="module")
def addon_names():
    zip_path = package_addon()
    with zipfile.ZipFile(zip_path) as archive:
        return set(archive.namelist())


def test_the_library_is_vendored(addon_names):
    assert "blended_agent/__init__.py" in addon_names
    assert "blended_agent/blended/agent/system_prompt.py" in addon_names


def test_the_prompt_templates_are_vendored(addon_names):
    """Package data is the classic thing to leave behind: the code
    imports fine and then cannot find its own text."""
    templates = {
        name
        for name in addon_names
        if name.startswith("blended_agent/blended/agent/prompts/")
        and name.endswith(".j2")
    }
    assert "blended_agent/blended/agent/prompts/system_prompt.md.j2" in templates
    # Every registered revision, not just some of them.
    from blended.agent.prompt_versions import PROMPT_REVISIONS

    for entry in PROMPT_REVISIONS:
        expected = (
            f"blended_agent/blended/agent/prompts/"
            f"working_agreement_v{entry.revision}.md.j2"
        )
        assert expected in templates, expected


@pytest.mark.parametrize("dependency", VENDORED_DEPENDENCIES)
def test_runtime_dependencies_are_vendored(addon_names, dependency):
    assert any(
        name.startswith(f"blended_agent/{dependency}/") and name.endswith(".py")
        for name in addon_names
    ), f"{dependency} is not in the addon zip"


def test_nothing_ships_precompiled(addon_names):
    """__pycache__ from the build machine is dead weight and can shadow
    the source it was built from."""
    assert not [name for name in addon_names if "__pycache__" in name]
