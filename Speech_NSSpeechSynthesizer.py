import queue
import weakref
import wx
from Settings import settings
from SpeechDialog import SpeechDialog
from Foundation import NSObject
import AppKit


# -------------------------
# Internal Objective-C delegate bridging
# -------------------------
class _SynthDelegate(NSObject):
    """
    Minimal NSSpeechSynthesizer delegate that notifies the owning Speech instance
    when an utterance completes so the next item in the queue can start.
    """

    def initWithOwner_(self, owner):
        self = (
            objc.super(_SynthDelegate, self).init() if hasattr(self, "init") else self
        )
        if self is None:
            return None
        # Store a weak reference to avoid cycles
        self._owner_ref = weakref.ref(owner)
        return self

    # Delegate signature: - (void)speechSynthesizer:(NSSpeechSynthesizer *)sender didFinishSpeaking:(BOOL)success
    def speechSynthesizer_didFinishSpeaking_(self, sender, success):
        owner = self._owner_ref() if hasattr(self, "_owner_ref") else None
        if owner is not None:
            owner._start_next_speech()


# PyObjC automatically provides objc module when installing pyobjc; import late to avoid
# import errors on non-mac platforms when this file is inspected.
try:
    import objc  # noqa: E402
except Exception:  # pragma: no cover
    objc = None


# -------------------------
# Public Speech API
# -------------------------
class Speech:
    """
    A thin queueing wrapper around AppKit.NSSpeechSynthesizer.

    Notes:
    - rate in NSSpeechSynthesizer is approximately words per minute (float).
    - voice identifiers look like 'com.apple.speech.synthesis.voice.Alex'.
    """

    # Common prefix used by NSSpeechSynthesizer voice identifiers
    _VOICE_PREFIX = "com.apple.speech.synthesis.voice."

    def __init__(self):
        if objc is None:
            raise RuntimeError(
                "PyObjC is required on macOS to use NSSpeechSynthesizer."
            )

        self.queue = queue.Queue()
        self.synth = self._setup_synth()

        # Initialize voice and rate from Settings (with sensible defaults)
        self.voice = (
            settings.voice
            if getattr(settings, "voice", "unknown") != "unknown"
            else self.synth.voice()
        )
        # Default to 200 wpm if settings not provided; NSS default is ~175
        self.rate = float(getattr(settings, "rate", 200.0))

        # Apply initial configuration safely
        if self.voice:
            self.set_voice(self.voice)
        self.set_rate(self.rate)

    # -------------------------
    # Setup and delegation
    # -------------------------
    def _setup_synth(self):
        synth = AppKit.NSSpeechSynthesizer.alloc().init()
        # Attach delegate so we get didFinishSpeaking callbacks
        self._delegate = _SynthDelegate.alloc().initWithOwner_(self)
        synth.setDelegate_(self._delegate)
        return synth

    # -------------------------
    # Core speak/queue controls
    # -------------------------
    def speak(self, text: str):
        """
        Enqueue text to be spoken. If synthesizer is idle, start immediately.
        """
        if not isinstance(text, str) or not text.strip():
            return

        # Store plain strings; NSSpeechSynthesizer accepts startSpeakingString_
        self.queue.put(text)

        if not self.synth.isSpeaking():
            self._start_next_speech()

    def _start_next_speech(self):
        """
        Dequeue the next string and speak it. Called after completion via delegate.
        """
        if not self.queue.empty():
            text = self.queue.get()
            # Start speaking; returns bool for success
            ok = self.synth.startSpeakingString_(text)
            # Mark the queue item done regardless; if failed, move on.
            self.queue.task_done()
            # If start failed and there is more queued, attempt to continue
            if not ok and not self.queue.empty():
                self._start_next_speech()

    def stop(self):
        """
        Immediately stop speaking and clear the queue.
        """
        # Clear pending queue
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except Exception:
                break
            finally:
                self.queue.task_done()

        # Stop current speech
        # NSSpeechSynthesizer supports stopSpeaking(), pause/continue APIs.
        self.synth.stopSpeaking()

    # -------------------------
    # Voice and rate controls
    # -------------------------
    def get_voices(self):
        """
        Return a sorted list of available voice identifiers.
        Example identifier: 'com.apple.speech.synthesis.voice.Alex'
        """
        voices = list(AppKit.NSSpeechSynthesizer.availableVoices())
        voices.sort()
        return voices

    def get_current_voice(self):
        """
        Return the currently configured voice identifier.
        """
        # Prefer the synthesizer's current setting
        current = self.synth.voice()
        return current or self.voice

    def set_voice(self, voice_identifier: str):
        """
        Set the voice by identifier (must be one of availableVoices()).
        """
        if not voice_identifier:
            return

        voices = set(AppKit.NSSpeechSynthesizer.availableVoices())
        # If user passed a short name, expand it with prefix
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
        """
        Return the current words-per-minute rate (float).
        """
        try:
            return float(self.synth.rate())
        except Exception:
            return float(self.rate)

    def set_rate(self, rate: float):
        """
        Set speaking rate (approximate words per minute).
        Typical comfortable range is ~120 to ~360 on macOS.
        """
        try:
            r = float(rate)
        except Exception:
            return

        # Apply reasonable bounds to avoid extreme values
        r = max(80.0, min(500.0, r))
        self.synth.setRate_(r)
        settings.rate = r
        self.rate = r

    # -------------------------
    # UI integration
    # -------------------------
    def present_voice_rate_dialog(self, e=None):
        """
        Show a wx dialog to choose voice and rate; updates settings on success.
        """
        voices = self.get_voices()

        # Display readable short names to users
        def _short(v: str) -> str:
            return v.replace(self._VOICE_PREFIX, "").replace("com.apple.", "")

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

                # Re-expand to full identifier
                # Prefer NSSpeechSynthesizer prefix; fall back to com.apple.* if present
                candidate = self._VOICE_PREFIX + selected_voice_short
                if candidate not in voices:
                    # Try with legacy 'com.apple.' prefix if the dialog used that form
                    candidate_alt = "com.apple." + selected_voice_short
                    if candidate_alt in voices:
                        candidate = candidate_alt

                self.set_voice(candidate)
                try:
                    self.set_rate(float(selected_rate))
                except Exception:
                    pass
        finally:
            dialog.Destroy()
