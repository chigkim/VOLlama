"""Everything the user has set, as one typed object.

The fields below are the schema. There is no other list of settings anywhere:
the defaults are here, the types are here, and a setting that is not here does
not exist. `settings.json` is this dataclass written out, field for field, so
the file format and the schema cannot drift apart.

Saving is explicit. `settings.save()` after a change. The previous design saved
on every attribute assignment, which read well until a nested value changed —
editing a preset in place never reached the disk — and needed a helper whose
body was `settings.presets = settings.presets` to work around it.

Loading is explicit too. `settings` starts as the defaults and `load()` reads
the file into it, called once by `VOLlama.main`. Reading the disk while the
module was being imported made `import vollama.config.settings` do I/O, made
the answer to "was the file readable" a module constant that the window had to
import, and left the test suite resetting a singleton it did not own.
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

    # Not a field, so it is neither written to the file nor compared: whether
    # saving is allowed is a fact about this run, not a setting. `load()` clears
    # it for a file this build cannot read, because the promise made to the user
    # then is that their old file — and the api keys in it — is still there. One
    # menu toggle used to be enough to save the defaults over it.
    writable = True

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
    speak_response: bool = False
    # The platform's own identifier for the chosen voice. Empty means the
    # voice the system would use on its own.
    voice: str = ""
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

    def adopt(self, other):
        """Take every field from `other`, in place.

        In place because every module imported this object by value, so
        rebinding the name here would leave them all holding the old one. It is
        what `load()` does with the file, and what the test fixture does with a
        clean object.
        """
        for one in fields(self):
            setattr(self, one.name, getattr(other, one.name))

    def save(self):
        """Write the settings out. Call it after changing one."""
        if not self.writable:
            log.error("Not saving over a settings file this build cannot read.")
            return
        store.write(store.settings_path(), self.to_dict())


# The application's settings. One object, because there is one settings file;
# `load()` fills it in.
settings = Settings()


def load():
    """Read the settings file into `settings`. Returns whether it was readable.

    False means the file is there and is not one this build understands, and the
    caller has to say so: the settings in memory are the defaults, and saving
    over the file would take the user's presets and api keys with it. The file
    is left exactly as it is, so an api key can still be recovered from it and
    choosing Reset Settings stays the user's decision.
    """
    path = store.settings_path()
    try:
        data = store.read(path)
    except (OSError, ValueError) as e:
        # A file that exists but will not parse is not replaced: overwriting
        # somebody's presets because of a bad read is not a recovery.
        log.error("Could not read %s: %s", path, e)
        settings.writable = False
        return False
    if data is None:
        settings.adopt(Settings(secret=store.new_secret()))
        settings.save()
        return True
    if data.get("version") != SETTINGS_VERSION:
        log.error("%s is version %s, not %s", path, data.get("version"), SETTINGS_VERSION)
        settings.writable = False
        return False
    settings.adopt(Settings.from_dict(data))
    if not settings.secret:
        settings.secret = store.new_secret()
        settings.save()
    return True
