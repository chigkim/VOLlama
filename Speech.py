import platform
import queue
import wx
from Settings import settings

# macOS specific imports
if platform.system() == "Darwin":
	import AVFoundation

# Windows specific imports
elif platform.system() == "Windows":
	import win32com.client


class Speech:
	def __init__(self):
		self.os = platform.system()
		self.queue = queue.Queue()
		self.synth = self.setup_synth()
		self.voice = settings.voice
		self.rate = 0.6
		if settings.voice != "unknown":
			self.set_voice(settings.voice)
			self.set_rate(settings.rate)

	def setup_synth(self):
		if self.os == "Darwin":
			synth = AVFoundation.AVSpeechSynthesizer.alloc().init()
			synth.setDelegate_(self)
			return synth
		elif self.os == "Windows":
			return win32com.client.Dispatch("SAPI.SpVoice")
		else:
			raise NotImplementedError(f"Platform '{self.os}' not supported")

	def speak(self, text):
		if self.os == "Windows":
			self.synth.Speak(text, 1)
		elif self.os == "Darwin":
			utterance = AVFoundation.AVSpeechUtterance.speechUtteranceWithString_(text)
			voice = AVFoundation.AVSpeechSynthesisVoice.voiceWithIdentifier_(self.voice)
			utterance.setVoice_(voice)
			utterance.setRate_(self.rate)
			self.queue.put(utterance)
			if not self.synth.isSpeaking():
				self._start_next_speech()

	def _start_next_speech(self):
		if not self.queue.empty():
			utterance = self.queue.get()
			self.synth.speakUtterance_(utterance)
			self.queue.task_done()

	def speechSynthesizer_didFinishSpeechUtterance_(self, synthesizer, utterance):
		self._start_next_speech()

	def stop(self):
		while not self.queue.empty():
			self.queue.get()
			self.queue.task_done()
		if self.os == "Darwin":
			self.synth.stopSpeakingAtBoundary_(AVFoundation.AVSpeechBoundaryImmediate)
		elif self.os == "Windows":
			self.synth.Speak("", 3)

	def get_voices(self):
		if self.os == "Darwin":
			voices = [
				voice.identifier()
				for voice in AVFoundation.AVSpeechSynthesisVoice.speechVoices()
			]
			voices.sort()
			return voices
		elif self.os == "Windows":
			return [voice.GetDescription() for voice in self.synth.GetVoices()]

	def get_current_voice(self):
		if self.os == "Darwin":
			return self.voice
		elif self.os == "Windows":
			return self.synth.Voice.GetDescription()

	def set_voice(self, voice_identifier):
		settings.voice = voice_identifier
		if self.os == "Darwin":
			self.voice = voice_identifier
		elif self.os == "Windows":
			for voice in self.synth.GetVoices():
				if voice.GetDescription() == voice_identifier:
					self.synth.Voice = voice
					break

	def get_rate(self):
		if self.os == "Darwin":
			return self.rate
		elif self.os == "Windows":
			return self.synth.Rate

	def set_rate(self, rate):
		settings.rate = rate
		if self.os == "Darwin":
			self.rate = rate
		elif self.os == "Windows":
			self.synth.Rate = rate

	def present_voice_rate_dialog(self, e=None):
		voices = self.get_voices()
		if self.os == "Darwin":
			voices = [voice.replace("com.apple.", "") for voice in voices]
		current_voice = self.get_current_voice()
		if self.os == "Darwin":
			current_voice = current_voice.replace("com.apple.", "")
		current_rate = str(self.get_rate())
		dialog = SpeechDialog(
			None, "Select Voice and Rate", voices, current_voice, current_rate
		)
		if dialog.ShowModal() == wx.ID_OK:
			selected_voice, selected_rate = dialog.get_selections()
			if self.os == "Darwin":
				selected_voice = "com.apple." + selected_voice
			self.set_voice(selected_voice)
			self.set_rate(float(selected_rate))
		dialog.Destroy()


class SpeechDialog(wx.Dialog):
	def __init__(self, parent, title, voices, current_voice, rate):
		super(SpeechDialog, self).__init__(parent, title=title, size=(250, 200))
		panel = wx.Panel(self)
		vbox = wx.BoxSizer(wx.VERTICAL)

		self.voices_choice = wx.Choice(panel, choices=voices)
		if current_voice in voices:
			self.voices_choice.SetStringSelection(current_voice)

		self.rate_text_ctrl = wx.TextCtrl(panel, value=str(rate))
		ok_button = wx.Button(panel, label="OK", id=wx.ID_OK)
		cancel_button = wx.Button(panel, label="Cancel", id=wx.ID_CANCEL)

		vbox.Add(wx.StaticText(panel, label="Voice"), flag=wx.LEFT | wx.TOP, border=10)
		vbox.Add(self.voices_choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)
		vbox.Add(wx.StaticText(panel, label="Rate"), flag=wx.LEFT | wx.TOP, border=10)
		vbox.Add(self.rate_text_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)
		vbox.Add(ok_button, flag=wx.LEFT | wx.BOTTOM, border=10)
		vbox.Add(cancel_button, flag=wx.LEFT | wx.BOTTOM, border=10)

		panel.SetSizer(vbox)

	def get_selections(self):
		return self.voices_choice.GetStringSelection(), self.rate_text_ctrl.GetValue()
