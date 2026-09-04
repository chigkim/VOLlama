"""Fixtures every test gets.

The settings object is a process-wide singleton, which is right for an
application with one settings file and wrong for a test suite. `isolated`
points the store at a temporary directory and resets the object in place, so
tests can change settings freely and none of them can touch the real file.
"""

import dataclasses

import pytest

from vollama.config import store
from vollama.config.settings import Settings, settings


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """A clean settings object, saved to a temporary directory."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(store, "settings_path", lambda: path)
    monkeypatch.setattr(store, "config_dir", lambda: tmp_path)
    fresh = Settings(secret=store.new_secret())
    # Reset in place: every module imported `settings` by value, so rebinding
    # the name here would leave them all holding the old one.
    for field in dataclasses.fields(Settings):
        setattr(settings, field.name, getattr(fresh, field.name))
    return settings
