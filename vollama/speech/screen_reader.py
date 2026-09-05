"""Speech through whatever screen reader is running.

The right answer when the user already has one: it speaks in the voice and at
the rate they have chosen system-wide, and it interleaves with the screen
reader's own announcements instead of talking over them. There is nothing here
to configure, which is what an empty voice list means.
"""

from accessible_output2.outputs.auto import Auto


class ScreenReaderSpeech:
    def __init__(self):
        self.output = Auto().get_first_available_output()

    def speak(self, text):
        self.output.speak(text, False)

    def stop(self):
        self.output.silence()

    def voices(self):
        return []

    # Plain attributes rather than read-only properties: there is nothing to
    # configure here, and a backend that raised on being set would make
    # `speech.create` ask which backend it was holding.
    voice = ""
    rate = 0.0
