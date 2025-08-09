from accessible_output2.outputs.auto import Auto


class Speech:
    def __init__(self):
        self.synth = Auto().get_first_available_output()

    def speak(self, text):
        self.synth.speak(text, False)

    def stop(self):
        self.synth.silence()

    def present_voice_rate_dialog(self, e=None):
        return
