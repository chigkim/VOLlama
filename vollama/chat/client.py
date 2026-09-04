"""Building the one LLM client, from the active preset.

Every endpoint VOLlama talks to — Ollama, llama.cpp, LM Studio, vLLM, OpenAI,
Gemini's OpenAI-compatible endpoint — is reached through this single path. There
is no provider interface and no per-provider branching, because there is nothing
for one to do: what differs between those servers is the base URL, the key and
the model name, which is exactly what a preset holds.

The `openai` library, directly. It was reached through llama_index's OpenAILike
before, which is one wrapper too many for what is asked of it here: a request
of our own messages with our own parameters, and a stream read back. What the
wrapper added was a `ChatMessage` type whose serializer sent fields we did not
mean to send, a `temperature` of its own in every request whether or not the
preset set one, and a merge of the streamed tool-call fragments that dropped
the vendor fields on them. Each of those was worked around here; none of them
is a problem the library below it has.

A fresh client per request. Presets can be switched, edited or have a parameter
changed between one message and the next, and building the client from the
preset each time is cheaper than keeping one in step with the settings.
"""

import tiktoken
from openai import OpenAI

# Imported for their side effect, not their names: PyInstaller cannot see that
# tiktoken loads its encodings through a plugin module, so a frozen build has no
# tokenizer unless this is spelled out.
import tiktoken_ext  # noqa: F401
from tiktoken_ext import openai_public  # noqa: F401

from vollama.config.settings import settings

# Generation parameters every OpenAI-compatible endpoint understands. Anything
# else in the schema stays local and is never sent, because these go out as
# top-level fields of the request and a name the server does not know raises
# rather than being ignored.
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

# The tokenizer the estimates use. Not the tokenizer any of these models
# actually has, so everything counted with it is an estimate and every caller
# has to leave itself room for being wrong.
ENCODING = "gpt-3.5-turbo"


class Client:
    """One endpoint, one model, and the parameters this preset asked for.

    `options` holds only what the preset set. An empty Temperature box has to
    mean *whatever the server would do on its own*: sending a default of ours
    overrides that silently, and some models reject the parameter outright —
    *temperature is deprecated for this model* — which fails the whole request
    over a value the user never chose and cannot see.
    """

    def __init__(self, api, model, options, tools=None, max_tokens=None):
        self.api = api
        self.model = model
        self.options = dict(options)
        self.tools = list(tools) if tools else None
        self.max_tokens = max_tokens

    def _request(self, messages, **extra):
        request = {
            "model": self.model,
            "messages": [message.to_wire() for message in messages],
            **self.options,
            **extra,
        }
        if self.max_tokens:
            request["max_tokens"] = self.max_tokens
        if self.tools:
            request["tools"] = self.tools
        return request

    def stream(self, messages):
        """The reply, as the chunks it arrives in.

        `include_usage` asks for the numbers alongside the stream. Servers that
        do not support it ignore it, which is why there is an estimate to fall
        back on.
        """
        return self.api.chat.completions.create(
            **self._request(
                messages, stream=True, stream_options={"include_usage": True}
            )
        )

    def complete(self, messages):
        """The whole reply as text, for a request nobody is watching arrive."""
        answer = self.api.chat.completions.create(**self._request(messages))
        choices = answer.choices or []
        return (choices[0].message.content or "") if choices else ""


def tools_enabled():
    """Whether the model is allowed to call tools.

    One switch for the whole application, on the Chat menu, rather than a preset
    field: it answers "do I want the model touching this machine right now",
    which changes mid-chat, not "which server is this".
    """
    return bool(settings.tools)


def count(text):
    """Roughly how many tokens `text` is, for a decision made before sending."""
    return len(tiktoken.encoding_for_model(ENCODING).encode(text))


def count_messages(messages):
    """Roughly what this request costs, for a server that reports no usage.

    Text only, and nothing for the shape the messages are sent in, so it reads
    a little low. It stands in for the server's own number in the one place
    that has to have one: deciding when the window is nearly full.
    """
    return count("\n".join(message.countable() for message in messages))


def build(preset, tools=None):
    """A client for this preset. `preset.validate()` has already been called.

    `tools` is the schema list to offer, or None for a request that must be
    answered in prose. Passing it here rather than setting it on a shared
    client is what lets compaction ask for a summary without disturbing the
    client the conversation is using.
    """
    options = preset.options()
    return Client(
        api=OpenAI(
            base_url=preset.base_url,
            api_key=preset.api_key or "none",
            timeout=TIMEOUT,
        ),
        model=preset.model,
        options={k: v for k, v in options.items() if k in OPENAI_PARAMS},
        tools=tools,
        max_tokens=options.get("max_tokens"),
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
