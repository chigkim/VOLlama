"""Everything that knows the shape of an OpenAI streaming chunk.

The rest of the chat layer works in `Message`s. This module is the seam where
the wire format is turned into them, and it is the only place that reads a
chunk. Keeping that here is what lets the turn loop be read without knowing
anything about the protocol, and lets the protocol be tested with dictionaries
instead of a server.

Every chunk is turned into a plain dict first. The library parses the fields it
knows into a model and leaves the rest in the model's extras, so a vendor field
is reached one way and a standard one another; `model_dump()` puts them back on
the same footing, and a fixture in a test is then the same thing the reader
sees at run time.

The reader that is not obvious is `Calls`. A tool call arrives in fragments
spread over many chunks — the name in one, the arguments a few characters at a
time — and they have to be joined by the index they carry rather than by the
order they turn up in, since fragments of different calls interleave. Joining
them here is also what keeps Gemini's thought signature: its thinking models
sign every function call and carry the signature as `tool_calls[i]
.extra_content.google.thought_signature`, and a call sent back without it is
refused — *Function call is missing a thought_signature* — which kills every
turn in which the model calls a tool.
"""


def plain(chunk):
    """One chunk as a dict, whatever the library handed us."""
    dump = getattr(chunk, "model_dump", None)
    return dump() if callable(dump) else dict(chunk or {})


def choices(chunk):
    """The chunk's choices, or [] if it carries none.

    The extra chunk `include_usage` adds at the end has an empty list, so "no
    choices" is a normal thing for a chunk to have rather than a failure.
    """
    return chunk.get("choices") or []


def delta(chunk):
    """What this chunk adds to the reply, or {}."""
    found = choices(chunk)
    return (found[0].get("delta") or {}) if found else {}


def text_of(chunk):
    """(answer text, reasoning text) in one chunk.

    Reasoning arrives on a key of its own so it can be shown differently, or
    not at all. Two names for it, because there are two conventions and no
    standard.
    """
    part = delta(chunk)
    reasoning = part.get("reasoning_content") or part.get("reasoning") or ""
    return part.get("content") or "", reasoning if isinstance(reasoning, str) else ""


def finish_reason(chunk):
    """Why the server stopped, or "" if this chunk did not say.

    Only one chunk of a stream carries it, and it is not the last one, so the
    caller keeps the last non-empty answer rather than reading the final chunk.
    """
    found = choices(chunk)
    return (found[0].get("finish_reason") or "") if found else ""


def usage_of(chunk):
    """(prompt, completion, cached prompt tokens) reported, or None.

    Present only on the extra chunk `stream_options={"include_usage": True}`
    asks for, and only from servers that honour it. `cached_tokens` is the part
    of the prompt the server had already processed, and is 0 wherever it is not
    reported: it lives under `prompt_tokens_details`, which OpenAI fills in and
    llama.cpp, Ollama and MLX leave out entirely.
    """
    usage = chunk.get("usage")
    if not usage:
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if prompt is None and completion is None:
        return None
    details = usage.get("prompt_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    return int(prompt or 0), int(completion or 0), cached


class Calls:
    """The tool calls in a stream, joined back together as they arrive."""

    def __init__(self):
        self.calls = {}

    def add(self, chunk):
        for position, fragment in enumerate(delta(chunk).get("tool_calls") or []):
            index = fragment.get("index")
            call = self.calls.setdefault(
                index if index is not None else position,
                {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )
            call["id"] = fragment.get("id") or call["id"]
            function = fragment.get("function") or {}
            call["function"]["name"] += function.get("name") or ""
            # Character by character, which is why this is +=: the arguments of
            # one call are split across as many chunks as the model needs.
            call["function"]["arguments"] += function.get("arguments") or ""
            if fragment.get("extra_content"):
                # A vendor field. It rides along on the call dict because that
                # is what goes back out, unchanged, in the next request.
                call["extra_content"] = fragment["extra_content"]

    def done(self):
        """The calls, in the order the model made them.

        A call with no name is dropped: it is a fragment of something that was
        never finished, and a call the server cannot run is worse than no call.
        An id is invented where the server sent none, since the tool result has
        to name the call it answers.
        """
        made = []
        for position, index in enumerate(sorted(self.calls)):
            call = self.calls[index]
            if not call["function"]["name"]:
                continue
            call["id"] = call["id"] or f"call_{position}"
            made.append(call)
        return made
