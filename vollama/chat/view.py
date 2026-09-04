"""The port the chat layer reports through.

`ChatSession` has to say what is happening while it happens: text as it
streams, a tool it is about to run, a status line, a note that the conversation
was compacted. It must not know that any of that ends up in a wxPython text
control, and it must not be the thing that remembers to marshal onto the GUI
thread. So it talks to a `ChatView`, and the UI provides one.

The methods are named for the *decisions* the presentation layer makes, not for
a stream of strings, which is what keeps the policy on the right side of the
line. Whether reasoning is shown, whether the reply is spoken, where a sentence
ends for text to speech, what prefix a tool call gets: all of that is a fact
about a text control and a speech synthesiser, and all of it lives in
`ui.transcript`. What is left here is a fact about the conversation.

A Protocol rather than a base class: the UI view and the recording view the
tests use have nothing to share but the shape, and inheriting from an empty
class would only make that harder to see.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TurnStats:
    """What one exchange cost, in tokens and in seconds."""

    prompt_tokens: int
    completion_tokens: int
    total_seconds: float
    first_token_seconds: float

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens

    def prompt_rate(self):
        """Prompt tokens per second, counting up to the first token out."""
        return self.prompt_tokens / max(self.first_token_seconds, 1e-6)

    def output_rate(self):
        """Generated tokens per second, counting from the first token out."""
        return self.completion_tokens / max(
            self.total_seconds - self.first_token_seconds, 1e-6
        )


class ChatView(Protocol):
    """Where a turn reports itself. One implementation in ui, one in tests."""

    def status(self, text: str) -> None:
        """Transient progress: what the session is doing right now."""

    def reply_started(self) -> None:
        """A reply is about to stream."""

    def reply_text(self, text: str) -> None:
        """Another piece of the answer."""

    def reasoning_text(self, text: str) -> None:
        """Another piece of the model's thinking, if it sends any."""

    def reply_finished(self) -> None:
        """The reply has stopped streaming."""

    def tool_called(self, description: str) -> None:
        """A tool is about to run, described in one line."""

    def tool_result(self, result: str) -> None:
        """What that tool returned."""

    def notice(self, text: str) -> None:
        """Something the user should read that the model did not say.

        Compaction, recovery from a truncated reply, a background command that
        finished between turns.
        """

    def stats(self, stats: TurnStats) -> None:
        """What the exchange cost."""

    def finished(self) -> None:
        """The turn is over, whether it succeeded or not."""


class NullView:
    """A view that discards everything, for code paths with nobody watching."""

    def status(self, text): ...
    def reply_started(self): ...
    def reply_text(self, text): ...
    def reasoning_text(self, text): ...
    def reply_finished(self): ...
    def tool_called(self, description): ...
    def tool_result(self, result): ...
    def notice(self, text): ...
    def stats(self, stats): ...
    def finished(self): ...
