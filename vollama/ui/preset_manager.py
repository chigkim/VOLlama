"""Managing presets: the preset button, and the pages editing one preset.

One dialog. The toolbar's own preset button, whose menu switches preset and
holds New, Duplicate and Delete, above four notebook pages editing whichever
preset the button names — connection, parameters, retrieval, system prompt;
each page knows how to fill itself from a `Preset` and how to write itself
back into one. Everything else about presets — whether a name is free, whether
the preset can be used, where it is stored, which one becomes active when
another is deleted — belongs to `config.presets`, and this dialog calls into it
rather than deciding again.

Edits go into copies, so Cancel discards them all. `ShowModal()` returning
`wx.ID_OK` means the presets have already been saved.
"""

import copy
import functools
import threading

import wx

from vollama.chat.client import fetch_models
from vollama.config import parameters, presets
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

# The connection page's place in the notebook, since it is the page a refusal
# about the preset's name or its URL and model belongs on.
CONNECTION_PAGE = 0


class Invalid(Exception):
    """What a page says when what is on it cannot be written to a preset.

    The message is already worded for the user, and `control` is the field that
    fixes it, so the dialog can put the focus there without knowing which page
    raised or what it holds.
    """

    def __init__(self, message, control=None):
        super().__init__(message)
        self.control = control


