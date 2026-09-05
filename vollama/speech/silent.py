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

    # Plain attributes rather than read-only properties: there is nothing to
    # configure here, and a backend that raised on being set would make
    # `speech.create` ask which backend it was holding.
    voice = ""
    rate = 0.0
