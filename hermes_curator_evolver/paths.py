"""Filesystem paths for Hermes Curator Evolver."""

from __future__ import annotations

import os
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
    path.mkdir(parents=True, exist_ok=True)
    return path


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
