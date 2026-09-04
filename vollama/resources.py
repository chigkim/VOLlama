"""Where the files that ship with the application are.

They sit next to the source when running from a checkout and in a temporary
directory PyInstaller unpacks at startup, so the path has to be asked for
rather than assumed. One place asks.
"""

import os
import sys


def root():
    """The directory the bundled data files are in."""
    # PyInstaller unpacks --add-data into _MEIPASS with the layout it was given,
    # which is the repository root.
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return bundle
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundled(name):
    """The full path of one file that ships with the application."""
    return os.path.join(root(), name)
