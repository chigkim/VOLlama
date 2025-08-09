import queue
from Settings import settings
import AVFoundation
from SpeechDialog import SpeechDialog
import wx


class Speech:
    def __init__(self):
        self.queue = queue.Queue()
        self.synth = self.setup_synth()
        self.voice = settings.voice
        self.rate = 0.6
        if settings.voice != "unknown":
            self.set_voice(settings.voice)
            self.set_rate(settings.rate)

    def setup_synth(self):
        synth = AVFoundation.AVSpeechSynthesizer.alloc().init()
        synth.setDelegate_(self)
        return synth

    def speak(self, text):
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

        self.synth.stopSpeakingAtBoundary_(AVFoundation.AVSpeechBoundaryImmediate)

    def get_voices(self):
        voices = [
            voice.identifier()
            for voice in AVFoundation.AVSpeechSynthesisVoice.speechVoices()
        ]
        voices.sort()
        return voices

    def get_current_voice(self):
        return self.voice

    def set_voice(self, voice_identifier):
        settings.voice = voice_identifier
        self.voice = voice_identifier

    def get_rate(self):
        return self.rate

    def set_rate(self, rate):
        settings.rate = rate
        self.rate = rate

    def present_voice_rate_dialog(self, e=None):
        voices = self.get_voices()
        voices = [voice.replace("com.apple.", "") for voice in voices]
        current_voice = self.get_current_voice()
        current_voice = current_voice.replace("com.apple.", "")
        current_rate = str(self.get_rate())
        dialog = SpeechDialog(
            None, "Select Voice and Rate", voices, current_voice, current_rate
        )
        if dialog.ShowModal() == wx.ID_OK:
            selected_voice, selected_rate = dialog.get_selections()
            selected_voice = "com.apple." + selected_voice
            self.set_voice(selected_voice)
            self.set_rate(float(selected_rate))
        dialog.Destroy()
