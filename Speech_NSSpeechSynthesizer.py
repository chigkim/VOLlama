import queue
import weakref
import wx
from Settings import settings
from SpeechDialog import SpeechDialog
from Foundation import NSObject
import AppKit
import objc


class _SynthDelegate(NSObject):

    def initWithOwner_(self, owner):
        self = (
            objc.super(_SynthDelegate, self).init() if hasattr(self, "init") else self
        )
        if self is None:
            return None
        # Store a weak reference to avoid cycles
        self._owner_ref = weakref.ref(owner)
        return self

    def speechSynthesizer_didFinishSpeaking_(self, sender, success):
        owner = self._owner_ref() if hasattr(self, "_owner_ref") else None
        if owner is not None:
            owner._start_next_speech()


class Speech:

    _VOICE_PREFIX = "com.apple.speech.synthesis.voice."

    def __init__(self):
        self.queue = queue.Queue()
        self.synth = self._setup_synth()

        # Initialize voice and rate from Settings (with sensible defaults)
        self.voice = (
            settings.voice
            if getattr(settings, "voice", "unknown") != "unknown"
            else self.synth.voice()
        )
        self.rate = float(getattr(settings, "rate", 175))

        if self.voice:
            self.set_voice(self.voice)
        self.set_rate(self.rate)

    def _setup_synth(self):
        synth = AppKit.NSSpeechSynthesizer.alloc().init()
        self._delegate = _SynthDelegate.alloc().initWithOwner_(self)
        synth.setDelegate_(self._delegate)
        return synth

    def speak(self, text: str):
        self.queue.put(text)
        if not self.synth.isSpeaking():
            self._start_next_speech()

    def _start_next_speech(self):
        if not self.queue.empty():
            text = self.queue.get()
            self.synth.startSpeakingString_(text)
            self.queue.task_done()

    def stop(self):
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except Exception:
                break
            finally:
                self.queue.task_done()

        self.synth.stopSpeaking()

    def get_voices(self):
        voices = list(AppKit.NSSpeechSynthesizer.availableVoices())
        voices.sort()
        return voices

    def get_current_voice(self):
        current = self.synth.voice()
        return current or self.voice

    def set_voice(self, voice_identifier: str):
        voices = set(AppKit.NSSpeechSynthesizer.availableVoices())
        if voice_identifier not in voices:
            short = voice_identifier
            if not short.startswith(self._VOICE_PREFIX):
                candidate = self._VOICE_PREFIX + short
                if candidate in voices:
                    voice_identifier = candidate

        if voice_identifier in voices:
            applied = self.synth.setVoice_(voice_identifier)
            if applied:  # setVoice_ returns BOOL
                settings.voice = voice_identifier
                self.voice = voice_identifier

    def get_rate(self) -> float:
        try:
            return float(self.synth.rate())
        except Exception:
            return float(self.rate)

    def set_rate(self, rate: float):
        self.synth.setRate_(rate)
        settings.rate = rate
        self.rate = rate

    def present_voice_rate_dialog(self, e=None):
        voices = self.get_voices()

        def _short(v: str) -> str:
            return (
                v.replace(self._VOICE_PREFIX, "")
                .replace("com.apple.", "")
                .replace("voice.", "")
            )

        short_voices = [_short(v) for v in voices]

        current_voice = self.get_current_voice() or ""
        current_voice_short = _short(current_voice)
        current_rate = str(self.get_rate())

        dialog = SpeechDialog(
            None,
            "Select Voice and Rate",
            short_voices,
            current_voice_short,
            current_rate,
        )
        try:
            if dialog.ShowModal() == wx.ID_OK:
                selected_voice_short, selected_rate = dialog.get_selections()

                candidate = self._VOICE_PREFIX + selected_voice_short
                if candidate not in voices:
                    candidate_alt = "com.apple." + selected_voice_short
                    if candidate_alt in voices:
                        candidate = candidate_alt

                self.set_voice(candidate)
                print(candidate)
                try:
                    self.set_rate(float(selected_rate))
                except Exception:
                    pass
        finally:
            dialog.Destroy()
