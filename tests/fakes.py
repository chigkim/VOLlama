"""Stand-ins for the two things the chat layer talks to: a server and a screen.

Both are written out rather than mocked. A recorded list of calls is easier to
assert against than a mock's call list, and a chunk built from a dictionary is
exactly what a real one looks like to `chat.streaming`.
"""


class Choice:
    def __init__(self, delta=None, finish_reason=None):
        self.delta = delta or {}
        self.finish_reason = finish_reason


class Raw:
    """What the openai library hands back for one streamed chunk."""

    def __init__(self, choices=(), usage=None):
        self.choices = list(choices)
        self.usage = usage


class Usage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class Message:
    def __init__(self, additional_kwargs=None):
        self.additional_kwargs = additional_kwargs or {}


class Chunk:
    """One streamed chunk as llama_index presents it."""

    def __init__(self, delta="", tool_calls=None, raw=None, additional_kwargs=None):
        self.delta = delta
        self.message = Message({"tool_calls": tool_calls} if tool_calls else {})
        self.raw = raw
        self.additional_kwargs = additional_kwargs or {}


def text_chunk(text, finish_reason=None):
    return Chunk(delta=text, raw=Raw([Choice(finish_reason=finish_reason)]))


def usage_chunk(prompt_tokens, completion_tokens):
    """The extra chunk stream_options asks for: usage, and no choices."""
    return Chunk(raw=Raw([], Usage(prompt_tokens, completion_tokens)))


def call(name, arguments, id="call_1"):
    return {"id": id, "type": "function", "function": {"name": name, "arguments": arguments}}


class FakeClient:
    """A client that replays prepared streams, one per request."""

    def __init__(self, *streams):
        self.streams = list(streams)
        self.requests = []

    def stream_chat(self, messages):
        self.requests.append(list(messages))
        if not self.streams:
            raise AssertionError("The session made more requests than were prepared.")
        stream = self.streams.pop(0)
        if isinstance(stream, Exception):
            raise stream
        return iter(stream)

    def chat(self, messages):
        self.requests.append(list(messages))
        stream = self.streams.pop(0)
        if isinstance(stream, Exception):
            raise stream
        return stream


class Reply:
    """What a non-streamed chat() call returns."""

    def __init__(self, text):
        self.message = Message()
        self.message.content = text


class RecordingView:
    """A ChatView that keeps what it was told, in order."""

    def __init__(self):
        self.events = []

    def _record(self, kind):
        return lambda *args: self.events.append((kind, *args))

    def __getattr__(self, name):
        return self._record(name)

    def of(self, kind):
        return [event[1:] for event in self.events if event[0] == kind]

    def text(self):
        return "".join(args[0] for args in self.of("reply_text"))
