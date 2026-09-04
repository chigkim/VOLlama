"""The generation parameters a preset can set, and what they mean.

The schema is data, not code: `default-parameters.json` holds one entry per
parameter with its default value, a sentence describing it and its range. The
preset editor builds its controls from that, so adding a parameter is an edit to
the file rather than to a dialog.

An unset parameter is `None`, and `None` means *not sent*. That is the rule the
whole module exists to keep: an empty box in the editor must leave the decision
to the server rather than quietly substituting our idea of a default.
"""

import copy
import json

from vollama.resources import bundled

# Parameters whose text is read as a number. Everything else is text, a list of
# text, or a checkbox, and is read from the shape of its current value.
INTEGERS = ("max_tokens", "seed")
DECIMALS = ("temperature", "top_p", "presence_penalty", "frequency_penalty")

with open(bundled("default-parameters.json"), encoding="utf-8") as _file:
    # Read once at import: the file ships with the application and cannot
    # change while it runs, and re-reading it per request was costing a disk
    # read in the middle of building every chat message.
    SCHEMA = json.load(_file)


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
