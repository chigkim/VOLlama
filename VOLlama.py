version = 45
import wx
import threading
import sounddevice as sd
import soundfile as sf
import os
from Model import Model
from Settings import settings, config_dir
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
import functools


def playSD(file):
    p = os.path.join(os.path.dirname(__file__), file)
    data, fs = sf.read(p, dtype="float32")
    sd.play(data, fs)


def play(file):
    threading.Thread(target=playSD, args=(file,)).start()


class ShiftEnterTextCtrl(wx.TextCtrl):
    def __init__(
        self,
        parent,
        id=wx.ID_ANY,
        value="",
        pos=wx.DefaultPosition,
        size=wx.DefaultSize,
        **kwargs,
    ):
        # Make sure the control is multiline and passes Enter events up
        style = kwargs.pop("style", 0) | wx.TE_MULTILINE | wx.TE_PROCESS_ENTER
        super().__init__(parent, id, value, pos, size, style, **kwargs)

        # Low-level key handler
        self.Bind(wx.EVT_KEY_DOWN, self._on_key_down)

    def _on_key_down(self, event: wx.KeyEvent):
        if event.GetKeyCode() == wx.WXK_RETURN and event.ShiftDown():
            # Insert a newline at the caret without triggering EVT_TEXT_ENTER
            self.WriteText("\n")
            # Do NOT call event.Skip(); we have fully handled the key
        else:
            event.Skip()  # Let wx handle everything else


