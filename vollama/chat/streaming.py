"""Everything that knows the shape of an OpenAI streaming chunk.

The rest of the chat layer works in `ChatMessage`s. This module is the seam
where a provider's wire format is turned into them, and it is the only place
that reaches into `chunk.raw`. Keeping that in one module is what lets the turn
loop be read without knowing anything about the protocol, and lets the protocol
be tested with dictionaries instead of a server.

Two things here are not obvious and both are hard-won:

Servers answer with pydantic models or with plain dictionaries depending on the
library version and the endpoint, so every read goes through `field()`.

Gemini's thinking models sign every function call, and its OpenAI-compatible
endpoint carries the signature as `tool_calls[i].extra_content.google
.thought_signature`. Send the call back without it and the next request is
refused — *Function call is missing a thought_signature* — so every turn in
which the model calls a tool dies on its second request. It is lost by default
twice over: the openai library parses an unknown key into the model's extras
rather than into a field, and llama_index merges the streamed fragments by
copying across the fields it knows about. So `collect_extras` reads it off the
raw chunks itself and `tool_calls_of` puts it back.
"""


def field(obj, name, default=None):
    """Read name off an object or a dict, whichever the server library gave us."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def plain(value):
    """A pydantic model as the dict it was parsed from, or the value unchanged."""
    dump = getattr(value, "model_dump", None)
    return dump() if callable(dump) else value


def choices(chunk):
    """The raw choices on a streamed chunk, or [] if it carries none.

    The usage chunk that `stream_options` adds at the end has an empty list, so
    "no choices" is a normal thing for a chunk to have rather than a failure.
    """
    raw = getattr(chunk, "raw", None)
    found = getattr(raw, "choices", None)
    if found is None and isinstance(raw, dict):
        found = raw.get("choices")
    return found or []


def extra_content(call):
    """The vendor fields hung off one streamed tool call fragment, if any.

    Both places are checked because a server that answers with plain dicts has
    it as a key, and the openai library has it in `model_extra`.
    """
    if isinstance(call, dict):
        return call.get("extra_content")
    found = getattr(call, "extra_content", None)
    if found is None:
        found = (getattr(call, "model_extra", None) or {}).get("extra_content")
    return plain(found)


def collect_extras(chunk, extras):
    """Remember this chunk's vendor tool-call fields, keyed by the call's index.

    By index rather than by arrival, since a fragment can belong to any call in
    progress and the field can arrive on any fragment of one.
    """
    found_choices = choices(chunk)
    if not found_choices:
        return
    delta = field(found_choices[0], "delta")
    for i, call in enumerate(field(delta, "tool_calls") or []):
        found = extra_content(call)
        if found:
            index = field(call, "index")
            extras[index if index is not None else i] = found


def tool_calls_of(chunk, extras=None):
    """Tool calls accumulated on the last streamed chunk, as OpenAI dicts.

    llama_index merges the streamed fragments for us, so the final chunk holds
    the whole list in `additional_kwargs`. What it does not hold is anything
    outside the OpenAI schema, which `collect_extras` saved.
    """
    message = getattr(chunk, "message", None)
    raw = field(getattr(message, "additional_kwargs", {}) or {}, "tool_calls") or []
    calls = []
    for i, call in enumerate(raw):
        function = field(call, "function") or {}
        name = field(function, "name") or ""
        if not name:
            continue
        index = field(call, "index")
        made = {
            "id": field(call, "id") or f"call_{i}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": field(function, "arguments") or "",
            },
        }
        found = (extras or {}).get(index if index is not None else i) or extra_content(call)
        if found:
            # to_openai_message_dict spreads additional_kwargs into the outgoing
            # message, so a call dict carrying this reaches the wire unchanged.
            made["extra_content"] = found
        calls.append(made)
    return calls


def finish_reason(chunk):
    """Why the server stopped, from one streamed chunk, or "" if it did not say.

    Only one chunk of a stream carries it, and it is not the last one, so the
    caller keeps the last non-empty answer rather than reading the final chunk.
    """
    found = choices(chunk)
    if not found:
        return ""
    return field(found[0], "finish_reason") or ""


def usage_of(chunk):
    """(prompt tokens, completion tokens) the server reported, or None.

    Present only on the extra chunk `stream_options={"include_usage": True}`
    asks for, and only from servers that honour it.
    """
    usage = getattr(getattr(chunk, "raw", None), "usage", None)
    if usage is None:
        return None
    prompt = field(usage, "prompt_tokens")
    completion = field(usage, "completion_tokens")
    if prompt is None and completion is None:
        return None
    return int(prompt or 0), int(completion or 0)


def text_of(chunk):
    """(answer text, reasoning text) in one streamed chunk.

    Reasoning arrives on its own key so it can be shown differently, or not at
    all. A plain string chunk is what the retrieval path yields.
    """
    if isinstance(chunk, str):
        return chunk, ""
    extra = getattr(chunk, "additional_kwargs", None) or {}
    reasoning = extra.get("thinking_delta") or ""
    return getattr(chunk, "delta", None) or "", reasoning
