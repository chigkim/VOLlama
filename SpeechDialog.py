import wx
from collections import defaultdict


class SpeechDialog(wx.Dialog):

    def __init__(self, parent, title, voices, current_voice, rate):
        super(SpeechDialog, self).__init__(parent, title=title, size=(360, 220))
        self.voices = list(["default"]+voices)  # expected short, dot-separated names
        self._menu_item_to_voice = {}  # int(id) -> full voice string
        self._selected_voice = current_voice if current_voice in self.voices else ""
        self._menu_root = None

        panel = wx.Panel(self)
        main = wx.BoxSizer(wx.VERTICAL)

        # Voice selection row
        voice_row = wx.BoxSizer(wx.HORIZONTAL)
        # The button now shows the selected voice (or a placeholder if none)
        self.voice_btn = wx.Button(
            panel, label=(self._selected_voice or "Choose Voice…")
        )
        self.voice_btn.Bind(wx.EVT_BUTTON, self._on_open_menu)

        voice_row.Add(
            wx.StaticText(panel, label="Voice"),
            flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            border=8,
        )
        voice_row.Add(self.voice_btn, proportion=1, flag=wx.EXPAND)

        # Rate row
        rate_row = wx.BoxSizer(wx.HORIZONTAL)
        self.rate_text_ctrl = wx.TextCtrl(panel, value=str(rate))
        rate_row.Add(
            wx.StaticText(panel, label="Rate"),
            flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            border=8,
        )
        rate_row.Add(self.rate_text_ctrl, proportion=1)

        # Buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        ok_button = wx.Button(panel, label="OK", id=wx.ID_OK)
        cancel_button = wx.Button(panel, label="Cancel", id=wx.ID_CANCEL)
        btn_row.Add(ok_button, flag=wx.RIGHT, border=8)
        btn_row.Add(cancel_button)

        # Pack
        main.AddSpacer(10)
        main.Add(voice_row, flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=12)
        main.AddSpacer(10)
        main.Add(rate_row, flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=12)
        main.AddStretchSpacer(1)
        main.Add(btn_row, flag=wx.ALL | wx.ALIGN_RIGHT, border=12)

        panel.SetSizer(main)

        # Build the nested menu once
        self._menu_root = self._build_voice_menu(self.voices)

        # Make Enter trigger OK by default
        self.SetDefaultItem(ok_button)

    # ---------- Public API ----------

    def get_selections(self):
        """
        Returns (selected_voice, rate_str)
        - selected_voice: dot-separated voice string selected from the menu
        - rate_str: the text from the rate field (caller may cast to float)
        """
        return self._selected_voice, self.rate_text_ctrl.GetValue()

    # ---------- Menu building ----------

    @staticmethod
    def _build_trie(voices):
        """
        Build a nested dict (trie) from a list of dot-separated strings.
        Leaf nodes have a special key "__leaf__" that stores the full voice string.
        """
        root = lambda: defaultdict(root)
        trie = root()
        for v in voices:
            parts = [p for p in v.split(".") if p]
            node = trie
            for p in parts:
                node = node[p]
            node["__leaf__"] = v
        return trie

    def _build_voice_menu(self, voices):
        """
        Construct a nested wx.Menu hierarchy from the trie.
        Each leaf is a selectable item; intermediate nodes are submenus.
        """
        trie = self._build_trie(voices)
        menu = wx.Menu()
        self._populate_menu_from_trie(menu, trie)
        return menu

    def _populate_menu_from_trie(self, menu, node):
        """
        Recursively populate a menu from a trie node.
        If a node has "__leaf__", create a selectable leaf item.
        Otherwise, create submenus for each child key.
        """
        # Sort keys so menus are stable/predictable
        keys = sorted(k for k in node.keys() if k != "__leaf__")

        # If this node itself is a leaf, add a selectable item (used when a voice ends at this level)
        if "__leaf__" in node and not keys:
            voice = node["__leaf__"]
            item_id = wx.NewIdRef()
            item = menu.Append(item_id, voice.split(".")[-1])
            self._menu_item_to_voice[int(item_id)] = voice
            self.Bind(wx.EVT_MENU, self._on_voice_selected, item)
            return

        for k in keys:
            child = node[k]
            # Leaf-only child: add a selectable item
            if (
                "__leaf__" in child
                and len([x for x in child.keys() if x != "__leaf__"]) == 0
            ):
                voice = child["__leaf__"]
                item_id = wx.NewIdRef()
                item = menu.Append(item_id, k)
                self._menu_item_to_voice[int(item_id)] = voice
                self.Bind(wx.EVT_MENU, self._on_voice_selected, item)
            else:
                # Create a submenu and recurse
                submenu = wx.Menu()
                self._populate_menu_from_trie(submenu, child)
                menu.AppendSubMenu(submenu, k)

    # ---------- Event handlers ----------

    def _on_open_menu(self, event):
        """
        Show the voice menu at the button's position.
        """
        if not self._menu_root:
            return
        btn = self.voice_btn
        pos = btn.ClientToScreen((0, btn.GetSize().height))
        self.PopupMenu(self._menu_root, self.ScreenToClient(pos))

    def _on_voice_selected(self, event):
        """
        Update the selected voice when a menu item is chosen.
        """
        item_id = event.GetId()
        voice = self._menu_item_to_voice.get(item_id)
        if voice:
            self._selected_voice = voice
            # Update the button to show the full selected voice
            self.voice_btn.SetLabel(voice)
            # Optional: ensure layout updates if label length changes
            self.Layout()
