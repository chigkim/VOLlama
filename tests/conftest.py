"""Fixtures every test gets.

The settings object is a process-wide singleton, which is right for an
application with one settings file and wrong for a test suite. `isolated`
points the store at a temporary directory and hands the object a clean set of
values, so tests can change settings freely and none of them can touch the
real file. It resets through `Settings.adopt`, which is the same thing
`config.settings.load` uses: every module imported this object by value, so
rebinding the name would leave them all holding the old one.
"""

import pytest

from vollama.config import store
from vollama.config.settings import Settings, settings


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """A clean settings object, saved to a temporary directory."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(store, "settings_path", lambda: path)
    monkeypatch.setattr(store, "config_dir", lambda: tmp_path)
    settings.adopt(Settings(secret=store.new_secret()))
    settings.writable = True
    return settings
