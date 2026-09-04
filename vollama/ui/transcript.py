"""Showing a chat: the ChatView the session reports to, and the whole transcript.

This is the only module that puts work on the GUI thread. Everything the chat
layer emits arrives here on a worker thread and leaves through `wx.CallAfter`,
so no code below `ui` has to remember to do it — which is the thing that was
wrong before, when twenty-odd `wx.CallAfter` calls were spread through the
conversation logic.

It is also where presentation policy lives, and that is deliberate. Whether
reasoning is shown, whether the reply is spoken, where a sentence ends for text
to speech, what a tool call looks like written down, how a token count reads:
every one of those is a fact about a text control and a speech synthesiser, and
none of them is a fact about a conversation.
"""

import os
import re

import wx

from vollama.chat.conversation import BACKGROUND
from vollama.config import presets
from vollama.config.settings import settings
from vollama.tools import registry

# How much of a tool call or its result the transcript shows. The whole of a
# build log in the middle of a conversation buries what the model then says
# about it, and the model has the whole of it either way.
SUMMARY_LENGTH = 200

# What a spoken sentence ends with. Text to speech is fed a sentence at a time
# so it starts talking while the rest is still arriving.
SENTENCE_END = re.compile(r"[.?!\n]\s*$")


def assistant_name():
    """What the assistant is called in the transcript: the active preset's name."""
    preset = presets.active()
    return presets.active_name() or (preset.model if preset else "") or "Assistant"


def trim(text, limit=SUMMARY_LENGTH):
    """One line, at most limit characters."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text[:limit] + "..." if len(text) > limit else text


def lines_for(message, name):
    """How one stored message reads in the transcript, tool rounds included."""
    content = (message.content or "").strip()
    if message.role == "tool":
        return [f"Result: {trim(content)}"]
    if message.additional_kwargs.get(BACKGROUND):
        return [f"Background: {content}"]
    if message.role != "assistant":
        return [f"You: {content}"]
    lines = [f"{name}: {content}"] if content else []
    for call in message.additional_kwargs.get("tool_calls") or []:
        function = call.get("function") or {}
        described = registry.describe(
            function.get("name") or "", function.get("arguments") or ""
        )
        lines.append(f"Tool: {trim(described)}")
    return lines


def render(conversation):
    """The whole conversation as transcript text, without the system prompt."""
    name = assistant_name()
    lines = []
    for message in conversation.messages:
        if message.role == "system":
            continue
        lines.extend(lines_for(message, name))
    return os.linesep.join(lines) + (os.linesep if lines else "")


class TranscriptView:
    """Writes what the chat session reports into the window.

    Holds the three things it writes to rather than the whole window, so what
    it can reach is visible in its constructor.
    """

    def __init__(self, output, status, speech, on_finished):
        self.output = output
        self.status_label = status
        self.speech = speech
        self.on_finished = on_finished
        self.sentence = ""
        self.showing_reasoning = False

    # -------------------------------------------------------- the ChatView

    def status(self, text):
        self._later(self.status_label, text)

    def reply_started(self):
        self.sentence = ""
        self.showing_reasoning = False
        self._append(f"{assistant_name()}: ")

    def reply_text(self, text):
        if self.showing_reasoning:
            self._append(f"{os.linesep}---{os.linesep}Response: ")
            self.showing_reasoning = False
        self._append(text)
        self._speak_sentences(text)

    def reasoning_text(self, text):
        if not settings.show_reasoning:
            return
        if not self.showing_reasoning:
            self._append("Reasoning: ")
            self.showing_reasoning = True
        self._append(text)

    def reply_finished(self):
        self._flush_sentence()
        self._append(os.linesep)

    def tool_called(self, description):
        self._append(f"Tool: {trim(description)}{os.linesep}")

    def tool_result(self, result):
        self._append(f"Result: {trim(result)}{os.linesep}")

    def notice(self, text):
        self._append(f"{text}{os.linesep}")

    def stats(self, stats):
        self.status(
            f"{stats.total_tokens} tokens in {stats.total_seconds:.2f} seconds. "
            f"Prompt: {stats.prompt_tokens} tokens "
            f"({stats.prompt_rate():.2f}/second). "
            f"Reply: {stats.completion_tokens} tokens "
            f"({stats.output_rate():.2f}/second)."
        )

    def finished(self):
        self._later(self.on_finished)

    # ------------------------------------------------------------- speaking

    def _speak_sentences(self, text):
        """Hand text to the synthesiser a finished sentence at a time."""
        if not settings.speakResponse:
            return
        self.sentence += text
        if SENTENCE_END.search(self.sentence):
            self._flush_sentence()

    def _flush_sentence(self):
        spoken, self.sentence = self.sentence.strip(), ""
        if spoken and settings.speakResponse:
            self._later(self.speech.speak, spoken)

    # --------------------------------------------------------------- plumbing

    def _append(self, text):
        self._later(self.output.AppendText, text)

    @staticmethod
    def _later(function, *args):
        wx.CallAfter(function, *args)
