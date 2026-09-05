"""One chat, and the loop that answers a message in it.

`ChatSession.ask` is the single path a message takes, whatever started it. It
sends the conversation, streams the reply, runs whatever tools the model asked
for, sends their results back, and does that until the model stops asking or
one of the budgets runs out. Around it sit the three things that keep a long
chat working: compaction when the window fills, a retry when the server refuses
the history as too long, and a retry when a reply comes back cut short.

It reports through a `ChatView` and knows nothing about how any of it is shown.
Errors are raised, not displayed: the caller has the context to decide whether
this is a dialog, a status line or a test failure.
"""

import itertools
import logging
import time
from dataclasses import dataclass

from vollama.chat import client, compaction, streaming, toolset
from vollama.chat.conversation import BACKGROUND, Conversation
from vollama.chat.message import Message, image_url
from vollama.chat.view import NullView, TurnStats
from vollama.config import presets
from vollama.errors import DocumentError
from vollama.rag import documents, search
from vollama.rag.index import RagIndex, describe_sources
from vollama.tools import registry
from vollama.tools.shell import cancellation, jobs

log = logging.getLogger(__name__)

# What a message must start with to be answered from the index instead of by
# the model alone.
RETRIEVAL_PREFIX = "/q "

# What to do about a retrieval prompt too big to answer. Said in two places —
# before sending, and after a server has answered an oversized prompt with
# nothing — so it is written once.
TOO_MUCH = (
    "A retrieval prompt is the question plus every chunk retrieved, so it may "
    "not have fit: lower Top K or the chunk size on this preset's RAG page, "
    "or raise its context window."
)

# How an attached document is joined to the message it came with.
DOCUMENT_SEPARATOR = "\n---\n"


@dataclass(frozen=True)
class Attachments:
    """What was attached to a message before it was sent.

    Frozen and passed in, rather than fields on the session poked by the UI
    beforehand: a turn should be able to say what it was given by looking at its
    own arguments. The window adds one kind at a time with
    `dataclasses.replace`, which is why this is a dataclass and not a class with
    three keyword arguments the caller has to repeat.
    """

    images: tuple = ()
    files: tuple = ()
    url: str = ""

    def __bool__(self):
        return bool(self.images or self.files or self.url)


NOTHING = Attachments()


