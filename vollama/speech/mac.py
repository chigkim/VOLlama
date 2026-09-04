"""macOS speech, through NSSpeechSynthesizer.

The synthesiser speaks one utterance at a time and tells its delegate when it
has finished, so a queue and a delegate are what turn "speak this sentence"
into something that can be called while a reply is still streaming.
"""

import queue
import weakref

import AppKit
import objc
from Foundation import NSObject

from vollama.config.settings import settings


class _Delegate(NSObject):
    """Starts the next utterance when the current one ends."""

    def initWithOwner_(self, owner):
        self = objc.super(_Delegate, self).init()
        if self is None:
            return None
        # Weak, so the delegate does not keep the speech object alive.
        self._owner = weakref.ref(owner)
        return self

    def speechSynthesizer_didFinishSpeaking_(self, sender, success):
        owner = self._owner()
        if owner is not None:
            owner._speak_next()


class MacSpeech:
    def __init__(self):
        self.queue = queue.Queue()
        self.synth = AppKit.NSSpeechSynthesizer.alloc().init()
        self.delegate = _Delegate.alloc().initWithOwner_(self)
        self.synth.setDelegate_(self.delegate)
        if settings.voice and settings.voice != "default":
            self.voice = settings.voice
        if settings.rate:
            self.rate = settings.rate

    def speak(self, text):
        self.queue.put(text)
        if not self.synth.isSpeaking():
            self._speak_next()

    def _speak_next(self):
        if not self.queue.empty():
            self.synth.startSpeakingString_(self.queue.get())
            self.queue.task_done()

    def stop(self):
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
        self.synth.stopSpeaking()

    def voices(self):
        return sorted(AppKit.NSSpeechSynthesizer.availableVoices())

    @property
    def voice(self):
        return self.synth.voice() or ""

    @voice.setter
    def voice(self, identifier):
        if identifier not in set(self.voices()):
            return
        if self.synth.setVoice_(identifier):
            settings.voice = identifier
            settings.save()

    @property
    def rate(self):
        return float(self.synth.rate())

    @rate.setter
    def rate(self, rate):
        self.synth.setRate_(float(rate))
        settings.rate = float(rate)
        settings.save()
