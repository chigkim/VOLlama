import torch
from TTS.api import TTS
import sounddevice as sd
import threading

class Speech:
	def __init__(self):
		device = "cuda" if torch.cuda.is_available() else "cpu"
		self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

	def speak(self, text):
		def generate(text):
			wav = self.tts.tts(text=text, speaker_wav="speaker.wav", language="en")
			sd.play(wav, samplerate=22050)
		threading.Thread(target=generate, args=(text,)).start()
