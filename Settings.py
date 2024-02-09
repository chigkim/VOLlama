import appdirs
import os
import json

class DotDict:
	def __init__(self, dictionary=None):
		if dictionary is None:
			dictionary = {}
		for key, value in dictionary.items():
			if isinstance(value, dict):
				value = DotDict(value)
			self.__dict__[key] = value

	def __setattr__(self, key, value):
		if isinstance(value, dict):
			value = DotDict(value)
		self.__dict__[key] = value

	def to_dict(self):
		"""Recursively convert DotDict objects to dictionaries."""
		dict_ = {}
		for key, value in self.__dict__.items():
			if isinstance(value, DotDict):
				dict_[key] = value.to_dict()
			else:
				dict_[key] = value
		return dict_

app_name = 'VOLlama'
company_name = None
config_dir = appdirs.user_config_dir(app_name, company_name)
settings_file_path = os.path.join(config_dir, 'settings.json')
os.makedirs(config_dir, exist_ok=True)

def save_settings():
	settings_dict = settings.to_dict()
	with open(settings_file_path, 'w') as file:
		json.dump(settings_dict, file, indent='\t')

def load_settings():
	global settings
	default = settings.to_dict()
	try:
		with open(settings_file_path, 'r') as file:
			settings_dict = json.load(file)
			different = True if default.keys() != settings_dict.keys() else False
			if different:
				for key in default:
					if key not in settings_dict: settings_dict[key] = default[key]
			settings = DotDict(settings_dict)
			if different: save_settings()
	except Exception as e: print(e)
	return settings

settings_dict = {
	'host':'http://localhost:11434',
	'system':"",
}
settings = DotDict(settings_dict)
