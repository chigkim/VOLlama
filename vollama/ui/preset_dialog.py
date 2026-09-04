"""Editing one preset: connection, generation parameters, system prompt.

Three notebook pages, each of which knows how to fill itself from a `Preset` and
how to write itself back into one. Everything else about presets — whether a
name is free, whether the preset can be used, where it is stored — belongs to
`config.presets`, and this dialog calls into it rather than deciding again.

Edits go into a copy, so Cancel discards them. Read the result with `name()` and
`preset()` after `ShowModal()` returns `wx.ID_OK`.
"""

import copy
import threading

import wx

from vollama.chat.client import fetch_models
from vollama.config import parameters
from vollama.config.presets import DEFAULT_CONTEXT_WINDOW, Preset
from vollama.config.prompts import PromptLibrary, fetch_shared
from vollama.errors import ConfigError, VOLlamaError
from vollama.ui.errors import show_error, show_info

# Endpoints people actually point VOLlama at, so a new preset is a pick and a
# key rather than a URL typed from memory. Not a provider list: every one of
# these takes the same OpenAI-compatible path, and anything not here still works
# by being typed in.
SERVERS = (
    ("OpenAI", "https://api.openai.com/v1/"),
    ("Anthropic", "https://api.anthropic.com/v1/"),
    ("Google", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ("OpenRouter", "https://openrouter.ai/api/v1/"),
    ("Ollama", "http://localhost:11434/v1/"),
    ("llama.cpp", "http://localhost:8080/v1/"),
    ("OMLX", "http://localhost:8000/v1/"),
)

# What a brand new preset starts with. A suggestion, made where suggestions
# belong: Preset itself has no default server, so that an empty one fails
# validation rather than half passing it.
STARTING_URL = "http://localhost:11434/v1/"

# The Base URL field's row in the connection grid, which its Choose button
# shares.
BASE_URL_ROW = 1

CONNECTION_PAGE = 0
PARAMETERS_PAGE = 1
PROMPT_PAGE = 2


class ConnectionPage(wx.Panel):
    """Name, base URL, api key, model and context window."""

    def __init__(self, parent):
        super().__init__(parent)
        self.SetName("Connection")
        grid = wx.GridBagSizer(5, 5)
        self.fields = {}
        row = 0

        for key, label, tip in (
            ("name", "&Name", "A label for this preset, shown on the toolbar."),
            (
                "base_url",
                "&Base URL",
                "OpenAI-compatible endpoint, for example "
                "http://localhost:11434/v1/ for Ollama.",
            ),
            ("api_key", "API &Key", "Leave empty if the endpoint does not need one."),
        ):
            self.fields[key] = self._row(grid, row, label, wx.TextCtrl(self), tip)
            row += 1

        self.server_button = self._button(
            grid, BASE_URL_ROW, "&Choose...", "Choose Base URL",
            "Fill in the URL of a server VOLlama already knows about.",
            self.on_server,
        )
        self.fields["model"] = self._row(
            grid, row, "&Model", wx.TextCtrl(self),
            "Model name as the endpoint reports it. Use Choose to pick from a list.",
        )
        self.choose_button = self._button(
            grid, row, "C&hoose...", "Choose Model",
            "Ask the endpoint which models it offers.", self.on_choose,
        )
        row += 1

        self.fields["context_window"] = self._row(
            grid, row, "Context &Window",
            wx.SpinCtrl(self, min=512, max=10_000_000, initial=DEFAULT_CONTEXT_WINDOW),
            "How many tokens this model can hold. Match what your server is "
            "running. It is not sent to the server: VOLlama uses it to decide "
            "when to compact the conversation, and to size retrieval prompts.",
        )
        row += 1

        self.status = wx.StaticText(self, label="Status: Ready")
        self.status.SetName("Status")
        grid.Add(self.status, pos=(row, 0), span=(1, 3), flag=wx.ALL, border=5)
        grid.AddGrowableCol(1)
        self.SetSizer(grid)

    def _row(self, grid, row, label, control, tip):
        grid.Add(
            wx.StaticText(self, label=label + ":"),
            pos=(row, 0),
            flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL,
            border=5,
        )
        control.SetName(label.replace("&", ""))
        control.SetToolTip(tip)
        grid.Add(control, pos=(row, 1), flag=wx.EXPAND | wx.ALL, border=5)
        return control

    def _button(self, grid, row, label, name, tip, handler):
        button = wx.Button(self, label=label)
        # Two buttons both labelled Choose would be announced identically, so
        # each gets an accessible name saying which one it is.
        button.SetName(name)
        button.SetToolTip(tip)
        button.Bind(wx.EVT_BUTTON, handler)
        grid.Add(button, pos=(row, 2), flag=wx.ALL, border=5)
        return button

    def set_status(self, text):
        self.status.SetLabel(f"Status: {text}")

    def load(self, name, preset):
        self.fields["name"].SetValue(name)
        self.fields["base_url"].SetValue(preset.base_url)
        self.fields["api_key"].SetValue(preset.api_key)
        self.fields["model"].SetValue(preset.model)
        self.fields["context_window"].SetValue(preset.context_window)

    def save_into(self, preset):
        preset.base_url = self.fields["base_url"].GetValue().strip()
        preset.api_key = self.fields["api_key"].GetValue().strip()
        preset.model = self.fields["model"].GetValue().strip()
        preset.context_window = self.fields["context_window"].GetValue()

    def on_server(self, event):
        """Pick a known endpoint. Only the URL is filled in, never the key."""
        labels = [f"{name} - {url}" for name, url in SERVERS]
        with wx.SingleChoiceDialog(self, "Choose a server:", "Servers", labels) as dialog:
            dialog.SetName("Server List")
            if dialog.ShowModal() != wx.ID_OK:
                return
            name, url = SERVERS[dialog.GetSelection()]
        self.fields["base_url"].SetValue(url)
        self.set_status(f"Base URL set to {name}. Enter an API key if it needs one.")
        # Focus follows the value that just changed, not the button that changed
        # it, so a screen reader announces the new URL.
        self.fields["base_url"].SetFocus()

    def on_choose(self, event):
        base_url = self.fields["base_url"].GetValue().strip()
        if not base_url:
            self.set_status("Enter a base URL first.")
            self.fields["base_url"].SetFocus()
            return
        api_key = self.fields["api_key"].GetValue().strip()
        self.choose_button.Enable(False)
        self.set_status("Fetching models...")
        threading.Thread(
            target=self._fetch, args=(base_url, api_key), daemon=True
        ).start()

    def _fetch(self, base_url, api_key):
        # Worker thread: nothing here may touch wx directly.
        try:
            models = fetch_models(base_url, api_key)
        except Exception as e:
            wx.CallAfter(self._fetch_failed, str(e))
            return
        wx.CallAfter(self._fetch_done, models)

    def _fetch_failed(self, message):
        self.choose_button.Enable(True)
        self.set_status(f"Could not fetch models. {message}")
        self.choose_button.SetFocus()

    def _fetch_done(self, models):
        self.choose_button.Enable(True)
        if not models:
            self.set_status(
                "This endpoint does not provide a model list. Type the model name."
            )
            self.fields["model"].SetFocus()
            return
        self.set_status(f"Found {len(models)} models.")
        with wx.SingleChoiceDialog(self, "Choose a model:", "Models", models) as dialog:
            dialog.SetName("Model List")
            current = self.fields["model"].GetValue().strip()
            if current in models:
                dialog.SetSelection(models.index(current))
            if dialog.ShowModal() == wx.ID_OK:
                self.fields["model"].SetValue(dialog.GetStringSelection())
        self.fields["model"].SetFocus()


class ParametersPage(wx.Panel):
    """Generation parameters, built from the schema rather than hand-written.

    A control per entry in default-parameters.json, so a parameter added to the
    schema appears here with its description and range and nothing else changes.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.SetName("Parameters")
        self.controls = {}
        self.parameters = {}
        self.area = wx.ScrolledWindow(self)
        self.area.SetScrollbars(1, 1, 1, 1)
        self.area_sizer = wx.BoxSizer(wx.VERTICAL)
        self.area.SetSizer(self.area_sizer)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.area, 1, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(sizer)

    def load(self, name, preset):
        self.parameters = parameters.reconcile(preset.parameters)
        self.area_sizer.Clear(True)
        self.controls = {}
        for key, entry in self.parameters.items():
            row = wx.BoxSizer(wx.HORIZONTAL)
            label = wx.StaticText(
                self.area, label=key.replace("_", " ").capitalize() + ":"
            )
            row.Add(label, 0, wx.ALL | wx.CENTER, 5)
            control = self._control(entry["value"])
            control.SetName(key)
            control.SetToolTip(f"Hint: {entry['description']} Range: {entry['range']}")
            self.controls[key] = control
            row.Add(control, 1, wx.EXPAND | wx.ALL, 5)
            self.area_sizer.Add(row, 0, wx.EXPAND)
        self.area.Layout()
        self.area.FitInside()

    def _control(self, value):
        if isinstance(value, bool):
            control = wx.CheckBox(self.area)
            control.SetValue(value)
            return control
        if isinstance(value, list):
            return wx.TextCtrl(self.area, value=", ".join(value))
        # None is an unset parameter and shows as an empty box, which is what
        # tells the server to use its own default.
        return wx.TextCtrl(self.area, value="" if value is None else str(value))

    def save_into(self, preset):
        for key, control in self.controls.items():
            if isinstance(control, wx.CheckBox):
                self.parameters[key]["value"] = control.IsChecked()
            else:
                self.parameters[key]["value"] = parameters.parse_value(
                    key, control.GetValue(), self.parameters[key]["value"]
                )
        preset.parameters = self.parameters


class PromptPage(wx.Panel):
    """The preset's system prompt, and the library of saved ones."""

    def __init__(self, parent):
        super().__init__(parent)
        self.SetName("System Prompt")
        self.library = PromptLibrary()

        self.saved = wx.ListBox(self, choices=self.library.names(), style=wx.LB_SINGLE)
        self.saved.SetName("Saved Prompts")
        self.saved.SetToolTip("Choose a saved prompt to copy it into the text below.")
        self.text = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self.text.SetName("System Prompt")
        self.text.SetToolTip("The system prompt this preset sends.")

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (
            ("Ne&w", self.on_new),
            ("Sa&ve", self.on_save),
            ("De&lete", self.on_delete),
            ("Download&&Update Awesome ChatGPT Prompts", self.on_update),
        ):
            button = wx.Button(self, label=label)
            button.SetName(label.replace("&", ""))
            button.Bind(wx.EVT_BUTTON, handler)
            buttons.Add(button, flag=wx.ALL, border=5)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(
            wx.StaticText(self, label="Saved &Prompts:"), flag=wx.LEFT | wx.TOP, border=5
        )
        sizer.Add(self.saved, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        sizer.Add(wx.StaticText(self, label="&System Prompt:"), flag=wx.LEFT, border=5)
        sizer.Add(self.text, proportion=2, flag=wx.EXPAND | wx.ALL, border=5)
        sizer.Add(buttons, flag=wx.ALIGN_CENTER)
        self.SetSizer(sizer)

        self.saved.Bind(wx.EVT_LISTBOX, self.on_selected)

    def load(self, name, preset):
        self.text.SetValue(preset.system)
        found = self.library.find(preset.system)
        if found is not None:
            self.saved.SetSelection(found)

    def save_into(self, preset):
        preset.system = self.text.GetValue()

    def on_selected(self, event):
        selection = self.saved.GetSelection()
        if selection != wx.NOT_FOUND:
            self.text.SetValue(self.library.prompts[selection].text)

    def _refresh(self, select=None):
        self.saved.Set(self.library.names())
        if select is not None:
            self.saved.SetSelection(select)

    def on_new(self, event):
        name = wx.GetTextFromUser("Enter new name:", "New")
        if not name:
            return
        self._do(lambda: self._refresh(self.library.put(name, self.text.GetValue())))

    def on_save(self, event):
        selection = self.saved.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        name = self.library.prompts[selection].name
        self._do(lambda: self._refresh(self.library.put(name, self.text.GetValue())))

    def on_delete(self, event):
        selection = self.saved.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        name = self.saved.GetStringSelection()
        if wx.MessageBox(
            f"Are you sure you want to delete {name}?",
            "Delete",
            wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        self._do(lambda: (self.library.remove(selection), self._refresh()))

    def on_update(self, event):
        def run():
            self.library.merge(fetch_shared())
            self._refresh()
            show_info("Prompts", "Prompts updated successfully.")

        self._do(run)

    @staticmethod
    def _do(action):
        try:
            action()
        except VOLlamaError as e:
            show_error(e, "Prompts")


class PresetDialog(wx.Dialog):
    """Edits a copy of one preset across three pages."""

    def __init__(self, parent, title, name="", preset=None, page=CONNECTION_PAGE):
        super().__init__(parent, title=title, size=(700, 560))
        self._name = name
        self._preset = copy.deepcopy(preset) if preset else Preset(base_url=STARTING_URL)

        panel = wx.Panel(self)
        self.notebook = wx.Notebook(panel)
        self.notebook.SetName("Preset Pages")
        self.connection = ConnectionPage(self.notebook)
        self.parameters = ParametersPage(self.notebook)
        self.prompt = PromptPage(self.notebook)
        self.notebook.AddPage(self.connection, "Connection")
        self.notebook.AddPage(self.parameters, "Parameters")
        self.notebook.AddPage(self.prompt, "System Prompt")
        for page_panel in self._pages():
            page_panel.load(self._name, self._preset)

        panel_sizer = wx.BoxSizer(wx.VERTICAL)
        panel_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(panel_sizer)

        # CreateStdDialogButtonSizer parents its buttons to the dialog, so the
        # sizer holding it has to be the dialog's and not the panel's.
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, 1, wx.EXPAND)
        sizer.Add(buttons, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        self.SetSizer(sizer)

        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.notebook.SetSelection(page)
        self.connection.fields["name"].SetFocus()

    def _pages(self):
        return (self.connection, self.parameters, self.prompt)

    def name(self):
        return self._name

    def preset(self):
        return self._preset

    def on_ok(self, event):
        name = self.connection.fields["name"].GetValue().strip()
        if not name:
            self._invalid("Enter a name for this preset.", "name", CONNECTION_PAGE)
            return
        try:
            for page_panel in self._pages():
                page_panel.save_into(self._preset)
        except ValueError as e:
            self._invalid(f"A parameter value is not valid: {e}", None, PARAMETERS_PAGE)
            return
        try:
            # The same rule the chat applies, so a preset that saves is a preset
            # that works.
            self._preset.validate()
        except ConfigError as e:
            field = "model" if "model" in str(e) else "base_url"
            self._invalid(str(e), field, CONNECTION_PAGE)
            return
        self._name = name
        self.EndModal(wx.ID_OK)

    def _invalid(self, message, field, page):
        self.notebook.SetSelection(page)
        if page == CONNECTION_PAGE:
            self.connection.set_status(message)
            if field:
                self.connection.fields[field].SetFocus()
        wx.MessageBox(message, "Preset", wx.OK | wx.ICON_ERROR)
