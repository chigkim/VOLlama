import wx
import threading
from ollama import Client
import sounddevice as sd
import soundfile as sf
import os

def playSD(file):
	p = os.path.join(os.path.dirname(__file__), file)
	data, fs = sf.read(p, dtype='float32')  
	sd.play(data, fs)

def play(file):
	threading.Thread(target=playSD, args=(file,)).start()
	
class Model:	
	def __init__(self, name="neural-chat", host="http://localhost:11434"):
		self.host = host
		self.client = Client(host=host)
		self.messages = []
		self.name = name

	def setHost(self, host):
		self.host = host
		self.client = Client(host=host)

	def setModel(self, name):
		self.name = name

	def ask(self, content, responseControl):
		self.messages.append({'role': 'user', 'content': content})
		try:
			play("send.wav")
			response = self.client.chat(model=self.name, messages=self.messages, stream=True)
			message = ""
			wx.CallAfter(responseControl.AppendText, self.name[:self.name.index(":")].capitalize() + ": ")
			for chunk in response:
				chunk = chunk['message']['content']
				message += chunk
				wx.CallAfter(responseControl.AppendText, chunk)
			wx.CallAfter(responseControl.AppendText, "\n")
			self.messages.append({"role":"assistant", "content":message.strip()})
			play("receive.wav")
		except Exception as e:
			dialog = wx.MessageDialog(None, str(e), "Error", wx.OK | wx.ICON_ERROR)
			dialog.ShowModal()
			dialog.Destroy()

class ChatWindow(wx.Frame):
	def __init__(self, parent, title):
		super(ChatWindow, self).__init__(parent, title=title, size=(1920,1080))
		self.model = Model()
		self.InitUI()
		self.Centre()
		self.Show()

	def InitUI(self):
		self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.NO_BORDER | wx.TB_FLAT)
		self.setHostButton = wx.Button(self.toolbar, label="Host Address")
		self.toolbar.AddControl(self.setHostButton, "Set Host Address")
		self.setHostButton.Bind(wx.EVT_BUTTON, self.setHost)
		self.models = []
		self.modelList= wx.Choice(self.toolbar, choices=self.models)
		self.modelList.Bind(wx.EVT_CHOICE, self.onSelectModel)
		self.toolbar.AddControl(self.modelList, "Model")
		self.refreshModels()
		self.copyButton = wx.Button(self.toolbar, label="Copy")
		self.toolbar.AddControl(self.copyButton, "Copy Message")
		self.copyButton.Bind(wx.EVT_BUTTON, self.OnCopyMessage)
		self.newButton = wx.Button(self.toolbar, label="New Chat")
		self.toolbar.AddControl(self.newButton, "Start a New Chat")
		self.newButton.Bind(wx.EVT_BUTTON, self.OnNewChat)
		self.toolbar.Realize()
		self.SetupAccelerators()
		panel = wx.Panel(self)
		vbox = wx.BoxSizer(wx.VERTICAL)
		self.response = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
		self.prompt = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
		sendButton = wx.Button(panel, label='Send')
		sendButton.Bind(wx.EVT_BUTTON, self.OnSend)
		vbox.Add(self.response, 7, wx.EXPAND | wx.ALL, 5)
		vbox.Add(self.prompt, 2, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
		self.prompt.Bind(wx.EVT_TEXT_ENTER, self.OnSend)
		vbox.Add(sendButton, 1, wx.EXPAND | wx.ALL, 5)
		panel.SetSizer(vbox)
		self.Maximize(True)
		self.modelList.SetFocus()

	def refreshModels(self):
		self.modelList.SetItems([])
		threading.Thread(target=self.getModels).start()

	def getModels(self):
		try: models = self.model.client.list()
		except Exception as e:
			dialog = wx.MessageDialog(self, str(e), "Error", wx.OK | wx.ICON_ERROR)
			dialog.ShowModal()
			dialog.Destroy()
			return
		self.models = [model['name'] for model in models['models']]
		self.modelList.SetItems(self.models)
		self.modelList.SetSelection(0)
		self.onSelectModel()
		self.modelList.SetFocus()

	def setHost(self, event):
		dlg = wx.TextEntryDialog(self, "Enter the host address:", "Host", value=self.model.host)
		if dlg.ShowModal() == wx.ID_OK:
			self.model.setHost(dlg.GetValue())
			self.refreshModels()
		dlg.Destroy()

	def OnNewChat(self, event):
		self.response.SetValue("")

	def OnCopyMessage(self, event):
		message = self.model.messages[-1]['content'].strip()
		if wx.TheClipboard.Open():
			wx.TheClipboard.SetData(wx.TextDataObject(message))
			wx.TheClipboard.Close()

	def onSelectModel(self, event=None):
		self.model.setModel(self.modelList.GetString(self.modelList.GetSelection()))

	def SetupAccelerators(self):
		shortcuts = {
			"model":(wx.ACCEL_CTRL, ord('M'), wx.NewIdRef()),
			"copy":(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('C'), wx.NewIdRef()),
			"newChat":(wx.ACCEL_CTRL, ord('N'), wx.NewIdRef()),
			"prompt":(wx.ACCEL_NORMAL, wx.WXK_ESCAPE, wx.NewIdRef()),
		}
		accelEntries = [v for k,v in shortcuts.items()]
		accelTable = wx.AcceleratorTable(accelEntries)
		self.SetAcceleratorTable(accelTable)
		self.Bind(wx.EVT_MENU, self.FocusOnModelList, id=shortcuts['model'][2])
		self.Bind(wx.EVT_MENU, self.OnCopyMessage, id=shortcuts['copy'][2])
		self.Bind(wx.EVT_MENU, self.OnNewChat, id=shortcuts['newChat'][2])
		self.Bind(wx.EVT_MENU, self.FocusOnPrompt, id=shortcuts['prompt'][2])

	def FocusOnModelList(self, event):
		self.modelList.SetFocus()

	def FocusOnPrompt(self, event):
		self.prompt.SetFocus()

	def OnSend(self, event):
		message = self.prompt.GetValue()
		if message:
			self.response.AppendText("You: " + message + "\n")
			self.prompt.SetValue("")
			threading.Thread(target=self.processMessage, args=(message,)).start()

	def processMessage(self, message):
		self.model.ask(message, self.response)

if __name__ == "__main__":
	app = wx.App(False)
	ChatWindow(None, "VOLlama")
	app.MainLoop()
