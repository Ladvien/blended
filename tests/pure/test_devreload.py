"""Hot-reload machinery: pure, no bpy required."""

import sys

from blended import devreload


def test_purge_removes_library_modules_and_reports_them():
    import blended.ops.primitives  # noqa: F401 — ensure something is cached

    assert any(name.startswith("blended.") for name in sys.modules)
    result = devreload.purge_library_modules()

    assert result.purged_modules
    assert all(
        name == "blended" or name.startswith("blended.")
        for name in result.purged_modules
    )
    assert not any(
        name == "blended" or name.startswith("blended.") for name in sys.modules
    )
    # And the library is importable again afterwards, fresh from disk.
    import blended.ops.primitives  # noqa: F401,F811

    assert "blended.ops.primitives" in sys.modules


def test_purge_never_touches_unrelated_modules():
    import json

    before = sys.modules["json"]
    devreload.purge_library_modules()
    assert sys.modules["json"] is before


def test_changed_files_detects_modification_addition_and_removal():
    previous = {"a.py": 1.0, "b.py": 2.0, "gone.py": 3.0}
    current = {"a.py": 1.0, "b.py": 9.9, "new.py": 4.0}
    assert devreload.changed_files(previous, current) == ("b.py", "gone.py", "new.py")


def test_unchanged_fingerprint_reports_nothing():
    fingerprint = {"a.py": 1.0, "b.py": 2.0}
    assert devreload.changed_files(fingerprint, dict(fingerprint)) == ()


def test_fingerprint_covers_the_real_package():
    from blended import devreload as reloader

    root = reloader.library_source_root()
    assert root is not None
    fingerprint = reloader.source_fingerprint(root)
    assert "ops/primitives.py" in fingerprint
    assert "agent/loop.py" in fingerprint


def test_snapshot_conversation_survives_a_purge():
    class FakeSession:
        messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]

    snapshot = devreload.snapshot_conversation(FakeSession())
    devreload.purge_library_modules()
    assert snapshot == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
    ]
    assert devreload.snapshot_conversation(None) == []
