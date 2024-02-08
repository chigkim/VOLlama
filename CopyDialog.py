import wx

class CopyDialog(wx.Dialog):
	def __init__(self, parent, title):
		super(CopyDialog, self).__init__(parent, title=title, size=(300, 600))
		self.mainSizer = wx.BoxSizer(wx.VERTICAL)
		self.name = wx.TextCtrl(self)
		self.modelfile = wx.TextCtrl(self)
		self.name.SetToolTip("Name")
		self.modelfile.SetToolTip("Modelfle)
		self.mainSizer.Add(self.name, 1, wx.EXPAND | wx.ALL, 5)
		self.mainSizer.Add(self.modelfile, 8, wx.EXPAND | wx.ALL, 5)
		self.buttonSizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
		self.mainSizer.Add(self.buttonSizer, 1, wx.EXPAND | wx.ALL, 5)
		self.SetSizer(self.mainSizer)
		self.mainSizer.Fit(self)

dialog = CopyDialog(None, title="Copy")
dialog.name.SetValue("Initial value for text 1")
dialog.modelfile.SetValue("Initial value for text 2")
if dialog.ShowModal() == wx.ID_OK:
	name_value = dialog.name.GetValue()
	modelfile_value = dialog.modelfile.GetValue()
dialog.Destroy()
