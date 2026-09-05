"""The script PyInstaller builds, and `python VOLlama.py` from a checkout.

The start-up itself is `vollama/__main__.py`, so that the `vollama` command
installed by pip and this file run the same code rather than two copies of it.
"""

from vollama.__main__ import main

if __name__ == "__main__":
    main()
