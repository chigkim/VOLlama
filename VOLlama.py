import wx
import threading
import sounddevice as sd
import soundfile as sf
import os
from Model import Model
from Settings import load_settings, save_settings

def playSD(file):
	p = os.path.join(os.path.dirname(__file__), file)
	data, fs = sf.read(p, dtype='float32')  
	sd.play(data, fs)

def play(file):
	threading.Thread(target=playSD, args=(file,)).start()
	
class ChatWindow(wx.Frame):
	def __init__(self, parent, title):
		super(ChatWindow, self).__init__(parent, title=title, size=(1920,1080))
		self.settings = load_settings()
		print(self.settings.to_dict())
		self.model = Model(host=self.settings.host)
		self.InitUI()
		self.Centre()
		self.Show()

	def InitUI(self):
		self.CreateStatusBar()
		chatMenu= wx.Menu()
		newMenu = chatMenu.Append(wx.ID_NEW)
		self.Bind(wx.EVT_MENU, self.OnNewChat, newMenu)
		copyMenu = chatMenu.Append(wx.ID_ANY, "&Copy\tCTRL+SHIFT+C")
		self.Bind(wx.EVT_MENU, self.OnCopyMessage, copyMenu)
		clearMenu = chatMenu.Append(wx.ID_ANY, "Clear\tCTRL+K")
		self.Bind(wx.EVT_MENU, self.clearLast, clearMenu)
		exitMenu = chatMenu.Append(wx.ID_EXIT)
		self.Bind(wx.EVT_MENU, self.OnExit, exitMenu)

		optionMenu= wx.Menu()
		hostMenu = optionMenu.Append(wx.ID_ANY, "Set Host\tCTRL+SHIFT+H")
		self.Bind(wx.EVT_MENU, self.setHost, hostMenu)

		menuBar = wx.MenuBar()
		menuBar.Append(chatMenu,"&Chat")
		menuBar.Append(optionMenu,"&Option")
		self.SetMenuBar(menuBar)

		self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.NO_BORDER | wx.TB_FLAT)
		self.models = []
		self.modelList= wx.Choice(self.toolbar, choices=self.models)
		self.modelList.Bind(wx.EVT_CHOICE, self.onSelectModel)
		self.toolbar.AddControl(self.modelList, "Model")
		self.refreshModels()
		self.copyButton = wx.Button(self.toolbar, label="Copy")
		self.toolbar.AddControl(self.copyButton, "Copy Message")
		self.copyButton.Bind(wx.EVT_BUTTON, self.OnCopyMessage)

		self.clearButton = wx.Button(self.toolbar, label="Clear Last Message")
		self.toolbar.AddControl(self.clearButton, "Clear Last Message")
		self.clearButton.Bind(wx.EVT_BUTTON, self.clearLast)
		self.newButton = wx.Button(self.toolbar, label="New Chat")
		self.toolbar.AddControl(self.newButton, "New Chat")
		self.newButton.Bind(wx.EVT_BUTTON, self.OnNewChat)
		self.toolbar.Realize()
		self.SetupAccelerators()
		panel = wx.Panel(self)
		self.response = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
		self.prompt = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
		self.prompt.Bind(wx.EVT_TEXT_ENTER, self.OnSend)
		self.sendButton = wx.Button(panel, label='Send')
		self.sendButton.Bind(wx.EVT_BUTTON, self.OnSend)
		vbox = wx.BoxSizer(wx.VERTICAL)
		vbox.Add(self.response, 7, wx.EXPAND | wx.ALL, 5)
		vbox.Add(self.prompt, 2, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
		vbox.Add(self.sendButton, 1, wx.EXPAND | wx.ALL, 5)
		panel.SetSizer(vbox)
		self.Maximize(True)
		self.modelList.SetFocus()

	def clearLast(self, event):
		self.model.messages = self.model.messages[:-2]
		text = ""
		for i in range(0,len(self.model.messages),2):
			text += f"You: {self.model.messages[i]['content']}\n"
			text += f"{self.model.name[:self.model.name.index(':')].capitalize()}: {self.model.messages[i+1]['content']}\n"
		self.response.SetValue(text)

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
			host = dlg.GetValue()
			self.model.setHost(host)
			self.settings.host = host
			save_settings()
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
		self.model.name = self.modelList.GetString(self.modelList.GetSelection())

	def SetupAccelerators(self):
		shortcuts = {
			"model":(wx.ACCEL_CTRL, ord('M'), wx.NewIdRef()),
			"prompt":(wx.ACCEL_NORMAL, wx.WXK_ESCAPE, wx.NewIdRef()),
		}
		accelEntries = [v for k,v in shortcuts.items()]
		accelTable = wx.AcceleratorTable(accelEntries)
		self.SetAcceleratorTable(accelTable)
		self.Bind(wx.EVT_MENU, self.FocusOnModelList, id=shortcuts['model'][2])
		self.Bind(wx.EVT_MENU, self.FocusOnPrompt, id=shortcuts['prompt'][2])

	def FocusOnModelList(self, event):
		self.modelList.SetFocus()

	def FocusOnPrompt(self, event):
		self.prompt.SetFocus()
		
	def OnSend(self, event):

		def processMessage(message):
			play("send.wav")
			self.model.ask(message, self.response, onStopGeneration)
	
		def onStopGeneration():
			play("receive.wav")
			self.sendButton.SetLabel("Send")

		if not self.model.generate:
			message = self.prompt.GetValue()
			if message:
				self.response.AppendText("You: " + message + "\n")
				self.prompt.SetValue("")
				self.sendButton.SetLabel("Stop")
				threading.Thread(target=processMessage, args=(message,)).start()
		else:
			self.model.generate = False

	def OnExit(self, event):
		self.Destroy()
		
if __name__ == "__main__":
	app = wx.App(False)
	ChatWindow(None, "VOLlama")
	app.MainLoop()
