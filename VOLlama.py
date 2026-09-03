version = 51
import wx
import threading
import sounddevice as sd
import soundfile as sf
import os
from Model import Model, assistant_name
from Settings import settings, config_dir, active_preset
import codecs
import json
import platform
from Update import check_update
from RAGParameterDialog import RAGParameterDialog
from PresetDialog import (
    PresetDialog,
    CONNECTION_PAGE,
)
from Utils import displayError
from llama_index.core.llms import ChatMessage
import functools


def playSD(file):
    if settings.sound:
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
        if settings.version == 0:
            displayError(
                "Your settings are not compatible with this version. Please choose reset settings in the advance menu and restart the app."
            )

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
        self.init_speech()
        if settings.speakResponse:
            self.speech.speak("VOLlama is starting...")
        self.InitUI()
        self.Maximize(True)
        self.Centre()
        self.Show()
        self.model = Model()
        self.model.setSystem(self.systemPrompt())
        self.historyIndex = len(self.model.messages)
        self.prompt.SetFocus()
        self.image = None
        self.document = None
        self.documentURL = None
        threading.Thread(target=check_update, args=(version,)).start()
        self.updatePresetLabel()
        # version 0 means the settings file is incompatible; the user has already
        # been told to reset, so don't pile a preset dialog on top of that.
        if not settings.presets and settings.version != 0:
            self.new_preset(None)

    def init_speech(self):
        if settings.screenreader:
            from Speech_Screen_Reader import Speech
        elif platform.system() == "Darwin":
            from Speech_NSSpeechSynthesizer import Speech  # Speech_AVSpeechSynthesizer
        elif platform.system() == "Windows":
            from Speech_SAPI import Speech
        else:
            from Speech_Silence import Speech

        self.speech = Speech()

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
        self.showReasoning = chatMenu.Append(
            wx.ID_ANY, "Show Reasoning", kind=wx.ITEM_CHECK
        )
        self.showReasoning.Check(settings.show_reasoning)
        self.Bind(wx.EVT_MENU, self.onToggleShowReasoning, self.showReasoning)
        self.speakResponse = chatMenu.Append(
            wx.ID_ANY, "Read Response", kind=wx.ITEM_CHECK
        )
        self.speakResponse.Check(settings.speakResponse)
        self.Bind(wx.EVT_MENU, self.onToggleSpeakResponse, self.speakResponse)
        self.playSound = chatMenu.Append(wx.ID_ANY, "Play Sound", kind=wx.ITEM_CHECK)
        self.playSound.Check(settings.sound)
        self.Bind(wx.EVT_MENU, self.onTogglePlaySound, self.playSound)

        if platform.system() == "Windows":
            self.useScreenReader = chatMenu.Append(
                wx.ID_ANY, "Use Screen Reader", kind=wx.ITEM_CHECK
            )
            self.useScreenReader.Check(settings.screenreader)
            self.Bind(wx.EVT_MENU, self.onToggleUseScreenReader, self.useScreenReader)
        self.configSpeech = chatMenu.Append(
            wx.ID_ANY, "Configure System Voice...\tCTRL+SHIFT+V"
        )
        self.Bind(wx.EVT_MENU, self.speech.present_voice_rate_dialog, self.configSpeech)
        self.presetMenu = chatMenu.Append(wx.ID_ANY, "&Presets\tCTRL+p")
        self.Bind(wx.EVT_MENU, self.onPresetPopup, self.presetMenu)
        chatMenu.AppendSeparator()
        resetMenu = chatMenu.Append(wx.ID_ANY, "&Reset Settings...")
        self.Bind(wx.EVT_MENU, self.OnResetSettings, resetMenu)
        exitMenu = chatMenu.Append(wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self.OnExit, exitMenu)

        editMenu = wx.Menu()
        copyMenu = editMenu.Append(wx.ID_ANY, "&Copy Last Message\tCTRL+SHIFT+C")
        self.Bind(wx.EVT_MENU, self.OnCopyMessage, copyMenu)
        clearMenu = editMenu.Append(wx.ID_ANY, "C&lear Last Message\tCTRL+K")
        self.Bind(wx.EVT_MENU, self.clearLast, clearMenu)
        editPreviousMenu = editMenu.Append(wx.ID_ANY, "Edit Previous Message\tAlt+Up")
        self.Bind(wx.EVT_MENU, self.OnHistoryUp, editPreviousMenu)
        editNextMenu = editMenu.Append(wx.ID_ANY, "Edit Next Message\tALT+Down")
        self.Bind(wx.EVT_MENU, self.OnHistoryDown, editNextMenu)

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
        menuBar.Append(ragMenu, "&Rag")
        self.SetMenuBar(menuBar)

        self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.NO_BORDER | wx.TB_FLAT)
        self.presetBtn = wx.Button(self.toolbar, label="Preset: none")
        self.toolbar.AddControl(self.presetBtn, "Preset")
        self.presetBtn.Bind(wx.EVT_BUTTON, self.onPresetPopup)

        # Toolbar buttons are shortcuts to menu items: the keyboard shortcut is
        # declared once, on the menu item, and the button fires that same item.
        self.copyButton = self.addToolButton("Copy Last Message", copyMenu)
        self.clearButton = self.addToolButton("Clear Last Message", clearMenu)
        self.newButton = self.addToolButton("New Chat", newMenu)
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
        name = assistant_name()
        for message in self.model.messages[start:]:
            role = name if message.role == "assistant" else "You"
            text = f"{role}: {message.content}"
            self.response.AppendText(text)
            self.response.AppendText(os.linesep)

    def onToggleShowReasoning(self, e):
        settings.show_reasoning = self.showReasoning.IsChecked()

    def onTogglePlaySound(self, e):
        settings.sound = self.playSound.IsChecked()

    def onToggleSpeakResponse(self, e):
        settings.speakResponse = self.speakResponse.IsChecked()

    def onToggleUseScreenReader(self, e):
        settings.screenreader = self.useScreenReader.IsChecked()
        self.init_speech()

    def OnResetSettings(self, event):
        with wx.MessageDialog(
            self,
            f"Are you sure you want to reset your settings?",
            "Reset",
            wx.YES_NO | wx.ICON_QUESTION,
        ) as dlg:
            dlg.SetYesNoLabels("Reset and Quit", "Cancel")
            if dlg.ShowModal() == wx.ID_YES:
                settings_file_path = config_dir() / "settings.json"
                if settings_file_path.exists():
                    settings_file_path.unlink()
                    self.OnExit(None)

    def OnNewChat(self, event):
        self.FocusOnPrompt()
        self.model.messages = []
        self.model.setSystem(self.systemPrompt())
        self.response.Clear()

    def addToolButton(self, label, item):
        """Add a toolbar button that triggers a menu item, shortcut included."""
        button = wx.Button(self.toolbar, label=label)
        button.SetName(label)
        parts = item.GetItemLabel().split("\t")
        button.SetToolTip(f"{label} ({parts[1]})" if len(parts) > 1 else label)
        self.toolbar.AddControl(button, label)
        button.Bind(
            wx.EVT_BUTTON,
            lambda event: self.ProcessEvent(
                wx.CommandEvent(wx.EVT_MENU.typeId, item.GetId())
            ),
        )
        return button

    def OnCopyMessage(self, event):
        message = self.model.messages[-1].content.strip()
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(message))
            wx.TheClipboard.Close()

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
            wildcard="Image files (*.jpg;*.jpeg;*.png)|*.jpg;*.jpeg;*.png;*.mp4",
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
        name = assistant_name()
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

    def onShowRagSettings(self, event):
        with RAGParameterDialog(self, "RAG Settings") as dlg:
            dlg.ShowModal()

    def OnExit(self, event):
        self.Destroy()

    def systemPrompt(self):
        preset = active_preset()
        return preset.get("system", "") if preset else ""

    def updatePresetLabel(self):
        name = (
            settings.active_preset if settings.active_preset in settings.presets else ""
        )
        self.presetBtn.SetLabel(f"Preset: {name or 'none'}")
        self.toolbar.Realize()

    def onPresetPopup(self, event):
        presets = settings.presets
        menu = wx.Menu()
        for name in sorted(presets):
            pid = wx.NewIdRef()
            item = menu.Append(pid, name, kind=wx.ITEM_CHECK)
            if name == settings.active_preset:
                item.Check(True)
            self.Bind(
                wx.EVT_MENU, functools.partial(self.apply_preset, name=name), id=pid
            )
        menu.AppendSeparator()
        new_id = wx.NewIdRef()
        menu.Append(new_id, "&New...")
        self.Bind(wx.EVT_MENU, self.new_preset, id=new_id)
        edit_id = wx.NewIdRef()
        edit_item = menu.Append(edit_id, "&Edit...")
        self.Bind(wx.EVT_MENU, self.edit_preset, id=edit_id)
        dup_id = wx.NewIdRef()
        dup_item = menu.Append(dup_id, "D&uplicate...")
        self.Bind(wx.EVT_MENU, self.duplicate_preset, id=dup_id)
        del_id = wx.NewIdRef()
        del_item = menu.Append(del_id, "&Delete...")
        self.Bind(wx.EVT_MENU, self.delete_preset, id=del_id)
        has_active = settings.active_preset in presets
        for item in (edit_item, dup_item, del_item):
            item.Enable(has_active)
        self.toolbar.PopupMenu(menu, self.presetBtn.Position)
        menu.Destroy()
        self.FocusOnPrompt()

    def apply_preset(self, event, name):
        if name not in settings.presets:
            self.updatePresetLabel()
            return
        settings.active_preset = name
        self.updatePresetLabel()
        self.OnNewChat(None)

    def store_preset(self, name, preset):
        presets = settings.presets
        presets[name] = preset
        settings.presets = presets
        settings.active_preset = name
        self.updatePresetLabel()

    def new_preset(self, event, name="", preset=None):
        with PresetDialog(self, "New Preset", name=name, preset=preset) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            name = dlg.get_name()
            if name in settings.presets:
                displayError(Exception(f"A preset named {name} already exists."))
                return
            self.store_preset(name, dlg.get_preset())
        self.OnNewChat(None)

    def edit_preset(self, event, page=CONNECTION_PAGE):
        name = settings.active_preset
        preset = settings.presets.get(name)
        if not preset:
            self.new_preset(event)
            return
        with PresetDialog(
            self, f"Edit Preset: {name}", name=name, preset=preset, page=page
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            new_name = dlg.get_name()
            presets = settings.presets
            if new_name != name:
                if new_name in presets:
                    displayError(
                        Exception(f"A preset named {new_name} already exists.")
                    )
                    return
                presets.pop(name, None)
            self.store_preset(new_name, dlg.get_preset())
        self.OnNewChat(None)

    def duplicate_preset(self, event):
        preset = settings.presets.get(settings.active_preset)
        if not preset:
            return
        self.new_preset(event, name=f"{settings.active_preset} copy", preset=preset)

    def delete_preset(self, event):
        name = settings.active_preset
        if name not in settings.presets:
            displayError(Exception("No preset is selected."))
            return
        confirm = wx.MessageBox(
            f"Delete the preset {name}?", "Delete Preset", wx.YES_NO | wx.ICON_WARNING
        )
        if confirm != wx.YES:
            return
        presets = settings.presets
        presets.pop(name, None)
        settings.presets = presets
        settings.active_preset = sorted(presets)[0] if presets else ""
        self.updatePresetLabel()
        self.OnNewChat(None)

    def log(self, e):
        print(settings.to_dict())


if __name__ == "__main__":
    app = wx.App(False)
    ChatWindow(None, "VOLlama")
    app.MainLoop()