class ChatWindow(wx.Frame):
    def __init__(self, parent, title):
        super(ChatWindow, self).__init__(parent, title=title, size=(1920, 1080))
        self.speech = Speech()
        self.speech.speak("VOLlama is starting...")
        self.InitUI()
        self.Maximize(True)
        self.Centre()
        self.Show()
        self.PRESETS_PATH = config_dir() / "presets.json"
        self.model = Model()
        self.model.setSystem(settings.system)
        self.historyIndex = len(self.model.messages)
        self.refreshModels()
        self.prompt.SetFocus()
        self.image = None
        self.document = None
        self.documentURL = None
        threading.Thread(target=check_update, args=(version,)).start()

    def InitUI(self):
        # self.CreateStatusBar()
        chatMenu = wx.Menu()
        newMenu = chatMenu.Append(wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.OnNewChat, newMenu)
        openMenu = chatMenu.Append(wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self.onOpen, openMenu)
        saveMenu = chatMenu.Append(wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self.onSave, saveMenu)
        imageMenu = chatMenu.Append(wx.ID_ANY, "Attach an &Image...\tCTRL+I")
        self.Bind(wx.EVT_MENU, self.onUploadImage, imageMenu)
        documentMenu = chatMenu.Append(wx.ID_ANY, "Attach a &Document...\tCTRL+D")
        self.Bind(wx.EVT_MENU, self.onUploadDocument, documentMenu)
        urlMenu = chatMenu.Append(wx.ID_ANY, "Attach a &URL...\tCTRL+U")
        self.Bind(wx.EVT_MENU, self.onUploadURL, urlMenu)
        self.speakResponse = chatMenu.Append(
            wx.ID_ANY, "Read Response with System Voice", kind=wx.ITEM_CHECK
        )
        self.speakResponse.Check(settings.speakResponse)
        self.Bind(wx.EVT_MENU, self.onToggleSpeakResponse, self.speakResponse)
        self.configSpeech = chatMenu.Append(wx.ID_ANY, "Configure Voice...")
        self.Bind(wx.EVT_MENU, self.speech.present_voice_rate_dialog, self.configSpeech)
        self.modelsMenu = chatMenu.Append(wx.ID_ANY, "&Models\tCTRL+l")
        self.Bind(wx.EVT_MENU, self.FocusOnModelList, self.modelsMenu)
        self.presetMenu = chatMenu.Append(wx.ID_ANY, "&Presets\tCTRL+p")
        self.Bind(wx.EVT_MENU, self.onPresetPopup, self.presetMenu)
        self.apiSettingsMenu = chatMenu.Append(
            wx.ID_ANY, "&API Settings...\tCTRL+SHIFT+A"
        )
        self.Bind(wx.EVT_MENU, self.displayAPISettingsDialog, self.apiSettingsMenu)
        exitMenu = chatMenu.Append(wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self.OnExit, exitMenu)

        editMenu = wx.Menu()
        copyMenu = editMenu.Append(wx.ID_ANY, "&Copy Last Message\tCTRL+SHIFT+C")
        self.Bind(wx.EVT_MENU, self.OnCopyMessage, copyMenu)
        clearMenu = editMenu.Append(wx.ID_ANY, "Clear Last Message\tCTRL+K")
        self.Bind(wx.EVT_MENU, self.clearLast, clearMenu)
        editPreviousMenu = editMenu.Append(wx.ID_ANY, "Edit Previous Message\tAlt+Up")
        self.Bind(wx.EVT_MENU, self.OnHistoryUp, editPreviousMenu)
        editNextMenu = editMenu.Append(wx.ID_ANY, "Edit Next Message\tALT+Down")
        self.Bind(wx.EVT_MENU, self.OnHistoryDown, editNextMenu)

        advanceMenu = wx.Menu()
        setSystemMenu = advanceMenu.Append(
            wx.ID_ANY, "System Prompt Manager...\tCTRL+ALT+S"
        )
        self.Bind(wx.EVT_MENU, self.setSystem, setSystemMenu)
        parametersMenu = advanceMenu.Append(
            wx.ID_ANY, "Generation Parameters...\tCTRL+ALT+P"
        )
        self.Bind(wx.EVT_MENU, self.setParameters, parametersMenu)
        self.copyModelMenu = advanceMenu.Append(wx.ID_ANY, "Copy Model...")
        self.Bind(wx.EVT_MENU, self.OnCopyModel, self.copyModelMenu)
        self.deleteModelMenu = advanceMenu.Append(wx.ID_ANY, "Delete Model")
        self.Bind(wx.EVT_MENU, self.OnDeleteModel, self.deleteModelMenu)
        self.copyModelMenu.Enable(settings.llm_name == "Ollama")
        self.deleteModelMenu.Enable(settings.llm_name == "Ollama")
        # logMenu = advanceMenu.Append(wx.ID_ANY, "Log\tCTRL+ALT+L")
        # self.Bind(wx.EVT_MENU, self.log, logMenu)

        ragMenu = wx.Menu()
        indexUrlMenu = ragMenu.Append(wx.ID_ANY, "Index &URL...")
        self.Bind(wx.EVT_MENU, self.onIndexURL, indexUrlMenu)
        indexFileMenu = ragMenu.Append(wx.ID_ANY, "Index &File...\tCTRL+F")
        self.Bind(wx.EVT_MENU, self.onIndexFile, indexFileMenu)
        indexFolderMenu = ragMenu.Append(wx.ID_ANY, "Index Directory...")
        self.Bind(wx.EVT_MENU, self.onIndexFolder, indexFolderMenu)
        loadIndexMenu = ragMenu.Append(wx.ID_ANY, "Load Index...")
        self.Bind(wx.EVT_MENU, self.loadIndex, loadIndexMenu)
        saveIndexMenu = ragMenu.Append(wx.ID_ANY, "Save Index...")
        self.Bind(wx.EVT_MENU, self.saveIndex, saveIndexMenu)
        ragSettingsMenu = ragMenu.Append(wx.ID_ANY, "Settings...")
        self.Bind(wx.EVT_MENU, self.onShowRagSettings, ragSettingsMenu)

        menuBar = wx.MenuBar()
        menuBar.Append(chatMenu, "&Chat")
        menuBar.Append(editMenu, "&Edit")
        menuBar.Append(advanceMenu, "&Advance")
        menuBar.Append(ragMenu, "&Rag")
        self.SetMenuBar(menuBar)

        self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.NO_BORDER | wx.TB_FLAT)
        self.modelList = wx.Choice(self.toolbar, choices=[])
        self.modelList.Bind(wx.EVT_CHOICE, self.onSelectModel)
        self.toolbar.AddControl(self.modelList, "Model")

        self.presetBtn = wx.Button(self.toolbar, label="Preset: <none>")
        self.toolbar.AddControl(self.presetBtn, "Preset")
        self.presetBtn.Bind(wx.EVT_BUTTON, self.onPresetPopup)

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
        self.prompt = ShiftEnterTextCtrl(
            panel, style=wx.TE_PROCESS_ENTER | wx.TE_MULTILINE
        )
        self.prompt.Bind(wx.EVT_TEXT_ENTER, self.OnSend)

        pnl = wx.Panel(panel)
        self.status = wx.StaticText(pnl, label="READY!")
        self.sendButton = wx.Button(pnl, label="Send")
        self.sendButton.Bind(wx.EVT_BUTTON, self.OnSend)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(self.status, 10, wx.ALL | wx.EXPAND, 5)
        hbox.Add(self.sendButton, 1, wx.ALL, 5)
        pnl.SetSizer(hbox)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self.response, 6, wx.EXPAND | wx.ALL, 5)
        vbox.Add(self.prompt, 3, wx.EXPAND | wx.ALL, 5)
        vbox.Add(pnl, 1, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(vbox)

    def setStatus(self, text):
        # self.SetStatusText(text)
        self.status.SetLabel(text)

    def clearLast(self, event):
        if len(self.model.messages) == 0 | (
            len(self.model.messages) == 1 and self.model.messages[0].role == "system"
        ):
            self.prompt.SetValue("")
            return
        delete = -1 if self.model.messages[-1].role == "user" else -2
        self.prompt.SetValue(self.model.messages[delete].content)
        self.model.messages = self.model.messages[:delete]
        self.historyIndex = len(self.model.messages)
        self.refreshChat()

    def refreshChat(self):
        self.response.Clear()
        start = 1 if self.model.messages[0].role == "system" else 0
        name = settings.model_name.capitalize()
        if ":" in name:
            name = name[: name.index(":")]
        for message in self.model.messages[start:]:
            role = name if message.role == "assistant" else "You"
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
        with ParametersDialog(self, "Generation Parameters") as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                dialog.save()

    def OnCopyModel(self, event):
        with CopyDialog(self, title="Copy Model") as dlg:
            dlg.name.SetValue("copy-" + settings.model_name)
            dlg.modelfile.SetValue(self.model.modelfile())
            if dlg.ShowModal() == wx.ID_OK:
                name = dlg.name.GetValue()
                modelfile = dlg.modelfile.GetValue()
                self.model.create(name, modelfile)
                self.refreshModels()

    def OnDeleteModel(self, event):
        with wx.MessageDialog(
            self,
            f"Are you sure you want to delete {settings.model_name}?",
            "Delete",
            wx.YES_NO | wx.ICON_QUESTION,
        ) as dlg:
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
            "prompt": (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, wx.NewIdRef()),
        }
        accelEntries = [v for k, v in shortcuts.items()]
        accelTable = wx.AcceleratorTable(accelEntries)
        self.SetAcceleratorTable(accelTable)
        self.Bind(wx.EVT_MENU, self.FocusOnPrompt, id=shortcuts["prompt"][2])

    def OnHistoryUp(self, event):
        self.historyIndex -= 1
        if self.historyIndex < 0:
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
        if self.historyIndex > length:
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
        if self.historyIndex < len(self.model.messages):
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
            if self.image:
                self.model.image = self.image
                self.image = None
            if self.document:
                self.model.loadDocument(self.document)
                self.document = None
            if self.documentURL:
                self.model.documentURL = self.documentURL
                self.documentURL = None
            self.model.ask(message, self)

        if not self.model.generate:
            message = self.prompt.GetValue()
            if message:
                self.prompt.SetValue("")
                if self.historyIndex < len(self.model.messages):
                    self.model.messages[self.historyIndex].content = message
                    self.refreshChat()
                    return
                self.response.AppendText("You: " + message + "\n")
                self.sendButton.SetLabel("Stop")
                threading.Thread(target=processMessage, args=(message,)).start()
        else:
            self.FocusOnPrompt()

    def onOpen(self, e):
        with wx.FileDialog(
            self, "Open", "", "", "*.json", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        ) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            filename = dlg.GetFilename()
            dirname = dlg.GetDirectory()
            with codecs.open(os.path.join(dirname, filename), "r", "utf-8") as f:
                messages = json.load(f)
                messages = [
                    ChatMessage(role=m["role"], content=m["content"]) for m in messages
                ]
                self.model.messages = messages
                self.refreshChat()

    def onUploadImage(self, e):
        with wx.FileDialog(
            self,
            "Choose an image",
            wildcard="Image files (*.jpg;*.jpeg;*.png)|*.jpg;*.jpeg;*.png",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            paths = dlg.GetPaths()
            dirname = dlg.GetDirectory()
            # file = os.path.join(dirname, filename)
            self.image = paths
            self.prompt.SetFocus()

    def onUploadDocument(self, event):
        wildcard = "Supported Files (*.txt;*.pdf;*.docx;*.pptx;*.ppt;*.pptm;*.hwp;*.csv;*.epub;*.md;*.mbox)|*.txt;*.pdf;*.docx;*.pptx;*.ppt;*.pptm;*.hwp;*.csv;*.epub;*.md"
        with wx.FileDialog(
            self,
            "Choose a file",
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            paths = fileDialog.GetPaths()
            self.document = paths
        self.prompt.SetFocus()

    def onUploadURL(self, e):
        with wx.TextEntryDialog(
            self, "Enter an url to retrieve:", "URL", value="https://"
        ) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            url = dlg.GetValue()
            self.documentURL = url

    def onIndexFile(self, event):
        wildcard = "Supported Files (*.txt;*.pdf;*.docx;*.pptx;*.ppt;*.pptm;*.hwp;*.csv;*.epub;*.md;*.mbox)|*.txt;*.pdf;*.docx;*.pptx;*.ppt;*.pptm;*.hwp;*.csv;*.epub;*.md"
        with wx.FileDialog(
            self,
            "Choose a file",
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            paths = fileDialog.GetPaths()
            self.setStatus(f"Indexing {paths}")
            threading.Thread(
                target=self.model.startRag, args=(paths, self.setStatus)
            ).start()

    def onIndexFolder(self, e):
        with wx.DirDialog(
            None,
            "Choose a folder with documents:",
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            folder = dlg.GetPath()
            self.setStatus(f"Indexing {folder}")
            threading.Thread(
                target=self.model.startRag, args=(folder, self.setStatus)
            ).start()

    def onIndexURL(self, e):
        with wx.TextEntryDialog(
            self, "Enter an url to index::", "URL", value="https://"
        ) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            url = dlg.GetValue()
            self.setStatus(f"Indexing {url}")
            threading.Thread(
                target=self.model.startRag, args=(url, self.setStatus)
            ).start()

    def onSave(self, e):
        name = settings.model_name.capitalize()
        if ":" in name:
            name = name[: name.index(":")]
        with wx.FileDialog(
            self,
            "Save",
            "",
            name + ".json",
            "*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return wx.ID_CANCEL
            filename = dlg.GetFilename()
            dirname = dlg.GetDirectory()
            messages = [
                {"role": m.role, "content": m.content} for m in self.model.messages
            ]
            with codecs.open(os.path.join(dirname, filename), "w", "utf-8") as f:
                json.dump(messages, f, indent="\t")

    def loadIndex(self, e):
        with wx.DirDialog(
            None,
            "Choose a folder with Index:",
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            folder = dlg.GetPath()
            self.model.load_index(folder)

    def saveIndex(self, e):
        with wx.DirDialog(
            None,
            "Choose a folder to Save Index:",
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
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

    def load_presets(self):
        try:
            with self.PRESETS_PATH.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            return {}

    def save_presets(self, presets):
        with self.PRESETS_PATH.open("w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2)

    def onPresetPopup(self, event):
        presets = self.load_presets()
        active = self.presetBtn.GetLabel().replace("Preset: ", "").strip()
        menu = wx.Menu()

        for name in sorted(presets):
            pid = wx.NewIdRef()
            item = menu.Append(pid, name, kind=wx.ITEM_CHECK)
            if name == active:
                item.Check(True)
            self.Bind(
                wx.EVT_MENU, functools.partial(self.apply_preset, name=name), id=pid
            )
        menu.AppendSeparator()
        # New / Save / Delete entries
        new_id = wx.NewIdRef()
        menu.Append(new_id, "New…")
        self.Bind(wx.EVT_MENU, self.new_preset, id=new_id)

        save_id = wx.NewIdRef()
        menu.Append(save_id, "Save…")
        self.Bind(wx.EVT_MENU, self.save_preset, id=save_id)

        del_id = wx.NewIdRef()
        menu.Append(del_id, "Delete…")
        self.Bind(wx.EVT_MENU, self.delete_preset, id=del_id)

        # Show the menu under the button
        self.toolbar.PopupMenu(menu, self.presetBtn.Position)
        menu.Destroy()
        self.FocusOnPrompt()

    def gather_current_settings(self):
        return {
            "llm_name": settings.llm_name,
            "model_name": settings.model_name,
            "system": settings.system,
            "parameters": settings.parameters,
        }

    def apply_preset(self, event, name):
        presets = self.load_presets()
        p = presets.get(name)
        if not p:
            return
        settings.llm_name = p["llm_name"]
        settings.model_name = p["model_name"]
        settings.system = p["system"]
        settings.parameters = p["parameters"]
        # refresh UI
        self.presetBtn.SetLabel(f"Preset: {name}")
        self.refreshModels()
        self.OnNewChat(None)

    def new_preset(self, event):
        dlg = wx.TextEntryDialog(self, "Enter new preset name:", "New Preset")
        if dlg.ShowModal() != wx.ID_OK:
            return
        name = dlg.GetValue().strip()
        dlg.Destroy()
        presets = self.load_presets()
        if name in presets:
            wx.MessageBox(f"«{name}» already exists.", "Error", wx.ICON_ERROR)
            return
        presets[name] = self.gather_current_settings()
        self.save_presets(presets)
        self.presetBtn.SetLabel(f"Preset: {name}")

    def save_preset(self, event):
        """Overwrite the currently selected preset after confirmation."""
        label = self.presetBtn.GetLabel()  # e.g. "Preset: MyPreset"
        name = label.replace("Preset: ", "").strip()
        if name in ("<none>", ""):
            wx.MessageBox("No preset selected to save.", "Info", wx.ICON_INFORMATION)
            return
        presets = self.load_presets()
        presets[name] = self.gather_current_settings()
        self.save_presets(presets)

    def delete_preset(self, event):
        """Delete the currently selected preset after confirmation."""
        label = self.presetBtn.GetLabel()
        name = label.replace("Preset: ", "").strip()
        if name in ("<none>", ""):
            wx.MessageBox("No preset selected to delete.", "Info", wx.ICON_INFORMATION)
            return
        if (
            wx.MessageBox(
                f"Delete “{name}” forever?", "Confirm", wx.YES_NO | wx.ICON_WARNING
            )
            != wx.YES
        ):
            return
        presets = self.load_presets()
        presets.pop(name, None)
        self.save_presets(presets)
        self.presetBtn.SetLabel("Preset: <none>")

    def log(self, e):
        print(settings.to_dict())


if __name__ == "__main__":
    app = wx.App(False)
    ChatWindow(None, "VOLlama")
    app.MainLoop()
