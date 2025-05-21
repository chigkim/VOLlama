from cryptography.fernet import Fernet
import appdirs
import os
import json
import threading
from pathlib import Path


def config_dir():
    app_name = "VOLlama"
    company_name = None
    dir = Path(appdirs.user_config_dir(app_name, company_name))
    dir.mkdir(parents=True, exist_ok=True)
    return dir


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
        self.settings = (
            self.load_settings()
        )  # Then attempt to load settings, or initialize with defaults if loading fails.

    def save_settings(self):
        settings_dict = self.settings.to_dict()
        for key, value in settings_dict.items():
            if "key" in key and value:
                settings_dict[key] = encrypt(settings_dict["secret"], value)
        with self.settings_file_path.open("w") as file:
            json.dump(settings_dict, file, indent="\t")

    def load_settings(self):
        p = os.path.join(os.path.dirname(__file__), "default-parameters.json")
        default_dict = json.load(open(p))
        try:
            with self.settings_file_path.open("r") as file:
                settings_dict = json.load(file)
        except FileNotFoundError:
            settings_dict = default_dict

        # Ensure all default settings are present, add missing ones
        for key, value in default_dict.items():
            if key not in settings_dict:
                settings_dict[key] = value
        if "secret" not in settings_dict:
            secret = Fernet.generate_key().decode()
            settings_dict["secret"] = secret
        else:
            secret = settings_dict["secret"]

        for key, value in settings_dict.items():
            if "key" in key and value:
                if value == "YOUR_API_KEY":
                    settings_dict[key] = "YOUR_API_KEY"
                else:
                    settings_dict[key] = decrypt(secret, value)

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
