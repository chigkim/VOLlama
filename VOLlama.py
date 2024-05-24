version = 30
import wx
import threading
import sounddevice as sd
import soundfile as sf
import os
from Model import Model
from Settings import settings
from CopyDialog import CopyDialog
import codecs
import json
from Speech import Speech
from Update import check_update
from Parameters import ParametersDialog
from RAGParameterDialog import RAGParameterDialog
from APISettingsDialog import APISettingsDialog
from Utils import displayError
from llama_index.core.llms import ChatMessage
from PromptDialog import PromptDialog
def playSD(file):
	p = os.path.join(os.path.dirname(__file__), file)
	data, fs = sf.read(p, dtype='float32')  
	sd.play(data, fs)

def play(file):
	threading.Thread(target=playSD, args=(file,)).start()
	
class ChatWindow(wx.Frame):
	def __init__(self, parent, title):
		super(ChatWindow, self).__init__(parent, title=title, size=(1920,1080))
		self.speech = Speech()
		self.speech.speak("VOLlama is starting...")
		self.InitUI()
		self.Maximize(True)
		self.Centre()
		self.Show()
		self.model = Model()
		self.model.setSystem(settings.system)
		self.historyIndex = len(self.model.messages)
		self.refreshModels()
		self.prompt.SetFocus()
		threading.Thread(target=check_update, args=(version,)).start()

	def InitUI(self):
		#self.CreateStatusBar()
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
		documentMenu = chatMenu.Append(wx.ID_ANY, "Attach a &Document...\tCTRL+D")
		self.Bind(wx.EVT_MENU, self.onUploadDocument, documentMenu)

		self.speakResponse = chatMenu.Append(wx.ID_ANY, "Speak Response with System Voice", kind=wx.ITEM_CHECK)
		self.speakResponse.Check(settings.speakResponse)
		self.Bind(wx.EVT_MENU, self.onToggleSpeakResponse, self.speakResponse)

		self.configSpeech = chatMenu.Append(wx.ID_ANY, "Configure Voice...")
		self.Bind(wx.EVT_MENU, self.speech.present_voice_rate_dialog, self.configSpeech)

		self.modelsMenu = chatMenu.Append(wx.ID_ANY, "&Models\tCTRL+l")
		self.Bind(wx.EVT_MENU, self.FocusOnModelList, self.modelsMenu)

		self.apiSettingsMenu = chatMenu.Append(wx.ID_ANY, "&API Settings...\tCTRL+SHIFT+A")
		self.Bind(wx.EVT_MENU, self.displayAPISettingsDialog, self.apiSettingsMenu)

		exitMenu = chatMenu.Append(wx.ID_EXIT)
		self.Bind(wx.EVT_MENU, self.OnExit, exitMenu)

		advanceMenu= wx.Menu()
		setSystemMenu = advanceMenu.Append(wx.ID_ANY, "System Prompt Manager...\tCTRL+ALT+S")
		self.Bind(wx.EVT_MENU, self.setSystem, setSystemMenu)
		parametersMenu = advanceMenu.Append(wx.ID_ANY, "Generation Parameters...\tCTRL+ALT+P")
		self.Bind(wx.EVT_MENU, self.setParameters, parametersMenu)
		self.copyModelMenu = advanceMenu.Append(wx.ID_ANY, "Copy Model...")
		self.Bind(wx.EVT_MENU, self.OnCopyModel, self.copyModelMenu)
		self.deleteModelMenu = advanceMenu.Append(wx.ID_ANY, "Delete Model")
		self.Bind(wx.EVT_MENU, self.OnDeleteModel, self.deleteModelMenu)
		self.copyModelMenu.Enable(settings.llm_name == "Ollama")
		self.deleteModelMenu.Enable(settings.llm_name == "Ollama")
		hostMenu = advanceMenu.Append(wx.ID_ANY, "Set Host...")
		self.Bind(wx.EVT_MENU, self.setHost, hostMenu)
		#logMenu = advanceMenu.Append(wx.ID_ANY, "Log\tCTRL+ALT+L")
		#self.Bind(wx.EVT_MENU, self.log, logMenu)

		ragMenu= wx.Menu()
		indexUrlMenu = ragMenu.Append(wx.ID_ANY, "Index &URL...\tCTRL+U")
		self.Bind(wx.EVT_MENU, self.onIndexURL, indexUrlMenu)
		indexFileMenu = ragMenu.Append(wx.ID_ANY, "Index &File...\tCTRL+F")
		self.Bind(wx.EVT_MENU, self.onIndexFile, indexFileMenu)
		indexFolderMenu = ragMenu.Append(wx.ID_ANY, "Index Directory...\tCTRL+D")
		self.Bind(wx.EVT_MENU, self.onIndexFolder, indexFolderMenu)
		loadIndexMenu = ragMenu.Append(wx.ID_ANY, "Load Index...")
		self.Bind(wx.EVT_MENU, self.loadIndex, loadIndexMenu)
		saveIndexMenu = ragMenu.Append(wx.ID_ANY, "Save Index...")
		self.Bind(wx.EVT_MENU, self.saveIndex, saveIndexMenu)
		ragSettingsMenu = ragMenu.Append(wx.ID_ANY, "Settings...")
		self.Bind(wx.EVT_MENU, self.onShowRagSettings, ragSettingsMenu  )
		
		menuBar = wx.MenuBar()
		menuBar.Append(chatMenu,"&Chat")
		menuBar.Append(advanceMenu,"&Advance")
		menuBar.Append(ragMenu,"&Rag")
		self.SetMenuBar(menuBar)
		
		self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.NO_BORDER | wx.TB_FLAT)
		self.modelList= wx.Choice(self.toolbar, choices=[])
		self.modelList.Bind(wx.EVT_CHOICE, self.onSelectModel)
		self.toolbar.AddControl(self.modelList, "Model")

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

		pnl = wx.Panel(panel)
		self.status = wx.StaticText(pnl, label="READY!")
		self.sendButton = wx.Button(pnl, label='Send')
		self.sendButton.Bind(wx.EVT_BUTTON, self.OnSend)

		hbox = wx.BoxSizer(wx.HORIZONTAL)
		hbox.Add(self.status, 10, wx.ALL|wx.EXPAND, 5)
		hbox.Add(self.sendButton, 1, wx.ALL, 5)
		pnl.SetSizer(hbox)

		vbox = wx.BoxSizer(wx.VERTICAL)
		vbox.Add(self.response, 6, wx.EXPAND | wx.ALL, 5)
		vbox.Add(self.prompt, 3, wx.EXPAND |wx.ALL, 5)
		vbox.Add(pnl, 1, wx.EXPAND |wx.ALL, 5)
		panel.SetSizer(vbox)

	def setStatus(self, text):
			#self.SetStatusText(text)
			self.status.SetLabel(text)

	def clearLast(self, event):
		if len(self.model.messages)==0 | (len(self.model.messages)==1 and self.model.messages[0].role == 'system'):
			self.prompt.SetValue("")
			return
		delete=-1 if self.model.messages[-1].role == 'user' else -2
		self.prompt.SetValue(self.model.messages[delete].content)
		self.model.messages = self.model.messages[:delete]
		self.historyIndex = len(self.model.messages)
		self.refreshChat()

	def refreshChat(self):
		self.response.Clear()
		start = 1 if self.model.messages[0].role == 'system' else 0
		name = settings.model_name.capitalize()
		if ":" in name:
			name = name[:name.index(':')]
		for message in self.model.messages[start:]:
			role = name if message.role == 'assistant' else "You"
			text = f"{role}: {message.content}"
			self.response.AppendText(text)
			self.response.AppendText(os.linesep)

	def refreshModels(self):
		self.modelList.SetItems([])
		threading.Thread(target=self.getModels).start()

	def getModels(self):
		try:
			models = self.model.get_models()
		except Exception as e:
			displayError(e)
			return
		self.modelList.SetItems(models)
		if settings.model_name in models:
			self.modelList.SetSelection(models.index(settings.model_name))
		else:
			self.modelList.SetSelection(0)
		self.onSelectModel()
		self.modelList.SetFocus()


	def setHost(self, event):
		dlg = wx.TextEntryDialog(self, "Enter the host address:", "Host", value=settings.host)
		if dlg.ShowModal() == wx.ID_OK:
			host = dlg.GetValue()
			self.model.setHost(host)
			settings.host = host
			self.refreshModels()
		dlg.Destroy()

	def onToggleSpeakResponse(self, e):
		settings.speakResponse = self.speakResponse.IsChecked()

	def setSystem(self, event):
		dlg = PromptDialog(self, prompt=settings.system)
		if dlg.ShowModal() == wx.ID_OK:
			system = dlg.prompt_text.GetValue()
			self.model.setSystem(system)
			if len(self.model.messages) == 1:
				self.historyIndex = 1
			settings.system = system
		dlg.Destroy()

	def setParameters(self, e):
		with ParametersDialog(self, 'Generation Parameters') as dialog:
			if dialog.ShowModal() == wx.ID_OK:
				dialog.save()

	def OnCopyModel(self, event):
		with CopyDialog(self, title="Copy Model") as dlg:
			dlg.name.SetValue("copy-"+settings.model_name)
			dlg.modelfile.SetValue(self.model.modelfile())
			if dlg.ShowModal() == wx.ID_OK:
				name = dlg.name.GetValue()
				modelfile = dlg.modelfile.GetValue()
				self.model.create(name, modelfile)
				self.refreshModels()

	def OnDeleteModel(self, event):
		with wx.MessageDialog(self, f"Are you sure you want to delete {settings.model_name}?", 'Delete', wx.YES_NO|wx.ICON_QUESTION) as dlg:
			dlg.SetYesNoLabels("Yes", "No")
			if dlg.ShowModal() == wx.ID_YES:
				self.model.delete()
				self.refreshModels()

	def OnNewChat(self, event):
		self.FocusOnPrompt()
		self.model.messages = []
		self.model.setSystem(settings.system)
		self.response.Clear()

	def OnCopyMessage(self, event):
		message = self.model.messages[-1].content.strip()
		if wx.TheClipboard.Open():
			wx.TheClipboard.SetData(wx.TextDataObject(message))
			wx.TheClipboard.Close()

	def onSelectModel(self, event=None):
		self.model.setModel(self.modelList.GetString(self.modelList.GetSelection()))

	def SetupAccelerators(self):
		shortcuts = {
			"prompt":(wx.ACCEL_NORMAL, wx.WXK_ESCAPE, wx.NewIdRef()),
			"history_up": (wx.ACCEL_ALT, wx.WXK_UP, wx.NewIdRef()),
			"history_down": (wx.ACCEL_ALT, wx.WXK_DOWN, wx.NewIdRef()),
		}
		accelEntries = [v for k,v in shortcuts.items()]
		accelTable = wx.AcceleratorTable(accelEntries)
		self.SetAcceleratorTable(accelTable)
		self.Bind(wx.EVT_MENU, self.FocusOnPrompt, id=shortcuts['prompt'][2])
		self.Bind(wx.EVT_MENU, self.OnHistoryUp, id=shortcuts['history_up'][2])
		self.Bind(wx.EVT_MENU, self.OnHistoryDown, id=shortcuts['history_down'][2])

	def OnHistoryUp(self, event):
		self.historyIndex -= 1
		if self.historyIndex<0:
			self.historyIndex = 0
		if self.model.messages[self.historyIndex].role == "system":
			self.historyIndex = 1
			return
		self.prompt.SetValue(self.model.messages[self.historyIndex].content)
		self.prompt.SetInsertionPointEnd()
		self.sendButton.SetLabel("Edit")

	def OnHistoryDown(self, event):
		self.historyIndex += 1
		length = len(self.model.messages)
		if self.historyIndex>length:
			self.historyIndex = length
		if self.historyIndex < length:
			self.prompt.SetValue(self.model.messages[self.historyIndex].content)
			self.prompt.SetInsertionPointEnd()
			self.sendButton.SetLabel("Edit")
		else:
			self.prompt.SetValue("")
			self.sendButton.SetLabel("Send")

	def FocusOnModelList(self, event):
		self.modelList.SetFocus()

	def FocusOnPrompt(self, event=None):
		self.model.generate = False
		self.speech.stop()
		self.prompt.SetFocus()
		self.historyIndex = len(self.model.messages)
		self.prompt.SetValue("")
		self.sendButton.SetLabel("Send")


	def onStopGeneration(self):
		play("receive.wav")
		self.sendButton.SetLabel("Send")
		self.historyIndex = len(self.model.messages)

	def OnSend(self, event):

		def processMessage(message):
			play("send.wav")
			self.model.ask(message, self)

		if not self.model.generate:
			message = self.prompt.GetValue()
			if message:
				self.prompt.SetValue("")
				if self.historyIndex<len(self.model.messages):
					self.model.messages[self.historyIndex].content = message
					self.refreshChat()
					return
				self.response.AppendText("You: " + message + "\n")
				self.sendButton.SetLabel("Stop")
				threading.Thread(target=processMessage, args=(message,)).start()
		else:
			self.FocusOnPrompt()

	def onOpen(self,e):
		with wx.FileDialog(self, "Open", "", "", "*.json", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
			if dlg.ShowModal() == wx.ID_CANCEL: return
			filename = dlg.GetFilename()
			dirname = dlg.GetDirectory()
			with codecs.open(os.path.join(dirname, filename), 'r', 'utf-8') as f:
				messages = json.load(f)
				messages = [ChatMessage(role=m['role'], content=m['content']) for m in messages]
				self.model.messages = messages
				self.refreshChat()

	def onUploadImage(self,e):
		with wx.FileDialog(self, "Choose an image", wildcard="Image files (*.jpg;*.jpeg;*.png)|*.jpg;*.jpeg;*.png", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
			if dlg.ShowModal() == wx.ID_CANCEL: return
			filename = dlg.GetFilename()
			dirname = dlg.GetDirectory()
			file = os.path.join(dirname, filename)
			self.model.image = file
			self.prompt.SetFocus()

	def onUploadDocument(self, event):
		wildcard = "Supported Files (*.txt;*.pdf;*.docx;*.pptx;*.ppt;*.pptm;*.hwp;*.csv;*.epub;*.md;*.mbox)|*.txt;*.pdf;*.docx;*.pptx;*.ppt;*.pptm;*.hwp;*.csv;*.epub;*.md"
		with wx.FileDialog(self, "Choose a file", wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST|wx.FD_MULTIPLE) as fileDialog:
			if fileDialog.ShowModal() == wx.ID_CANCEL: return
			paths = fileDialog.GetPaths()
			self.model.loadDocument(paths)
		self.prompt.SetFocus()

	def onIndexFile(self, event):
		wildcard = "Supported Files (*.txt;*.pdf;*.docx;*.pptx;*.ppt;*.pptm;*.hwp;*.csv;*.epub;*.md;*.mbox)|*.txt;*.pdf;*.docx;*.pptx;*.ppt;*.pptm;*.hwp;*.csv;*.epub;*.md"
		with wx.FileDialog(self, "Choose a file", wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST|wx.FD_MULTIPLE) as fileDialog:
			if fileDialog.ShowModal() == wx.ID_CANCEL: return
			paths = fileDialog.GetPaths()
			self.setStatus(f"Indexing {paths}")
			threading.Thread(target=self.model.startRag, args=(paths, self.setStatus)).start()
		
	def onIndexFolder(self,e):
		with wx.DirDialog(None, "Choose a folder with documents:", style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dlg:
			if dlg.ShowModal() == wx.ID_CANCEL: return
			folder = dlg.GetPath()
			self.setStatus(f"Indexing {folder}")
			threading.Thread(target=self.model.startRag, args=(folder, self.setStatus)).start()

	def onIndexURL(self, e):
		with wx.TextEntryDialog(self, "Enter an url to index::", "URL", value="https://") as dlg:
			if dlg.ShowModal() == wx.ID_CANCEL: return
			url = dlg.GetValue()
			self.setStatus(f"Indexing {url}")
			threading.Thread(target=self.model.startRag, args=(url, self.setStatus)).start()

	def onSave(self, e):
		name = settings.model_name.capitalize()
		if ":" in name:
			name = name[:name.index(":")]
		with wx.FileDialog(self, "Save", "", name+".json", "*.json", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
			if dlg.ShowModal() == wx.ID_CANCEL: return wx.ID_CANCEL
			filename = dlg.GetFilename()
			dirname = dlg.GetDirectory()
			messages = [{"role":m.role, "content":m.content} for m in self.model.messages]
			with codecs.open(os.path.join(dirname, filename), 'w', 'utf-8') as f:
				json.dump(messages, f, indent="\t")

	def loadIndex(self,e):
		with wx.DirDialog(None, "Choose a folder with Index:", style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dlg:
			if dlg.ShowModal() == wx.ID_CANCEL: return
			folder = dlg.GetPath()
			self.model.load_index(folder)
			
	def saveIndex(self,e):
		with wx.DirDialog(None, "Choose a folder to Save Index:", style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dlg:
			if dlg.ShowModal() == wx.ID_CANCEL: return
			folder = dlg.GetPath()
			self.model.rag.save_index(folder)

	def displayAPISettingsDialog(self, event):
		with APISettingsDialog(self, "API Settings") as dlg:
			dlg.ShowModal()
			self.copyModelMenu.Enable(settings.llm_name == "Ollama")
			self.deleteModelMenu.Enable(settings.llm_name == "Ollama")
			self.model.models = []
			self.refreshModels()

	def onShowRagSettings(self, event):
		with RAGParameterDialog(self, "RAG Settings") as dlg:
			    dlg.ShowModal()

	def OnExit(self, event):
		self.Destroy()

	def log(self,e):
		print(settings.to_dict())

if __name__ == "__main__":
	app = wx.App(False)
	ChatWindow(None, "VOLlama")
	app.MainLoop()
