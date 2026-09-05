"""Windows speech, through SAPI.

The `_repaired` wrapper is here for one specific failure. pywin32 caches
generated COM wrappers under `gen_py`, and a cache written by a different
Python or left half-finished raises `AttributeError: CLSIDToClassMap` on every
call afterwards. The only fix is to delete the cache and dispatch again, which
the user cannot be expected to know, so we do it once and retry.
"""

import logging
import shutil
from pathlib import Path

import win32com.client.dynamic
import win32com.client.gencache

from vollama.speech import described

log = logging.getLogger(__name__)


class SapiSpeech:
    def __init__(self):
        self.synth = _dispatch()

    def speak(self, text):
        # 1 is SPF_ASYNC: queue it and return, so streaming text is not blocked
        # waiting for the previous sentence to finish.
        self.synth.Speak(text, 1)

    def stop(self):
        # 3 is SPF_ASYNC | SPF_PURGEBEFORESPEAK: drop the queue.
        self.synth.Speak("", 3)

    def voices(self):
        """Every installed voice, split into a name and a language.

        `described()` does the splitting and keeps the whole description as the
        identifier, so `voice` below still matches on `GetDescription()`.
        """
        return self._repaired(
            lambda: [described(voice.GetDescription()) for voice in self.synth.GetVoices()]
        )

    @property
    def voice(self):
        return self._repaired(lambda: self.synth.Voice.GetDescription())

    @voice.setter
    def voice(self, identifier):
        def apply():
            for voice in self.synth.GetVoices():
                if voice.GetDescription() == identifier:
                    self.synth.Voice = voice
                    return

        self._repaired(apply)

    @property
    def rate(self):
        return self.synth.Rate

    @rate.setter
    def rate(self, rate):
        self.synth.Rate = int(rate)

    def _repaired(self, action):
        """Run action, rebuilding pywin32's COM cache once if it is corrupt."""
        try:
            return action()
        except AttributeError as e:
            if "CLSIDToClassMap" not in str(e):
                raise
            log.warning("Rebuilding the pywin32 COM cache after %s", e)
            _clear_cache()
            self.synth = _dispatch()
            return action()


def _dispatch():
    return win32com.client.dynamic.Dispatch("SAPI.SpVoice")


def _clear_cache():
    path = Path(win32com.client.gencache.GetGeneratePath())
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
