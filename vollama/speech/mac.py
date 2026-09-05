"""macOS speech, through NSSpeechSynthesizer.

The synthesiser speaks one utterance at a time and tells its delegate when it
has finished, so a queue and a delegate are what turn "speak this sentence"
into something that can be called while a reply is still streaming.
"""

import functools
import queue
import weakref

import AppKit
import objc
from Foundation import NSLocale, NSObject

from vollama.speech import Voice


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
        """Every installed voice, as a record naming it and its language.

        Sorted by language and then name, which is the order the menu shows
        them in; `group()` keeps whatever order it is handed.

        This is every voice the system will lend out, and on a machine with
        Siri voices installed it is fewer than the ones you can hear Siri use.
        Only the `neuralAX` build of a Siri voice is published to
        NSSpeechSynthesizer, so `en_US.nora.neuralAX.premium` shows up as
        "Voice 4" while `ko_KR.minji.gryphon.premium`, sitting in the same
        asset folder, is not offered here, by AVSpeechSynthesisVoice, or by
        `say -v '?'`. There is nothing to fix on our side of that.
        """
        return sorted(
            (_voice(identifier) for identifier in AppKit.NSSpeechSynthesizer.availableVoices()),
            key=lambda voice: (voice.language, voice.name),
        )

    @property
    def voice(self):
        return self.synth.voice() or ""

    @voice.setter
    def voice(self, identifier):
        # A voice this machine does not have is ignored rather than passed on,
        # since NSSpeechSynthesizer answers a bad identifier by falling silent.
        if identifier in set(AppKit.NSSpeechSynthesizer.availableVoices()):
            self.synth.setVoice_(identifier)

    @property
    def rate(self):
        return float(self.synth.rate())

    @rate.setter
    def rate(self, rate):
        self.synth.setRate_(float(rate))


def _voice(identifier):
    """One `Voice` from a macOS voice identifier.

    A voice with no attributes at all is named by its identifier rather than
    dropped: it is still speakable, and an unnamed entry in the menu is a
    better failure than a voice that has silently gone missing.
    """
    attributes = AppKit.NSSpeechSynthesizer.attributesForVoice_(identifier) or {}
    name = str(attributes.get("VoiceName") or identifier)
    return Voice(identifier, name, _language(str(attributes.get("VoiceLocaleIdentifier") or "")))


@functools.lru_cache(maxsize=None)
def _language(locale):
    """`ko_KR` as "Korean (South Korea)", in the user's own language.

    Cached because there are far more voices than locales, and every macOS
    release adds voices faster than languages.
    """
    if not locale:
        return ""
    return str(NSLocale.currentLocale().localizedStringForLocaleIdentifier_(locale) or locale)
