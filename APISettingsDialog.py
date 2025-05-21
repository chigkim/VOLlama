from Settings import settings
import wx


class APISettingsDialog(wx.Dialog):
    def __init__(self, parent, title):
        super().__init__(parent, title=title, size=(400, 400))

        self.panel = wx.Panel(self)
        self.grid_sizer = wx.GridBagSizer(
            5, 5
        )  # Specify vertical and horizontal gap between widgets

        # Define parameters and their tooltips
        self.parameters = {
            "llm_name": {
                "label": "LLM",
                "control": "Choice",
                "choices": ["Ollama", "OpenAI", "OpenAILike", "Gemini"],
                "initial": settings.llm_name,
            },
            "base_url": {
                "label": "Base Url",
                "control": "Text",
                "initial": self.get_base_url(),
            },
            "api_key": {
                "label": "API Key",
                "control": "Text",
                "initial": self.get_api_key(),
            },
        }

        self.controls = {}
        row_index = 0
        for key, value in self.parameters.items():
            self.add_parameter_control(row_index, key, **value)
            row_index += 1

        # Add OK and Cancel buttons at the bottom
        ok_button = wx.Button(self.panel, label="OK", id=wx.ID_OK)
        ok_button.Bind(wx.EVT_BUTTON, self.on_ok)
        cancel_button = wx.Button(self.panel, label="Cancel", id=wx.ID_CANCEL)
        self.grid_sizer.Add(ok_button, pos=(row_index, 0), flag=wx.ALL, border=5)
        self.grid_sizer.Add(cancel_button, pos=(row_index, 1), flag=wx.ALL, border=5)

        self.panel.SetSizer(self.grid_sizer)

    def add_parameter_control(self, row, name, label, control, **kwargs):
        label_widget = wx.StaticText(self.panel, label=label)
        self.grid_sizer.Add(
            label_widget, pos=(row, 0), flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=5
        )

        if control == "SpinCtrl":
            widget = wx.SpinCtrl(
                self.panel,
                value=str(kwargs["initial"]),
                min=kwargs["min"],
                max=kwargs["max"],
            )
        elif control == "CheckBox":
            widget = wx.CheckBox(self.panel)
            widget.SetValue(kwargs["initial"])
        elif control == "SpinCtrlDouble":
            widget = wx.SpinCtrlDouble(
                self.panel,
                value=str(kwargs["initial"]),
                min=kwargs["min"],
                max=kwargs["max"],
                inc=kwargs["inc"],
            )
            widget.SetValue(kwargs["initial"])
        elif control == "Choice":
            widget = wx.Choice(self.panel, choices=kwargs["choices"])
            widget.SetStringSelection(kwargs["initial"])
        elif control == "Text":
            widget = wx.TextCtrl(self.panel, value=kwargs["initial"])
        else:
            raise ValueError("Unsupported control type")
        widget.SetName(label)
        if name == "llm_name":
            widget.Bind(wx.EVT_CHOICE, self.onSelectLlm)
        self.controls[name] = widget
        self.grid_sizer.Add(widget, pos=(row, 1), flag=wx.EXPAND | wx.ALL, border=5)

    def on_ok(self, event):
        for key, widget in self.controls.items():
            if isinstance(widget, wx.Choice):
                value = widget.GetStringSelection()
            else:
                value = widget.GetValue()
            if key != "llm":
                key = settings.llm_name + "_" + key
            setattr(settings, key.lower(), value)

        self.Close()

    def get_api_key(self):
        if settings.llm_name == "OpenAI":
            return settings.openai_api_key
        if settings.llm_name == "OpenAILike":
            return settings.openailike_api_key
        elif settings.llm_name == "Gemini":
            return settings.gemini_api_key
        else:
            return "Unused"

    def get_base_url(self):
        if settings.llm_name == "Ollama":
            return settings.ollama_base_url
        if settings.llm_name == "OpenAILike":
            return settings.openailike_base_url
        else:
            return "Unused"

    def onSelectLlm(self, event):
        settings.llm_name = self.controls["llm_name"].GetStringSelection()
        self.controls["api_key"].SetValue(self.get_api_key())
        self.controls["base_url"].SetValue(self.get_base_url())
