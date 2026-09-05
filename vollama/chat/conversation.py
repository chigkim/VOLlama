"""The conversation: every message, and what of it the server is shown.

Two different things, which is the point of the module. `messages` is the whole
chat and never loses anything — it is what the transcript shows, what Save
writes, and what alt+up walks. `outgoing()` is what goes on the wire, and it is
allowed to leave things out: a summary standing in for the first half, and the
tool calls from turns before this one.

Nothing here talks to a server or to a screen, so all of it can be tested with
lists.
"""

import copy

from vollama.chat.message import Message

# Markers on messages we made up rather than received. `extra` is never sent,
# so neither reaches the server; they are here so the UI can tell these apart
# from something the user actually typed.
BACKGROUND = "background"  # a background command that ended between turns
SUMMARY = "summary"  # the handoff summary standing in for older messages

# The model's own thinking, kept beside the answer it led to. On the message
# rather than in its content so the transcript, Save and a re-render all still
# have it, while the request it goes back in leaves it out: `extra` is not sent,
# and the point of a reasoning model is that it thinks again rather than being
# handed what it thought last time.
REASONING = "reasoning"

# The keys of a saved chat. The messages used to be the whole file, a bare
# list; a file that is still one loads as exactly that and nothing else, which
# is all an older save has to say.
MESSAGES = "messages"
SUMMARY_AT = "summary_at"  # SUMMARY is the same key here as it is on a message

# What `extra` is called in a saved chat: the same thing it is called here.
# It used to be written out as `additional_kwargs`, named after the field of
# llama_index's ChatMessage that this layer replaced — a key in the user's own
# files named after a class the program no longer contains.
EXTRA = "extra"

# How many of your messages back tool calls and their results are still sent.
# 1 means the turn in progress only.
KEEP_TOOL_TURNS = 1


