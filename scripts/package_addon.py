"""Package the Blender addon as an installable .zip.

The plugin VENDORS the `blended` library inside itself, so a user
installs one file and configures nothing — no repo path, no sys.path
edits, no pip inside Blender. Run from the repo root:

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
    for cache_directory in (addon_directory / "blended").rglob("__pycache__"):
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
