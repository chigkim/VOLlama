"""Building the one LLM client, from the active preset.

Every endpoint VOLlama talks to — Ollama, llama.cpp, LM Studio, vLLM, OpenAI,
Gemini's OpenAI-compatible endpoint — is reached through this single path. There
is no provider interface and no per-provider branching, because there is nothing
for one to do: what differs between those servers is the base URL, the key and
the model name, which is exactly what a preset holds.

A fresh client per request. Presets can be switched, edited or have a parameter
changed between one message and the next, and building the client from the
preset each time is cheaper than keeping one in step with the settings.
"""

import tiktoken
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from llama_index.llms.openai_like import OpenAILike
from openai import OpenAI

# Imported for their side effect, not their names: PyInstaller cannot see that
# tiktoken loads its encodings through a plugin module, so a frozen build has no
# tokenizer unless this is spelled out.
import tiktoken_ext  # noqa: F401
from tiktoken_ext import openai_public  # noqa: F401

from vollama.config.settings import settings

# Generation parameters every OpenAI-compatible endpoint understands. Anything
# else in the schema stays local and is never sent, because additional_kwargs
# are spread as top-level keyword arguments into chat.completions.create() and
# a name the server does not know raises rather than being ignored.
OPENAI_PARAMS = frozenset(
    {
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "stop",
        "reasoning_effort",
    }
)

# How long to wait on a request. Generous, because a local model on a busy
# machine can take a very long time to answer and there is nothing to gain by
# giving up on it: the user has a Stop button.
TIMEOUT = 3600


class Client(OpenAILike):
    """OpenAILike, minus the parameter it sends whether or not you asked.

    llama_index puts `temperature` into every request unconditionally: it is a
    constructor field with a default of its own rather than part of
    additional_kwargs, so a preset with the Temperature box left empty still
    sent 0.1. That is wrong twice over. It quietly overrides whatever default
    the server would have used, which is the one thing an empty box should
    mean, and some models reject the parameter outright — *temperature is
    deprecated for this model* — which fails the whole request over a value the
    user never set and cannot see.

    Whether the preset set one is read off additional_kwargs rather than kept as
    a flag of its own, since that dict is what actually goes out and the two
    cannot then drift apart.
    """

    def _get_model_kwargs(self, **kwargs):
        options = super()._get_model_kwargs(**kwargs)
        if "temperature" not in self.additional_kwargs:
            options.pop("temperature", None)
        return options


def tools_enabled():
    """Whether the model is allowed to call tools.

    One switch for the whole application, on the Chat menu, rather than a preset
    field: it answers "do I want the model touching this machine right now",
    which changes mid-chat, not "which server is this".
    """
    return bool(settings.tools)


def token_counter():
    """A handler that counts tokens, for servers that report no usage of their own."""
    return TokenCountingHandler(
        tokenizer=tiktoken.encoding_for_model("gpt-3.5-turbo").encode
    )


def build(preset, tools=None, counter=None):
    """A client for this preset. `preset.validate()` has already been called.

    `tools` is the schema list to offer, or None for a request that must be
    answered in prose. Passing it here rather than mutating a shared client's
    additional_kwargs is what lets compaction ask for a summary without
    disturbing the client the conversation is using.
    """
    options = preset.options()
    additional = {k: v for k, v in options.items() if k in OPENAI_PARAMS}
    # Ask for the usage numbers alongside the stream. Servers that do not
    # support it ignore it, which is why there is a token-counting fallback.
    additional["stream_options"] = {"include_usage": True}
    if tools:
        additional["tools"] = list(tools)
    return Client(
        model=preset.model,
        api_base=preset.base_url,
        api_key=preset.api_key or "none",
        context_window=preset.context_window,
        is_chat_model=True,
        timeout=TIMEOUT,
        max_tokens=options.get("max_tokens"),
        additional_kwargs=additional,
        callback_manager=CallbackManager([counter] if counter else []),
    )


def max_output(preset):
    """The reply length this preset asked for, or 0 if it did not ask."""
    try:
        return int(preset.options().get("max_tokens") or 0)
    except (TypeError, ValueError):
        return 0


def fetch_models(base_url, api_key):
    """Model ids an OpenAI-compatible endpoint offers, or [] if it lists none."""
    client = OpenAI(base_url=base_url, api_key=api_key or "none")
    return sorted(model.id for model in client.models.list().data if model.id)