class Conversation:
    """Every message of one chat, and the rules for what the server sees."""

    def __init__(self, system=""):
        self.messages = []
        # What everything before summary_at was compacted into. The summary is
        # spliced in on the way out rather than replacing anything, so the
        # transcript and the saved file keep the whole chat.
        self.summary = ""
        self.summary_at = 0
        self.set_system(system)

    # ---------------------------------------------------------------- adding

    def set_system(self, system):
        """Put this system prompt at the front, replacing one already there."""
        if not system:
            if self.messages and self.messages[0].role == "system":
                del self.messages[0]
            return
        message = Message("system", system)
        if self.messages and self.messages[0].role == "system":
            self.messages[0] = message
        else:
            self.messages.insert(0, message)

    def add(self, message):
        self.messages.append(message)
        return message

    def add_user(self, content, marker=None):
        kwargs = {marker: True} if marker else {}
        return self.add(Message("user", content, kwargs))

    def add_assistant(self, text, tool_calls=(), reasoning=""):
        kwargs = {}
        if tool_calls:
            kwargs["tool_calls"] = list(tool_calls)
        if reasoning:
            kwargs[REASONING] = reasoning
        return self.add(Message("assistant", (text or "").strip(), kwargs))

    def add_tool_result(self, call_id, name, result):
        return self.add(
            Message("tool", result, {"tool_call_id": call_id, "name": name})
        )

    # -------------------------------------------------------------- outgoing

    def outgoing(self, environment=None, upto=None):
        """What this request goes out with.

        Anything before `summary_at` is replaced by the summary, which stands in
        for it as a message from the user: a model told it wrote that itself
        reads it as its own words and repeats them.

        Tool calls and results older than KEEP_TOOL_TURNS are dropped, because
        otherwise every command's output is resent on every later request and a
        session that ran a few chatty commands spends most of its context
        replaying them. A call and its result go together, since a call the
        server cannot match to a result makes the whole history unusable, and an
        assistant message that only carried a call goes with them while one that
        also said something keeps its text.

        `environment` is the description of this machine, or None. It is left
        out of the compaction request for the same reason that request drops the
        tool list: a model still being told how to run commands writes commands
        rather than prose.

        `upto` limits it to the first that many messages, which is how
        compaction asks for the half of the chat it is about to summarize.
        """
        messages = self.messages if upto is None else self.messages[:upto]
        if self.summary:
            cut = min(self.summary_at, len(messages))
            messages = (
                [m for m in messages[:cut] if m.role == "system"]
                + [Message("user", self.summary, {SUMMARY: True})]
                + list(messages[cut:])
            )

        starts = [i for i, m in enumerate(messages) if m.role == "user"]
        if len(starts) > KEEP_TOOL_TURNS:
            messages = _without_old_tool_rounds(messages, starts[-KEEP_TOOL_TURNS])
        return _with_environment(messages, environment)

    # ----------------------------------------------------------- compaction

    def compacted(self, summary, upto):
        """Replace everything before `upto` with this summary."""
        self.summary = summary
        self.summary_at = upto

    def reset_context(self):
        """Forget the summary, for when the messages it stood in for are gone."""
        self.summary = ""
        self.summary_at = 0

    def halfway(self):
        """A user-message boundary about midway to the end, or None.

        The overflow path cannot summarize everything at once: that request
        would carry the same history the server just refused. Halving it is the
        cheapest thing that might fit. The cut lands on one of the user's own
        messages, so a tool call is never separated from its result. None when
        fewer than two remain, since the cut would then land in front of the
        only one and summarize nothing.
        """
        starts = [
            i
            for i, m in enumerate(self.messages)
            if m.role == "user" and i > self.summary_at
        ]
        if len(starts) < 2:
            return None
        return starts[len(starts) // 2]

    def compactable(self):
        """Whether there is enough here for a summary to save anything.

        One message too big for the window on its own cannot be helped by
        summarizing what came before it.
        """
        return len(self.messages) - self.summary_at >= 2

    # ----------------------------------------------------------- editing

    def clear_last(self):
        """Drop everything from the last thing the user said, and return it.

        More than two messages when the model made tool calls in between, which
        is why this counts back to a user message rather than by a fixed number.
        """
        last = next(
            (
                i
                for i in reversed(range(len(self.messages)))
                if self.messages[i].role == "user"
            ),
            None,
        )
        if last is None:
            return ""
        text = self.messages[last].content or ""
        del self.messages[last:]
        self.reset_context()
        return text

    def drop_last(self):
        """Remove the final message. Used when a reply came back cut short."""
        del self.messages[-1:]

    def reviewable(self, index):
        """Whether alt+up may land here: something you or the model actually said.

        Tool results, the empty assistant message that carries a tool call, and
        reports about background commands are skipped, since there is nothing
        there to edit or resend.
        """
        if not 0 <= index < len(self.messages):
            return False
        message = self.messages[index]
        if message.role in ("tool", "system"):
            return False
        if message.extra.get(BACKGROUND):
            return False
        return bool((message.content or "").strip())

    # ------------------------------------------------------ saving and loading

    def to_json(self):
        """The chat as plain data: every message, and where the summary stands.

        Tool calls and their ids live in `extra`; without them a reloaded chat
        has tool results the server cannot match up.

        The summary is saved because it is not a cache of the messages: it is
        what the model wrote about them, and a chat that has been compacted
        several times cannot be sent without one. Saving the messages alone
        meant a reopened chat went out in full, was refused, and had to buy the
        summary again — from a different cut point, so it was not even the same
        summary. It is a field of the file rather than a message in the list
        because it stands in for messages that are all still there.
        """
        saved = {
            MESSAGES: [
                {
                    "role": message.role,
                    "content": message.content,
                    **({EXTRA: copy.deepcopy(message.extra)} if message.extra else {}),
                }
                for message in self.messages
            ]
        }
        if self.summary:
            saved[SUMMARY] = self.summary
            saved[SUMMARY_AT] = self.summary_at
        return saved

    def load_json(self, data):
        """Replace the chat with one that was saved.

        A bare list is a chat saved before the summary was written out, and is
        read as the messages with nothing compacted — which is what it holds.
        """
        if isinstance(data, list):
            data = {MESSAGES: data}
        self.messages = [
            Message(
                item["role"],
                item.get("content") or "",
                item.get(EXTRA) or {},
            )
            for item in data.get(MESSAGES) or []
        ]
        self.reset_context()
        summary = str(data.get(SUMMARY) or "")
        if summary:
            # Clamped rather than trusted: the cut is an index into the list
            # that was saved beside it, and a file edited by hand can put it
            # past the end, where it would swallow the whole chat.
            at = data.get(SUMMARY_AT)
            at = at if isinstance(at, int) and at >= 0 else 0
            self.compacted(summary, min(at, len(self.messages)))


def _without_old_tool_rounds(messages, cut):
    kept = []
    for i, message in enumerate(messages):
        if i >= cut:
            kept.append(message)
            continue
        if message.role == "tool":
            continue
        if message.extra.get("tool_calls"):
            if not (message.content or "").strip():
                continue
            message = Message(message.role, message.content)
        kept.append(message)
    return kept


def _with_environment(messages, environment):
    """Add what the machine looks like, after the preset's own system prompt.

    A system message of its own rather than part of the preset's: that prompt is
    the user's to write and this is not, and it has to be built fresh for every
    request since the working directory and the date both move while the app is
    open. It goes after any system messages so it cannot shift `summary_at`.
    """
    if not environment:
        return messages
    at = 0
    while at < len(messages) and messages[at].role == "system":
        at += 1
    return (
        messages[:at]
        + [Message("system", environment)]
        + messages[at:]
    )
