from Settings import settings
from SpeechDialog import SpeechDialog
import wx


class Speech:
    def __init__(self):
        self.voice = "Silence"
        self.rate = 0.0

    def speak(self, text):
        return

    def stop(self):
        return

    def get_voices(self):
        return ["Silence"]

    def get_current_voice(self):
        return "Silence"

    def set_voice(self, voice):
        self.voice = voice

    def get_rate(self):
        return self.rate

    def set_rate(self, rate):
        self=rate = rate

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
