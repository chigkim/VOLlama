"""No speech at all, for platforms with no backend of their own.

A real implementation of "say nothing" rather than a None the callers have to
check for: the window speaks a sentence at a time while a reply streams, and
guarding every one of those calls would be worse than this file.
"""


class SilentSpeech:
    def speak(self, text):
        pass

    def stop(self):
        pass

    def voices(self):
        return []

    @property
    def voice(self):
        return ""

    @property
    def rate(self):
        return 0.0
