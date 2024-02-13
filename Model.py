from ollama import Client
import wx
from pathlib import Path
from Utils import displayError
from RAG import RAG

class Model:	
	def __init__(self, name="neural-chat", host="http://localhost:11434"):
		self.host = host
		self.client = Client(host=host)
		self.messages = []
		self.name = name
		self.generate = False
<<<<<<< HEAD
		self.rag = RAG(self.host, self.name)
=======
		self.rag = RAG(self.name, self.host)
>>>>>>> 48128a31d794baaa59c79ebfc51f3443331af89c
		self.image = None
		self.folder = None
		self.url = None

	def setHost(self, host):
		self.host = host
		self.client = Client(host=host)

	def setModel(self, name):
		self.name = name
<<<<<<< HEAD
		self.rag.setModel(self.host, name)
=======
		self.rag.setModel(name, self.host)
>>>>>>> 48128a31d794baaa59c79ebfc51f3443331af89c

	def setSystem(self, system):
		if system == "": return
		system = {'role': 'system', 'content':system}
		if len(self.messages) == 0 or self.messages[0]['role'] != "system":
			self.messages.insert(0, system)
		elif self.messages[0]['role'] == "system":
			self.messages[0] = system

	def ask(self, content, responseControl, onStop):
		message = {'role': 'user', 'content': content}
		if self.image:
			message['images'] = [Path(self.image)]
			self.image = None
			for i in range(len(self.messages)):
				if 'images' in self.messages[i]: self.messages[i].pop('images')
		try:
			if content.startswith("/r ") and (self.folder or self.url):
				message['content'] = message['content'][3:]
				response = self.rag.ask(message['content'])
			else:
				response = self.client.chat(model=self.name, messages=self.messages, stream=True)
			self.messages.append(message)
			message = ""
			wx.CallAfter(responseControl.AppendText, self.name[:self.name.index(":")].capitalize() + ": ")
			self.generate = True
			for chunk in response:
				if not isinstance(chunk, str):
					chunk = chunk['message']['content']
				message += chunk
				wx.CallAfter(responseControl.AppendText, chunk)
				if not self.generate: break
			wx.CallAfter(responseControl.AppendText, "\n")
			self.messages.append({"role":"assistant", "content":message.strip()})
		except Exception as e:
			displayError(e)
		finally:
			self.generate = False
			wx.CallAfter(onStop)
