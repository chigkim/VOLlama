"""Retrieval settings, and the embedding endpoint they use.

Straight controls rather than the table of control names that was here before.
That table let one loop build every widget, at the price of a dispatch on the
string "SpinCtrl"; nine fields written out is longer and says what it does.
"""

import wx

from vollama.config.settings import settings
from vollama.rag.index import RESPONSE_MODES


class RagDialog(wx.Dialog):
    """Reads the retrieval settings, and writes them back on OK."""

    def __init__(self, parent):
        super().__init__(parent, title="RAG Settings", size=(520, 520))
        panel = wx.Panel(self)
        grid = wx.GridBagSizer(5, 5)
        self.panel = panel
        self.grid = grid
        self.row = 0

        self.chunk_size = self._spin(
            "Chunk Size", settings.chunk_size, 1, 1_000_000,
            "How much text goes into one indexed chunk. Smaller chunks make "
            "retrieval more precise and lose more surrounding context.",
        )
        self.chunk_overlap = self._spin(
            "Chunk Overlap", settings.chunk_overlap, 0, 1000,
            "How much of each chunk repeats the one before it, so a sentence "
            "split across the boundary is still findable.",
        )
        self.similarity_top_k = self._spin(
            "Similarity Top K", settings.similarity_top_k, 1, 100,
            "How many chunks to retrieve for a question.",
        )
        self.similarity_cutoff = self._float(
            "Similarity Cutoff", settings.similarity_cutoff,
            "The lowest similarity score a chunk may have and still be used.",
        )
        self.response_mode = self._choice(
            "Response Mode", settings.response_mode, list(RESPONSE_MODES),
            "How the retrieved chunks are turned into an answer.",
        )
        self.show_context = self._check(
            "Show Context", settings.show_context,
            "Print the retrieved chunks and their scores with the answer.",
        )
        self.embedding_base_url = self._text(
            "Embedding Base URL", settings.embedding_base_url,
            "OpenAI-compatible endpoint that serves the embedding model.",
        )
        self.embedding_api_key = self._text(
            "Embedding API Key", settings.embedding_api_key,
            "Leave empty if the embedding endpoint does not need one.",
        )
        self.embedding_model = self._text(
            "Embedding Model", settings.embedding_model,
            "The embedding model's name. Changing it after indexing means the "
            "index has to be built again, since old and new vectors are not "
            "comparable.",
        )

        grid.AddGrowableCol(1)
        panel.SetSizer(grid)
        # CreateStdDialogButtonSizer parents its buttons to the dialog, so the
        # sizer holding it has to be the dialog's and not the panel's.
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        outer.Add(
            self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL),
            0,
            wx.ALIGN_CENTER | wx.ALL,
            5,
        )
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)

    # Each helper adds one labelled row and hands back the control.
    def _add(self, label, make, tip):
        """`make` builds the control, and is called once the label exists.

        A screen reader on Windows pairs a field with the static text created
        before it, not with the one the sizer puts to its left, so a control
        built as an argument to this method is announced with the label of the
        row above.
        """
        self.grid.Add(
            wx.StaticText(self.panel, label=label + ":"),
            pos=(self.row, 0),
            flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL,
            border=5,
        )
        control = make()
        control.SetName(label)
        control.SetToolTip(tip)
        self.grid.Add(control, pos=(self.row, 1), flag=wx.EXPAND | wx.ALL, border=5)
        self.row += 1
        return control

    def _spin(self, label, value, low, high, tip):
        return self._add(
            label,
            lambda: wx.SpinCtrl(self.panel, value=str(value), min=low, max=high),
            tip,
        )

    def _float(self, label, value, tip):
        def make():
            control = wx.SpinCtrlDouble(self.panel, min=0.0, max=1.0, inc=0.01)
            control.SetValue(value)
            return control

        return self._add(label, make, tip)

    def _choice(self, label, value, choices, tip):
        def make():
            control = wx.Choice(self.panel, choices=choices)
            control.SetStringSelection(value if value in choices else choices[0])
            return control

        return self._add(label, make, tip)

    def _check(self, label, value, tip):
        def make():
            control = wx.CheckBox(self.panel)
            control.SetValue(value)
            return control

        return self._add(label, make, tip)

    def _text(self, label, value, tip):
        return self._add(label, lambda: wx.TextCtrl(self.panel, value=str(value)), tip)

    def on_ok(self, event):
        settings.chunk_size = self.chunk_size.GetValue()
        settings.chunk_overlap = self.chunk_overlap.GetValue()
        settings.similarity_top_k = self.similarity_top_k.GetValue()
        settings.similarity_cutoff = self.similarity_cutoff.GetValue()
        settings.response_mode = self.response_mode.GetStringSelection()
        settings.show_context = self.show_context.GetValue()
        settings.embedding_base_url = self.embedding_base_url.GetValue().strip()
        settings.embedding_api_key = self.embedding_api_key.GetValue().strip()
        settings.embedding_model = self.embedding_model.GetValue().strip()
        settings.save()
        self.EndModal(wx.ID_OK)
