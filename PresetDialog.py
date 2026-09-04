import copy
import io
import os
import threading

import pandas as pd
import requests
import wx

from Parameters import parse_value, reconcile
from Settings import DEFAULT_CONTEXT_WINDOW, config_dir, preset_template


# Endpoints people actually point VOLlama at, so a new preset is a pick and a
# key rather than a URL typed from memory. Not a provider list: every one of
# these is the same OpenAI-compatible path, and anything not here still works by
# typing it.
SERVERS = [
    ("OpenAI", "https://api.openai.com/v1/"),
    ("Anthropic", "https://api.anthropic.com/v1/"),
    ("Google", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ("OpenRouter", "https://openrouter.ai/api/v1/"),
    ("Ollama", "http://localhost:11434/v1/"),
    ("llama.cpp", "http://localhost:8080/v1/"),
    ("OMLX", "http://localhost:8000/v1/"),
]


class ConnectionPage(wx.Panel):
    """Base URL, API key, model and context window for one preset."""

    def __init__(self, parent):
        super().__init__(parent)
        self.SetName("Connection")
        sizer = wx.GridBagSizer(5, 5)
        self.fields = {}

        rows = [
            ("name", "&Name", "A label for this preset, shown on the toolbar."),
            (
                "base_url",
                "&Base URL",
                "OpenAI-compatible endpoint, for example http://localhost:11434/v1/ for Ollama.",
            ),
            ("api_key", "API &Key", "Leave empty if the endpoint does not need one."),
        ]
        row = 0
        for key, label, tooltip in rows:
            sizer.Add(
                wx.StaticText(self, label=label + ":"),
                pos=(row, 0),
                flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL,
                border=5,
            )
            ctrl = wx.TextCtrl(self)
            ctrl.SetName(label.replace("&", ""))
            ctrl.SetToolTip(tooltip)
            self.fields[key] = ctrl
            sizer.Add(ctrl, pos=(row, 1), flag=wx.EXPAND | wx.ALL, border=5)
            if key == "base_url":
                self.server_button = wx.Button(self, label="&Choose...")
                # Same label as the model's button, a different accessible name:
                # two buttons announced as "Choose" would be indistinguishable.
                self.server_button.SetName("Choose Base URL")
                self.server_button.SetToolTip(
                    "Fill in the URL of a server VOLlama already knows about."
                )
                self.server_button.Bind(wx.EVT_BUTTON, self.on_server)
                sizer.Add(self.server_button, pos=(row, 2), flag=wx.ALL, border=5)
            row += 1

        sizer.Add(
            wx.StaticText(self, label="&Model:"),
            pos=(row, 0),
            flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL,
            border=5,
        )
        self.fields["model"] = wx.TextCtrl(self)
        self.fields["model"].SetName("Model")
        self.fields["model"].SetToolTip(
            "Model name as the endpoint reports it. Use Choose to pick from a list."
        )
        sizer.Add(self.fields["model"], pos=(row, 1), flag=wx.EXPAND | wx.ALL, border=5)
        self.choose_button = wx.Button(self, label="C&hoose...")
        self.choose_button.SetName("Choose Model")
        self.choose_button.SetToolTip("Ask the endpoint which models it offers.")
        self.choose_button.Bind(wx.EVT_BUTTON, self.on_choose)
        sizer.Add(self.choose_button, pos=(row, 2), flag=wx.ALL, border=5)
        row += 1

        sizer.Add(
            wx.StaticText(self, label="Context &Window:"),
            pos=(row, 0),
            flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL,
            border=5,
        )
        self.fields["context_window"] = wx.SpinCtrl(
            self, min=512, max=10000000, initial=DEFAULT_CONTEXT_WINDOW
        )
        self.fields["context_window"].SetName("Context Window")
        self.fields["context_window"].SetToolTip(
            "How many tokens this model can hold. Match what your server is "
            "running. It is not sent to the server: VOLlama uses it to decide "
            "when to compact the conversation, and to size RAG prompts."
        )
        sizer.Add(
            self.fields["context_window"], pos=(row, 1), flag=wx.EXPAND | wx.ALL, border=5
        )
        row += 1

        self.status = wx.StaticText(self, label="Status: Ready")
        self.status.SetName("Status")
        sizer.Add(self.status, pos=(row, 0), span=(1, 3), flag=wx.ALL, border=5)

        sizer.AddGrowableCol(1)
        self.SetSizer(sizer)

    def setStatus(self, text):
        self.status.SetLabel(f"Status: {text}")

    def load(self, name, preset):
        self.fields["name"].SetValue(name)
        self.fields["base_url"].SetValue(preset.get("base_url", ""))
        self.fields["api_key"].SetValue(preset.get("api_key", ""))
        self.fields["model"].SetValue(preset.get("model", ""))
        try:
            window = int(preset.get("context_window") or DEFAULT_CONTEXT_WINDOW)
        except (TypeError, ValueError):
            window = DEFAULT_CONTEXT_WINDOW
        self.fields["context_window"].SetValue(window)

    def save_into(self, preset):
        preset["base_url"] = self.fields["base_url"].GetValue().strip()
        preset["api_key"] = self.fields["api_key"].GetValue().strip()
        preset["model"] = self.fields["model"].GetValue().strip()
        preset["context_window"] = self.fields["context_window"].GetValue()

    def on_server(self, event):
        """Pick a known endpoint. Only the URL is filled in, never the key.

        Focus goes back to the URL field rather than staying on the button, since
        the value it announces is the thing that just changed.
        """
        labels = [f"{name} - {url}" for name, url in SERVERS]
        with wx.SingleChoiceDialog(self, "Choose a server:", "Servers", labels) as dlg:
            dlg.SetName("Server List")
            if dlg.ShowModal() != wx.ID_OK:
                return
            name, url = SERVERS[dlg.GetSelection()]
        self.fields["base_url"].SetValue(url)
        self.setStatus(f"Base URL set to {name}. Enter an API key if it needs one.")
        self.fields["base_url"].SetFocus()

    def on_choose(self, event):
        base_url = self.fields["base_url"].GetValue().strip()
        if not base_url:
            self.setStatus("Enter a base URL first.")
            self.fields["base_url"].SetFocus()
            return
        api_key = self.fields["api_key"].GetValue().strip()
        self.choose_button.Enable(False)
        self.setStatus("Fetching models...")
        threading.Thread(
            target=self.fetch, args=(base_url, api_key), daemon=True
        ).start()

    def fetch(self, base_url, api_key):
        # Worker thread: never touch wx from here.
        from Model import fetch_models

        try:
            models = fetch_models(base_url, api_key)
        except Exception as e:
            wx.CallAfter(self.fetch_failed, str(e))
            return
        wx.CallAfter(self.fetch_done, models)

    def fetch_failed(self, message):
        self.choose_button.Enable(True)
        self.setStatus(f"Could not fetch models. {message}")
        self.choose_button.SetFocus()

    def fetch_done(self, models):
        self.choose_button.Enable(True)
        if not models:
            self.setStatus(
                "This endpoint does not provide a model list. Type the model name."
            )
            self.fields["model"].SetFocus()
            return
        self.setStatus(f"Found {len(models)} models.")
        with wx.SingleChoiceDialog(self, "Choose a model:", "Models", models) as dlg:
            dlg.SetName("Model List")
            current = self.fields["model"].GetValue().strip()
            if current in models:
                dlg.SetSelection(models.index(current))
            if dlg.ShowModal() == wx.ID_OK:
                self.fields["model"].SetValue(dlg.GetStringSelection())
        self.fields["model"].SetFocus()


class ParametersPage(wx.Panel):
    """Generation parameters, built from the preset's parameter schema."""

    def __init__(self, parent):
        super().__init__(parent)
        self.SetName("Parameters")
        self.controls = {}
        self.parameters = {}
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.scroll_area = wx.ScrolledWindow(self)
        self.scroll_area.SetScrollbars(1, 1, 1, 1)
        self.scroll_sizer = wx.BoxSizer(wx.VERTICAL)
        self.scroll_area.SetSizer(self.scroll_sizer)
        self.sizer.Add(self.scroll_area, 1, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(self.sizer)

    def load(self, name, preset):
        self.parameters = reconcile(preset.setdefault("parameters", {}))
        self.scroll_sizer.Clear(True)
        self.controls = {}
        for key, val in self.parameters.items():
            hbox = wx.BoxSizer(wx.HORIZONTAL)
            label = wx.StaticText(
                self.scroll_area, label=key.replace("_", " ").capitalize() + ":"
            )
            hbox.Add(label, 0, wx.ALL | wx.CENTER, 5)

            value = val["value"]
            if isinstance(value, bool):
                ctrl = wx.CheckBox(self.scroll_area)
                ctrl.SetValue(value)
            elif value is None:
                ctrl = wx.TextCtrl(self.scroll_area, value="")
            elif isinstance(value, list):
                ctrl = wx.TextCtrl(self.scroll_area, value=", ".join(value))
            else:
                ctrl = wx.TextCtrl(self.scroll_area, value=str(value))
            ctrl.SetName(key)
            ctrl.SetToolTip(f"Hint: {val['description']} Range: {val['range']}")
            self.controls[key] = ctrl
            hbox.Add(ctrl, 1, wx.EXPAND | wx.ALL, 5)
            self.scroll_sizer.Add(hbox, 0, wx.EXPAND)
        self.scroll_area.Layout()
        self.scroll_area.FitInside()

    def save_into(self, preset):
        for key, ctrl in self.controls.items():
            if isinstance(ctrl, wx.CheckBox):
                self.parameters[key]["value"] = ctrl.IsChecked()
            else:
                self.parameters[key]["value"] = parse_value(
                    key, ctrl.GetValue().strip(), self.parameters[key]["value"]
                )
        preset["parameters"] = self.parameters


class PromptPage(wx.Panel):
    """The preset's system prompt, plus the shared prompt library."""

    def __init__(self, parent):
        super().__init__(parent)
        self.SetName("System Prompt")
        self.prompt_file = config_dir() / "prompts.csv"
        if os.path.exists(self.prompt_file):
            self.prompt_data = pd.read_csv(self.prompt_file)
            self.prompt_data = self.prompt_data.sort_values(by="act").reset_index(
                drop=True
            )
        else:
            self.prompt_data = pd.DataFrame(columns=["act", "prompt"])

        self.act_list = wx.ListBox(
            self, choices=self.prompt_data["act"].tolist(), style=wx.LB_SINGLE
        )
        self.act_list.SetName("Saved Prompts")
        self.act_list.SetToolTip("Choose a saved prompt to copy it into the text below.")
        self.prompt_text = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self.prompt_text.SetName("System Prompt")
        self.prompt_text.SetToolTip("The system prompt this preset sends.")
        self.new_button = wx.Button(self, label="Ne&w")
        self.save_button = wx.Button(self, label="Sa&ve")
        self.delete_button = wx.Button(self, label="De&lete")
        self.update_button = wx.Button(
            self, label="Download&&Update Awesome ChatGPT Prompts"
        )
        for button in (
            self.new_button,
            self.save_button,
            self.delete_button,
            self.update_button,
        ):
            button.SetName(button.GetLabel().replace("&", ""))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(
            wx.StaticText(self, label="Saved &Prompts:"), flag=wx.LEFT | wx.TOP, border=5
        )
        sizer.Add(self.act_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        sizer.Add(
            wx.StaticText(self, label="&System Prompt:"), flag=wx.LEFT, border=5
        )
        sizer.Add(self.prompt_text, proportion=2, flag=wx.EXPAND | wx.ALL, border=5)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(self.new_button, flag=wx.ALL, border=5)
        buttons.Add(self.save_button, flag=wx.ALL, border=5)
        buttons.Add(self.delete_button, flag=wx.ALL, border=5)
        buttons.Add(self.update_button, flag=wx.ALL, border=5)
        sizer.Add(buttons, flag=wx.ALIGN_CENTER)
        self.SetSizer(sizer)

        self.act_list.Bind(wx.EVT_LISTBOX, self.on_act_selected)
        self.new_button.Bind(wx.EVT_BUTTON, self.on_new)
        self.save_button.Bind(wx.EVT_BUTTON, self.on_save)
        self.delete_button.Bind(wx.EVT_BUTTON, self.on_delete)
        self.update_button.Bind(wx.EVT_BUTTON, self.on_update)

    def load(self, name, preset):
        prompt = preset.get("system", "")
        self.prompt_text.SetValue(prompt)
        result = self.prompt_data[self.prompt_data["prompt"] == prompt]
        if not result.empty:
            self.act_list.SetSelection(int(result.index[0]))

    def save_into(self, preset):
        preset["system"] = self.prompt_text.GetValue()

    def on_act_selected(self, event):
        selection = self.act_list.GetSelection()
        if selection != wx.NOT_FOUND:
            self.prompt_text.SetValue(self.prompt_data.iloc[selection]["prompt"])

    def refresh_list(self, act=None):
        self.act_list.Set(self.prompt_data["act"].tolist())
        if act is not None:
            indexes = self.prompt_data.index[self.prompt_data["act"] == act].tolist()
            if indexes:
                self.act_list.SetSelection(int(indexes[0]))

    def on_new(self, event):
        act = wx.GetTextFromUser("Enter new name:", "New")
        if not act:
            return
        self.prompt_data = self.prompt_data._append(
            {"act": act, "prompt": self.prompt_text.GetValue()}, ignore_index=True
        )
        self.prompt_data = self.prompt_data.sort_values(by="act").reset_index(drop=True)
        self.prompt_data.to_csv(self.prompt_file, index=False)
        self.refresh_list(act)

    def on_save(self, event):
        selection = self.act_list.GetSelection()
        if selection != wx.NOT_FOUND:
            self.prompt_data.at[selection, "prompt"] = self.prompt_text.GetValue()
            self.prompt_data.to_csv(self.prompt_file, index=False)

    def on_delete(self, event):
        selection = self.act_list.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        with wx.MessageDialog(
            self,
            f"Are you sure you want to delete {self.act_list.GetStringSelection()}?",
            "Delete",
            wx.YES_NO | wx.ICON_QUESTION,
        ) as dlg:
            dlg.SetYesNoLabels("Yes", "No")
            if dlg.ShowModal() == wx.ID_NO:
                return
        self.prompt_data = self.prompt_data.drop(selection).reset_index(drop=True)
        self.prompt_data = self.prompt_data.sort_values(by="act").reset_index(drop=True)
        self.prompt_data.to_csv(self.prompt_file, index=False)
        self.refresh_list()

    def on_update(self, event):
        try:
            url = "https://github.com/f/awesome-chatgpt-prompts/raw/main/prompts.csv"
            response = requests.get(url)
            response.raise_for_status()
            new_prompt_data = pd.read_csv(io.StringIO(response.text))
            combined_data = (
                pd.concat([self.prompt_data, new_prompt_data])
                .drop_duplicates(subset="act", keep="last")
                .reset_index(drop=True)
            )
            self.prompt_data = combined_data.sort_values(by="act").reset_index(
                drop=True
            )
            self.prompt_data.to_csv(self.prompt_file, index=False)
            self.refresh_list()
            wx.MessageBox(
                "Prompts updated successfully.", "Info", wx.OK | wx.ICON_INFORMATION
            )
        except requests.RequestException as e:
            wx.MessageBox(
                f"Failed to update prompts: {e}", "Error", wx.OK | wx.ICON_ERROR
            )


CONNECTION_PAGE = 0
PARAMETERS_PAGE = 1
PROMPT_PAGE = 2


class PresetDialog(wx.Dialog):
    """Edits one preset: connection, generation parameters and system prompt.

    Edits go into a working copy, so Cancel discards everything. Read the
    result with get_name() and get_preset() after ShowModal returns wx.ID_OK.
    """

    def __init__(self, parent, title, name="", preset=None, page=CONNECTION_PAGE):
        super().__init__(parent, title=title, size=(700, 560))
        self.name = name
        self.preset = copy.deepcopy(preset) if preset else preset_template()

        panel = wx.Panel(self)
        self.notebook = wx.Notebook(panel)
        self.notebook.SetName("Preset Pages")
        self.connection = ConnectionPage(self.notebook)
        self.parameters = ParametersPage(self.notebook)
        self.prompt = PromptPage(self.notebook)
        self.notebook.AddPage(self.connection, "Connection")
        self.notebook.AddPage(self.parameters, "Parameters")
        self.notebook.AddPage(self.prompt, "System Prompt")
        for pageObject in (self.connection, self.parameters, self.prompt):
            pageObject.load(self.name, self.preset)

        panel_sizer = wx.BoxSizer(wx.VERTICAL)
        panel_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(panel_sizer)

        # CreateStdDialogButtonSizer parents its buttons to the dialog, so the
        # sizer holding it has to be the dialog's, not the panel's.
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

    def get_name(self):
        return self.name

    def get_preset(self):
        return self.preset

    def invalid(self, message, ctrl):
        self.notebook.SetSelection(CONNECTION_PAGE)
        self.connection.setStatus(message)
        ctrl.SetFocus()
        wx.MessageBox(message, "Preset", wx.OK | wx.ICON_ERROR)

    def on_ok(self, event):
        fields = self.connection.fields
        name = fields["name"].GetValue().strip()
        if not name:
            self.invalid("Enter a name for this preset.", fields["name"])
            return
        if not fields["base_url"].GetValue().strip():
            self.invalid("Enter a base URL.", fields["base_url"])
            return
        try:
            for pageObject in (self.connection, self.parameters, self.prompt):
                pageObject.save_into(self.preset)
        except ValueError as e:
            self.notebook.SetSelection(PARAMETERS_PAGE)
            wx.MessageBox(
                f"A parameter value is not valid: {e}", "Preset", wx.OK | wx.ICON_ERROR
            )
            return
        self.name = name
        self.EndModal(wx.ID_OK)
