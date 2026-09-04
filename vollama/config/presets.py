"""Presets: the unit of configuration.

A preset owns everything about talking to one model on one server — base URL,
api key, model name, context window, system prompt and generation parameters.
There is no separate connection dialog and no per-provider branching, because
every endpoint takes the same OpenAI-compatible path; what differs between them
is exactly the fields below.

This module owns the rules as well as the shape. Whether a preset is usable,
whether a name is free, and which preset becomes active when the current one is
deleted are decisions about presets, not about dialogs, so the editor calls into
here rather than implementing them a second time.
"""

import copy
from dataclasses import dataclass, field

from vollama.config import parameters
from vollama.config.settings import settings
from vollama.errors import ConfigError

# What we assume a model holds when a preset does not say. Only ever used to
# decide when to compact and how much retrieved text to send; it is never sent
# to the server, so guessing low is safe and guessing high is not.
DEFAULT_CONTEXT_WINDOW = 8192


@dataclass
class Preset:
    """One server, one model, and how to talk to it."""

    # No default server. A Preset with nothing filled in must fail validate(),
    # and a base URL that is there by default makes half of that check silently
    # pass; the editor is where a helpful starting URL belongs.
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    context_window: int = DEFAULT_CONTEXT_WINDOW
    system: str = ""
    parameters: dict = field(default_factory=parameters.defaults)

    @classmethod
    def from_dict(cls, data):
        preset = cls(
            base_url=str(data.get("base_url") or ""),
            api_key=str(data.get("api_key") or ""),
            model=str(data.get("model") or ""),
            context_window=_whole(data.get("context_window")),
            system=str(data.get("system") or ""),
            parameters=copy.deepcopy(data.get("parameters") or {}),
        )
        parameters.reconcile(preset.parameters)
        return preset

    def to_dict(self):
        return {
            "base_url": self.base_url,
            "api_key": self.api_key,
            "model": self.model,
            "context_window": self.context_window,
            "system": self.system,
            "parameters": self.parameters,
        }

    def options(self):
        """The generation parameters that are set, ready for the request."""
        return parameters.options(self.parameters)

    def validate(self):
        """Raise ConfigError if this preset cannot be used to hold a chat.

        One rule, checked here, so the editor and the chat agree on what a
        usable preset is. They did not before: the editor required a name and a
        base URL, the chat required a base URL and a model, and a preset saved
        without a model failed only when you tried to use it.
        """
        if not self.base_url.strip():
            raise ConfigError("This preset has no base URL.")
        if not self.model.strip():
            raise ConfigError("This preset has no model.")


def _whole(value):
    try:
        return int(value) or DEFAULT_CONTEXT_WINDOW
    except (TypeError, ValueError):
        return DEFAULT_CONTEXT_WINDOW


def names():
    """Every preset name, in the order they are shown."""
    return sorted(settings.presets)


def get(name):
    """One preset by name, or None."""
    data = settings.presets.get(name)
    return Preset.from_dict(data) if isinstance(data, dict) else None


def active_name():
    """The name of the active preset, correcting a stale one on the way past.

    A settings file can name a preset that has since been deleted, so the first
    preset stands in for it. Corrected here rather than at each call site, since
    every one of them would have to make the same choice.
    """
    if settings.active_preset in settings.presets:
        return settings.active_preset
    remaining = names()
    if not remaining:
        return ""
    settings.active_preset = remaining[0]
    settings.save()
    return settings.active_preset


def active():
    """The active preset, or None when none are configured yet."""
    return get(active_name())


def require_active():
    """The active preset, validated, for code about to use it.

    The same rule as `Preset.validate`, with the way out added: the editor shows
    the bare sentence because the user is already in the place that fixes it,
    and everywhere else has to say where that place is.
    """
    preset = active()
    if preset is None:
        raise ConfigError("No preset configured. Press control+p to create one.")
    try:
        preset.validate()
    except ConfigError as e:
        raise ConfigError(f"{e} Press control+p to edit it.") from None
    return preset


def context_window():
    """How many tokens the active preset's model holds.

    A preset field, not a global one, because it describes one model on one
    server. It is never sent: VOLlama uses it to decide when to compact the
    conversation and to size retrieval prompts.
    """
    preset = active()
    return preset.context_window if preset else DEFAULT_CONTEXT_WINDOW


def create(name, preset):
    """Add a new preset and make it active. The name must be free."""
    name = _named(name)
    if name in settings.presets:
        raise ConfigError(f"A preset named {name} already exists.")
    _write(name, preset)


def update(name, new_name, preset):
    """Replace a preset, renaming it if new_name differs, and make it active."""
    new_name = _named(new_name)
    if new_name != name and new_name in settings.presets:
        raise ConfigError(f"A preset named {new_name} already exists.")
    settings.presets.pop(name, None)
    _write(new_name, preset)


def delete(name):
    """Remove a preset. The first of what is left becomes active."""
    settings.presets.pop(name, None)
    remaining = names()
    settings.active_preset = remaining[0] if remaining else ""
    settings.save()


def activate(name):
    """Make an existing preset the active one."""
    if name in settings.presets:
        settings.active_preset = name
        settings.save()


def _named(name):
    name = (name or "").strip()
    if not name:
        raise ConfigError("Enter a name for this preset.")
    return name


def _write(name, preset):
    settings.presets[name] = preset.to_dict()
    settings.active_preset = name
    settings.save()
