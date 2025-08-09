import wx


class SpeechDialog(wx.Dialog):
    def __init__(self, parent, title, voices, current_voice, rate):
        super(SpeechDialog, self).__init__(parent, title=title, size=(250, 200))
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.voices_choice = wx.Choice(panel, choices=voices)
        if current_voice in voices:
            self.voices_choice.SetStringSelection(current_voice)

        self.rate_text_ctrl = wx.TextCtrl(panel, value=str(rate))
        ok_button = wx.Button(panel, label="OK", id=wx.ID_OK)
        cancel_button = wx.Button(panel, label="Cancel", id=wx.ID_CANCEL)

        vbox.Add(wx.StaticText(panel, label="Voice"), flag=wx.LEFT | wx.TOP, border=10)
        vbox.Add(self.voices_choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)
        vbox.Add(wx.StaticText(panel, label="Rate"), flag=wx.LEFT | wx.TOP, border=10)
        vbox.Add(self.rate_text_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)
        vbox.Add(ok_button, flag=wx.LEFT | wx.BOTTOM, border=10)
        vbox.Add(cancel_button, flag=wx.LEFT | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)

    def get_selections(self):
        return self.voices_choice.GetStringSelection(), self.rate_text_ctrl.GetValue()
