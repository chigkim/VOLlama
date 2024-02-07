import sounddevice as sd
import soundfile as sf
import numpy as np
import whisper
import queue

class AudioTranscriber:
	def __init__(self, threshold=-16, sample_rate=44100, channels=1, model_name="base"):
		self.threshold = threshold
		self.sample_rate = sample_rate
		self.channels = channels
		self.model_name = model_name
		self.model = whisper.load_model(model_name)

	def audio_callback(self, indata, frames, time, status):
		power = 20 * np.log10(np.abs(indata).max() + 1e-20)  # Avoid log(0) error
		if power < self.threshold:
			self.recording = False
		else:
			self.q.put(indata.copy())

	def record(self):
		self.recording = True
		self.q = queue.Queue()
		self.audio_data = []
		with sd.InputStream(callback=self.audio_callback, samplerate=self.sample_rate, channels=self.channels):
			print("Recording... Speak into the microphone. Stop speaking to end recording.")
			while self.recording:
				sd.sleep(100)
			while not self.q.empty():
				self.audio_data.append(self.q.get())

		self.audio_data = np.concatenate(self.audio_data, axis=0)

	def save_audio(self, filename='output_below_threshold.wav'):
		sf.write(filename, self.audio_data, self.sample_rate)
		return filename

	def transcribe(self, filename):
		result = self.model.transcribe(filename)
		return result["text"]

	def start(self):
		self.record()
		print("Recording stopped. Processing audio...")
		filename = self.save_audio()
		return self.transcribe(filename)
