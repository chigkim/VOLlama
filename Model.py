from ollama import Client
import wx
from Utils import displayError
from pathlib import Path
import re

class Model:	
	def __init__(self, name="neural-chat", host="http://localhost:11434"):
		self.host = host
		self.client = Client(host=host)
		self.messages = []
		self.name = name
		self.generate = False
		self.image = None

	def setHost(self, host):
		self.host = host
		self.client = Client(host=host)

	def setModel(self, name):
		self.name = name

	def setSystem(self, system):
		if system == "": return
		system = {'role': 'system', 'content':system}
		if len(self.messages) == 0 or self.messages[0]['role'] != "system":
			self.messages.insert(0, system)
		elif self.messages[0]['role'] == "system":
			self.messages[0] = system

	def ask(self, content, window):
		message = {'role': 'user', 'content': content}
		if self.image:
			message['images'] = [Path(self.image)]
			self.image = None
			for i in range(len(self.messages)):
				if 'images' in self.messages[i]: self.messages[i].pop('images')
		try:
			response = self.client.chat(model=self.name, messages=self.messages, stream=True)
			self.messages.append(message)
			message = ""
			wx.CallAfter(window.response.AppendText, self.name[:self.name.index(":")].capitalize() + ": ")
			self.generate = True
			sentence = ""
			for chunk in response:
				chunk = chunk['message']['content']
				message += chunk
				if window.speakResponse.IsChecked():
					sentence += chunk
					if re.search(r'[\.\?!\n]\s*$', sentence):
						window.speech.speak(sentence)
						sentence = ""
				wx.CallAfter(window.response.AppendText, chunk)
				if not self.generate: break
			wx.CallAfter(window.response.AppendText, "\n")
			self.messages.append({"role":"assistant", "content":message.strip()})
		except Exception as e:
			displayError(e)
		finally:
			self.generate = False
			wx.CallAfter(window.onStopGeneration)
