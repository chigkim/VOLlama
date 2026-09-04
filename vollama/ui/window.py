"""The main window: menus, the transcript, the prompt box, and what they do.

Every action here is short, because none of them decides anything. Sending a
message is a call into `ChatSession`; renaming a preset is a call into
`config.presets`; saving a chat is `Conversation.to_json` and a file dialog.
The window's job is to turn a keystroke into one of those calls and to show what
comes back, which is what lets the rest of the application be tested without it.

Work that can block runs on a worker thread through `_in_background`, and
everything a worker sends back goes through `TranscriptView` or
`ui.errors`, which are the two places that know about `wx.CallAfter`.
"""

import codecs
import functools
import json
import logging
import os
import platform
import threading

import sounddevice
import soundfile
import wx

from vollama import BUILD, resources
from vollama.chat.session import Attachments, ChatSession
from vollama.config import presets
from vollama.config.settings import compatible, settings
from vollama.errors import VOLlamaError
from vollama.rag import documents
from vollama.speech import create as create_speech
from vollama.tools import shell
from vollama.tools.workspace import working_dir
from vollama.ui import transcript, update
from vollama.ui.errors import show_error, show_info
from vollama.ui.preset_dialog import CONNECTION_PAGE, PresetDialog
from vollama.ui.rag_dialog import RagDialog
from vollama.ui.speech_dialog import SpeechDialog

DOCUMENT_FILTER = documents.wildcard("Supported Files", documents.DOCUMENT_EXTENSIONS)
IMAGE_FILTER = documents.wildcard(
    "Image and video files", documents.IMAGE_EXTENSIONS + documents.VIDEO_EXTENSIONS
)

INCOMPATIBLE_SETTINGS = (
    "Your settings were written by a different version of VOLlama and cannot be "
    "read. Choose Reset Settings in the Chat menu and restart the app. Your old "
    "settings file is still on disk if you need to copy an API key out of it."
)


log = logging.getLogger(__name__)


def play(name):
    """Play one of the bundled sounds, if sounds are on."""
    if not settings.sound:
        return

    def run():
        try:
            data, rate = soundfile.read(resources.bundled(name), dtype="float32")
            sounddevice.play(data, rate)
        except Exception as e:
            # A machine with no sound device is not a reason to interrupt a
            # chat, so this is logged and never shown.
            log.info("Could not play %s: %s", name, e)

    threading.Thread(target=run, daemon=True).start()


class PromptBox(wx.TextCtrl):
    """The message box: Enter sends, shift+Enter starts a new line."""

    def __init__(self, parent, **kwargs):
        style = kwargs.pop("style", 0) | wx.TE_MULTILINE | wx.TE_PROCESS_ENTER
        super().__init__(parent, style=style, **kwargs)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN and event.ShiftDown():
            # Handled here so EVT_TEXT_ENTER, which sends, never fires.
            self.WriteText("\n")
        else:
            event.Skip()


