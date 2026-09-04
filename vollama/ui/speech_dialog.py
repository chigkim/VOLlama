"""Choosing a voice and a speaking rate.

The dialog asks; it does not apply. The window takes the answer and sets it on
the speech backend, so the backends stay free of wxPython — each of them used to
carry its own near-identical copy of this.

The voices go into a nested menu rather than a list, because macOS offers well
over a hundred and their identifiers already say how they group:
`com.apple.ttsbundle.siri_*`, `com.apple.voice.premium.*` and
`com.apple.speech.synthesis.voice.*` are three different sets of voices and you
almost always know which one you want. A submenu per level is also the shape a
screen reader announces best: it says how many items are in the level you are
in, which a flat list of a hundred cannot. `speech.group()` works out the levels;
this module only turns them into menus.
"""

import wx

from vollama.speech import group


class SpeechDialog(wx.Dialog):
    """Asks for a voice and a rate. Read `choice()` after wx.ID_OK."""

    def __init__(self, parent, voices, voice, rate):
        super().__init__(parent, title="Select Voice and Rate", size=(460, 240))
        self.selected = voice if voice in voices else ""

        panel = wx.Panel(self)
        self.voice_button = wx.Button(panel, label=self._label())
        self.voice_button.SetName("Voice")
        self.voice_button.SetToolTip("Choose a voice, grouped by its family.")
        self.voice_button.Bind(wx.EVT_BUTTON, self.on_open)
        self.menu = self._menu(group(voices))

        self.rate = wx.TextCtrl(panel, value=str(rate))
        self.rate.SetName("Rate")
        self.rate.SetToolTip(
            "How fast the voice speaks. What the number means depends on the "
            "platform's own scale."
        )

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(panel, label="&Voice:"), flag=wx.LEFT | wx.TOP, border=10)
        sizer.Add(self.voice_button, flag=wx.EXPAND | wx.ALL, border=10)
        sizer.Add(wx.StaticText(panel, label="&Rate:"), flag=wx.LEFT, border=10)
        sizer.Add(self.rate, flag=wx.EXPAND | wx.ALL, border=10)
        panel.SetSizer(sizer)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        outer.Add(
            self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL),
            0,
            wx.ALIGN_CENTER | wx.ALL,
            5,
        )
        self.SetSizer(outer)
        self.voice_button.SetFocus()

    def choice(self):
        """The chosen voice and rate. The rate is None if it was not a number."""
        try:
            rate = float(self.rate.GetValue().strip())
        except ValueError:
            rate = None
        return self.selected, rate

    # ------------------------------------------------------------------ menu

    def _menu(self, node):
        """One wx.Menu for a level of the namespace, submenus for the levels below.

        A name that is both a voice and a group gets an item of its own first,
        so a voice is never unreachable because something is nested under it.
        """
        menu = wx.Menu()
        if node.voice:
            self._leaf(menu, "This one", node.voice)
        for name in sorted(node.groups):
            child = node.groups[name]
            if child.groups:
                menu.AppendSubMenu(self._menu(child), name)
            else:
                self._leaf(menu, name, child.voice)
        return menu

    def _leaf(self, menu, label, voice):
        item = menu.Append(wx.ID_ANY, label)
        self.Bind(wx.EVT_MENU, lambda event, chosen=voice: self.on_chosen(chosen), item)

    def _label(self):
        return self.selected or "Choose Voice..."

    def on_open(self, event):
        self.PopupMenu(self.menu, self.voice_button.Position)

    def on_chosen(self, voice):
        self.selected = voice
        # The button is the only place the choice is shown, so it has to say the
        # whole identifier and take focus back for a screen reader to read it.
        self.voice_button.SetLabel(self._label())
        self.Layout()
        self.voice_button.SetFocus()
