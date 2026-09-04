"""The generation parameters a preset can set, and what they mean.

The schema is data, not code: `SCHEMA` holds one entry per parameter with its
default value, a sentence describing it and its range. The preset editor builds
its controls from that, so adding a parameter is an edit to this table rather
than to a dialog.

An unset parameter is `None`, and `None` means *not sent*. That is the rule the
whole module exists to keep: an empty box in the editor must leave the decision
to the server rather than quietly substituting our idea of a default.
"""

import copy

# Parameters whose text is read as a number. Everything else is text, a list of
# text, or a checkbox, and is read from the shape of its current value.
INTEGERS = ("max_tokens", "seed")
DECIMALS = ("temperature", "top_p", "presence_penalty", "frequency_penalty")

SCHEMA = {
    "max_tokens": {
        "value": None,
        "description": "Maximum number of tokens to generate in the response.",
        "range": "Integer value, empty for the model default",
    },
    "temperature": {
        "value": None,
        "description": "Increasing the temperature will make the model answer more creatively.",
        "range": "0.0-2.0",
    },
    "top_p": {
        "value": None,
        "description": "Nucleus sampling. A higher value will lead to more diverse text, while a lower value will generate more focused and conservative text.",
        "range": "0.0-1.0",
    },
    "presence_penalty": {
        "value": None,
        "description": "Penalizes new tokens based on their presence in the text so far.",
        "range": "-2.0-2.0",
    },
    "frequency_penalty": {
        "value": None,
        "description": "Penalizes new tokens based on their frequency in the text so far.",
        "range": "-2.0-2.0",
    },
    "stop": {
        "value": [],
        "description": "When this pattern is encountered the LLM will stop generating text and return.",
        "range": "Array of strings",
    },
    "seed": {
        "value": None,
        "description": "Sets the random number seed to use for generation. Setting this to a specific number will make the model generate the same text for the same prompt.",
        "range": "Integer value",
    },
    "reasoning_effort": {
        "value": None,
        "description": "Sets the reasoning effort.",
        "range": "none, low, medium, high",
    },
}


def defaults():
    """A fresh copy of the full parameter set, all of it unset."""
    return copy.deepcopy(SCHEMA)


def reconcile(parameters):
    """Bring one preset's parameters up to date with the schema, in place.

    A preset saved by an older build is missing parameters added since, and
    holds ones that have been removed. Neither is an error worth troubling the
    user with, so the set is squared up on the way past. Values already set are
    left alone.
    """
    for key, value in SCHEMA.items():
        if key not in parameters:
            parameters[key] = copy.deepcopy(value)
    for key in list(parameters):
        if key not in SCHEMA:
            del parameters[key]
    return parameters


def parse_value(key, text, previous):
    """One editor field's text as a parameter value.

    Empty means unset, which is the whole point of the exercise. `previous` says
    what shape the value had, which is how a list is told from a string without
    a second table to keep in step with the schema.

    Raises ValueError on text that is not the number it has to be; the dialog
    catches it and says which field.
    """
    text = text.strip()
    if text == "":
        return None
    if key in INTEGERS:
        return int(text)
    if key in DECIMALS:
        return float(text)
    if isinstance(previous, list):
        items = [item.strip() for item in text.split(",") if item.strip()]
        return items
    return text


def options(parameters):
    """The parameters that are actually set, as name to value.

    Unset ones and empty lists are left out rather than sent as null, since a
    server reads a null temperature as a temperature.
    """
    return {
        key: entry["value"]
        for key, entry in parameters.items()
        if entry.get("value") is not None and entry.get("value") != []
    }