class ChatSession:
    """One conversation, and the ability to add to it."""

    def __init__(self, system=""):
        self.conversation = Conversation(system)
        self.index = None
        self.generating = False
        self.usage = None
        # Why the server stopped the last reply, which is what tells a cut-off
        # answer from a finished one.
        self.finish_reason = ""
        # What the last request went out with, kept so the turn can be costed
        # when the server reports no usage of its own.
        self.sent = []
        # The tools this turn is offering. Set per turn, since search comes and
        # goes with the index and the Tools checkbox moves mid-chat.
        self.tools = []

    # -------------------------------------------------------------- the turn

    def ask(self, prompt, view=None, attachments=NOTHING):
        """Answer one message. Raises if the request cannot be made at all."""
        view = view or NullView()
        preset = presets.require_active()
        # Composed once for the turn: what is offered must not change between
        # the request that made a call and the one that answers it.
        self.tools = toolset.for_turn(self.index)
        llm = client.build(preset, tools=[tool.schema for tool in self.tools] or None)

        mark = len(self.conversation.messages)
        try:
            # So a command in its first seconds, before it goes to the
            # background, is cut short by the same Escape that stops the reply.
            # Only for the length of the turn: between turns nothing is being
            # waited on, and a stale stop flag would answer for the next
            # command anybody starts.
            with cancellation.watching(lambda: not self.generating):
                self._run_turn(prompt, attachments, llm, preset, view)
        except Exception:
            # The turn did not happen, so it should not be in the history: a
            # half-added turn is one the next request cannot send.
            del self.conversation.messages[mark:]
            raise
        finally:
            self.generating = False
            view.finished()

    def _run_turn(self, prompt, attachments, llm, preset, view):
        """One turn, from what the user typed to the model having nothing left."""
        self._report_background(view)
        message, retrieval = self._compose(prompt, attachments, view)
        self.conversation.add(message)
        self.generating = True
        if retrieval:
            self._answer_from_index(message.content, llm, preset, view)
        else:
            view.status("Processing...")
            self._converse(llm, preset, view)
        # Not after a retrieval turn: what it spent is the chunks retrieved for
        # it, which were never in the history and will not be in the next
        # request either, so summarizing the chat over them shrinks the one
        # thing that was not the problem.
        if self.generating and not retrieval:
            self._compact_if_full(preset, view)

    def stop(self):
        """Give up on the reply. Background commands keep running."""
        self.generating = False

    def restart(self, system=""):
        """Begin a new chat.

        The index is deliberately kept: New Chat is about the conversation, and
        rebuilding an index over a book because you wanted a fresh question is
        not what anybody means by it.
        """
        self.conversation = Conversation(system)
        self.usage = None
        self.finish_reason = ""

    def _converse(self, llm, preset, view):
        """Stream replies and run tools until the model has nothing more to ask."""
        response, started = self._send(llm, preset, view)
        rounds = 0
        calls = 0
        retried = False
        while True:
            text, reasoning, tool_calls = self._stream(response, view, started)
            self.conversation.add_assistant(text, tool_calls, reasoning)
            if not tool_calls:
                if self.generating and not retried and self._recover(preset, view):
                    retried = True
                    response, started = self._send(llm, preset, view)
                    continue
                return
            # A dangling tool call the server never sees an answer for makes the
            # whole history unusable, so every call gets a tool message even when
            # we are not going to run it.
            allowed = (
                self.generating
                and rounds < registry.MAX_TOOL_ROUNDS
                and calls < registry.MAX_TOOL_CALLS
            )
            calls += len(tool_calls)
            for call in tool_calls:
                self._run_tool(call, view, allowed)
            if not allowed:
                return
            # Polls and reads only look at work already there, so they do not
            # spend the budget: waiting for a build would otherwise use it all.
            if any(
                not registry.is_free(_name(call), self.tools) for call in tool_calls
            ):
                rounds += 1
            view.status("Processing...")
            response, started = self._send(llm, preset, view)

    def _run_tool(self, call, view, allowed):
        """Run one tool call, report it, and record its result as a message."""
        name = _name(call)
        arguments = call["function"]["arguments"]
        view.tool_called(registry.describe(name, arguments, self.tools))
        if allowed:
            view.status(f"Running {name}...")
            result = registry.call(name, arguments, self.tools)
        elif self.generating:
            result = "Not run: the limit on tool calls in one message was reached."
        else:
            result = "Not run: the user stopped generation."
        view.tool_result(result)
        self.conversation.add_tool_result(call["id"], name, result)
        if name == search.NAME and allowed:
            # What a search the model asked for was answered from, which is the
            # retrieval the user has least other way of seeing. Whether it is
            # printed is the view's to decide.
            view.sources(describe_sources(self.index.sources()))

    def _stream(self, response, view, started):
        """Consume one streamed reply.

        Returns its text, the thinking that came with it, and its tool calls.
        The thinking is collected as well as shown because it belongs to the
        message: a transcript re-rendered from the history, a saved chat and a
        chat reopened would otherwise all lose what the user had just read.
        """
        view.reply_started()
        first = 0.0
        answer = []
        thinking = []
        calls = streaming.Calls()
        usage = None
        self.finish_reason = ""
        for chunk in response:
            if not first:
                first = time.monotonic()
                view.status("Typing...")
            chunk = streaming.plain(chunk)
            calls.add(chunk)
            usage = streaming.usage_of(chunk) or usage
            text, reasoning = streaming.text_of(chunk)
            if reasoning:
                thinking.append(reasoning)
                view.reasoning_text(reasoning)
            if text:
                answer.append(text)
                view.reply_text(text)
            self.finish_reason = streaming.finish_reason(chunk) or self.finish_reason
            if not self.generating:
                break
        view.reply_finished()
        text = "".join(answer)
        self._record_usage(usage, started, first or time.monotonic(), view, text)
        return text, "".join(thinking), calls.done()

    def _record_usage(self, usage, started, first, view, text):
        """Note what the exchange cost, from the server or from our own count."""
        if usage is None and self.sent:
            # Not every server honours stream_options, so a local tokenizer
            # stands in. It is an estimate, and it is what compaction reads.
            usage = (client.count_messages(self.sent), client.count(text))
        if usage is None:
            self.usage = None
            view.status("Finished")
            return
        self.usage = TurnStats(
            prompt_tokens=usage[0],
            completion_tokens=usage[1],
            cached_tokens=usage[2] if len(usage) > 2 else 0,
            total_seconds=time.monotonic() - started,
            first_token_seconds=first - started,
        )
        view.stats(self.usage)

    # ------------------------------------------------------------- the request

    def _send(self, llm, preset, view):
        """Make the request, compacting and trying once more if it will not fit."""
        try:
            return self._start(llm, self.conversation.outgoing(toolset.environment()))
        except Exception as refusal:
            if not compaction.overflowed(refusal):
                raise
            # The server has just said the conversation no longer fits, so there
            # is nothing left to lose by summarizing it and asking again.
            upto = self.conversation.halfway()
            if upto is None:
                raise
            view.status("Too long for the model, compacting...")
            try:
                compacted = self.compact(preset, view, upto)
            except Exception:
                # A deliberate boundary: whatever went wrong trying to work
                # around the refusal, what the user needs to see is the refusal.
                log.exception("Compaction after an overflow failed")
                raise refusal from None
            if not compacted:
                raise
            return self._start(llm, self.conversation.outgoing(toolset.environment()))

    def _start(self, llm, messages):
        """Send the request and pull the first chunk.

        Pulled here because the stream is lazy: without it a request the server
        refuses fails somewhere in the middle of showing a reply, which is too
        late to compact and ask again.

        Returns the stream and the moment the request went out, which is when
        the turn's clock has to start: the first chunk is already in hand by the
        time anybody reads the stream, so a clock started there measures
        generation only and reports the prompt as having been processed
        instantly.

        What went out is kept, since costing the turn falls to us when the
        server reports no usage of its own.
        """
        self.sent = list(messages)
        started = time.monotonic()
        response = iter(llm.stream(messages))
        try:
            first = next(response)
        except StopIteration:
            return iter(()), started
        return itertools.chain([first], response), started

    def _recover(self, preset, view):
        """Compact and retry when a reply came back cut short. Once per turn.

        The truncated reply is dropped from the history the retry goes out with,
        since asking again with half an answer already in place invites the model
        to carry on from it rather than start over. It stays in the transcript,
        because the user has already read it and text that vanishes is worse than
        text that is explained.
        """
        if not compaction.truncated(
            self.finish_reason,
            self.usage.completion_tokens if self.usage else 0,
            client.max_output(preset),
            self.usage.prompt_tokens if self.usage else 0,
            preset.context_window,
        ):
            return False
        upto = self.conversation.halfway()
        if upto is None:
            return False
        view.notice(
            "Cut short: that reply ended early, which usually means the "
            "conversation is too long for the model. Compacting and asking again."
        )
        try:
            compacted = self.compact(preset, view, upto)
        except Exception as e:
            view.status(f"Could not compact: {e}")
            return False
        if not compacted:
            return False
        self.conversation.drop_last()
        return True

    # -------------------------------------------------------------- compaction

    def compact(self, preset=None, view=None, upto=None):
        """Replace the conversation up to `upto` with a summary of it.

        Returns whether the summary was made. The client is built without tools:
        a model left holding them goes and runs something instead of writing
        prose, and the turn ends with no summary.
        """
        view = view or NullView()
        preset = preset or presets.require_active()
        upto = len(self.conversation.messages) if upto is None else upto
        view.status("Compacting conversation...")
        summary = compaction.summarize(
            client.build(preset), self.conversation.outgoing(upto=upto)
        )
        if not summary:
            return False
        self.conversation.compacted(summary, upto)
        self.usage = None
        view.notice(
            "Compacted: the conversation so far was replaced with a summary of "
            f"it, {len(summary)} characters long."
        )
        view.status("Compacted")
        return True

    def _compact_if_full(self, preset, view):
        """Compact when the exchange that just finished nearly filled the window."""
        used = self.usage.total_tokens if self.usage else 0
        if not compaction.needed(used, preset.context_window):
            return
        if not self.conversation.compactable():
            return
        try:
            self.compact(preset, view)
        except Exception as e:
            # A failed summary is not a failed answer: the user already has one.
            log.exception("Compaction failed")
            view.status(f"Could not compact: {e}")

    # ------------------------------------------------------------ the message

    def _compose(self, prompt, attachments, view):
        """The user message to send, and whether it should go to the index.

        Attachments are resolved here, where a failure can still stop the turn
        before anything is added to the conversation.
        """
        retrieval = prompt.startswith(RETRIEVAL_PREFIX)
        if retrieval:
            prompt = prompt[len(RETRIEVAL_PREFIX) :]
        images = list(attachments.images)
        text = prompt
        if attachments.url:
            if documents.is_image_url(attachments.url):
                images.append(attachments.url)
            else:
                view.status("Fetching the page...")
                text += DOCUMENT_SEPARATOR + documents.fetch_page(attachments.url)
        if attachments.files:
            view.status("Reading the documents...")
            text += DOCUMENT_SEPARATOR + documents.read_files(attachments.files)
        images = [_image(path) for path in images]
        return Message("user", text, images=images), retrieval

    def _report_background(self, view):
        """Pass on what background commands did while nobody was looking.

        A job that outlives its turn has no way to announce itself, since there
        is no path to inject a message into a finished turn, so it rides along
        with the next one as a message from the user.
        """
        note = jobs.notes()
        if not note:
            return
        self.conversation.add_user(note, marker=BACKGROUND)
        view.notice(note)

    # --------------------------------------------------------------- retrieval

    def load_index(self, folder):
        self.index = RagIndex()
        self.index.load(folder)

    def build_index(self, source, progress):
        """Index a folder, files or a URL, replacing whatever was indexed before."""
        self.index = RagIndex()
        return self.index.build(source, progress)

    def clear_index(self):
        """Forget the index, and say whether there was one to forget.

        Which also takes the model's `search` tool away, since `toolset` offers
        it on an index being loaded rather than on a setting: with no way to
        clear one, retrieval could be turned on and never off again.
        """
        had = self.index is not None
        self.index = None
        return had

    def save_index(self, folder):
        if not self.index:
            raise DocumentError("Nothing has been indexed yet.")
        self.index.save(folder)

    def _answer_from_index(self, question, llm, preset, view):
        """Answer from the index instead of from the conversation alone.

        The prompt is assembled here and sent through the same streaming path
        as any other request, rather than handed to a llama_index query engine.
        That engine yields bare strings, so it lost the model's reasoning, the
        usage numbers and the finish reason on the way through.

        The retrieval prompt is what goes out, and only the question is kept in
        the history: the chunks belong to this question and resending them with
        every later message would fill the window with them.
        """
        if not self.index or not self.index.ready():
            raise DocumentError(
                "Nothing has been indexed yet, so there is nothing to answer "
                "from. Index a document or load an index first."
            )
        view.status("Processing with RAG...")
        # The clock starts at retrieval, which is part of what the user waited
        # for, and before the size check so a refusal is still timed.
        started = time.monotonic()
        prompt = self.index.prompt(question)
        self._check_fits(prompt, preset)
        response, _ = self._start(llm, [Message("user", prompt)])
        text, reasoning, _ = self._stream(response, view, started)
        self.conversation.add_assistant(text, reasoning=reasoning)
        if self.generating and not text.strip():
            # A server that truncates an oversized prompt instead of refusing
            # it answers with nothing rather than with an error, and unexplained
            # silence reads as the app having failed to send anything at all.
            size = (
                f" The prompt was {self.usage.prompt_tokens} tokens long."
                if self.usage
                else ""
            )
            view.notice("The model answered nothing." + size + " " + TOO_MUCH)
        view.sources(describe_sources(self.index.sources()))

    @staticmethod
    def _check_fits(prompt, preset):
        """Refuse a retrieval prompt that cannot fit before sending it.

        The synthesizer used to pack the chunks to the window itself. Counting
        them here instead is a local tokenizer's estimate rather than the
        server's own count, so the headroom is generous: the point is to name
        the cause of a prompt that is wildly too big, not to fill the window to
        the token.
        """
        window = preset.context_window
        room = window - client.max_output(preset)
        if room <= 0 or client.count(prompt) <= room:
            return
        raise DocumentError(
            f"The retrieved text does not fit in {window} tokens. " + TOO_MUCH
        )


def _name(call):
    return call["function"]["name"]


def _image(path):
    """One attached picture, as the data URL a vision model is sent."""
    return image_url(path, documents.read_image(path))
