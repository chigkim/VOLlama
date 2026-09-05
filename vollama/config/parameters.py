"""The generation parameters a preset can set, and what they mean.

The schema is data, not code: `SCHEMA` holds one `Parameter` per name with the
kind of value it takes, a sentence describing it and its range. The preset
editor builds its controls from that table, so adding a parameter is an edit
here rather than to a dialog.

The schema is **never written to disk**. A preset stores `{name: value}` for the
parameters it actually sets, and nothing else: a description belongs in the
program that shows it, not in the user's configuration file once per preset.
Storing the whole schema was the reason this module needed a `reconcile()` to
repair the drift between the two copies, and the reason the editor had to work
out a value's type from the shape of the last value saved.

An unset parameter is absent, and absent means *not sent*. That is the rule the
module exists to keep: an empty box must leave the decision to the server rather
than quietly substituting our idea of a default.
"""

from dataclasses import dataclass
from typing import Callable


def csv_list(text):
    """A comma-separated field as a list of strings, blanks dropped."""
    return [item.strip() for item in text.split(",") if item.strip()]


@dataclass(frozen=True)
class Parameter:
    """One parameter: how to read its value, and how to describe it.

    `kind` is the converter, which is the single answer to "what type is this".
    Both the editor's parsing of a typed box and the checking of a value read
    out of the settings file go through it, so the two cannot disagree.
    """

    kind: Callable[[str], object]
    description: str
    range: str

    def holds(self, value):
        """Whether this is a value of the kind this parameter takes."""
        if self.kind is csv_list:
            return isinstance(value, list) and all(
                isinstance(item, str) for item in value
            )
        if self.kind is float:
            # A whole number in the file is a perfectly good temperature.
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if self.kind is int:
            return isinstance(value, int) and not isinstance(value, bool)
        return isinstance(value, str)


SCHEMA = {
    "max_tokens": Parameter(
        int,
        "Maximum number of tokens to generate in the response.",
        "Integer value, empty for the model default",
    ),
    "temperature": Parameter(
        float,
        "Increasing the temperature will make the model answer more creatively.",
        "0.0-2.0",
    ),
    "top_p": Parameter(
        float,
        "Nucleus sampling. A higher value will lead to more diverse text, while "
        "a lower value will generate more focused and conservative text.",
        "0.0-1.0",
    ),
    "presence_penalty": Parameter(
        float,
        "Penalizes new tokens based on their presence in the text so far.",
        "-2.0-2.0",
    ),
    "frequency_penalty": Parameter(
        float,
        "Penalizes new tokens based on their frequency in the text so far.",
        "-2.0-2.0",
    ),
    "stop": Parameter(
        csv_list,
        "When this pattern is encountered the LLM will stop generating text and "
        "return.",
        "Array of strings",
    ),
    "seed": Parameter(
        int,
        "Sets the random number seed to use for generation. Setting this to a "
        "specific number will make the model generate the same text for the "
        "same prompt.",
        "Integer value",
    ),
    "reasoning_effort": Parameter(
        str,
        "Sets the reasoning effort.",
        "none, low, medium, high",
    ),
}


def parse(key, text):
    """One editor field's text as a parameter value, or None if it is empty.

    Empty means unset, which is the whole point of the exercise. Raises
    ValueError on text that is not the kind of value the parameter takes; the
    dialog catches it and says which field.
    """
    text = text.strip()
    if not text:
        return None
    return SCHEMA[key].kind(text)


def checked(values):
    """The parameters out of a settings file: the ones the schema recognises.

    A name the schema does not have is dropped, and so is a value of the wrong
    kind — a hand-edited file, or one written before this parameter took the
    type it has now. Dropping it means the server decides, which is what an
    unset parameter has always meant, rather than sending something a server
    will refuse the whole request over.
    """
    if not isinstance(values, dict):
        return {}
    return {
        key: list(value) if isinstance(value, list) else value
        for key, value in values.items()
        if key in SCHEMA and SCHEMA[key].holds(value)
    }


def options(values):
    """The parameters that are actually set, as name to value.

    An empty list is left out along with a missing name, since a server reads a
    null or empty stop sequence as a stop sequence.
    """
    return {key: value for key, value in values.items() if value or value == 0}
