"""Telling the user something went wrong, from any thread.

Two rules, both learned from the version before this one. A dialog may only be
opened on the GUI thread, and the chat runs on a worker, so every call is
marshalled. And the user is shown the message, not the traceback: the traceback
goes to the log, where it is useful, instead of into a modal box the user has to
read past to find the sentence that matters.
"""

import logging

import wx

from vollama.errors import VOLlamaError

log = logging.getLogger(__name__)


def show_error(error, title="Error"):
    """Report a failure. Safe to call from a worker thread."""
    if isinstance(error, VOLlamaError):
        # Raised on purpose and worded for the user, so there is nothing to
        # diagnose and the traceback would only be noise.
        log.info("%s", error)
    else:
        log.exception("Unhandled failure", exc_info=error)
    _on_gui_thread(_dialog, str(error) or error.__class__.__name__, title, wx.ICON_ERROR)


def show_info(title, message):
    """Report something that went right and is worth saying."""
    _on_gui_thread(_dialog, message, title, wx.ICON_INFORMATION)


def _dialog(message, title, icon):
    with wx.MessageDialog(None, message, title, wx.OK | icon) as dialog:
        dialog.ShowModal()


def _on_gui_thread(function, *args):
    if wx.IsMainThread():
        function(*args)
    else:
        wx.CallAfter(function, *args)
