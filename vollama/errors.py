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
    """Configuration is missing or will not do what was asked of it.

    `field` names the setting at fault, when one field is. The rule belongs to
    the domain and the mapping from a field to a control belongs to the editor,
    so a name is the narrowest thing that lets each keep its own knowledge: the
    preset dialog puts the focus where the error is fixed without reading the
    sentence to work out which field it means. It is a field *name*, never its
    value, so nothing an error carries can leak an api key.
    """

    def __init__(self, message, field=""):
        super().__init__(message)
        self.field = field


class DocumentError(VOLlamaError):
    """A document or web page could not be read."""
