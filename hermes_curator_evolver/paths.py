"""Filesystem paths for Hermes Curator Evolver."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PLUGIN_NAME = "curator-evolver"


def _platform_default_hermes_home() -> Path:
    """Mirror Hermes' platform-native fallback when its constants are unavailable."""

    if sys.platform == "win32":
        local_appdata = os.getenv("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return base / "hermes"
    return Path.home() / ".hermes"


def hermes_home() -> Path:
    """Return Hermes home, profile-aware when running inside Hermes."""
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        env_home = os.getenv("HERMES_HOME")
        if env_home:
            return Path(env_home).expanduser()
        return _platform_default_hermes_home()
    return Path(get_hermes_home())


def data_dir() -> Path:
    """Return plugin data directory and create it if needed.

    State lives in ``<hermes home>/plugin-data/<plugin>/``, the location Hermes
    core reserves for plugin state. It must NOT live in ``<hermes home>/plugins/``:
    that is the install directory, which ``hermes plugins update`` git-pulls and
    ``hermes plugins remove`` deletes. Worse, core hashes every enabled plugin's
    source tree to decide whether the dependency environment is still in sync
    (``pm.workspace.members_stamp``), so writing an evidence database into the
    install directory makes that stamp change on every turn. Dependency syncs then
    fail with "Dependency inputs changed while preparing publication", the
    ``source-completion-pending`` marker is never cleared, and every launch
    re-runs a tail it can never finish.

    ``plugin_data_dir`` is the supported core API for this; fall back to the same
    path when Hermes is not importable (standalone CLI use).
    """
    try:
        from plugins.plugin_storage import plugin_data_dir
    except ImportError:
        path = hermes_home() / "plugin-data" / PLUGIN_NAME
    else:
        path = plugin_data_dir(PLUGIN_NAME)
    _migrate_legacy_data(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _migrate_legacy_data(new_dir: Path) -> None:
    """Move pre-existing state from the install dir to the new location, once.

    Without this, upgrading would look like every candidate's evidence vanished:
    the database would simply reappear empty under the new path while the real
    history sat in ``<install dir>/data/evidence.sqlite``. Best-effort throughout
    — never fail a run over a migration. ``backups/`` and ``logs/`` move as whole
    directories, matching their new defaults; the database's contents move up into
    the data dir itself, because that is where ``default_db_path()`` now looks.
    """
    legacy_home = hermes_home() / "plugins" / PLUGIN_NAME
    if legacy_home.resolve() == new_dir.resolve():
        return

    legacy_data = legacy_home / "data"
    if legacy_data.is_dir():
        try:
            new_dir.mkdir(parents=True, exist_ok=True)
            for entry in legacy_data.iterdir():
                target = new_dir / entry.name
                if target.exists():
                    continue  # never clobber what is already in place
                shutil.move(str(entry), str(target))
            # Only tidy up a real directory. A symlink here is an operator
            # override (and is the shape this fix ships as on some installs):
            # leave it in place, but still adopt its contents above.
            if not legacy_data.is_symlink() and not any(legacy_data.iterdir()):
                legacy_data.rmdir()
        except OSError:
            pass

    for name in ("backups", "logs"):
        legacy = legacy_home / name
        if not legacy.is_dir() or legacy.is_symlink():
            continue  # a symlink here is a deliberate operator override
        if not any(legacy.iterdir()):
            continue
        target = new_dir / name
        if target.exists() and any(target.iterdir()):
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(target))
        except OSError:
            pass


def default_db_path() -> Path:
    """Return the configured SQLite database path."""
    override = os.getenv("HERMES_CURATOR_EVOLVER_DB")
    if override:
        path = Path(override).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return data_dir() / "evidence.sqlite"


def default_backup_dir() -> Path:
    """Return the default guarded-apply backup directory.

    Like the evidence database, backups must stay out of the install directory:
    ``--apply-low-risk`` runs write them, so hashing them into the dependency
    stamp has the same failure mode as the database.
    """
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path
