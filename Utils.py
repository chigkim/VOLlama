import traceback
import wx


def displayError(e):
    message = f"{e}\n{traceback.format_exc()}"
    print(message)
    dlg = wx.MessageDialog(None, message, "Error", wx.OK | wx.ICON_ERROR)
    dlg.ShowModal()
    dlg.Destroy()


def displayInfo(title, message):
    dlg = wx.MessageDialog(None, message, title, wx.OK | wx.ICON_INFORMATION)
    dlg.ShowModal()
    dlg.Destroy()
