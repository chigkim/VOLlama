import platform

class Speech:
    def __init__(self):
        self.os = platform.system()
        self.synth = self.setup_synth()

    def setup_synth(self):
        if self.os == 'Darwin':
            from AppKit import NSSpeechSynthesizer
            return NSSpeechSynthesizer.alloc().init()
        elif self.os == 'Windows':
            import win32com.client
            return win32com.client.Dispatch("SAPI.SpVoice")
        else:
            raise NotImplementedError(f"Platform '{self.os}' not supported")

    def speak(self, text):
        if self.os == 'Darwin':
            self.synth.startSpeakingString_(text)
        elif self.os == 'Windows':
            self.synth.Speak(text)

    def stop(self):
        if self.os == 'Darwin':
            self.synth.stopSpeaking()
        elif self.os == 'Windows':
            self.synth.Speak("", 3)

    def get_voices(self):
        if self.os == 'Darwin':
            from AppKit import NSSpeechSynthesizer
            return [NSSpeechSynthesizer.availableVoices().objectAtIndex_(i).lastPathComponent() for i in range(NSSpeechSynthesizer.availableVoices().count())]
        elif self.os == 'Windows':
            return [voice.GetDescription() for voice in self.synth.GetVoices()]

    def set_voice(self, voice_name):
        if self.os == 'Darwin':
            from AppKit import NSSpeechSynthesizer
            self.synth.setVoice_(NSSpeechSynthesizer.availableVoices().objectAtIndex_(voice_name))
        elif self.os == 'Windows':
            for voice in self.synth.GetVoices():
                if voice.GetDescription() == voice_name:
                    self.synth.Voice = voice
                    break

    def get_rate(self):
        if self.os == 'Darwin':
            return self.synth.rate()
        elif self.os == 'Windows':
            return self.synth.Rate

    def set_rate(self, rate):
        if self.os == 'Darwin':
            self.synth.setRate_(rate)
        elif self.os == 'Windows':
            self.synth.Rate = rate
