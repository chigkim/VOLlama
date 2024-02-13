from ollama import Client
import wx
from Utils import displayError
from pathlib import Path
import re
import os
from Parameters import get_parameters

class Model:	
	def __init__(self, name="neural-chat", host="http://localhost:11434"):
		self.host = host
		self.client = Client(host=host)
		self.messages = []
		self.name = name
		self.generate = False
		self.image = None
		self.parameters = None
		
	def load_parameters(self):
		self.parameters = get_parameters()

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
			self.messages.append(message)
			response = self.client.chat(model=self.name, messages=self.messages, stream=True, options=self.parameters)
			message = ""
			wx.CallAfter(window.response.AppendText, self.name[:self.name.index(":")].capitalize() + ": ")
			self.generate = True
			sentence = ""
			for chunk in response:
				data = chunk
				chunk = chunk['message']['content']
				message += chunk
				if window.speakResponse.IsChecked():
					sentence += chunk
					if re.search(r'[\.\?!\n]\s*$', sentence):
						sentence = sentence.strip()
						if sentence:
							wx.CallAfter(window.speech.speak, sentence)
						sentence = ""
				wx.CallAfter(window.response.AppendText, chunk)
				if not self.generate: break
			if sentence and window.speakResponse.IsChecked(): wx.CallAfter(window.speech.speak, sentence)
			wx.CallAfter(window.response.AppendText, os.linesep)
			div = 1000000000
			if 'total_duration' in data:
				total = data['total_duration']/div
				load = data['load_duration']/div
				prompt_count = data['prompt_eval_count'] if 'prompt_eval_count' in data else 0
				prompt_duration = data['prompt_eval_duration']/div
				gen_count = data['eval_count']
				gen_duration = data['eval_duration']/div
				stat = f"Total: {total:.2f} secs, Load: {load:.2f} secs, Prompt: {prompt_count} tokens ({prompt_count/prompt_duration:.2f} t/s), Output: {gen_count} tokens ({gen_count/gen_duration:.2f} t/s)"
				wx.CallAfter(window.setStatus, stat)
			else:
				wx.CallAfter(window.setStatus, "Interrupted.")
			self.messages.append({"role":"assistant", "content":message.strip()})
		except Exception as e:
			self.messages.pop()
			displayError(e)
		finally:
			self.generate = False
			wx.CallAfter(window.onStopGeneration)
