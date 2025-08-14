from Settings import settings
import win32com.client
from SpeechDialog import SpeechDialog
import wx


class Speech:
    def __init__(self):
        self.synth = self.setup_synth()
        self.voice = settings.voice
        self.rate = 0.6
        if settings.voice != "default":
            self.set_voice(settings.voice)
            self.set_rate(settings.rate)

    def setup_synth(self):
        return win32com.client.Dispatch("SAPI.SpVoice")

    def speak(self, text):
        self.synth.Speak(text, 1)

    def stop(self):
        self.synth.Speak("", 3)

    def get_voices(self):
        return [voice.GetDescription() for voice in self.synth.GetVoices()]

    def get_current_voice(self):
        return self.synth.Voice.GetDescription()

    def set_voice(self, voice_identifier):
        settings.voice = voice_identifier
        if "default" in voice_identifier:
            self.synth = self.setup_synth()
            return
        for voice in self.synth.GetVoices():
            if voice.GetDescription() == voice_identifier:
                self.synth.Voice = voice
                return

    def get_rate(self):
        return self.synth.Rate

    def set_rate(self, rate):
        settings.rate = rate
        self.synth.Rate = rate

    def present_voice_rate_dialog(self, e=None):
        voices = self.get_voices()
        current_voice = self.get_current_voice()
        current_rate = str(self.get_rate())
        dialog = SpeechDialog(
            None, "Select Voice and Rate", voices, current_voice, current_rate
        )
        if dialog.ShowModal() == wx.ID_OK:
            selected_voice, selected_rate = dialog.get_selections()
            self.set_voice(selected_voice)
            self.set_rate(float(selected_rate))
        dialog.Destroy()
