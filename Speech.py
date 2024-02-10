import platform
import time

class Speech:
	def __init__(self):
		self.os = platform.system()
		self.synth = self.setup_synth()

	def setup_synth(self):
		if self.os == 'Darwin':
			import AppKit
			return AppKit.NSSpeechSynthesizer.alloc().init()
		elif self.os == 'Windows':
			import win32com.client as wincom
			return wincom.Dispatch("SAPI.SpVoice")
		else:
			raise NotImplementedError(f"Platform '{self.os}' not supported")

	def speak(self, text):
		if self.os == 'Darwin':
			self.synth.startSpeakingString_(text)
		elif self.os == 'Windows':
			self.synth.Speak(text, 1)

	def stop(self):
		if self.os == 'Darwin':
			self.synth.stopSpeaking()
		elif self.os == 'Windows':
			self.synth.Speak("", 3)
