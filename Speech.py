from RealtimeTTS import TextToAudioStream, SystemEngine
import threading

class Speech:
	def __init__(self):
		engine = SystemEngine()
		self.stream = TextToAudioStream(engine)

	def speak(self, text):
		def generate(text):
			self.stream.feed(text)
			self.stream.play_async()
		threading.Thread(target=generate, args=(text,)).start()
