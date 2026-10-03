"""Never let plugin tests discover or mutate the operator's Hermes state."""

import pytest


@pytest.fixture(autouse=True)
def isolated_hermes_home(tmp_path, monkeypatch):
    user_home = tmp_path / "user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(user_home / ".config"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.delenv("HERMES_CURATOR_EVOLVER_DB", raising=False)
