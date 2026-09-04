"""The errors VOLlama raises on purpose.

Everything here means "the request was understood and cannot be carried out",
which is what separates it from a bug. The UI shows the message of one of these
without a traceback; anything else is a fault and gets logged in full.

The tool layer is the deliberate exception: a tool returns its error as text
rather than raising, because that text is the tool's product. It is what the
model reads and acts on, so a failed `edit` is not an exception to be handled
but an answer to be sent.
"""


class VOLlamaError(Exception):
    """Base for every error this application raises deliberately."""


class ConfigError(VOLlamaError):
    """Configuration is missing or will not do what was asked of it."""


class DocumentError(VOLlamaError):
    """A document or web page could not be read."""
