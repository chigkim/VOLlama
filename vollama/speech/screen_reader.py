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

    @property
    def voice(self):
        return ""

    @property
    def rate(self):
        return 0.0
