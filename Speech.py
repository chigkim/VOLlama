import platform
import wx
class SpeechDialog(wx.Dialog):
	def __init__(self, parent, title, voices, current_voice, rate):
		super(SpeechDialog, self).__init__(parent, title=title, size=(250, 200))
		panel = wx.Panel(self)
		vbox = wx.BoxSizer(wx.VERTICAL)

		self.voices_choice = wx.Choice(panel, choices=voices)
		if current_voice in voices:
			self.voices_choice.SetStringSelection(current_voice)

		self.rate_text_ctrl = wx.TextCtrl(panel, value=str(rate))
		ok_button = wx.Button(panel, label='OK', id=wx.ID_OK)
		cancel_button = wx.Button(panel, label='Cancel', id=wx.ID_CANCEL)

		vbox.Add(wx.StaticText(panel, label="Voice"), flag=wx.LEFT|wx.TOP, border=10)
		vbox.Add(self.voices_choice, flag=wx.EXPAND|wx.LEFT|wx.RIGHT, border=10)
		vbox.Add(wx.StaticText(panel, label="Rate"), flag=wx.LEFT|wx.TOP, border=10)
		vbox.Add(self.rate_text_ctrl, flag=wx.EXPAND|wx.LEFT|wx.RIGHT, border=10)
		vbox.Add(ok_button, flag=wx.LEFT|wx.BOTTOM, border=10)
		vbox.Add(cancel_button, flag=wx.LEFT|wx.BOTTOM, border=10)

		panel.SetSizer(vbox)

	def get_selections(self):
		return self.voices_choice.GetStringSelection(), self.rate_text_ctrl.GetValue()

class Speech:
	def __init__(self):
		self.os = platform.system()
		self.synth = self.setup_synth()

	def setup_synth(self):
		if self.os == 'Darwin':
			from AppKit import NSSpeechSynthesizer
			return NSSpeechSynthesizer.alloc().init()
		elif self.os == 'Windows':
			import win32com.client
			return win32com.client.Dispatch("SAPI.SpVoice")
		else:
			raise NotImplementedError(f"Platform '{self.os}' not supported")

	def get_current_voice(self):
		if self.os == 'Darwin':
			from AppKit import NSSpeechSynthesizer
			voice_description = self.synth.voice().lastPathComponent()
			return voice_description
		elif self.os == 'Windows':
			return self.synth.Voice.GetDescription()

	def speak(self, text):
		if self.os == 'Darwin':
			self.synth.startSpeakingString_(text)
		elif self.os == 'Windows':
			self.synth.Speak(text,1)

	def stop(self):
		if self.os == 'Darwin':
			self.synth.stopSpeaking()
		elif self.os == 'Windows':
			self.synth.Speak("", 3)

	def get_voices(self):
		if self.os == 'Darwin':
			from AppKit import NSSpeechSynthesizer
			return [NSSpeechSynthesizer.availableVoices().objectAtIndex_(i).lastPathComponent() for i in range(NSSpeechSynthesizer.availableVoices().count())]
		elif self.os == 'Windows':
			return [voice.GetDescription() for voice in self.synth.GetVoices()]

	def set_voice(self, voice_name):
		if self.os == 'Darwin':
			from AppKit import NSSpeechSynthesizer
			self.synth.setVoice_(NSSpeechSynthesizer.availableVoices().objectAtIndex_(voice_name))
		elif self.os == 'Windows':
			for voice in self.synth.GetVoices():
				if voice.GetDescription() == voice_name:
					self.synth.Voice = voice
					break

	def get_rate(self):
		if self.os == 'Darwin':
			return self.synth.rate()
		elif self.os == 'Windows':
			return self.synth.Rate

	def set_rate(self, rate):
		if self.os == 'Darwin':
			self.synth.setRate_(rate)
		elif self.os == 'Windows':
			self.synth.Rate = rate

	def present_voice_rate_dialog(self, e=None):
		voices = self.get_voices()
		current_voice = self.get_current_voice()
		current_rate = str(self.get_rate())
		dialog = SpeechDialog(None, 'Select Voice and Rate', voices, current_voice, current_rate)
		if dialog.ShowModal() == wx.ID_OK:
			selected_voice, selected_rate = dialog.get_selections()
			self.set_voice(selected_voice)
			self.set_rate(int(selected_rate))
		dialog.Destroy()
