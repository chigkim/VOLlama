"""Everything the user has set, as one typed object.

The fields below are the schema. There is no other list of settings anywhere:
the defaults are here, the types are here, and a setting that is not here does
not exist. `settings.json` is this dataclass written out, field for field, so
the file format and the schema cannot drift apart.

Saving is explicit. `settings.save()` after a change. The previous design saved
on every attribute assignment, which read well until a nested value changed —
editing a preset in place never reached the disk — and needed a helper whose
body was `settings.presets = settings.presets` to work around it.
"""

import logging
from dataclasses import asdict, dataclass, field, fields

from vollama.config import store

log = logging.getLogger(__name__)

# The shape of settings.json. A file that says anything else is refused rather
# than migrated: the app tells the user to reset and configure again, which is
# the same answer it has always given and the only one worth maintaining.
SETTINGS_VERSION = 1


@dataclass
class Settings:
    """The settings file, in memory."""

    version: int = SETTINGS_VERSION
    # The key the api keys in the file are obfuscated with. It lives in the
    # same file; see store.py for what that is and is not worth.
    secret: str = ""

    # Presets. Kept as plain dictionaries here because this object's job is to
    # mirror the file; config.presets is what turns one into a Preset.
    active_preset: str = ""
    presets: dict = field(default_factory=dict)

    # The embedding endpoint and how much text to retrieve are preset fields,
    # not fields here: see config.presets. Whether the retrieved chunks are
    # printed is not one of them — it answers "do I want to see the passages
    # right now", which changes mid-chat and has nothing to do with which
    # server is being used, so it lives on the Documents menu with the rest of
    # the retrieval actions.
    show_context: bool = False

    # Presentation and accessibility.
    sound: bool = True
    screenreader: bool = False
    speakResponse: bool = False  # spelling fixed by the file format, not by us
    voice: str = "default"
    rate: float = 0.0
    show_reasoning: bool = True

    # Whether the model may act on this machine, and where it acts. Global
    # rather than per preset: it answers "do I want this right now", which
    # changes mid-chat, not "what server is this".
    tools: bool = False
    workdir: str = ""

    @classmethod
    def from_dict(cls, data):
        """Settings from a parsed file, taking defaults for anything missing.

        Unknown keys are dropped. A field left out of a hand-edited file is not
        an error, and one added by a newer build is not either.
        """
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self):
        return asdict(self)

    def save(self):
        """Write the settings out. Call it after changing one."""
        store.write(store.settings_path(), self.to_dict())


def _load():
    """The settings on disk, and whether the file was one we understand."""
    path = store.settings_path()
    try:
        data = store.read(path)
    except (OSError, ValueError) as e:
        # A file that exists but will not parse is not replaced: overwriting
        # somebody's presets because of a bad read is not a recovery.
        log.error("Could not read %s: %s", path, e)
        return Settings(), False
    if data is None:
        fresh = Settings(secret=store.new_secret())
        fresh.save()
        return fresh, True
    if data.get("version") != SETTINGS_VERSION:
        # Left on disk exactly as it is, so the user can still get their api
        # keys out of it, and so choosing Reset stays their decision.
        log.error("%s is version %s, not %s", path, data.get("version"), SETTINGS_VERSION)
        return Settings(), False
    loaded = Settings.from_dict(data)
    if not loaded.secret:
        loaded.secret = store.new_secret()
        loaded.save()
    return loaded, True


settings, compatible = _load()
