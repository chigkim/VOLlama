import wx

class CopyDialog(wx.Dialog):
	def __init__(self, parent, title):
		super(CopyDialog, self).__init__(parent, title=title, size=(400, 300))
		self.mainSizer = wx.BoxSizer(wx.VERTICAL)
		self.name = wx.TextCtrl(self)
		self.modelfile = wx.TextCtrl(self, style=wx.TE_MULTILINE)
		self.name.SetToolTip("Name")
		self.modelfile.SetToolTip("Modelfle")
		self.mainSizer.Add(self.name, 1, wx.EXPAND | wx.ALL, 5)
		self.mainSizer.Add(self.modelfile, 8, wx.EXPAND | wx.ALL, 5)
		self.buttonSizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
		self.mainSizer.Add(self.buttonSizer, 1, wx.EXPAND | wx.ALL, 5)
		self.SetSizer(self.mainSizer)
		self.mainSizer.Fit(self)
		self.Maximize(True)

