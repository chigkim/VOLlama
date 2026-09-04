"""Choosing a voice and a speaking rate.

The dialog asks; it does not apply. The window takes the answer and sets it on
the speech backend, so the backends stay free of wxPython — each of them used to
carry its own near-identical copy of this.

The voices go into a submenu per language rather than a flat list, because
macOS offers well over a hundred and language is the thing you actually know
about the voice you want. A submenu is also the shape a screen reader announces
best: it says how many items are in the level you are in, which a flat list of
a hundred cannot. `speech.group()` works out the levels; this module only turns
them into menus.
"""

import wx

from vollama.speech import group


class SpeechDialog(wx.Dialog):
    """Asks for a voice and a rate. Read `choice()` after wx.ID_OK."""

    def __init__(self, parent, voices, voice, rate):
        super().__init__(parent, title="Select Voice and Rate", size=(460, 240))
        self.voices = {each.identifier: each for each in voices}
        self.selected = voice if voice in self.voices else ""

        panel = wx.Panel(self)
        self.voice_button = wx.Button(panel, label=self._label())
        self.voice_button.SetName("Voice")
        self.voice_button.SetToolTip("Choose a voice, grouped by its language.")
        self.voice_button.Bind(wx.EVT_BUTTON, self.on_open)
        self.menu = self._menu(voices)

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
        """The chosen voice identifier and rate. The rate is None if not a number."""
        try:
            rate = float(self.rate.GetValue().strip())
        except ValueError:
            rate = None
        return self.selected, rate

    # ------------------------------------------------------------------ menu

    def _menu(self, voices):
        """A submenu per language, and the languageless voices at the top level.

        The top-level voices come first, since on Windows before a description
        splits — and on any backend that gives us no language — they are the
        whole menu, and a menu that opens on a submenu is harder to hear.
        """
        languages = group(voices)
        menu = wx.Menu()
        for voice in languages.get("", ()):
            self._leaf(menu, voice.name, voice)
        for language in sorted(name for name in languages if name):
            submenu = wx.Menu()
            for voice in languages[language]:
                self._leaf(submenu, voice.within(language), voice)
            menu.AppendSubMenu(submenu, language)
        return menu

    def _leaf(self, menu, label, voice):
        item = menu.Append(wx.ID_ANY, label)
        self.Bind(
            wx.EVT_MENU,
            lambda event, chosen=voice.identifier: self.on_chosen(chosen),
            item,
        )

    def _label(self):
        """The button's label: the voice with its language, or the prompt."""
        if not self.selected:
            return "Choose Voice..."
        return self.voices[self.selected].describe()

    def on_open(self, event):
        self.PopupMenu(self.menu, self.voice_button.Position)

    def on_chosen(self, identifier):
        self.selected = identifier
        # The button is the only place the choice is shown, so it has to say the
        # whole thing and take focus back for a screen reader to read it.
        self.voice_button.SetLabel(self._label())
        self.Layout()
        self.voice_button.SetFocus()
