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

None of them opens a dialog, and none of them saves anything. They used to do
both: each carried its own copy of the voice dialog, which made a speech driver
depend on wxPython, and each wrote `settings.voice` and `settings.rate` inside
its own property setters — the same responsibility implemented twice, with two
different answers to what happens when the platform refuses the voice.
`ui.speech_dialog` asks the question, `create()` below applies what was stored
last time, and `remember()` applies and stores a new choice. A backend drives
the device and nothing else.

`voices()` hands back `Voice` records while `voice` stays a bare identifier
string, because that string is what `settings.voice` holds and what each
platform API takes back.
"""

import platform
from dataclasses import dataclass
from typing import Protocol

from vollama.config.settings import settings


@dataclass(frozen=True)
class Voice:
    """One voice: what to ask the platform for, and what to call it.

    `identifier` is the platform's own handle, which is the only part that goes
    back to the synthesiser or into the settings file. `name` and `language` are
    for the person choosing, and are the reason this is a record rather than the
    identifier alone: a macOS identifier is not the voice's name and does not
    always contain it. The one Siri voice macOS lends to third-party apps is
    `com.apple.ttsbundle.gryphon-neuralAX_Nora_en-US_premium`, and it is called
    "Voice 4" — nothing a user could search for is anywhere in that string.

    `language` is already written for reading ("Korean (South Korea)"), not a
    code, because the platform is the only thing that can localize it and the
    platform is where these records are built.
    """

    identifier: str
    name: str
    language: str = ""

    def within(self, language):
        """The name to show under `language`, without repeating it.

        macOS names every Eloquence voice for its locale — `VoiceName` really is
        "Eddy (Korean (South Korea))" — which under a Korean heading reads as
        "Korean (South Korea) > Eddy (Korean (South Korea))".
        """
        suffix = f" ({language})"
        if language and self.name.endswith(suffix):
            return self.name[: -len(suffix)] or self.name
        return self.name

    def describe(self):
        """The voice on one line, for a button that has to say the whole choice.

        Comma-separated rather than parenthesized, since the language is itself
        usually parenthesized and a screen reader pauses on the comma.
        """
        return f"{self.name}, {self.language}" if self.language else self.name


class Speech(Protocol):
    """What a backend has to be. `voice` and `rate` are read and written."""

    def speak(self, text: str) -> None: ...
    def stop(self) -> None: ...
    def voices(self) -> list[Voice]: ...

    voice: str
    rate: float


def group(voices):
    """Voices by language: `{language: [Voice, ...]}`, ready to build a menu from.

    Language is the one thing a person picking a voice actually knows, and it is
    what the identifier namespace this used to group by never told them. macOS
    offers well over a hundred voices whose identifiers sort them by *engine* —
    `com.apple.eloquence.*`, `com.apple.voice.compact.*`,
    `com.apple.speech.synthesis.voice.*` — so the nine Korean voices on a
    machine landed in three different places, two of them levels deep behind
    words like "compact" that name an implementation detail. Grouped by
    language they are one submenu.

    Voices whose backend has no language for them come back under `""`, meaning
    show them at the top level rather than inside a heading that says nothing.
    Within a language, voices keep the order they were given, so a backend that
    sorts them keeps its sort.
    """
    languages = {}
    for voice in voices:
        languages.setdefault(voice.language, []).append(voice)
    return languages


def described(description):
    """A `Voice` from a SAPI voice description.

    SAPI has no identifier apart from the description and no language field
    worth reading — an LCID in hex, which needs a table to mean anything —
    but the description already ends with the language: "Microsoft Zira
    Desktop - English (United States)". The identifier stays the *whole*
    description, because that is what `settings.voice` holds and what
    `SapiSpeech.voice` matches on, so an existing settings file keeps working.

    A description that does not split gets no language and shows at the top
    level, which is what every voice did before. This lives here rather than in
    `sapi` so it can be tested off Windows.
    """
    name, separator, language = description.rpartition(" - ")
    if not separator or not name.strip() or not language.strip():
        return Voice(description, description)
    return Voice(description, name.strip(), language.strip())


def create(use_screen_reader):
    """The speech backend for this machine, set to the stored voice and rate."""
    backend = _backend(use_screen_reader)
    # A voice the machine no longer has, or a backend with no voices at all, is
    # left to the platform's own default rather than reported: there is nothing
    # for the user to do about it here, and silence would be worse.
    if settings.voice:
        backend.voice = settings.voice
    if settings.rate:
        backend.rate = settings.rate
    return backend


def remember(backend, voice, rate):
    """Apply a chosen voice and rate, and keep them for the next run.

    One place, because the two backends that can be configured used to do this
    for themselves and did not agree: one saved only what the platform accepted,
    the other saved first and could store a voice it then failed to find.
    """
    if voice:
        backend.voice = voice
        settings.voice = voice
    if rate is not None:
        backend.rate = rate
        settings.rate = float(rate)
    settings.save()


def _backend(use_screen_reader):
    """The backend class for this machine.

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
