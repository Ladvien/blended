"""Package the Blender addon as an installable .zip.

The plugin VENDORS the `blended` library inside itself, so a user
installs one file and configures nothing — no repo path, no sys.path
edits, no pip inside Blender. Third-party pure-Python dependencies are
vendored the same way and for the same reason: Blender's bundled Python
has no pip, so anything `blended` imports at runtime must be in the zip.
Run from the repo root:

    python scripts/package_addon.py

Produces dist/blended_agent.zip, installable via
Blender > Preferences > Add-ons > Install...
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

ADDON_PACKAGE_NAME = "blended_agent"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DISTRIBUTION_DIRECTORY = REPOSITORY_ROOT / "dist"

# Imported by `blended` at runtime and absent from Blender's Python.
# `blended.agent.prompt_templates` renders the system prompt with Jinja,
# and `AgentSession.__post_init__` builds that prompt — so the addon
# reaches this code on its very first turn. Both are pure Python, so
# copying the package directory is a complete install. Verified by
# tests/pure/test_addon_packaging.py, which asserts they land in the zip.
VENDORED_DEPENDENCIES = ("jinja2", "markupsafe")


class MissingVendoredDependency(FileNotFoundError):
    """A dependency the addon needs is not installed in the venv."""


def venv_site_packages() -> Path:
    candidates = sorted(
        (REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages")
    )
    if not candidates:
        raise MissingVendoredDependency(
            f"No .venv under {REPOSITORY_ROOT}: nothing to vendor from. "
            f"Run `uv sync` first."
        )
    return candidates[-1]


def package_addon() -> Path:
    staging_root = DISTRIBUTION_DIRECTORY / "_stage"
    addon_directory = staging_root / ADDON_PACKAGE_NAME
    if staging_root.exists():
        shutil.rmtree(staging_root)
    addon_directory.mkdir(parents=True)

    shutil.copy(
        REPOSITORY_ROOT / "blender_addon" / "__init__.py",
        addon_directory / "__init__.py",
    )
    shutil.copytree(
        REPOSITORY_ROOT / "src" / "blended", addon_directory / "blended"
    )
    site_packages = venv_site_packages()
    for dependency in VENDORED_DEPENDENCIES:
        source = site_packages / dependency
        if not source.is_dir():
            raise MissingVendoredDependency(
                f"{dependency!r} is not in {site_packages}. The addon would "
                f"install and then fail on its first turn, inside Blender, "
                f"where there is no pip to fix it. Run `uv sync`."
            )
        shutil.copytree(source, addon_directory / dependency)

    for cache_directory in addon_directory.rglob("__pycache__"):
        shutil.rmtree(cache_directory)

    zip_path = DISTRIBUTION_DIRECTORY / f"{ADDON_PACKAGE_NAME}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(staging_root.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(staging_root))
    shutil.rmtree(staging_root)
    return zip_path


if __name__ == "__main__":
    output_path = package_addon()
    print(f"Packaged {output_path} ({output_path.stat().st_size // 1024} KB)")
    print("Install via Blender > Preferences > Add-ons > Install...")