def labelled(panel, grid, row, label, make, tip):
    """Add one labelled control to `grid`, and hand the control back.

    `make` is what builds the control, rather than the control itself, because
    a screen reader on Windows pairs a field with the static text created
    before it and not with the one the sizer puts to its left. Every field here
    used to be constructed as an argument, so each was announced with the label
    of the row above: the Base URL box read as "Name".
    """
    grid.Add(
        wx.StaticText(panel, label=label + ":"),
        pos=(row, 0),
        flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL,
        border=5,
    )
    control = make(panel)
    control.SetName(label.replace("&", ""))
    control.SetToolTip(tip)
    grid.Add(control, pos=(row, 1), flag=wx.EXPAND | wx.ALL, border=5)
    return control


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
            self.fields[key] = self._row(grid, row, label, wx.TextCtrl, tip)
            row += 1

        self.server_button = self._button(
            grid, BASE_URL_ROW, "&Choose...", "Choose Base URL",
            "Fill in the URL of a server VOLlama already knows about.",
            self.on_server,
        )
        self.fields["model"] = self._row(
            grid, row, "&Model", wx.TextCtrl,
            "Model name as the endpoint reports it. Use Choose to pick from a list.",
        )
        self.choose_button = self._button(
            grid, row, "C&hoose...", "Choose Model",
            "Ask the endpoint which models it offers.", self.on_choose,
        )
        row += 1

        self.fields["context_window"] = self._row(
            grid, row, "Context &Window",
            functools.partial(
                wx.SpinCtrl, min=512, max=10_000_000, initial=DEFAULT_CONTEXT_WINDOW
            ),
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

    def _row(self, grid, row, label, make, tip):
        return labelled(self, grid, row, label, make, tip)

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

    A control per entry in the parameter schema, so a parameter added to the
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
                continue
            try:
                self.parameters[key]["value"] = parameters.parse_value(
                    key, control.GetValue(), self.parameters[key]["value"]
                )
            except ValueError as e:
                raise Invalid(f"A parameter value is not valid: {e}", control) from None
        preset.parameters = self.parameters


class RetrievalPage(wx.Panel):
    """The embedding endpoint this preset uses, and how much it retrieves.

    A preset field rather than a global one because a preset is a server: the
    endpoint serving the chat model is usually the one serving the embedding
    model. Switching preset does not re-embed an index that is already built;
    see `rag.index.RagIndex._configure`.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.SetName("RAG")
        grid = wx.GridBagSizer(5, 5)
        row = 0

        self.embedding_base_url = self._text(
            grid, row, "Embedding Base &URL",
            "OpenAI-compatible endpoint that serves the embedding model.",
        )
        row += 1
        self.embedding_api_key = self._text(
            grid, row, "Embedding API &Key",
            "Leave empty if the embedding endpoint does not need one.",
        )
        row += 1
        self.embedding_model = self._text(
            grid, row, "Embedding &Model",
            "The embedding model's name. Changing it after indexing means the "
            "index has to be built again, since old and new vectors are not "
            "comparable.",
        )
        row += 1
        self.chunk_size = self._spin(
            grid, row, "Chunk &Size", 1, 1_000_000,
            "How much text goes into one indexed chunk. Smaller chunks make "
            "retrieval more precise and lose more surrounding context.",
        )
        row += 1
        self.chunk_overlap = self._spin(
            grid, row, "Chunk &Overlap", 0, 1000,
            "How much of each chunk repeats the one before it, so a sentence "
            "split across the boundary is still findable.",
        )
        row += 1
        self.similarity_top_k = self._spin(
            grid, row, "Similarity &Top K", 1, 100,
            "How many chunks to retrieve for a question.",
        )
        row += 1
        # A plain text box, so the fraction can be typed as 0.35 and read back
        # as one. `wx.SpinCtrlDouble` spares the parsing at the price of the
        # field's name: it is generic on every platform, a container holding a
        # text control and a spin button, and the name belongs to the container
        # while the focus lands on the text control inside — so it was the one
        # field a screen reader announced without its label, and naming the
        # inner control did not fix it.
        self.similarity_cutoff = self._text(
            grid, row, "Similarity &Cutoff",
            "The lowest similarity score a chunk may have and still be used, "
            "between 0 and 1. 0 keeps every chunk Top K returned.",
        )
        row += 1

        grid.AddGrowableCol(1)
        self.SetSizer(grid)

    def _text(self, grid, row, label, tip):
        return labelled(self, grid, row, label, wx.TextCtrl, tip)

    def _spin(self, grid, row, label, low, high, tip):
        return labelled(
            self,
            grid,
            row,
            label,
            functools.partial(wx.SpinCtrl, min=low, max=high),
            tip,
        )

    def load(self, name, preset):
        self.embedding_base_url.SetValue(preset.embedding_base_url)
        self.embedding_api_key.SetValue(preset.embedding_api_key)
        self.embedding_model.SetValue(preset.embedding_model)
        self.chunk_size.SetValue(preset.chunk_size)
        self.chunk_overlap.SetValue(preset.chunk_overlap)
        self.similarity_top_k.SetValue(preset.similarity_top_k)
        self.similarity_cutoff.SetValue(str(preset.similarity_cutoff))

    def save_into(self, preset):
        preset.similarity_cutoff = self._cutoff()
        preset.embedding_base_url = self.embedding_base_url.GetValue().strip()
        preset.embedding_api_key = self.embedding_api_key.GetValue().strip()
        preset.embedding_model = self.embedding_model.GetValue().strip()
        preset.chunk_size = self.chunk_size.GetValue()
        preset.chunk_overlap = self.chunk_overlap.GetValue()
        preset.similarity_top_k = self.similarity_top_k.GetValue()

    def _cutoff(self):
        """The similarity cutoff as typed. Raises Invalid if it is not a score."""
        text = self.similarity_cutoff.GetValue().strip()
        try:
            value = float(text)
        except ValueError:
            raise Invalid(
                f"{text!r} is not a number.", self.similarity_cutoff
            ) from None
        if not 0.0 <= value <= 1.0:
            raise Invalid(
                "The similarity cutoff has to be between 0 and 1.",
                self.similarity_cutoff,
            )
        return value


class PromptPage(wx.Panel):
    """The preset's system prompt, and the library of saved ones."""

    def __init__(self, parent):
        super().__init__(parent)
        self.SetName("System Prompt")
        self.library = PromptLibrary()

        # Each label is created before the control it names, since that order is
        # what pairs the two for a screen reader. See ConnectionPage._row.
        saved_label = wx.StaticText(self, label="Saved &Prompts:")
        self.saved = wx.ListBox(self, choices=self.library.names(), style=wx.LB_SINGLE)
        self.saved.SetName("Saved Prompts")
        self.saved.SetToolTip(
            "Choose a saved prompt to copy it into the text below. Enter copies "
            "the highlighted one again."
        )
        text_label = wx.StaticText(self, label="&System Prompt:")
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
        sizer.Add(saved_label, flag=wx.LEFT | wx.TOP, border=5)
        sizer.Add(self.saved, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        sizer.Add(text_label, flag=wx.LEFT, border=5)
        sizer.Add(self.text, proportion=2, flag=wx.EXPAND | wx.ALL, border=5)
        sizer.Add(buttons, flag=wx.ALIGN_CENTER)
        self.SetSizer(sizer)

        self.saved.Bind(wx.EVT_LISTBOX, self.on_selected)
        # Choosing the prompt that is already highlighted fires no selection
        # event, so Enter and a double click mean "use this one" as well.
        self.saved.Bind(wx.EVT_LISTBOX_DCLICK, self.on_selected)
        self.saved.Bind(wx.EVT_KEY_DOWN, self.on_key)

    def load(self, name, preset):
        self.text.SetValue(preset.system)
        # Cleared when this preset's prompt is not one of the saved ones, rather
        # than left highlighting the last preset's: a highlight that no longer
        # matches the box is both wrong and a dead end, since choosing that same
        # prompt again fires no selection event.
        found = self.library.find(preset.system)
        self.saved.SetSelection(wx.NOT_FOUND if found is None else found)

    def save_into(self, preset):
        preset.system = self.text.GetValue()

    def on_selected(self, event):
        selection = self.saved.GetSelection()
        if selection != wx.NOT_FOUND:
            self.text.SetValue(self.library.prompts[selection].text)

    def on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            # Not skipped: Enter left to the dialog presses OK and closes it.
            self.on_selected(event)
            return
        event.Skip()

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


class Entry:
    """One preset as the manager holds it while being edited: a name and a copy."""

    def __init__(self, name, preset):
        self.name = name
        self.preset = preset


class PresetManager(wx.Dialog):
    """Every preset, behind the same one button the toolbar uses.

    The button says which preset the pages below it are showing, and its menu
    is the one that used to be on the toolbar: the presets to switch between,
    then New, Duplicate and Delete. One widget, in the place where the preset
    it names can actually be edited; the toolbar menu keeps only the switching,
    which is the part worth a keystroke.

    Nothing is written until OK. Edits live on `Entry` copies of the presets, so
    Cancel discards them and a delete is just an entry dropped from the list;
    OK hands the whole list to `presets.replace`, which is where storing them
    and choosing the active one is decided.
    """

    def __init__(self, parent, select=None):
        super().__init__(parent, title="Preset Manager", size=(760, 600))
        self.entries = [Entry(name, presets.get(name)) for name in presets.names()]
        self.index = None

        panel = wx.Panel(self)
        self.preset_button = wx.Button(panel, label="Preset: none")
        # The toolbar button's accessible name, because it is the same control
        # doing the same job.
        self.preset_button.SetName("Preset")
        self.preset_button.SetToolTip(
            "The preset the pages below are editing. Its menu switches between "
            "your presets and creates, copies and deletes them."
        )
        self.preset_button.Bind(wx.EVT_BUTTON, self.on_menu)

        self.notebook = wx.Notebook(panel)
        self.notebook.SetName("Preset Pages")
        self.connection = ConnectionPage(self.notebook)
        self.parameters = ParametersPage(self.notebook)
        self.prompt = PromptPage(self.notebook)
        self.retrieval = RetrievalPage(self.notebook)
        self.notebook.AddPage(self.connection, "Connection")
        self.notebook.AddPage(self.parameters, "Parameters")
        self.notebook.AddPage(self.prompt, "System Prompt")
        # Named for the menu it belongs with, since the Rag menu's items act
        # on what this page configures.
        self.notebook.AddPage(self.retrieval, "RAG")
        self.connection.fields["name"].Bind(wx.EVT_KILL_FOCUS, self.on_renamed)

        body = wx.BoxSizer(wx.VERTICAL)
        body.Add(self.preset_button, 0, wx.ALL, 5)
        body.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(body)

        # CreateStdDialogButtonSizer parents its buttons to the dialog, so the
        # sizer holding it has to be the dialog's and not the panel's.
        std = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, 1, wx.EXPAND)
        sizer.Add(std, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        self.SetSizer(sizer)

        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)

        if not self.entries:
            # Nothing to manage yet, so the manager opens on the one thing
            # there is to do.
            self.on_new(None)
            return
        labels = self._labels()
        self._show(labels.index(select) if select in labels else 0)
        self.preset_button.SetFocus()

    def name(self):
        """The name of the preset the manager was left on, or ""."""
        return self.entries[self.index].name if self.index is not None else ""

    def _labels(self):
        return [entry.name for entry in self.entries]

    # -------------------------------------------------------------- the pages

    def _pages(self):
        """The pages in the order the notebook shows them.

        In that order because `_collect` reports a refusal by its position
        here, and the dialog then selects that tab.
        """
        return (self.connection, self.parameters, self.prompt, self.retrieval)

    def _show(self, index):
        """Put entry `index` on the pages and name it on the button."""
        self.index = index
        entry = self.entries[index]
        self._label()
        for page in self._pages():
            page.load(entry.name, entry.preset)

    def _label(self):
        self.preset_button.SetLabel(f"Preset: {self.name() or 'none'}")

    def _collect(self):
        """Read the pages back into the shown entry, or say why they cannot be.

        Returns None when the entry is valid, or a (message, control, page)
        triple naming what is wrong and where it is fixed. The page that cannot
        save says so itself, since it is the one that knows which of its own
        fields the focus belongs in. The rule about whether a preset is usable
        is the chat's own, so a preset that saves here is a preset that works.
        """
        if self.index is None:
            return None
        entry = self.entries[self.index]
        field = self.connection.fields["name"]
        name = field.GetValue().strip()
        if not name:
            return "Enter a name for this preset.", field, CONNECTION_PAGE
        if name in self._others():
            return f"A preset named {name} already exists.", field, CONNECTION_PAGE
        for number, page in enumerate(self._pages()):
            try:
                page.save_into(entry.preset)
            except Invalid as e:
                return str(e), e.control, number
        try:
            entry.preset.validate()
        except ConfigError as e:
            key = "model" if "model" in str(e) else "base_url"
            return str(e), self.connection.fields[key], CONNECTION_PAGE
        entry.name = name
        self._label()
        return None

    def _others(self):
        """The names of the presets other than the one being shown."""
        return [e.name for i, e in enumerate(self.entries) if i != self.index]

    def _refuse(self, problem):
        """Say what is wrong, put the focus where it is fixed, and stay put."""
        message, control, page = problem
        self.notebook.SetSelection(page)
        if page == CONNECTION_PAGE:
            self.connection.set_status(message)
        wx.MessageBox(message, "Preset", wx.OK | wx.ICON_ERROR)
        if control:
            control.SetFocus()

    def on_renamed(self, event):
        """Keep the button in step with the name box on leaving it.

        A rename is the one edit the button itself shows, and a button still
        saying the old name lies about which preset is being edited. Only the
        name is taken here: a new preset must not be refused for its base URL
        merely because the focus moved out of a field.
        """
        event.Skip()
        name = self.connection.fields["name"].GetValue().strip()
        if self.index is not None and name and name not in self._others():
            self.entries[self.index].name = name
            self._label()

    # --------------------------------------------------------------- the menu

    def on_menu(self, event):
        """The toolbar's preset menu, with the editing items it used to have."""
        menu = wx.Menu()
        for index, entry in enumerate(self.entries):
            item = menu.Append(wx.NewIdRef(), entry.name, kind=wx.ITEM_CHECK)
            item.Check(index == self.index)
            self.Bind(
                wx.EVT_MENU, functools.partial(self.on_choose, index=index), item
            )
        if self.entries:
            menu.AppendSeparator()
        for label, handler, needs_preset in (
            ("&New", self.on_new, False),
            ("D&uplicate", self.on_duplicate, True),
            ("&Delete...", self.on_delete, True),
        ):
            item = menu.Append(wx.NewIdRef(), label)
            self.Bind(wx.EVT_MENU, handler, item)
            if needs_preset:
                item.Enable(self.index is not None)
        self.preset_button.PopupMenu(menu)
        menu.Destroy()

    def on_choose(self, event, index):
        if index == self.index:
            return
        problem = self._collect()
        if problem:
            self._refuse(problem)
            return
        self._show(index)
        # Focus follows the value that changed, which here is the button's own
        # label: every page behind it has just been refilled from it.
        self.preset_button.SetFocus()

    def on_new(self, event, preset=None, name="New Preset"):
        # Called with no event to add a copy or the first preset, neither of
        # which can be refused for what is on the pages.
        if event is not None:
            problem = self._collect()
            if problem:
                self._refuse(problem)
                return
        entry = Entry(self._free(name), preset or Preset(base_url=STARTING_URL))
        self.entries.append(entry)
        self._show(len(self.entries) - 1)
        self.connection.fields["name"].SetFocus()
        self.connection.fields["name"].SelectAll()

    def on_duplicate(self, event):
        problem = self._collect()
        if problem:
            self._refuse(problem)
            return
        entry = self.entries[self.index]
        self.on_new(None, copy.deepcopy(entry.preset), f"{entry.name} copy")

    def on_delete(self, event):
        if self.index is None:
            return
        entry = self.entries[self.index]
        if wx.MessageBox(
            f"Delete the preset {entry.name}?",
            "Delete Preset",
            wx.YES_NO | wx.ICON_WARNING,
        ) != wx.YES:
            return
        self.entries.pop(self.index)
        self.index = None
        if self.entries:
            self._show(0)
            self.preset_button.SetFocus()
            return
        # Nothing left to edit: the pages are emptied rather than left showing
        # a preset that is gone.
        self._label()
        for page in self._pages():
            page.load("", Preset())
        self.connection.set_status("No presets. Choose New to create one.")
        self.preset_button.SetFocus()

    def _free(self, name):
        """`name`, or the first numbered variant of it that is not taken."""
        taken = self._labels()
        if name not in taken:
            return name
        number = 2
        while f"{name} {number}" in taken:
            number += 1
        return f"{name} {number}"

    # ----------------------------------------------------------------- saving

    def on_ok(self, event):
        problem = self._collect()
        if problem:
            self._refuse(problem)
            return
        try:
            # The preset the manager was left on is the one the user means to
            # end up on, so it is the one that becomes active.
            presets.replace(
                [(entry.name, entry.preset) for entry in self.entries], self.name()
            )
        except VOLlamaError as e:
            show_error(e, "Preset")
            return
        self.EndModal(wx.ID_OK)
