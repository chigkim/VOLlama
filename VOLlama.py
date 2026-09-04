"""VOLlama's entry point.

Everything it does is start-up: configure logging, create the wxPython
application, open the window, and hand control to the event loop. The
application itself is the `vollama` package, laid out as its layers.
"""

import logging
import sys

import wx

from vollama.config.store import config_dir
from vollama.ui.window import ChatWindow

LOG_FILE = "vollama.log"


def configure_logging():
    """Log to a file next to the settings, and to the console when there is one.

    A file because a packaged build has no console to print to, and the log is
    the only account of what went wrong that a user can send back.
    """
    handlers = [logging.FileHandler(config_dir() / LOG_FILE, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def main():
    configure_logging()
    app = wx.App(False)
    ChatWindow(None, "VOLlama")
    app.MainLoop()


if __name__ == "__main__":
    main()
