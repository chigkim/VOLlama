"""Reading and writing settings.json.

This module owns the file: where it lives, how it is parsed, which fields are
obfuscated, and what permissions it is written with. It knows nothing about
what any particular setting means, which is `settings.py`'s job.

On the encryption. The api keys in the file are encrypted with a Fernet key
that is stored **in the same file**, so anybody who can read the file can
decrypt them. That is worth saying plainly rather than leaving to be
discovered: it defends against a glance over the shoulder or a key pasted into
a support thread, and against nothing else. The real protection is the file
mode, which is why `write` sets it. Storing the key somewhere the operating
system guards would need a keyring dependency and a story for every platform;
promising secrecy we do not deliver would be worse than either.
"""

import json
import logging
import os
from pathlib import Path

import appdirs
from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

APP_NAME = "VOLlama"

# Fields holding an api key. Listed rather than matched on their names: a
# substring test decides what to encrypt by accident, and gets it wrong the
# first time somebody adds a field called "keyboard_shortcut".
SECRETS = ("embedding_api_key",)
PRESET_SECRET = "api_key"

# The value the shipped defaults use to mean "no key yet". Encrypting it would
# turn the placeholder into ciphertext that decrypts back to a placeholder.
PLACEHOLDER = "YOUR_API_KEY"


def config_dir():
    """The per-user directory settings live in, created if it is not there."""
    directory = Path(appdirs.user_config_dir(APP_NAME, None))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def settings_path():
    return config_dir() / "settings.json"


def new_secret():
    """A fresh key for obfuscating the api keys in the file."""
    return Fernet.generate_key().decode()


def _hide(secret, value):
    if not isinstance(value, str) or not value or value == PLACEHOLDER:
        return value
    return Fernet(secret.encode()).encrypt(value.encode()).decode()


def _show(secret, value):
    if not isinstance(value, str) or not value or value == PLACEHOLDER:
        return value
    try:
        return Fernet(secret.encode()).decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        # A key typed straight into the file by hand, or one written before the
        # secret was rotated. Returning it as it stands is what the user meant;
        # refusing to start over an unreadable key would not be.
        return value


def _apply(data, secret, transform):
    """A copy of the settings with every api key put through transform.

    A copy, because the caller's presets must not end up holding ciphertext:
    that was a real bug when the encryption worked on the live dictionaries.
    """
    out = dict(data)
    for field in SECRETS:
        if field in out:
            out[field] = transform(secret, out[field])
    presets = out.get("presets")
    if isinstance(presets, dict):
        out["presets"] = {
            name: {**preset, PRESET_SECRET: transform(secret, preset.get(PRESET_SECRET, ""))}
            for name, preset in presets.items()
            if isinstance(preset, dict)
        }
    return out


def read(path):
    """The settings file as a dictionary, with its api keys readable.

    Returns None when there is no file yet, which is a first run and not a
    failure. A file that is there but unreadable is a failure, and is reported
    rather than silently replaced: overwriting somebody's presets because the
    disk hiccuped is not a recovery.
    """
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a settings object.")
    secret = data.get("secret") or ""
    return _apply(data, secret, _show) if secret else data


def write(path, data):
    """Write the settings, with the api keys hidden and the file kept private.

    Written to a temporary file in the same directory and moved into place, so
    an interrupted write leaves the previous settings rather than half of the
    new ones.
    """
    secret = data.get("secret") or ""
    out = _apply(data, secret, _hide) if secret else dict(data)
    temporary = Path(f"{path}.new")
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(out, file, indent="\t")
    _restrict(temporary)
    os.replace(temporary, path)


def _restrict(path):
    """Keep the file to its owner, since it holds api keys and their key."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Some filesystems have no permissions to set. The keys are no worse
        # off than they were, and refusing to save settings over it would be.
        log.warning("Could not restrict permissions on %s", path)
