"""State must never be written into the plugin install directory.

Hermes hashes every enabled plugin's source tree to decide whether the dependency
environment is still in sync (``pm.workspace.members_stamp``). A plugin that writes
runtime state into that tree changes the hash on every turn, so dependency syncs fail
with "Dependency inputs changed while preparing publication" and the
``source-completion-pending`` marker is never cleared.

These tests pin the paths so a future refactor cannot quietly move state back.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from hermes_curator_evolver import auto_evolve, paths


def test_data_dir_is_outside_the_install_dir(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    (home / "plugins" / "curator-evolver").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_CURATOR_EVOLVER_DB", raising=False)

    resolved = paths.data_dir().resolve()

    assert "plugin-data" in resolved.parts, resolved
    assert resolved == (home / "plugin-data" / "curator-evolver").resolve(), resolved
    assert home / "plugins" not in resolved.parents, resolved


def test_default_backup_dir_is_outside_the_install_dir(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    (home / "plugins" / "curator-evolver").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))

    resolved = auto_evolve._default_backup_dir().resolve()

    assert resolved == (home / "plugin-data" / "curator-evolver" / "backups").resolve()
    assert home / "plugins" not in resolved.parents, resolved


def test_writing_the_database_does_not_touch_the_install_dir(tmp_path, monkeypatch):
    """The regression that mattered: a write under the old default moved the stamp."""
    home = tmp_path / ".hermes"
    (home / "plugins" / "curator-evolver").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_CURATOR_EVOLVER_DB", raising=False)

    from hermes_curator_evolver.storage import EvidenceStore

    store = EvidenceStore(paths.default_db_path())
    store.record_tool_call(tool_name="terminal", args={"cmd": "true"}, result="ok",
                           session_id="s1")

    assert paths.default_db_path().is_file()
    assert not (home / "plugins" / "curator-evolver" / "data").exists()
    written = [p for p in (home / "plugins" / "curator-evolver").rglob("*") if p.is_file()]
    assert written == [], written


def test_env_override_still_wins(tmp_path, monkeypatch):
    target = tmp_path / "elsewhere" / "custom.sqlite"
    monkeypatch.setenv("HERMES_CURATOR_EVOLVER_DB", str(target))
    with patch.object(Path, "home", return_value=tmp_path):
        assert paths.default_db_path() == target
    assert target.parent.is_dir()


def test_falls_back_to_home_plugin_data_without_hermes_installed(tmp_path, monkeypatch):
    """The ImportError branch must produce the same location, not the install dir."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_CURATOR_EVOLVER_DB", raising=False)

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def blocked(name, *args, **kwargs):
        if name == "plugins.plugin_storage":
            raise ImportError("hermes not installed")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked):
        resolved = paths.data_dir().resolve()

    assert resolved == (home / "plugin-data" / "curator-evolver").resolve()
    assert home / "plugins" not in resolved.parents


def test_no_stray_reference_to_the_old_path():
    """Guard the source itself: the old literal must not reappear."""
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for source in (root / "hermes_curator_evolver").glob("*.py"):
        text = source.read_text(encoding="utf-8")
        for needle in ('"plugins", PLUGIN_NAME', '"plugins" / "curator-evolver"',
                       '"plugins", "curator-evolver"'):
            if needle in text:
                offenders.append(f"{source.name}: {needle}")
    assert offenders == [], offenders


def test_plugin_data_dir_api_is_used_when_available(tmp_path, monkeypatch):
    """Inside Hermes, core's own helper is the source of truth for the location."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_CURATOR_EVOLVER_DB", raising=False)

    expected = home / "plugin-data" / "curator-evolver"

    # Stand in for `plugins.plugin_storage.plugin_data_dir`, which only exists when
    # Hermes itself is importable. The plugin must go through it rather than
    # reimplementing the path, so core stays the single source of truth.
    stub = ModuleType("plugins")
    stub.__path__ = []  # mark as a package so the submodule import resolves
    storage = ModuleType("plugins.plugin_storage")
    calls: list[str] = []
    storage.plugin_data_dir = lambda name: (calls.append(name) or expected)
    stub.plugin_storage = storage

    with patch.dict(sys.modules, {"plugins": stub, "plugins.plugin_storage": storage}):
        resolved = paths.data_dir().resolve()

    assert calls == ["curator-evolver"], calls
    assert resolved == expected.resolve()
    assert home / "plugins" not in resolved.parents


def test_legacy_state_is_migrated_on_first_use(tmp_path, monkeypatch):
    """An upgrade must not look like the evidence history vanished."""
    home = tmp_path / ".hermes"
    install = home / "plugins" / "curator-evolver"
    (install / "data").mkdir(parents=True)
    (install / "data" / "evidence.sqlite").write_bytes(b"legacy-history")
    (install / "backups").mkdir()
    (install / "backups" / "skill.md").write_text("v1")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_CURATOR_EVOLVER_DB", raising=False)

    resolved = paths.data_dir().resolve()

    # The DB moves up into the data dir itself: that is where default_db_path() looks.
    assert (resolved / "evidence.sqlite").read_bytes() == b"legacy-history"
    assert (resolved / "backups" / "skill.md").read_text() == "v1"
    assert not (install / "data" / "evidence.sqlite").exists()
    assert not (install / "backups" / "skill.md").exists()
    assert paths.default_db_path() == resolved / "evidence.sqlite"


def test_migration_never_clobbers_a_populated_destination(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    install = home / "plugins" / "curator-evolver"
    (install / "data").mkdir(parents=True)
    (install / "data" / "evidence.sqlite").write_bytes(b"old")
    new = home / "plugin-data" / "curator-evolver"
    new.mkdir(parents=True)
    (new / "evidence.sqlite").write_bytes(b"new")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_CURATOR_EVOLVER_DB", raising=False)

    paths.data_dir()

    assert (new / "evidence.sqlite").read_bytes() == b"new", "must not clobber"
    assert (install / "data" / "evidence.sqlite").read_bytes() == b"old", "must not delete"


def test_migration_leaves_a_symlinked_install_dir_alone(tmp_path, monkeypatch):
    """A symlinked install dir is a deliberate operator override, not legacy state."""
    home = tmp_path / ".hermes"
    install = home / "plugins" / "curator-evolver"
    real = home / "plugin-data" / "curator-evolver"
    (real / "data").mkdir(parents=True)
    (real / "data" / "evidence.sqlite").write_bytes(b"real")
    install.mkdir(parents=True)
    (install / "data").symlink_to(real / "data")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_CURATOR_EVOLVER_DB", raising=False)

    resolved = paths.data_dir().resolve()

    # A symlinked install dir is an operator override: adopt its contents into the
    # new location so history is reachable, but never delete the link itself.
    assert (resolved / "evidence.sqlite").read_bytes() == b"real"
    assert (install / "data").is_symlink(), "symlink must survive"
