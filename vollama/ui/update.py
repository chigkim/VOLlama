"""Checking GitHub for a newer release.

Runs on a worker thread at startup and is allowed to fail quietly: not being
able to reach GitHub is not something to interrupt the user about, and the
version they have still works.
"""

import logging
import re
import webbrowser

import requests
import wx

log = logging.getLogger(__name__)

REPO = "chigkim/vollama"
TIMEOUT = 10


def latest_release():
    """(name, build number, page) of the newest release, or None."""
    response = requests.get(
        f"https://api.github.com/repos/{REPO}/releases", timeout=TIMEOUT
    )
    response.raise_for_status()
    releases = response.json()
    if not releases:
        return None
    release = releases[0]
    # The build number is the last run of digits in the tag, so v0.6.0-72 and
    # 0.6.72 both answer 72.
    numbers = re.findall(r"\d+", release.get("tag_name") or "")
    if not numbers:
        return None
    return release.get("name") or "A new version", int(numbers[-1]), release.get("html_url")


def check(current_build):
    """Offer the newest release if it is newer than this one."""
    try:
        newest = latest_release()
    except (requests.RequestException, ValueError) as e:
        log.info("Could not check for updates: %s", e)
        return
    if not newest:
        return
    name, build, url = newest
    if build > current_build:
        wx.CallAfter(_offer, name, url)


def _offer(name, url):
    with wx.MessageDialog(
        None,
        f"{name} is available. Would you like to open the link to download?",
        "New Update",
        wx.YES_NO | wx.ICON_QUESTION,
    ) as dialog:
        dialog.SetYesNoLabels("Yes", "No")
        if dialog.ShowModal() == wx.ID_YES:
            webbrowser.open(url)
