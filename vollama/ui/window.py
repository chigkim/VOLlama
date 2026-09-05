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

import dataclasses
import functools
import json
import logging
import os
import platform
import threading

import sounddevice
import soundfile
import wx

from vollama import BUILD, resources, speech
from vollama.chat.session import Attachments, ChatSession
from vollama.config import presets
from vollama.config.settings import settings
from vollama.config.store import settings_path
from vollama.errors import VOLlamaError
from vollama.rag import documents
from vollama.tools import shell
from vollama.tools.workspace import ensure_working_dir, working_dir
from vollama.ui import transcript, update
from vollama.ui.errors import show_error, show_info
from vollama.ui.preset_manager import PresetManager
from vollama.ui.speech_dialog import SpeechDialog


def wildcard(label, extensions):
    """A wx file-dialog filter built from a list of extensions."""
    patterns = ";".join(f"*{extension}" for extension in extensions)
    return f"{label} ({patterns})|{patterns}"


DOCUMENT_FILTER = wildcard("Supported Files", documents.DOCUMENT_EXTENSIONS)
IMAGE_FILTER = wildcard("Image files", documents.IMAGE_EXTENSIONS)
CHAT_FILTER = wildcard("Saved chats", (".json",))

INCOMPATIBLE_SETTINGS = (
    "Your settings could not be read: they were written by a different version "
    "of VOLlama, or the file is damaged. Nothing will be saved over them, so "
    "your old settings file stays on disk if you need to copy an API key out of "
    "it. Choose Reset Settings in the Chat menu and restart the app."
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
    def __init__(self, parent, title, settings_readable=True):
        super().__init__(parent, title=title, size=(1920, 1080))
        self.speech = speech.create(settings.screenreader)
        if settings.speak_response:
            self.speech.speak("VOLlama is starting...")

        self.session = ChatSession(self._system_prompt())
        self.attachments = Attachments()
        self.history_index = len(self.session.conversation.messages)

        self._build_ui()
        self.view = transcript.TranscriptView(
            self.output, self.set_status, self.speech, self._on_turn_finished
        )
        self.Maximize(True)
        self.Centre()
        self.Show()
        self.prompt.SetFocus()
        self._update_preset_label()
        # Tools left on from an earlier session: the folder they run in may
        # have been deleted since, and it is made here rather than on the first
        # command so the failure is reported before the model hits it.
        if settings.tools:
            self._make_workdir()

        threading.Thread(target=update.check, args=(BUILD,), daemon=True).start()
        if not settings_readable:
            show_error(VOLlamaError(INCOMPATIBLE_SETTINGS), "Settings")
        elif not settings.presets:
            self.on_manage_presets(None)

    # ------------------------------------------------------------------ layout

    def _build_ui(self):
        self.Bind(wx.EVT_CLOSE, self.on_exit)
        menus = wx.MenuBar()
        menus.Append(self._chat_menu(), "&Chat")
        menus.Append(self._edit_menu(), "&Edit")
        menus.Append(self._documents_menu(), "&Documents")
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
            "does so without asking you first. Searching documents you have "
            "indexed is not covered by this and is always allowed.",
        )
        self.workdir_item = self._item(
            menu,
            "Workspace",
            handler=self.on_change_workdir,
            help="Choose the folder the model's commands run in.",
        )
        self._show_workdir()
        self.speak_item = self._check(
            menu, "Read Response", settings.speak_response, self.on_toggle_speak
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

    def _documents_menu(self):
        menu = wx.Menu()
        self._item(menu, "Index &URL...", handler=self.on_index_url)
        self._item(menu, "Index &File...\tCTRL+F", handler=self.on_index_files)
        self._item(menu, "Index Directory...", handler=self.on_index_folder)
        self._item(menu, "Load Index...", handler=self.on_load_index)
        self._item(menu, "Save Index...", handler=self.on_save_index)
        self._item(menu, "Clear Index", handler=self.on_clear_index)
        self.context_item = self._check(
            menu,
            "Show Conte&xt",
            settings.show_context,
            self.on_toggle_context,
            "Print the retrieved passages and their similarity scores with "
            "the answer.",
        )
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
        if self.session.conversation.reviewable(self.history_index):
            # Editing a message alt+up walked back to, rather than sending a new
            # one. Asked of the conversation rather than compared against its
            # length: a preset with a system prompt puts a message at index 0, so
            # the first thing ever typed counted as an edit of it and was
            # swallowed, replacing the system prompt with the user's own text.
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
        self.history_index = len(self.session.conversation.messages)

    def on_open(self, event):
        with wx.FileDialog(
            self, "Open", wildcard=CHAT_FILTER, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        ) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return
            path = dialog.GetPath()
        try:
            with open(path, encoding="utf-8") as file:
                self.session.conversation.load_json(json.load(file))
        # TypeError as well, since the file says what shape it is and a
        # hand-written one can say something that is not a chat at all.
        except (OSError, ValueError, KeyError, TypeError) as e:
            show_error(VOLlamaError(f"Could not open {path}: {e}"))
            return
        self._refresh_transcript()

    def on_save(self, event):
        with wx.FileDialog(
            self,
            "Save",
            defaultFile=transcript.assistant_name() + ".json",
            wildcard=CHAT_FILTER,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return
            path = dialog.GetPath()
        try:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(self.session.conversation.to_json(), file, indent="\t")
        except OSError as e:
            show_error(VOLlamaError(f"Could not save {path}: {e}"))

    # ------------------------------------------------------------ attachments

    def on_attach_image(self, event):
        paths = self._choose_files("Choose an image", IMAGE_FILTER)
        if paths:
            self._attach(images=tuple(paths))
        self.prompt.SetFocus()

    def on_attach_document(self, event):
        paths = self._choose_files("Choose a file", DOCUMENT_FILTER)
        if paths:
            self._attach(files=tuple(paths))
        self.prompt.SetFocus()

    def on_attach_url(self, event):
        url = self._ask_url("Enter an url to retrieve:")
        if url:
            self._attach(url=url)
        self.prompt.SetFocus()

    def _attach(self, **kind):
        """Add one kind of attachment, keeping whatever else is already on."""
        self.attachments = dataclasses.replace(self.attachments, **kind)

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
            show_info(message, "Index")

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

    def on_clear_index(self, event):
        """Forget the loaded index, and with it the model's search tool.

        Reported either way rather than greyed out when there is nothing to
        clear: a disabled item is one a screen reader reads past without saying
        why, and "nothing has been indexed yet" is the answer to the question
        the user was asking by choosing it.
        """
        message = (
            "The index has been cleared."
            if self.session.clear_index()
            else "Nothing has been indexed yet."
        )
        self.set_status(message)
        show_info(message, "Index")
        self.focus_prompt()

    def _choose_folder(self, title, start=""):
        with wx.DirDialog(
            self, title, start, wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST
        ) as dialog:
            return dialog.GetPath() if dialog.ShowModal() == wx.ID_OK else ""

    # --------------------------------------------------------------- settings

    def on_toggle_reasoning(self, event):
        settings.show_reasoning = self.reasoning_item.IsChecked()
        settings.save()

    def on_toggle_context(self, event):
        """Whether a retrieval turn prints the passages it used.

        Here rather than on a preset's RAG page: it is a question about
        what to show right now, not about the server, and it belongs beside the
        retrieval it describes.
        """
        settings.show_context = self.context_item.IsChecked()
        settings.save()

    def on_toggle_tools(self, event):
        """Switch the tools on or off, asking first on the way on.

        The checkbox is the only gate there is: there is no confirmation before
        a command runs or a file is written, so this is the one place the user
        can be told that, and it is asked every time rather than once and
        remembered. Answering no puts the checkbox back rather than leaving it
        looking on, and the folder is made here because this is the moment the
        model gets somewhere to write.
        """
        if not self.tools_item.IsChecked():
            settings.tools = False
            settings.save()
            self._show_workdir()
            return
        if not self._agreed_to_tools():
            self.tools_item.Check(False)
            return
        if not self._make_workdir():
            self.tools_item.Check(False)
            return
        settings.tools = True
        settings.save()
        self._show_workdir()

    def _make_workdir(self):
        """Make the folder the tools work in, or say why it could not be."""
        try:
            ensure_working_dir()
            return True
        except OSError as e:
            show_error(VOLlamaError(f"Could not create {working_dir()}: {e}"))
            return False

    def _agreed_to_tools(self):
        """The warning, with the two answers written out on the buttons.

        A plain Yes/No would leave a screen reader announcing "Yes" with none
        of what is being agreed to, so the labels carry the sentence and No is
        the default answer.
        """
        message = (
            "Tools are an experimental feature and they are dangerous.\n\n"
            "With them on, the model runs shell commands and creates, edits "
            "and overwrites files on this computer without asking you first. "
            "There is no confirmation step and no undo. It can delete work, "
            "change settings, install software or send data over the network, "
            "and a mistake cannot be taken back.\n\n"
            f"Its commands run in {working_dir()}, which will be created if it "
            "is not there, but nothing stops the model from working outside "
            "it.\n\n"
            "Only switch this on if you accept that risk."
        )
        with wx.MessageDialog(
            self,
            message,
            "Turn tools on?",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        ) as dialog:
            dialog.SetYesNoLabels(
                "I agree, and I am responsible for any damage",
                "I disagree, leave tools off",
            )
            return dialog.ShowModal() == wx.ID_YES

    def on_toggle_speak(self, event):
        settings.speak_response = self.speak_item.IsChecked()
        settings.save()

    def on_toggle_sound(self, event):
        settings.sound = self.sound_item.IsChecked()
        settings.save()

    def on_toggle_screen_reader(self, event):
        settings.screenreader = self.screenreader_item.IsChecked()
        settings.save()
        self.speech = speech.create(settings.screenreader)
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

        Greyed out with the tools off, since with nothing able to run there the
        folder is not a setting the user can act on. It sits directly under the
        checkbox that explains it, which is what keeps it from being an item a
        screen reader passes over with no way of knowing why.
        """
        self.workdir_item.SetItemLabel("Workspace " + working_dir().replace("&", "&&"))
        self.workdir_item.Enable(settings.tools)

    def on_configure_voice(self, event):
        voices = self.speech.voices()
        if not voices:
            show_info(
                "Speech is coming from your screen reader, so its voice and "
                "rate are set there rather than here.",
                "Voice",
            )
            return
        with SpeechDialog(self, voices, self.speech.voice, self.speech.rate) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            voice, rate = dialog.choice()
        speech.remember(self.speech, voice, rate)

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
        """The presets you have, and the way to the one place that edits them.

        Switching preset is one keystroke and is what this menu is for; New,
        Edit, Duplicate and Delete all moved into the Preset Manager, where the
        list they act on is visible instead of being the active preset by
        implication.
        """
        menu = wx.Menu()
        for name in presets.names():
            item = menu.Append(wx.NewIdRef(), name, kind=wx.ITEM_CHECK)
            item.Check(name == presets.active_name())
            self.Bind(
                wx.EVT_MENU,
                functools.partial(self.on_choose_preset, name=name),
                item,
            )
        if presets.names():
            menu.AppendSeparator()
        manage_item = menu.Append(wx.NewIdRef(), "Preset &Manager...")
        self.Bind(wx.EVT_MENU, self.on_manage_presets, manage_item)
        self.toolbar.PopupMenu(menu, self.preset_button.Position)
        menu.Destroy()
        self.focus_prompt()

    def on_choose_preset(self, event, name):
        presets.activate(name)
        self._preset_changed()

    def on_manage_presets(self, event):
        """The manager saves its own edits; this only reacts to them."""
        with PresetManager(self, select=presets.active_name()) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
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
