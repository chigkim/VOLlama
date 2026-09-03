from Settings import active_preset, defaults, save_presets

INTS = ["max_tokens", "seed"]
FLOATS = ["temperature", "top_p", "presence_penalty", "frequency_penalty"]


def default_parameters():
    return defaults()["parameters"]


def reconcile(parameters):
    """Add parameters new to this version, drop ones that no longer exist."""
    default = default_parameters()
    for key, value in default.items():
        if key not in parameters:
            parameters[key] = value
    for key in list(parameters):
        if key not in default:
            del parameters[key]
    return parameters


def parse_value(key, text, previous):
    """Turn one text control's contents into a parameter value."""
    if text == "":
        return None
    if key in INTS:
        return int(text)
    if key in FLOATS:
        return float(text)
    if isinstance(previous, list):
        value = text.split(", ")
        return [] if value == [""] else value
    return text


def get_parameters():
    """Generation options from the active preset, ready for the LLM client."""
    preset = active_preset()
    if not preset:
        return {}
    parameters = preset.get("parameters")
    if not parameters:
        parameters = default_parameters()
    before = dict(parameters)
    reconcile(parameters)
    preset["parameters"] = parameters
    if parameters != before:
        save_presets()
    options = {}
    for key, value in parameters.items():
        if value["value"] == []:
            continue
        options[key] = value["value"]
    return options
