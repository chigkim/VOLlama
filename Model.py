from ollama import Client
import wx
import traceback
from pathlib import Path

class Model:	
	def __init__(self, name="neural-chat", host="http://localhost:11434"):
		self.host = host
		self.client = Client(host=host)
		self.messages = []
		self.name = name
		self.generate = False
	def setHost(self, host):
		self.host = host
		self.client = Client(host=host)
		self.image = None

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
		self.messages.append(message)
		try:
			response = self.client.chat(model=self.name, messages=self.messages, stream=True)
			message = ""
			wx.CallAfter(responseControl.AppendText, self.name[:self.name.index(":")].capitalize() + ": ")
			self.generate = True
			for chunk in response:
				chunk = chunk['message']['content']
				message += chunk
				wx.CallAfter(responseControl.AppendText, chunk)
				if not self.generate: break
			wx.CallAfter(responseControl.AppendText, "\n")
			self.messages.append({"role":"assistant", "content":message.strip()})
		except Exception as e:
			print(traceback.format_exc())
			dialog = wx.MessageDialog(None, str(e), "Error", wx.OK | wx.ICON_ERROR)
			dialog.ShowModal()
			dialog.Destroy()
		finally:
			self.generate = False
			wx.CallAfter(onStop)
