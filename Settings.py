import appdirs
import os
import json
import threading
class DotDict:
	def __init__(self, dictionary=None, parent=None):
		self.__dict__["_parent"] = parent  # Reference to the SettingsManager for autosave.
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
		if self._initialized: return
		self._initialized = True
		self.app_name = 'VOLlama'
		self.company_name = None
		self.config_dir = appdirs.user_config_dir(self.app_name, self.company_name)
		self.settings_file_path = os.path.join(self.config_dir, 'settings.json')
		os.makedirs(self.config_dir, exist_ok=True)
		self.settings = self.load_settings()

	def save_settings(self):
		settings_dict = self.settings.to_dict()
		with open(self.settings_file_path, 'w') as file:
			json.dump(settings_dict, file, indent='\t')

	def load_settings(self):
		default_dict = {
			'host': 'http://localhost:11434',
			'system': "",
			'speakResponse': False,
			'voice': 'unknown',
			'rate': 0.0
		}
		try:
			with open(self.settings_file_path, 'r') as file:
				settings_dict = json.load(file)
				settings = DotDict(settings_dict, parent=self)
				# Check for differences and update if necessary.
				different = set(default_dict.keys()) != set(settings_dict.keys())
				if different:
					for key, value in default_dict.items():
						if key not in settings_dict:
							setattr(settings, key, value)  # Use setattr to ensure autosave is triggered.
		except Exception as e:
			print(e)
			settings = DotDict(default_dict, parent=self)
			self.save_settings()  # Ensure defaults are saved if the file is missing or corrupted.
		return settings

settings_manager = SettingsManager()  # This will be the shared instance.

def get_settings():
	return settings_manager.settings

def save_settings():
	settings_manager.save_settings()
