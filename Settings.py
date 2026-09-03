from cryptography.fernet import Fernet
import appdirs
import copy
import os
import json
import threading
from pathlib import Path

SETTINGS_VERSION = 1

# Keys that live in default-parameters.json purely as templates. They are read
# on demand (see preset_template) and never merged into settings.json as
# top-level values.
TEMPLATE_KEYS = ("preset_template", "parameters")

# A settings file missing any of these predates the OpenAI-compatible preset
# schema. There is no migration: the app flags it as incompatible (version 0)
# and asks the user to reset and configure from scratch.
REQUIRED_KEYS = ("presets", "active_preset", "embedding_base_url")

DEFAULT_CONTEXT_WINDOW = 8192


def config_dir():
    app_name = "VOLlama"
    company_name = None
    dir = Path(appdirs.user_config_dir(app_name, company_name))
    dir.mkdir(parents=True, exist_ok=True)
    return dir


def defaults():
    p = os.path.join(os.path.dirname(__file__), "default-parameters.json")
    with open(p) as file:
        return json.load(file)


def encrypt(key, value):
    # Convert the string representation of the key back to bytes
    key_bytes = key.encode()
    cipher_suite = Fernet(key_bytes)
    # Encrypt the value, which is then encoded to a string for easy handling
    encrypted_value = cipher_suite.encrypt(value.encode()).decode()
    return encrypted_value


def decrypt(key, encrypted_value):
    key_bytes = key.encode()
    encrypted_value_bytes = encrypted_value.encode()
    cipher_suite = Fernet(key_bytes)
    decrypted_value = cipher_suite.decrypt(encrypted_value_bytes).decode()
    return decrypted_value


def encrypt_value(secret, value):
    """Encrypt one api key, leaving empty values and the sentinel alone."""
    if not isinstance(value, str) or not value or value == "YOUR_API_KEY":
        return value
    return encrypt(secret, value)


def decrypt_value(secret, value):
    """Decrypt one api key. Plaintext leftovers are returned as they are."""
    if not isinstance(value, str) or not value or value == "YOUR_API_KEY":
        return value
    try:
        return decrypt(secret, value)
    except Exception:
        return value


def preset_template():
    """A fresh preset, with the full default generation parameter set."""
    default = defaults()
    preset = copy.deepcopy(default["preset_template"])
    preset["parameters"] = copy.deepcopy(default["parameters"])
    return preset


class DotDict:
    def __init__(self, dictionary=None, parent=None):
        self.__dict__["_parent"] = (
            parent  # Reference to the SettingsManager for autosave.
        )
        if dictionary is None:
            dictionary = {}
        for key, value in dictionary.items():
            # Directly assign the value without converting it to DotDict.
            self.__dict__[key] = value

    def __setattr__(self, key, value):
        # Directly assign the value without checking for dict type to convert.
        self.__dict__[key] = value
        if "_parent" in self.__dict__ and self._parent:
            self._parent.save_settings()

    def to_dict(self):
        dict_ = {}
        for key, value in self.__dict__.items():
            if key == "_parent":
                continue  # Skip the parent reference when converting to dict.
            # Directly assign the value without converting from DotDict to dict.
            dict_[key] = value
        return dict_


class SettingsManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SettingsManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.settings_file_path = config_dir() / "settings.json"
        self.settings = self.load_settings()

    def save_settings(self):
        settings_dict = self.settings.to_dict()
        secret = settings_dict.get("secret")
        out = dict(settings_dict)
        for key, value in settings_dict.items():
            if "key" in key:
                out[key] = encrypt_value(secret, value)
        presets = settings_dict.get("presets")
        if isinstance(presets, dict):
            # to_dict() hands back the live nested dicts, so copy before
            # encrypting or the in-memory presets end up holding ciphertext.
            out["presets"] = copy.deepcopy(presets)
            for preset in out["presets"].values():
                if isinstance(preset, dict):
                    preset["api_key"] = encrypt_value(secret, preset.get("api_key", ""))
        with self.settings_file_path.open("w") as file:
            json.dump(out, file, indent="\t")

    def load_settings(self):
        default_dict = defaults()
        try:
            with self.settings_file_path.open("r") as file:
                settings_dict = json.load(file)
        except FileNotFoundError:
            settings_dict = copy.deepcopy(default_dict)
            settings_dict["version"] = SETTINGS_VERSION
        if "secret" not in settings_dict:
            secret = Fernet.generate_key().decode()
            settings_dict["secret"] = secret
        else:
            secret = settings_dict["secret"]

        for key, value in settings_dict.items():
            if "key" in key:
                settings_dict[key] = decrypt_value(secret, value)
        presets = settings_dict.get("presets")
        if isinstance(presets, dict):
            for preset in presets.values():
                if isinstance(preset, dict):
                    preset["api_key"] = decrypt_value(secret, preset.get("api_key", ""))

        # No migration path from the old per-provider settings. Mark the file
        # incompatible so the app tells the user to reset (see VOLlama.py).
        if settings_dict.get("version") != SETTINGS_VERSION or any(
            key not in settings_dict for key in REQUIRED_KEYS
        ):
            settings_dict["version"] = 0

        # Ensure all default settings are present, add missing ones
        for key, value in default_dict.items():
            if key == "version" or key in TEMPLATE_KEYS:
                continue
            if key not in settings_dict:
                settings_dict[key] = copy.deepcopy(value)
        for key in TEMPLATE_KEYS:
            settings_dict.pop(key, None)

        self.settings = DotDict(settings_dict, parent=self)
        self.save_settings()  # Save settings, ensuring any additions are persisted
        return self.settings

    @property
    def settings(self):
        return self._settings

    @settings.setter
    def settings(self, value):
        self._settings = value
        self.save_settings()


settings = SettingsManager().settings


def save_presets():
    """Persist in-place edits to settings.presets.

    DotDict only autosaves on attribute assignment, so mutating the nested
    presets dict needs an explicit reassignment to reach disk.
    """
    settings.presets = settings.presets


def active_preset():
    """The active preset dict, or None when none are configured yet."""
    presets = settings.presets
    if not presets:
        return None
    name = settings.active_preset
    if name not in presets:
        name = sorted(presets)[0]
        settings.active_preset = name
    return presets[name]


def set_active_preset(name):
    if name in settings.presets:
        settings.active_preset = name


def context_window():
    """Global context window, used to size RAG prompts (see RAG Settings)."""
    try:
        return int(settings.context_window or DEFAULT_CONTEXT_WINDOW)
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_CONTEXT_WINDOW
