"""Presets: the unit of configuration.

A preset owns everything about talking to one model on one server — base URL,
api key, model name, context window, system prompt, generation parameters, and
the embedding endpoint and retrieval settings that go with them. There is no
separate connection dialog and no per-provider branching, because every
endpoint takes the same OpenAI-compatible path; what differs between them is
exactly the fields below.

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

# What a preset embeds with when it does not say. Unlike `base_url`, this one
# does have a default: `validate()` does not check it, so a default here cannot
# make an empty preset half pass, and a preset with nothing in this field can
# index nothing at all.
DEFAULT_EMBEDDING_URL = "http://localhost:11434/v1/"
DEFAULT_EMBEDDING_MODEL = "EmbeddingGemma"


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

    # The embedding endpoint and how much text to retrieve from it. Here
    # rather than global because a preset is a server: the endpoint that
    # serves the chat model is usually the one serving the embedding model,
    # and pointing every preset at one embedding URL meant that switching
    # from a local model to a hosted one left retrieval talking to a server
    # that was no longer running. Switching preset does not re-embed what is
    # already indexed; see `rag.index.RagIndex._configure`.
    embedding_base_url: str = DEFAULT_EMBEDDING_URL
    embedding_api_key: str = ""
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    chunk_size: int = 1024
    chunk_overlap: int = 20
    similarity_top_k: int = 2
    similarity_cutoff: float = 0.0

    @classmethod
    def from_dict(cls, data):
        preset = cls(
            base_url=str(data.get("base_url") or ""),
            api_key=str(data.get("api_key") or ""),
            model=str(data.get("model") or ""),
            context_window=_whole(data.get("context_window")),
            system=str(data.get("system") or ""),
            parameters=copy.deepcopy(data.get("parameters") or {}),
            embedding_base_url=str(
                data.get("embedding_base_url") or DEFAULT_EMBEDDING_URL
            ),
            embedding_api_key=str(data.get("embedding_api_key") or ""),
            embedding_model=str(data.get("embedding_model") or DEFAULT_EMBEDDING_MODEL),
            chunk_size=_whole(data.get("chunk_size"), 1024),
            chunk_overlap=_number(data.get("chunk_overlap"), int, 20),
            similarity_top_k=_whole(data.get("similarity_top_k"), 2),
            similarity_cutoff=_number(data.get("similarity_cutoff"), float, 0.0),
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
            "embedding_base_url": self.embedding_base_url,
            "embedding_api_key": self.embedding_api_key,
            "embedding_model": self.embedding_model,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "similarity_top_k": self.similarity_top_k,
            "similarity_cutoff": self.similarity_cutoff,
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


def _whole(value, default=DEFAULT_CONTEXT_WINDOW):
    """A positive whole number from the file, or the default. 0 is not one."""
    return _number(value, int, default) or default


def _number(value, kind, default):
    """A number from the file, whatever a hand-edited file put in the field."""
    try:
        return kind(value)
    except (TypeError, ValueError):
        return default


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


def retrieval():
    """The preset retrieval reads its settings from.

    The defaults stand in when no preset is configured, so building an index
    is not a second place that has to have an opinion about that: it will fail
    on the embedding request instead, where the reason is visible.
    """
    return active() or Preset()


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


def replace(items, active=""):
    """Replace every preset at once, and say which one is active.

    `items` is (name, preset) pairs. The manager edits the whole list, so it
    hands the whole list back, and that makes two things simple that are not
    otherwise: a name that is no longer here is a preset deleted, and two
    presets swapping names is one write rather than a rename that has to dodge
    the other. An `active` naming nothing falls to the first preset there is,
    the same way `delete` chooses.
    """
    written = {}
    for name, preset in items:
        name = _named(name)
        if name in written:
            raise ConfigError(f"There are two presets named {name}.")
        written[name] = preset.to_dict()
    settings.presets = written
    remaining = names()
    if active not in written:
        active = remaining[0] if remaining else ""
    settings.active_preset = active
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
