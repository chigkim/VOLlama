import traceback
import wx

def displayError(e):
	print(traceback.format_exc())
	dialog = wx.MessageDialog(None, str(e), "Error", wx.OK | wx.ICON_ERROR)
	dialog.ShowModal()
	dialog.Destroy()