class ChatWindow(wx.Frame):
    def __init__(self, parent, title):
        super().__init__(parent, title=title, size=(1920, 1080))
        self.speech = create_speech(settings.screenreader)
        if settings.speakResponse:
            self.speech.speak("VOLlama is starting...")

        self.session = ChatSession(self._system_prompt())
        self.attachments = Attachments()
        self.history_index = 0

        self._build_ui()
        self.view = transcript.TranscriptView(
            self.output, self.set_status, self.speech, self._on_turn_finished
        )
        self.Maximize(True)
        self.Centre()
        self.Show()
        self.prompt.SetFocus()
        self._update_preset_label()

        threading.Thread(target=update.check, args=(BUILD,), daemon=True).start()
        if not compatible:
            show_error(VOLlamaError(INCOMPATIBLE_SETTINGS), "Settings")
        elif not settings.presets:
            self.on_new_preset(None)

    # ------------------------------------------------------------------ layout

    def _build_ui(self):
        self.Bind(wx.EVT_CLOSE, self.on_exit)
        menus = wx.MenuBar()
        menus.Append(self._chat_menu(), "&Chat")
        menus.Append(self._edit_menu(), "&Edit")
        menus.Append(self._rag_menu(), "&Rag")
        self.SetMenuBar(menus)
        self._build_toolbar()
        self._build_panel()
        # Escape leaves the edit box and stops whatever is generating.
        escape = wx.NewIdRef()
        self.SetAcceleratorTable(
            wx.AcceleratorTable([(wx.ACCEL_NORMAL, wx.WXK_ESCAPE, escape)])
        )
        self.Bind(wx.EVT_MENU, self.focus_prompt, id=escape)

    def _chat_menu(self):
        menu = wx.Menu()
        self.new_item = self._standard(menu, wx.ID_NEW, self.on_new_chat)
        self._standard(menu, wx.ID_OPEN, self.on_open)
        self._standard(menu, wx.ID_SAVE, self.on_save)
        self._item(menu, "Attach an &Image...\tCTRL+I", handler=self.on_attach_image)
        self._item(menu, "Attach a &Document...\tCTRL+D", handler=self.on_attach_document)
        self._item(menu, "Attach a &URL...\tCTRL+U", handler=self.on_attach_url)
        self.reasoning_item = self._check(
            menu, "Show Reasoning", settings.show_reasoning, self.on_toggle_reasoning
        )
        self.tools_item = self._check(
            menu,
            "Tools",
            settings.tools,
            self.on_toggle_tools,
            "Let the model run commands and edit files on this computer. It "
            "does so without asking you first.",
        )
        self.workdir_item = self._item(
            menu,
            "CD",
            handler=self.on_change_workdir,
            help="Choose the folder the model's commands run in.",
        )
        self._show_workdir()
        self.speak_item = self._check(
            menu, "Read Response", settings.speakResponse, self.on_toggle_speak
        )
        self.sound_item = self._check(
            menu, "Play Sound", settings.sound, self.on_toggle_sound
        )
        if platform.system() == "Windows":
            self.screenreader_item = self._check(
                menu,
                "Use Screen Reader",
                settings.screenreader,
                self.on_toggle_screen_reader,
            )
        self._item(
            menu, "Configure System Voice...\tCTRL+SHIFT+V", handler=self.on_configure_voice
        )
        self._item(menu, "&Presets\tCTRL+p", handler=self.on_presets)
        menu.AppendSeparator()
        self._item(menu, "&Reset Settings...", handler=self.on_reset_settings)
        self._standard(menu, wx.ID_EXIT, self.on_exit)
        return menu

    def _edit_menu(self):
        menu = wx.Menu()
        self.copy_item = self._item(
            menu, "&Copy Last Message\tCTRL+SHIFT+C", handler=self.on_copy
        )
        self.clear_item = self._item(
            menu, "C&lear Last Message\tCTRL+K", handler=self.on_clear_last
        )
        self._item(menu, "Edit Previous Message\tAlt+Up", handler=self.on_history_up)
        self._item(menu, "Edit Next Message\tALT+Down", handler=self.on_history_down)
        self._item(
            menu, "Compact Conversation\tCTRL+SHIFT+K", handler=self.on_compact
        )
        return menu

    def _rag_menu(self):
        menu = wx.Menu()
        self._item(menu, "Index &URL...", handler=self.on_index_url)
        self._item(menu, "Index &File...\tCTRL+F", handler=self.on_index_files)
        self._item(menu, "Index Directory...", handler=self.on_index_folder)
        self._item(menu, "Load Index...", handler=self.on_load_index)
        self._item(menu, "Save Index...", handler=self.on_save_index)
        self._item(menu, "Settings...", handler=self.on_rag_settings)
        return menu

    def _standard(self, menu, identifier, handler):
        """A menu item wx already knows the label and shortcut for."""
        item = menu.Append(int(identifier))
        self.Bind(wx.EVT_MENU, handler, item)
        return item

    def _item(self, menu, label, handler, help=""):
        """A menu item of ours. The shortcut is part of the label, after a tab."""
        item = menu.Append(wx.ID_ANY, label, help)
        self.Bind(wx.EVT_MENU, handler, item)
        return item

    def _check(self, menu, label, value, handler, help=""):
        item = menu.Append(wx.ID_ANY, label, help, wx.ITEM_CHECK)
        item.Check(value)
        self.Bind(wx.EVT_MENU, handler, item)
        return item

    def _build_toolbar(self):
        self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.NO_BORDER | wx.TB_FLAT)
        self.preset_button = wx.Button(self.toolbar, label="Preset: none")
        self.toolbar.AddControl(self.preset_button, "Preset")
        self.preset_button.Bind(wx.EVT_BUTTON, self.on_presets)
        for label, item in (
            ("Copy Last Message", self.copy_item),
            ("Clear Last Message", self.clear_item),
            ("New Chat", self.new_item),
        ):
            self._tool_button(label, item)
        self.toolbar.Realize()

    def _tool_button(self, label, item):
        """A toolbar button that fires a menu item.

        The shortcut is declared once, on the menu item, and the button raises
        that same item's event, so the two cannot come apart.
        """
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

    def _build_panel(self):
        panel = wx.Panel(self)
        self.output = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.output.SetName("Transcript")
        self.prompt = PromptBox(panel)
        self.prompt.SetName("Message")
        self.prompt.Bind(wx.EVT_TEXT_ENTER, self.on_send)

        bar = wx.Panel(panel)
        self.status = wx.StaticText(bar, label="READY!")
        self.send_button = wx.Button(bar, label="Send")
        self.send_button.Bind(wx.EVT_BUTTON, self.on_send)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.status, 10, wx.ALL | wx.EXPAND, 5)
        row.Add(self.send_button, 1, wx.ALL, 5)
        bar.SetSizer(row)

        column = wx.BoxSizer(wx.VERTICAL)
        column.Add(self.output, 6, wx.EXPAND | wx.ALL, 5)
        column.Add(self.prompt, 3, wx.EXPAND | wx.ALL, 5)
        column.Add(bar, 1, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(column)

    # ----------------------------------------------------------------- helpers

    def set_status(self, text):
        self.status.SetLabel(text)

    def _in_background(self, work, *args):
        """Run work off the GUI thread, reporting anything it raises."""

        def run():
            try:
                work(*args)
            except Exception as e:
                show_error(e)

        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _system_prompt():
        preset = presets.active()
        return preset.system if preset else ""

    def _refresh_transcript(self):
        self.output.SetValue(transcript.render(self.session.conversation))
        self.history_index = len(self.session.conversation.messages)

    # ------------------------------------------------------------- sending

    def on_send(self, event):
        if self.session.generating:
            self.focus_prompt()
            return
        message = self.prompt.GetValue()
        if not message:
            return
        self.prompt.SetValue("")
        if self.history_index < len(self.session.conversation.messages):
            # Editing an earlier message rather than sending a new one.
            self.session.conversation.messages[self.history_index].content = message
            self._refresh_transcript()
            return
        play("send.wav")
        self.output.AppendText(f"You: {message}{os.linesep}")
        self.send_button.SetLabel("Stop")
        attachments, self.attachments = self.attachments, Attachments()
        self._in_background(self.session.ask, message, self.view, attachments)

    def _on_turn_finished(self):
        play("receive.wav")
        self.send_button.SetLabel("Send")
        self.history_index = len(self.session.conversation.messages)

    def focus_prompt(self, event=None):
        self.session.stop()
        self.speech.stop()
        self.prompt.SetFocus()
        if self.history_index < len(self.session.conversation.messages):
            self.history_index = len(self.session.conversation.messages)
            self.prompt.SetValue("")
        self.send_button.SetLabel("Send")

    # ------------------------------------------------------------- the history

    def on_history_up(self, event):
        self._move_history(-1)

    def on_history_down(self, event):
        self._move_history(1)

    def _move_history(self, step):
        """Walk to the next message worth editing, in the given direction."""
        conversation = self.session.conversation
        total = len(conversation.messages)
        index = self.history_index + step
        while 0 <= index < total and not conversation.reviewable(index):
            index += step
        if index >= total:
            self.history_index = total
            self.prompt.SetValue("")
            self.send_button.SetLabel("Send")
            return
        if index < 0 or not conversation.reviewable(index):
            return
        self.history_index = index
        self.prompt.SetValue(conversation.messages[index].content)
        self.prompt.SetInsertionPointEnd()
        self.send_button.SetLabel("Edit")

    def on_copy(self, event):
        messages = self.session.conversation.messages
        if not messages:
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(
                wx.TextDataObject((messages[-1].content or "").strip())
            )
            wx.TheClipboard.Close()

    def on_clear_last(self, event):
        self.prompt.SetValue(self.session.conversation.clear_last())
        self._refresh_transcript()

    def on_compact(self, event):
        if self.session.generating or not self.session.conversation.messages:
            return
        self._in_background(self.session.compact, None, self.view)

    # ---------------------------------------------------------------- the chat

    def on_new_chat(self, event):
        self.focus_prompt()
        # Nothing in the new chat could read their output, so let them go.
        shell.jobs.kill_all()
        self.session.restart(self._system_prompt())
        self.output.Clear()
        self.history_index = 0

    def on_open(self, event):
        with wx.FileDialog(
            self, "Open", wildcard="*.json", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        ) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return
            path = dialog.GetPath()
        try:
            with codecs.open(path, "r", "utf-8") as file:
                self.session.conversation.load_json(json.load(file))
        except (OSError, ValueError, KeyError) as e:
            show_error(VOLlamaError(f"Could not open {path}: {e}"))
            return
        self._refresh_transcript()

    def on_save(self, event):
        with wx.FileDialog(
            self,
            "Save",
            defaultFile=transcript.assistant_name() + ".json",
            wildcard="*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return
            path = dialog.GetPath()
        try:
            with codecs.open(path, "w", "utf-8") as file:
                json.dump(self.session.conversation.to_json(), file, indent="\t")
        except OSError as e:
            show_error(VOLlamaError(f"Could not save {path}: {e}"))

    # ------------------------------------------------------------ attachments

    def on_attach_image(self, event):
        paths = self._choose_files("Choose an image", IMAGE_FILTER)
        if paths:
            self.attachments = Attachments(
                images=paths, files=self.attachments.files, url=self.attachments.url
            )
        self.prompt.SetFocus()

    def on_attach_document(self, event):
        paths = self._choose_files("Choose a file", DOCUMENT_FILTER)
        if paths:
            self.attachments = Attachments(
                images=self.attachments.images, files=paths, url=self.attachments.url
            )
        self.prompt.SetFocus()

    def on_attach_url(self, event):
        url = self._ask_url("Enter an url to retrieve:")
        if url:
            self.attachments = Attachments(
                images=self.attachments.images, files=self.attachments.files, url=url
            )
        self.prompt.SetFocus()

    def _choose_files(self, title, wildcard):
        with wx.FileDialog(
            self,
            title,
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return []
            return dialog.GetPaths()

    def _ask_url(self, question):
        with wx.TextEntryDialog(self, question, "URL", value="https://") as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return ""
            return dialog.GetValue().strip()

    # ------------------------------------------------------------- retrieval

    def on_index_files(self, event):
        paths = self._choose_files("Choose a file", DOCUMENT_FILTER)
        if paths:
            self._index(paths)

    def on_index_folder(self, event):
        folder = self._choose_folder("Choose a folder with documents:")
        if folder:
            self._index(folder)

    def on_index_url(self, event):
        url = self._ask_url("Enter an url to index:")
        if url:
            self._index(url)

    def _index(self, source):
        self.set_status(f"Indexing {source}")

        def run():
            chunks = self.session.build_index(source, self._progress)
            message = f"Indexed {source} into {chunks} chunks."
            wx.CallAfter(self.set_status, message)
            show_info("Index", message)

        self._in_background(run)

    def _progress(self, text):
        wx.CallAfter(self.set_status, text)

    def on_load_index(self, event):
        folder = self._choose_folder("Choose a folder with an index:")
        if folder:
            self._in_background(self.session.load_index, folder)

    def on_save_index(self, event):
        folder = self._choose_folder("Choose a folder to save the index in:")
        if folder:
            self._in_background(self.session.save_index, folder)

    def on_rag_settings(self, event):
        with RagDialog(self) as dialog:
            dialog.ShowModal()

    def _choose_folder(self, title, start=""):
        with wx.DirDialog(
            self, title, start, wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST
        ) as dialog:
            return dialog.GetPath() if dialog.ShowModal() == wx.ID_OK else ""

    # --------------------------------------------------------------- settings

    def on_toggle_reasoning(self, event):
        settings.show_reasoning = self.reasoning_item.IsChecked()
        settings.save()

    def on_toggle_tools(self, event):
        settings.tools = self.tools_item.IsChecked()
        settings.save()

    def on_toggle_speak(self, event):
        settings.speakResponse = self.speak_item.IsChecked()
        settings.save()

    def on_toggle_sound(self, event):
        settings.sound = self.sound_item.IsChecked()
        settings.save()

    def on_toggle_screen_reader(self, event):
        settings.screenreader = self.screenreader_item.IsChecked()
        settings.save()
        self.speech = create_speech(settings.screenreader)
        self.view.speech = self.speech

    def on_change_workdir(self, event):
        folder = self._choose_folder(
            "Choose the folder the model's commands run in", working_dir()
        )
        if folder:
            settings.workdir = folder
            settings.save()
            self._show_workdir()

    def _show_workdir(self):
        """Put the working directory in the menu item, so it reads as a label.

        An ampersand in a path would otherwise be swallowed as the mnemonic
        marker and the folder would appear under a name it does not have.
        """
        self.workdir_item.SetItemLabel("CD " + working_dir().replace("&", "&&"))

    def on_configure_voice(self, event):
        voices = self.speech.voices()
        if not voices:
            show_info(
                "Voice",
                "Speech is coming from your screen reader, so its voice and "
                "rate are set there rather than here.",
            )
            return
        with SpeechDialog(self, voices, self.speech.voice, self.speech.rate) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            voice, rate = dialog.choice()
        if voice:
            self.speech.voice = voice
        if rate is not None:
            self.speech.rate = rate

    def on_reset_settings(self, event):
        with wx.MessageDialog(
            self,
            "Are you sure you want to reset your settings? Presets and API keys "
            "are deleted with them.",
            "Reset",
            wx.YES_NO | wx.ICON_QUESTION,
        ) as dialog:
            dialog.SetYesNoLabels("Reset and Quit", "Cancel")
            if dialog.ShowModal() != wx.ID_YES:
                return
        from vollama.config.store import settings_path

        path = settings_path()
        try:
            if path.exists():
                path.unlink()
        except OSError as e:
            show_error(VOLlamaError(f"Could not delete {path}: {e}"))
            return
        self.on_exit(None)

    # ----------------------------------------------------------------- presets

    def on_presets(self, event):
        menu = wx.Menu()
        for name in presets.names():
            item = menu.Append(wx.NewIdRef(), name, kind=wx.ITEM_CHECK)
            item.Check(name == presets.active_name())
            self.Bind(
                wx.EVT_MENU,
                functools.partial(self.on_choose_preset, name=name),
                item,
            )
        menu.AppendSeparator()
        new_item = menu.Append(wx.NewIdRef(), "&New...")
        self.Bind(wx.EVT_MENU, self.on_new_preset, new_item)
        editable = []
        for label, handler in (
            ("&Edit...", self.on_edit_preset),
            ("D&uplicate...", self.on_duplicate_preset),
            ("&Delete...", self.on_delete_preset),
        ):
            item = menu.Append(wx.NewIdRef(), label)
            self.Bind(wx.EVT_MENU, handler, item)
            editable.append(item)
        for item in editable:
            item.Enable(bool(presets.active_name()))
        self.toolbar.PopupMenu(menu, self.preset_button.Position)
        menu.Destroy()
        self.focus_prompt()

    def on_choose_preset(self, event, name):
        presets.activate(name)
        self._preset_changed()

    def on_new_preset(self, event, name="", preset=None):
        self._edit(PresetDialog(self, "New Preset", name=name, preset=preset), None)

    def on_edit_preset(self, event):
        name = presets.active_name()
        preset = presets.get(name)
        if not preset:
            self.on_new_preset(event)
            return
        self._edit(
            PresetDialog(
                self, f"Edit Preset: {name}", name=name, preset=preset,
                page=CONNECTION_PAGE,
            ),
            name,
        )

    def on_duplicate_preset(self, event):
        name = presets.active_name()
        preset = presets.get(name)
        if preset:
            self.on_new_preset(event, name=f"{name} copy", preset=preset)

    def on_delete_preset(self, event):
        name = presets.active_name()
        if not name:
            return
        if wx.MessageBox(
            f"Delete the preset {name}?", "Delete Preset", wx.YES_NO | wx.ICON_WARNING
        ) != wx.YES:
            return
        presets.delete(name)
        self._preset_changed()

    def _edit(self, dialog, replacing):
        """Show a preset dialog and store what it produced.

        `replacing` is the name being edited, or None for a new preset. Whether
        the name is free and where the preset is kept are decided by
        config.presets, not here.
        """
        with dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            name, preset = dialog.name(), dialog.preset()
        try:
            if replacing is None:
                presets.create(name, preset)
            else:
                presets.update(replacing, name, preset)
        except VOLlamaError as e:
            show_error(e, "Preset")
            return
        self._preset_changed()

    def _preset_changed(self):
        self._update_preset_label()
        self.on_new_chat(None)

    def _update_preset_label(self):
        self.preset_button.SetLabel(f"Preset: {presets.active_name() or 'none'}")
        self.toolbar.Realize()

    # -------------------------------------------------------------------- exit

    def on_exit(self, event):
        # The window close button does not go through the Exit menu item, and
        # background commands outlive the app unless something stops them.
        shell.jobs.kill_all()
        self.Destroy()
