import wx
import json
from Settings import settings
import os


class ParametersDialog(wx.Dialog):
    def __init__(self, parent, title):
        super(ParametersDialog, self).__init__(parent, title=title, size=(400, 600))
        get_parameters()
        self.controls = {}  # Store controls here to access them later
        self.InitUI()

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        scroll_area = wx.ScrolledWindow(panel)
        scroll_area.SetScrollbars(1, 1, 1, 1)
        scroll_sizer = wx.BoxSizer(wx.VERTICAL)

        for key, val in settings.parameters.items():
            hbox = wx.BoxSizer(wx.HORIZONTAL)
            label = wx.StaticText(
                scroll_area, label=key.replace("_", " ").capitalize() + ":"
            )
            hbox.Add(label, 0, wx.ALL | wx.CENTER, 5)

            if isinstance(val["value"], bool):
                ctrl = wx.CheckBox(scroll_area)
                ctrl.SetValue(val["value"])
            elif val["value"] is None:
                ctrl = wx.TextCtrl(scroll_area, value="")
            elif isinstance(val["value"], int) or isinstance(val["value"], float):
                ctrl = wx.TextCtrl(scroll_area, value=str(val["value"]))
            else:
                ctrl = wx.TextCtrl(
                    scroll_area,
                    value=(
                        ", ".join(val["value"])
                        if isinstance(val["value"], list)
                        else str(val["value"])
                    ),
                )
            ctrl.SetName(key)  # Use the setting key as the control name
            self.controls[key] = ctrl  # Add control to the dictionary
            hbox.Add(ctrl, 1, wx.EXPAND | wx.ALL, 5)

            # Create a hint string and assign it as a tooltip to the control
            hint = f"Hint: {val['description']} Range: {val['range']}"
            ctrl.SetToolTip(hint)

            scroll_sizer.Add(hbox, 0, wx.EXPAND)

        scroll_area.SetSizer(scroll_sizer)
        vbox.Add(scroll_area, 1, wx.EXPAND | wx.ALL, 10)

        ok_button = wx.Button(panel, label="OK", id=wx.ID_OK)
        cancel_button = wx.Button(panel, label="Cancel", id=wx.ID_CANCEL)
        buttons_hbox = wx.BoxSizer(wx.HORIZONTAL)
        buttons_hbox.Add(ok_button, 0, wx.ALL, 5)
        buttons_hbox.Add(cancel_button, 0, wx.ALL, 5)
        vbox.Add(buttons_hbox, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 10)

        panel.SetSizer(vbox)

    def save(self):
        ints = [
            "num_ctx",
            "num_predict",
            "top_k",
            "repeat_last_n",
            "mirostat",
            "num_keep",
            "seed",
            "num_gpu",
        ]
        floats = [
            "temperature",
            "top_p",
            "min_p",
            "typical_p",
            "tfs_z",
            "repeat_penalty",
            "presence_penalty",
            "frequency_penalty",
            "mirostat_tau",
            "mirostat_eta",
        ]
        for key, ctrl in self.controls.items():
            if isinstance(ctrl, wx.CheckBox):
                settings.parameters[key]["value"] = ctrl.IsChecked()
            else:
                value = ctrl.GetValue()
                # Convert value back to the appropriate type based on its original type
                if value == "":
                    value = None
                elif key in ints:
                    value = int(value)
                elif key in floats:
                    value = float(value)
                elif isinstance(settings.parameters[key]["value"], list):
                    value = value.split(", ")
                    if value == [""]:
                        value = []
                settings.parameters[key]["value"] = value
        settings.parameters = settings.parameters


def get_parameters():
    p = os.path.join(os.path.dirname(__file__), "default-parameters.json")
    with open(p) as file:
        default = json.load(file)
        default = default["parameters"]
    if not hasattr(settings, "parameters"):
        settings.parameters = default
    else:
        parameters = settings.parameters
        for key, value in default.items():
            if key in parameters:
                continue
            parameters[key] = value
        keys = list(parameters.keys())
        for key in keys:
            if key not in default:
                del parameters[key]
        settings.parameters = parameters
    options = {}
    for key, value in settings.parameters.items():
        if value["value"] == []:
            continue
        options[key] = value["value"]
    return options
