"""Text to speech, which for this application is an accessibility feature.

Four backends, one per platform arrangement, chosen once at startup. They share
a shape rather than a base class, since there is nothing for a base class to
hold: no two of them can run on the same machine, and each is a thin wrapper
over a system API that already does the work.

    speak(text)   say it, after anything already queued
    stop()        stop now and drop what is queued
    voices()      the voices to choose from, [] when there is no choice
    voice         the current voice identifier
    rate          the current speaking rate

None of them opens a dialog. They used to, each with its own near-identical
copy, which made a speech driver depend on wxPython; `ui.speech_dialog` asks
the question now and sets the answer through these five names.
"""

import platform
from typing import Protocol


class Speech(Protocol):
    def speak(self, text: str) -> None: ...
    def stop(self) -> None: ...
    def voices(self) -> list: ...

    @property
    def voice(self) -> str: ...

    @property
    def rate(self) -> float: ...


class VoiceGroup:
    """One level of the voice namespace: some voices, and deeper groups.

    A voice identifier is a dotted namespace, and on macOS that namespace is the
    only thing that makes a voice list usable: `com.apple.ttsbundle.siri_*`,
    `com.apple.voice.premium.*` and `com.apple.speech.synthesis.voice.*` are
    three quite different sets of voices, and there are well over a hundred of
    them. Grouping is how you find one.

    A name can be both a group and a voice, so `voice` is a field rather than a
    reserved key in `groups`.
    """

    __slots__ = ("groups", "voice")

    def __init__(self):
        self.groups = {}
        self.voice = None

    def __repr__(self):
        return f"VoiceGroup(voice={self.voice!r}, groups={sorted(self.groups)})"


def group(voices):
    """Voices arranged by their dotted namespace, ready to build a menu from.

    A level that adds nothing but a name — one child and no voice of its own —
    is folded into that child, **keeping both names**, so `voice.premium.en-US`
    holding one voice becomes a single entry called `premium.en-US.Zoe` rather
    than a submenu three deep or, worse, an entry called `premium` that turns
    out to be a voice. The root is folded away entirely, since it has no label
    to show: that is what drops the `com.apple.` every macOS voice shares.

    Names with no dots, which is every SAPI voice on Windows, come back as one
    flat level.
    """
    root = VoiceGroup()
    for voice in voices:
        parts = [part for part in voice.split(".") if part]
        node = root
        for part in parts:
            node = node.groups.setdefault(part, VoiceGroup())
        node.voice = voice
    root = _folded(root)
    while root.voice is None and len(root.groups) == 1:
        root = next(iter(root.groups.values()))
    return root


def _folded(node):
    """This level with each chain of single-child groups folded into one entry."""
    groups = {}
    for name, child in node.groups.items():
        while child.voice is None and len(child.groups) == 1:
            only, child = next(iter(child.groups.items()))
            name = f"{name}.{only}"
        groups[name] = _folded(child)
    node.groups = groups
    return node


def create(use_screen_reader):
    """The speech backend for this machine.

    Imported here rather than at the top of the module because three of the
    four import a platform library that only exists on one platform.
    """
    if use_screen_reader:
        from vollama.speech.screen_reader import ScreenReaderSpeech

        return ScreenReaderSpeech()
    system = platform.system()
    if system == "Darwin":
        from vollama.speech.mac import MacSpeech

        return MacSpeech()
    if system == "Windows":
        from vollama.speech.sapi import SapiSpeech

        return SapiSpeech()
    from vollama.speech.silent import SilentSpeech

    return SilentSpeech()
