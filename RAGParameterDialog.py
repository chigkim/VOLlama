from Settings import settings
import wx

class RAGParameterDialog(wx.Dialog):
	def __init__(self, parent, title):
		super().__init__(parent, title=title, size=(400, 400))

		self.panel = wx.Panel(self)
		self.main_sizer = wx.BoxSizer(wx.VERTICAL)

		# Define parameters
		self.parameters = {
			"chunk_size": {"label": "Chunk Size", "control": "SpinCtrl", "min": 1, "max": int(settings.parameters['num_ctx']['value']/2), "initial": settings.chunk_size},
			"chunk_overlap": {"label": "Chunk Overlap", "control": "SpinCtrl", "min": 0, "max": 100, "initial": settings.chunk_overlap},
			"similarity_top_k": {"label": "Similarity Top K", "control": "SpinCtrl", "min": 1, "max": 100, "initial": settings.similarity_top_k},
			"similarity_cutoff": {"label": "Similarity Cutoff", "control": "SpinCtrlDouble", "min": 0.0, "max": 1.0, "inc": 0.01, "initial": settings.similarity_cutoff},
			"response_modes": {"label": "Response Mode", "control": "Choice", "choices": ['refine', 'compact', 'tree_summarize', 'simple_summarize', 'accumulate', 'compact_accumulate'], "initial": settings.response_mode},
			"show_context": {"label": "Show Context", "control": "CheckBox", "initial": settings.show_context},
		}

		self.controls = {}

		for key, value in self.parameters.items():
			self.add_parameter_control(key, **value)


		ok_button = wx.Button(self.panel, label='OK', id=wx.ID_OK)
		ok_button.Bind(wx.EVT_BUTTON, self.on_ok)
		cancel_button = wx.Button(self.panel, label='Cancel', id=wx.ID_CANCEL)		
		buttons_hbox = wx.BoxSizer(wx.HORIZONTAL)
		buttons_hbox.Add(ok_button, 0, wx.ALL, 5)
		buttons_hbox.Add(cancel_button, 0, wx.ALL, 5)		
		self.main_sizer.Add(buttons_hbox, 0, wx.ALL | wx.CENTER, 5)

		self.panel.SetSizer(self.main_sizer)

	def add_parameter_control(self, name, label, control, **kwargs):
		row_sizer = wx.BoxSizer(wx.HORIZONTAL)
		label_widget = wx.StaticText(self.panel, label=label)
		row_sizer.Add(label_widget, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

		if control == "SpinCtrl":
			widget = wx.SpinCtrl(self.panel, value=str(kwargs["initial"]), min=kwargs["min"], max=kwargs["max"])
		elif control == "CheckBox":
			widget = wx.CheckBox(self.panel)
			widget.SetValue(kwargs["initial"])
		elif control == "SpinCtrlDouble":
			widget = wx.SpinCtrlDouble(self.panel, value=str(kwargs["initial"]), min=kwargs["min"], max=kwargs["max"], inc=kwargs["inc"])
			widget.SetValue(kwargs["initial"])
		elif control == "Choice":
			widget = wx.Choice(self.panel, choices=kwargs["choices"])
			widget.SetStringSelection(kwargs["initial"])
		else:
			raise ValueError("Unsupported control type")

		self.controls[name] = widget
		row_sizer.Add(widget, 1, wx.EXPAND)
		self.main_sizer.Add(row_sizer, 0, wx.EXPAND | wx.ALL, 5)

	def on_ok(self, event):
		for key, widget in self.controls.items():
			if isinstance(widget, wx.Choice):
				value = widget.GetStringSelection()
			else:
				value = widget.GetValue()
			setattr(settings, key, value)
		self.Close()
