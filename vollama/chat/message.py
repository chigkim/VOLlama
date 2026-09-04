"""One message, and what it looks like on the wire.

This is the type the whole chat layer works in. It replaced llama_index's
`ChatMessage`, which came with a serializer that decided rather more than we
wanted: it spread `additional_kwargs` into the outgoing message as top-level
fields, so any key we invented to hold something of our own — the model's
thinking, a marker saying a message came from a background job — went out to
the server as part of the request unless it was stripped again first.

`to_wire()` is a whitelist instead. `extra` holds whatever this layer needs to
remember about a message, and only the four keys a server understands are ever
sent. Nothing has to be stripped, and adding a field of our own cannot leak
into a request.
"""

import base64
import copy
import mimetypes

from vollama.errors import DocumentError


class Message:
    """A role, what was said, and whatever we need to remember alongside it.

    `extra` is ours: tool calls, a tool result's call id, the thinking that
    came with an answer, the markers on messages we made up. `images` are data
    URLs, kept apart from the text because the text is what everything else
    here reads — the transcript, Save, the token count, alt+up.
    """

    __slots__ = ("role", "content", "extra", "images")

    def __init__(self, role, content="", extra=None, images=()):
        self.role = role
        self.content = content or ""
        self.extra = dict(extra or {})
        self.images = list(images)

    def __repr__(self):
        return f"Message({self.role!r}, {self.content[:40]!r})"

    def __eq__(self, other):
        if not isinstance(other, Message):
            return NotImplemented
        return (
            self.role == other.role
            and self.content == other.content
            and self.extra == other.extra
            and self.images == other.images
        )

    def copy(self):
        return Message(self.role, self.content, copy.deepcopy(self.extra), self.images)

    def to_wire(self):
        """This message as the request wants it.

        Only what a server understands: the role, the content, the tool calls
        an assistant made and the id a tool result answers. A tool call is
        passed through as it arrived, vendor fields and all, because one of
        those fields is Gemini's thought signature and a call sent back without
        it is refused.
        """
        message = {"role": self.role, "content": self.content}
        if self.images:
            message["content"] = [
                {"type": "text", "text": self.content},
                *(
                    {"type": "image_url", "image_url": {"url": url}}
                    for url in self.images
                ),
            ]
        calls = self.extra.get("tool_calls")
        if calls and self.role == "assistant":
            message["tool_calls"] = copy.deepcopy(calls)
            # A server that is given a tool call to make sense of will not take
            # "" as the message it came with: the call *is* the message.
            message["content"] = self.content or None
        if self.role == "tool":
            message["tool_call_id"] = self.extra.get("tool_call_id", "")
        return message

    def countable(self):
        """The text of this message, for an estimate of what it costs.

        Images are left out. What they cost is the server's own arithmetic over
        the picture, and a base64 string counted as words is not an estimate of
        it but a much larger number that happens to be numeric.
        """
        parts = [self.content]
        for call in self.extra.get("tool_calls") or []:
            function = call.get("function") or {}
            parts.append(str(function.get("name") or ""))
            parts.append(str(function.get("arguments") or ""))
        return "\n".join(part for part in parts if part)


def image_url(source, content):
    """These bytes as the data URL a vision model is sent.

    Inlined rather than passed on as the address it came from, because a local
    server has no way to fetch a picture from the internet and no way to say
    that it could not.
    """
    kind = image_type(source, content)
    if not kind:
        raise DocumentError(f"{source} is not an image a model can be sent.")
    return f"data:{kind};base64," + base64.b64encode(content).decode("ascii")


def image_type(source, content):
    """The mime type to send an image as, from its name or its first bytes.

    A local file usually has a usable extension; an address often does not, and
    the type has to be read out of what came back. A picture no server would
    accept anyway is better refused here, where the file it came from can still
    be named.
    """
    guessed, _ = mimetypes.guess_type(source)
    if guessed and guessed.startswith("image/"):
        return guessed
    return sniff(content)


# Enough of each format's first bytes to tell it apart from the others.
SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
    (b"BM", "image/bmp"),
)


def sniff(content):
    """The image type these bytes are, or "" if they are not a picture."""
    for signature, kind in SIGNATURES:
        if content.startswith(signature):
            return kind
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return ""
