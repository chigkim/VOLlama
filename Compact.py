"""Compaction: replace an old conversation with a handoff summary of it.

A chat that runs long enough stops fitting in the model's context window. The
server either errors or, worse, silently drops the oldest messages, so the model
forgets the start of the conversation without anyone being told.

So before that happens, the model is asked to summarize the conversation for a
copy of itself that will never see the original. What comes back stands in for
everything before the compaction point on the way out to the server. Nothing is
deleted: VOLlama still holds the whole chat for the transcript, for saving, and
for alt+up.
"""

import re

from llama_index.core.llms import ChatMessage


# Compact once the last exchange used this much of the context window. Low
# enough that the reply after it still has somewhere to go, since the summary
# request itself has to fit in the window too.
COMPACT_AT = 0.8


PROMPT = """Write a handoff summary of this conversation.

You are being replaced by a copy of yourself that will not see anything above
this line: the conversation so far is about to be removed and your summary put
in its place. Everything that copy needs in order to keep working has to be in
what you write now. Write it for the copy, not for the user. Do not address the
user and do not ask questions.

Use these sections, in this order, with these headings. Skip a section only when
it is genuinely empty.

1. Request
What the user asked for, in their own words as far as possible, including how
the goal changed along the way. State the current goal last, since that is the
one that matters.

2. Decisions
Every choice already settled, and why, especially the ones the user made or
approved. A decision recorded here will not be reopened, so record the ones your
replacement would otherwise be tempted to revisit.

3. What was done
What actually happened: files read or written, with their paths; commands run
and what they printed; facts established. Quote names, paths, numbers, versions,
identifiers and code exactly. A detail you paraphrase is a detail your
replacement has to go and find again.

4. What is true now
The state of the work: what is finished and checked, what is written but
untested, what is still broken. Say which is which. Include any background
command still running, with its session id.

5. Errors and corrections
Failures hit and what fixed them, and anything the user corrected you on.
Include approaches that were tried and abandoned, so they are not tried twice.

6. Next step
The one thing to do next, specific enough to start on without asking, and
whatever else is pending after it. If you stopped part way through something,
say exactly where.

7. How the user works
Language, tone, format and length they want, tools they do or do not want used,
and anything they told you to stop doing.

Rules:
- Facts from this conversation only. Do not guess, do not fill gaps, and do not
  smooth over something you are unsure of. Mark it uncertain instead.
- Length follows the conversation. A short exchange gets a short summary. Do not
  pad a thin section to make it look finished.
- Prefer the specific everywhere. "Set timeout to 30 in init_llm in Model.py"
  is worth more than "adjusted a timeout".
- Keep the most recent work in the most detail. Older finished work can shrink
  to its outcome.
- Quote output that still matters rather than describing it. Drop output that
  does not.
- Plain prose and lists. No preamble, no closing remarks, no offer to help."""


def needed(used, window):
    """Whether the last exchange came close enough to filling the window."""
    if not window or not used:
        return False
    return used >= window * COMPACT_AT


# What each server says when the conversation no longer fits. There is no
# standard wording and several do not say "context" at all, so this is a list of
# what they actually send back, taken from pi's overflow.ts.
OVERFLOW = [
    r"context[_ ]length[_ ]exceeded",  # the closest thing to a standard
    r"exceeds the context window",  # OpenAI
    r"exceeds (?:the )?(?:model'?s )?maximum context length",  # OpenAI-compatible proxies
    r"maximum context length is \d+ tokens",  # OpenRouter
    r"prompt is too long",  # Anthropic
    r"request_too_large",  # Anthropic, too many bytes rather than too many tokens
    r"input token count.*exceeds the maximum",  # Gemini
    r"maximum prompt length is \d+",  # xAI
    r"reduce the length of the messages",  # Groq
    r"exceeds the available context size",  # llama.cpp
    r"greater than the context length",  # LM Studio
    r"prompt too long; exceeded (?:max )?context length",  # Ollama
    r"is longer than the model'?s context length",  # Together
    r"too large for model with \d+ maximum context length",  # Mistral
    r"but the configured context size is",  # DS4
    r"exceeds the limit of \d+",  # GitHub Copilot
    r"exceeds (?:the )?maximum allowed input length",  # Poolside
    r"context window exceeds limit",  # MiniMax
    r"exceeded model token limit",  # Kimi
    r"range of input length should be",  # DashScope, Qwen
    r"reduce context",  # oMLX
    r"too many tokens",
    r"token limit exceeded",
    r"^4(?:00|13)\s*(?:status code)?\s*\(no body\)",  # Cerebras says nothing at all
]

# Checked first, because a server that is rate limiting you can use wording that
# looks like an overflow. Bedrock's throttling message is "Too many tokens,
# please wait before trying again", which matches the pattern above.
NOT_OVERFLOW = [
    r"throttl",
    r"rate limit",
    r"too many requests",
    r"^(?:throttling error|service unavailable):",
]


def overflowed(error):
    """Whether a failed request looks like the conversation not fitting."""
    text = str(error).lower()
    if any(re.search(p, text) for p in NOT_OVERFLOW):
        return False
    return any(re.search(p, text) for p in OVERFLOW)


def truncated(stop, output, limit, prompt, window):
    """Whether a reply that ended on "length" was cut short by the history.

    Two of these. A server can accept a prompt that is too long by silently
    cutting the front off it and then filling the window exactly, which leaves no
    room to answer: the reply comes back empty and successful. And a reply that
    stops short of the length you asked for stopped for some reason you did not
    ask for, context pressure being the usual one. Neither reports an error, so
    without this the user gets half an answer, or none, and no explanation.
    """
    if stop != "length":
        return False
    if limit and output < limit:
        return True
    return not output and window and prompt >= window * 0.99


def summarize(llm, messages):
    """Ask the model for a handoff summary of messages, and return its text."""
    request = list(messages) + [ChatMessage(role="user", content=PROMPT)]
    # The model has to answer this one in prose. Left with a tool list it may
    # well go and run something instead, and the turn ends with no summary.
    kwargs = llm.additional_kwargs
    llm.additional_kwargs = {k: v for k, v in kwargs.items() if k != "tools"}
    try:
        response = llm.chat(request)
    finally:
        llm.additional_kwargs = kwargs
    return (response.message.content or "").strip()
