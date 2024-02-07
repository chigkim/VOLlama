from ollama import Client
import wx

class Model:	
	def __init__(self, name="neural-chat", host="http://localhost:11434", temperature=0.1):
		self.host = host
		self.client = Client(host=host)
		self.messages = []
		self.name = name
		self.generate = False
		self.temperature = temperature

	def setHost(self, host):
		self.host = host
		self.client = Client(host=host)

	def ask(self, content, responseControl, onStop):
		self.messages.append({'role': 'user', 'content': content})
		try:
			response = self.client.chat(model=self.name, messages=self.messages, stream=True, options={"temperature":self.temperature})
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
			dialog = wx.MessageDialog(None, str(e), "Error", wx.OK | wx.ICON_ERROR)
			dialog.ShowModal()
			dialog.Destroy()
		finally:
			self.generate = False
			wx.CallAfter(onStop)
