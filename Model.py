from ollama import Client
import wx
from Utils import displayError
from pathlib import Path
import re
import os
from Parameters import get_parameters
from RAG import RAG
from Settings import settings
import re

class Model:	
	def __init__(self, name="neural-chat", host="http://localhost:11434"):
		self.host = host
		self.client = Client(host=host)
		self.messages = []
		self.name = name
		self.generate = False
		self.image = None
		self.rag = None
		self.load_parameters()

	def updateRag(self):
		self.rag.update_settings(self.host, self.name)

	def startRag(self, path, setStatus):
		self.rag = RAG(self.host, self.name)
		if isinstance(path, list): self.rag.loadFolder(path, setStatus)
		elif path.startswith("http"): self.rag.loadUrl(path, setStatus)
		else: self.rag.loadFolder(path, setStatus)
		
	def load_parameters(self):
		self.parameters = get_parameters()
		
	def setHost(self, host):
		self.host = host
		self.client = Client(host=host)
		if self.rag: self.updateRag()

	def setModel(self, name):
		self.name = name
		if self.rag: self.updateRag()

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
			if content.startswith("/q ") and self.rag:
				if not self.rag.index:
					displayError(Exception("No index found."))
					return
				message['content'] = message['content'][3:]
				self.messages.append(message)
				wx.CallAfter(window.setStatus, "Processing with RAG...")
				response = self.rag.ask(message['content'])
			else:
				self.messages.append(message)
				wx.CallAfter(window.setStatus, "Processing...")
				response = self.client.chat(model=self.name, messages=self.messages, stream=True, options=self.parameters)
			message = ""
			wx.CallAfter(window.response.AppendText, self.name[:self.name.index(":")].capitalize() + ": ")
			self.generate = True
			sentence = ""
			for chunk in response:
				if not sentence: wx.CallAfter(window.setStatus, "Typing...")
				data = chunk
				if not isinstance(chunk, str):
					chunk = chunk['message']['content']
				message += chunk
				if settings.speakResponse:
					sentence += chunk
					if re.search(r'[\.\?!\n]\s*$', sentence):
						sentence = sentence.strip()
						if sentence:
							wx.CallAfter(window.speech.speak, sentence)
						sentence = ""
				wx.CallAfter(window.response.AppendText, chunk)
				if not self.generate: break
			if sentence and settings.speakResponse: wx.CallAfter(window.speech.speak, sentence)
			wx.CallAfter(window.response.AppendText, os.linesep)
			if settings.show_context and content.startswith("/q ") and self.rag:
				nodes = self.rag.response.source_nodes
				for i in range(len(nodes)):
					text = nodes[i].text
					text = re.sub(r'\n+', '\n', text)
					wx.CallAfter(window.response.AppendText, f"----------{os.linesep}Context {i+1} similarity score: {nodes[i].score:.2f}\n{text}{os.linesep}")

			if 'total_duration' in data:
				div = 1000000000
				total = data['total_duration']/div
				load = data['load_duration']/div
				prompt_count = data['prompt_eval_count'] if 'prompt_eval_count' in data else 0
				prompt_duration = data['prompt_eval_duration']/div
				gen_count = data['eval_count']
				gen_duration = data['eval_duration']/div
				stat = f"Total: {total:.2f} secs, Load: {load:.2f} secs, Prompt: {prompt_count} tokens ({prompt_count/prompt_duration:.2f} t/s), Output: {gen_count} tokens ({gen_count/gen_duration:.2f} t/s)"
				wx.CallAfter(window.setStatus, stat)
			elif content.startswith("/q ") and self.rag:
				message = f"Embedding Tokens: {self.rag.token_counter.total_embedding_token_count}, LLM Prompt Tokens: {self.rag.token_counter.prompt_llm_token_count}, LLM Completion Tokens: {self.rag.token_counter.completion_llm_token_count}, Total LLM Token Count {self.rag.token_counter.total_llm_token_count}"
				wx.CallAfter(window.setStatus, message)
			else:
				wx.CallAfter(window.setStatus, "Finished.")
			self.messages.append({"role":"assistant", "content":message.strip()})
		except Exception as e:
			self.messages.pop()
			displayError(e)
		finally:
			self.generate = False
			wx.CallAfter(window.onStopGeneration)
