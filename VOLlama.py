import wx
import threading
import sounddevice as sd
import soundfile as sf
import os
from Model import Model
from Settings import load_settings, save_settings
from CopyDialog import CopyDialog
import codecs
import json
from Speech import Speech

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
		self.speech = Speech()
		self.model = Model(host=self.settings.host)
		self.model.setSystem(self.settings.system)
		self.InitUI()
		self.Centre()
		self.Show()

	def InitUI(self):
		self.CreateStatusBar()
		chatMenu= wx.Menu()
		newMenu = chatMenu.Append(wx.ID_NEW)
		self.Bind(wx.EVT_MENU, self.OnNewChat, newMenu)
		openMenu = chatMenu.Append(wx.ID_OPEN)
		self.Bind(wx.EVT_MENU, self.onOpen, openMenu)
		saveMenu = chatMenu.Append(wx.ID_SAVE)
		self.Bind(wx.EVT_MENU, self.onSave, saveMenu)
		copyMenu = chatMenu.Append(wx.ID_ANY, "&Copy\tCTRL+SHIFT+C")
		self.Bind(wx.EVT_MENU, self.OnCopyMessage, copyMenu)
		clearMenu = chatMenu.Append(wx.ID_ANY, "Clear\tCTRL+K")
		self.Bind(wx.EVT_MENU, self.clearLast, clearMenu)
		imageMenu = chatMenu.Append(wx.ID_ANY, "Attach an &Image...\tCTRL+I")
		self.Bind(wx.EVT_MENU, self.onUploadImage, imageMenu)
		self.speakResponse = chatMenu.Append(wx.ID_ANY, "Speak Response with System Voice", kind=wx.ITEM_CHECK)
		self.speakResponse.Check(self.settings.speakResponse)
		self.Bind(wx.EVT_MENU, self.onToggleSpeakResponse, self.speakResponse)
		if self.speech.os == 'Windows':
			self.configSpeech = chatMenu.Append(wx.ID_ANY, "Configure Voice")
			self.Bind(wx.EVT_MENU, self.speech.present_voice_rate_dialog, self.configSpeech)
		exitMenu = chatMenu.Append(wx.ID_EXIT)
		self.Bind(wx.EVT_MENU, self.OnExit, exitMenu)
		optionMenu= wx.Menu()
		setSystemMenu = optionMenu.Append(wx.ID_ANY, "Set System Message...\tCTRL+ALT+S")
		self.Bind(wx.EVT_MENU, self.setSystem, setSystemMenu)
		copyModelMenu = optionMenu.Append(wx.ID_ANY, "Copy Model...")
		self.Bind(wx.EVT_MENU, self.OnCopyModel, copyModelMenu)
		deleteModelMenu = optionMenu.Append(wx.ID_ANY, "Delete Model")
		self.Bind(wx.EVT_MENU, self.OnDeleteModel, deleteModelMenu)
		hostMenu = optionMenu.Append(wx.ID_ANY, "Set Host...")
		self.Bind(wx.EVT_MENU, self.setHost, hostMenu)
		menuBar = wx.MenuBar()
		menuBar.Append(chatMenu,"&Chat")
		menuBar.Append(optionMenu,"&Advance")
		self.SetMenuBar(menuBar)

		self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.NO_BORDER | wx.TB_FLAT)
		self.models = []
		self.modelList= wx.Choice(self.toolbar, choices=self.models)
		self.modelList.Bind(wx.EVT_CHOICE, self.onSelectModel)
		self.toolbar.AddControl(self.modelList, "Model")
		self.refreshModels()
		self.copyButton = wx.Button(self.toolbar, label="Copy Last Message")
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
		self.prompt = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER|wx.TE_MULTILINE)
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

	def setStatus(self, text):
			self.SetStatusText(text)

	def clearLast(self, event):
		if len(self.model.messages)<2: return
		self.model.messages = self.model.messages[:-2]
		self.refreshChat(self.model.messages)

	def refreshChat(self, messages):
		text = ""
		if len(self.model.messages)<2:
			self.response.SetValue(text)
			return
		start = 0
		if messages[0]['role'] == 'system':
			start = 1
		for i in range(start,len(messages),2):
			text += f"You: {messages[i]['content']}\n"
			text += f"{self.model.name[:self.model.name.index(':')].capitalize()}: {messages[i+1]['content']}\n"
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

	def onToggleSpeakResponse(self, e):
		self.settings.speakResponse = self.speakResponse.IsChecked()
		save_settings()

	def setSystem(self, event):
		dlg = wx.TextEntryDialog(self, "Enter the system message:", "System", value=self.settings.system)
		if dlg.ShowModal() == wx.ID_OK:
			system = dlg.GetValue()
			self.model.setSystem(system)
			self.settings.system = system
			save_settings()
		dlg.Destroy()

	def OnCopyModel(self, event):
		dialog = CopyDialog(self, title="Copy Model")
		dialog.name.SetValue("copy-"+self.model.name)
		dialog.modelfile.SetValue(self.model.client.show(self.model.name)['modelfile'])
		if dialog.ShowModal() == wx.ID_OK:
			name = dialog.name.GetValue()
			modelfile = dialog.modelfile.GetValue()
			result = self.model.client.create(name, modelfile=modelfile, stream=False)
			print(result)
			self.refreshModels()
		dialog.Destroy()

	def OnDeleteModel(self, event):
		with wx.MessageDialog(self, f"Are you sure you want to delete {self.model.name}?", 'Delete', wx.YES_NO|wx.ICON_QUESTION) as dlg:
			dlg.SetYesNoLabels("Yes", "No")
			if dlg.ShowModal() == wx.ID_YES:
				self.model.client.delete(self.model.name)
				self.refreshModels()

	def OnNewChat(self, event):
		self.response.SetValue("")
		self.model.messages = []
		self.model.setSystem(self.settings.system)

	def OnCopyMessage(self, event):
		message = self.model.messages[-1]['content'].strip()
		if wx.TheClipboard.Open():
			wx.TheClipboard.SetData(wx.TextDataObject(message))
			wx.TheClipboard.Close()

	def onSelectModel(self, event=None):
		self.model.setModel(self.modelList.GetString(self.modelList.GetSelection()))

	def SetupAccelerators(self):
		shortcuts = {
			"model":(wx.ACCEL_CTRL, ord('l'), wx.NewIdRef()),
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
		self.speech.stop()
		self.prompt.SetFocus()

	def onStopGeneration(self):
		if self.speakResponse.IsChecked(): self.speech.speak(self.model.messages[-1]['content'])
		play("receive.wav")
		self.sendButton.SetLabel("Send")

	def OnSend(self, event):

		def processMessage(message):
			play("send.wav")
			self.model.ask(message, self)

		if not self.model.generate:
			message = self.prompt.GetValue()
			if message:
				self.response.AppendText("You: " + message + "\n")
				self.prompt.SetValue("")
				self.sendButton.SetLabel("Stop")
				threading.Thread(target=processMessage, args=(message,)).start()
		else:
			self.model.generate = False

	def onOpen(self,e):
		with wx.FileDialog(self, "Open", "", "", "*.json", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
			if dlg.ShowModal() == wx.ID_CANCEL: return
			filename = dlg.GetFilename()
			dirname = dlg.GetDirectory()
			with codecs.open(os.path.join(dirname, filename), 'r', 'utf-8') as f:
				messages = json.load(f)
				self.model.messages = messages
				self.refreshChat(messages)

	def onUploadImage(self,e):
		with wx.FileDialog(self, "Choose an image", wildcard="Image files (*.jpg;*.jpeg;*.png)|*.jpg;*.jpeg;*.png", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
			if dlg.ShowModal() == wx.ID_CANCEL: return
			filename = dlg.GetFilename()
			dirname = dlg.GetDirectory()
			file = os.path.join(dirname, filename)
			self.model.image = file

	def onSave(self, e):
		name = self.model.name[:self.model.name.index(":")].capitalize()
		with wx.FileDialog(self, "Save", "", name+".json", "*.json", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
			if dlg.ShowModal() == wx.ID_CANCEL: return wx.ID_CANCEL
			filename = dlg.GetFilename()
			dirname = dlg.GetDirectory()
			with codecs.open(os.path.join(dirname, filename), 'w', 'utf-8') as f:
				json.dump(self.model.messages, f, indent="\t")

	def OnExit(self, event):
		self.Destroy()
		
if __name__ == "__main__":
	app = wx.App(False)
	ChatWindow(None, "VOLlama")
	app.MainLoop()
