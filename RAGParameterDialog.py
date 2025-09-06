from Settings import settings
import wx


class RAGParameterDialog(wx.Dialog):
    def __init__(self, parent, title):
        super().__init__(parent, title=title, size=(400, 420))

        self.panel = wx.Panel(self)
        self.grid_sizer = wx.GridBagSizer(
            5, 5
        )  # Specify vertical and horizontal gap between widgets

        # Define parameters and their tooltips
        self.parameters = {
            "chunk_size": {
                "label": "Chunk Size",
                "control": "SpinCtrl",
                "min": 1,
                "max": int(settings.parameters["num_ctx"]["value"] / 2),
                "initial": settings.chunk_size,
                "tooltip": "Defines the size of text chunks for indexing. Smaller sizes may improve search granularity.",
            },
            "chunk_overlap": {
                "label": "Chunk Overlap",
                "control": "SpinCtrl",
                "min": 0,
                "max": 100,
                "initial": settings.chunk_overlap,
                "tooltip": "Overlap between chunks to ensure continuity in search results.",
            },
            "similarity_top_k": {
                "label": "Similarity Top K",
                "control": "SpinCtrl",
                "min": 1,
                "max": 100,
                "initial": settings.similarity_top_k,
                "tooltip": "The number of top results to consider when evaluating similarity.",
            },
            "similarity_cutoff": {
                "label": "Similarity Cutoff",
                "control": "SpinCtrlDouble",
                "min": 0.0,
                "max": 1.0,
                "inc": 0.01,
                "initial": settings.similarity_cutoff,
                "tooltip": "The minimum similarity score for a result to be considered relevant.",
            },
            "response_mode": {
                "label": "Response Mode",
                "control": "Choice",
                "choices": [
                    "refine",
                    "compact",
                    "tree_summarize",
                    "simple_summarize",
                    "accumulate",
                    "compact_accumulate",
                ],
                "initial": settings.response_mode,
                "tooltip": "Determines how the indexed results are processed and presented.",
            },
            "show_context": {
                "label": "Show Context",
                "control": "CheckBox",
                "initial": settings.show_context,
                "tooltip": "Toggle to show or hide additional context related to your query.",
            },
            "embedding_model": {
                "label": "Embedding Model",
                "control": "TextCtrl",
                "initial": getattr(settings, "embedding_model", ""),
                "tooltip": "Name of the embedding model to use.",
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
        elif control == "TextCtrl":
            widget = wx.TextCtrl(self.panel, value=str(kwargs["initial"]))
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
        else:
            raise ValueError("Unsupported control type")

        # Set tooltip
        widget.SetToolTip(kwargs["tooltip"])
        widget.SetName(label)
        self.controls[name] = widget
        self.grid_sizer.Add(widget, pos=(row, 1), flag=wx.EXPAND | wx.ALL, border=5)

    def on_ok(self, event):
        for key, widget in self.controls.items():
            if isinstance(widget, wx.Choice):
                value = widget.GetStringSelection()
            else:
                value = widget.GetValue()
            setattr(settings, key, value)
        self.Close()
