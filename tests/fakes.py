"""Stand-ins for the two things the chat layer talks to: a server and a screen.

Both are written out rather than mocked. A recorded list of calls is easier to
assert against than a mock's call list, and a chunk built from a dictionary is
exactly what a real one looks like to `chat.streaming`: the reader turns every
chunk into a dict before touching it, so a dict *is* the wire format here.
"""

from vollama.config import presets
from vollama.config.presets import Preset


def preset(**fields):
    """One usable preset, active, with `fields` set on it.

    The retrieval settings live on a preset, so a test that wants a different
    cutoff or chunk size sets it here rather than on `settings`.
    """
    made = Preset(base_url="http://localhost/v1/", model="m", **fields)
    presets.replace([("test", made)], "test")
    return made


def chunk(delta=None, finish_reason=None, usage=None):
    """One streamed chunk, in the shape the server sends it."""
    made = {}
    if delta is not None or finish_reason is not None:
        made["choices"] = [{"delta": delta or {}, "finish_reason": finish_reason}]
    if usage is not None:
        made["usage"] = usage
    return made


def text_chunk(text, finish_reason=None):
    return chunk(delta={"content": text}, finish_reason=finish_reason)


def reasoning_chunk(text):
    return chunk(delta={"reasoning_content": text})


def usage_chunk(prompt_tokens, completion_tokens, cached_tokens=None):
    """The extra chunk stream_options asks for: usage, and no choices."""
    usage = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
    if cached_tokens is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached_tokens}
    return chunk(usage=usage)


def call_chunk(name, arguments, id="call_1", index=0, extra_content=None):
    """A whole tool call in one chunk, which is enough for most tests."""
    fragment = {
        "index": index,
        "id": id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }
    if extra_content:
        fragment["extra_content"] = extra_content
    return chunk(delta={"tool_calls": [fragment]})


def call(name, arguments, id="call_1"):
    """A finished tool call, as it is stored on an assistant message."""
    return {
        "id": id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


class FakeClient:
    """A client that replays prepared streams, one per request."""

    def __init__(self, *streams):
        self.streams = list(streams)
        self.requests = []

    def _next(self, messages):
        self.requests.append([message.copy() for message in messages])
        if not self.streams:
            raise AssertionError("The session made more requests than were prepared.")
        stream = self.streams.pop(0)
        if isinstance(stream, Exception):
            raise stream
        return stream

    def stream(self, messages):
        return iter(self._next(messages))

    def complete(self, messages):
        return self._next(messages)


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
