"""The turn loop: tool rounds, budgets, stopping, and the two retries.

Everything here runs against a fake client and a recording view, which is the
whole point of the `ChatView` port: this is the most intricate logic in the
project and none of it needs a window to exercise.
"""

import time

import pytest

from tests import fakes
from vollama.chat import client as client_module
from vollama.chat import compaction
from vollama.chat.session import ChatSession
from vollama.config import presets
from vollama.config.presets import Preset
from vollama.errors import DocumentError


@pytest.fixture(autouse=True)
def a_usable_preset(isolated):
    presets.create("test", Preset(base_url="http://localhost/v1/", model="m"))


@pytest.fixture
def build(monkeypatch):
    """Hand the session a prepared client instead of a real one."""
    made = []

    def use(*streams):
        client = fakes.FakeClient(*streams)
        made.append(client)
        monkeypatch.setattr(client_module, "build", lambda *a, **k: client)
        return client

    return use


@pytest.fixture
def ran(monkeypatch):
    """Record tool calls instead of running them."""
    calls = []

    def fake_call(name, arguments, extra=()):
        calls.append((name, arguments))
        return f"{name} ran"

    monkeypatch.setattr("vollama.tools.registry.call", fake_call)
    return calls


def stream(text, tool_calls=None, finish_reason=None, usage=(10, 5)):
    """One prepared reply: some text, any calls, then the usage chunk.

    A call arrives whole here. Joining the fragments it really comes in is
    `streaming.Calls`' job and is tested there.
    """
    made = [fakes.text_chunk(text, finish_reason=finish_reason)]
    for index, call in enumerate(tool_calls or []):
        made.append(
            fakes.call_chunk(
                call["function"]["name"],
                call["function"]["arguments"],
                id=call["id"],
                index=index,
            )
        )
    return made + [fakes.usage_chunk(*usage)]


# ------------------------------------------------------------- a plain turn


def test_a_plain_turn_records_the_question_and_the_answer(build):
    build(stream("hello there"))
    session = ChatSession()
    view = fakes.RecordingView()

    session.ask("hi", view)

    assert [m.content for m in session.conversation.messages] == ["hi", "hello there"]
    assert view.text() == "hello there"
    assert view.of("finished") == [()]


def test_a_cached_prompt_does_not_count_towards_the_prompt_rate(build):
    """Only the part the server actually processed is a speed.

    Counting a cache hit as tokens per second measures the cache, and a server
    that reports none is left with the plain prompt rate.
    """
    build(
        [
            fakes.text_chunk("hi"),
            fakes.usage_chunk(1000, 5, cached_tokens=900),
        ]
    )
    session = ChatSession()
    view = fakes.RecordingView()

    session.ask("hi", view)

    stats = view.of("stats")[0][0]
    assert (stats.prompt_tokens, stats.cached_tokens) == (1000, 900)
    assert stats.prompt_rate() == pytest.approx(100 / stats.first_token_seconds)


def test_the_thinking_that_came_with_a_reply_is_kept_on_the_message(build):
    """Shown live and stored, because it belongs to the message.

    It used to be folded into the assistant message's content, so a re-rendered
    transcript, a saved chat and alt+up all kept it; showing it through the view
    alone lost it from every one of them.
    """
    build(
        [
            fakes.reasoning_chunk("let me "),
            fakes.chunk(delta={"content": "42", "reasoning_content": "count"}),
            fakes.usage_chunk(10, 5),
        ]
    )
    session = ChatSession()
    view = fakes.RecordingView()

    session.ask("how many", view)

    reply = session.conversation.messages[-1]
    assert reply.content == "42"
    assert reply.extra["reasoning"] == "let me count"
    assert view.of("reasoning_text") == [("let me ",), ("count",)]


def test_the_cost_of_the_turn_is_reported(build):
    build(stream("hi", usage=(120, 8)))
    session = ChatSession()
    view = fakes.RecordingView()

    session.ask("hi", view)

    stats = view.of("stats")[0][0]
    assert (stats.prompt_tokens, stats.completion_tokens) == (120, 8)
    assert stats.total_tokens == 128


def test_the_clock_starts_when_the_request_goes_out(monkeypatch):
    """Not when the stream is first read.

    `_start` pulls the first chunk itself, so by the time `_stream` loops there
    is one waiting: a clock started there put the whole wait for the prompt to
    be processed outside the measurement and reported it as instant — a prompt
    rate in the billions of tokens a second.
    """

    class SlowClient(fakes.FakeClient):
        def stream(self, messages):
            time.sleep(0.05)
            return super().stream(messages)

    client = SlowClient(stream("hi", usage=(100, 2)))
    monkeypatch.setattr(client_module, "build", lambda *a, **k: client)
    session = ChatSession()
    view = fakes.RecordingView()

    session.ask("hi", view)

    stats = view.of("stats")[0][0]
    assert stats.first_token_seconds >= 0.05
    assert stats.total_seconds >= stats.first_token_seconds
    assert stats.prompt_rate() <= 100 / 0.05


def test_a_turn_that_cannot_be_made_leaves_the_conversation_alone(build):
    build(RuntimeError("the server is down"))
    session = ChatSession()
    session.conversation.add_user("earlier")

    with pytest.raises(RuntimeError):
        session.ask("hi", fakes.RecordingView())

    assert [m.content for m in session.conversation.messages] == ["earlier"]


def test_no_preset_is_an_error_before_anything_is_sent(isolated, build):
    isolated.presets = {}
    with pytest.raises(Exception, match="No preset"):
        ChatSession().ask("hi", fakes.RecordingView())


# ------------------------------------------------------------- tool rounds


def test_a_tool_call_is_run_and_its_result_sent_back(build, ran):
    client = build(
        stream("", [fakes.call("run", '{"command": "ls"}')]),
        stream("all done"),
    )
    session = ChatSession()
    view = fakes.RecordingView()

    session.ask("list the files", view)

    assert ran == [("run", '{"command": "ls"}')]
    roles = [m.role for m in session.conversation.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert session.conversation.messages[2].extra["tool_call_id"] == "call_1"
    assert view.of("tool_called") == [("ls",)]
    assert view.of("tool_result") == [("run ran",)]
    # The tool result went back with the second request.
    assert any(m.role == "tool" for m in client.requests[1])


def test_the_round_budget_ends_the_turn(build, ran, monkeypatch):
    monkeypatch.setattr("vollama.tools.registry.MAX_TOOL_ROUNDS", 2)
    asking = [stream("", [fakes.call("run", "{}")]) for _ in range(3)]
    build(*asking)
    session = ChatSession()

    session.ask("keep going", fakes.RecordingView())

    assert len(ran) == 2
    # The call that was refused still got a tool message: a dangling call makes
    # the whole history unusable to the server.
    results = [m for m in session.conversation.messages if m.role == "tool"]
    assert len(results) == 3
    assert "Not run" in results[-1].content


def test_reads_and_polls_do_not_spend_a_round(build, ran, monkeypatch):
    monkeypatch.setattr("vollama.tools.registry.MAX_TOOL_ROUNDS", 1)
    build(
        stream("", [fakes.call("read", '{"path": "a"}')]),
        stream("", [fakes.call("poll", "{}")]),
        stream("", [fakes.call("run", "{}")]),
        stream("finished"),
    )
    session = ChatSession()

    session.ask("look around", fakes.RecordingView())

    assert [name for name, _ in ran] == ["read", "poll", "run"]
    assert session.conversation.messages[-1].content == "finished"


def test_the_call_ceiling_stops_a_model_that_only_ever_reads(build, ran, monkeypatch):
    monkeypatch.setattr("vollama.tools.registry.MAX_TOOL_CALLS", 3)
    reading = [stream("", [fakes.call("read", '{"path": "a"}')]) for _ in range(4)]
    build(*reading)
    session = ChatSession()

    session.ask("read everything", fakes.RecordingView())

    assert len(ran) == 3


def test_stopping_mid_turn_still_answers_every_call(build, ran):
    """A dangling call makes the whole history unusable to the server.

    The call is in hand before the words are, so stopping on the first of them
    stops a turn that has a call to answer for.
    """
    build(
        [
            fakes.call_chunk("run", "{}"),
            fakes.text_chunk("about to run"),
            fakes.usage_chunk(10, 5),
        ]
    )
    session = ChatSession()

    class StopOnFirstChunk(fakes.RecordingView):
        def reply_text(self, text):
            session.stop()

    session.ask("go", StopOnFirstChunk())

    assert ran == []
    result = session.conversation.messages[-1]
    assert result.role == "tool"
    assert "the user stopped generation" in result.content


# ----------------------------------------------------------------- retries


def test_a_history_the_server_refuses_is_compacted_and_sent_again(build, monkeypatch):
    monkeypatch.setattr(compaction, "summarize", lambda client, messages: "a summary")
    client = build(
        RuntimeError("This model's maximum context length is 8192 tokens"),
        stream("answered after compacting"),
    )
    session = ChatSession()
    for n in range(4):
        session.conversation.add_user(f"q{n}")
        session.conversation.add_assistant(f"a{n}")
    view = fakes.RecordingView()

    session.ask("one more", view)

    assert session.conversation.summary == "a summary"
    assert "a summary" in [m.content for m in client.requests[-1]]
    assert any("Compacted" in note for (note,) in view.of("notice"))


def test_an_error_that_is_not_an_overflow_is_reported_as_it_is(build):
    build(RuntimeError("connection refused"))
    with pytest.raises(RuntimeError, match="connection refused"):
        ChatSession().ask("hi", fakes.RecordingView())


def test_an_overflow_with_nothing_left_to_summarize_reports_the_refusal(build):
    build(RuntimeError("prompt is too long"))
    with pytest.raises(RuntimeError, match="too long"):
        ChatSession().ask("hi", fakes.RecordingView())


def test_a_reply_cut_short_is_retried_once_after_compacting(build, monkeypatch):
    monkeypatch.setattr(compaction, "summarize", lambda client, messages: "a summary")
    build(
        stream("half an ans", finish_reason="length", usage=(100, 3)),
        stream("a whole answer"),
    )
    session = ChatSession()
    for n in range(4):
        session.conversation.add_user(f"q{n}")
        session.conversation.add_assistant(f"a{n}")
    presets.update("test", "test", Preset(base_url="u", model="m", parameters=_max(500)))
    view = fakes.RecordingView()

    session.ask("go on", view)

    assert session.conversation.messages[-1].content == "a whole answer"
    # The truncated reply was dropped from the history but the user still read it.
    assert "half an ans" not in [m.content for m in session.conversation.messages]
    assert any("Cut short" in note for (note,) in view.of("notice"))


def test_the_cut_short_retry_happens_at_most_once(build, monkeypatch):
    monkeypatch.setattr(compaction, "summarize", lambda client, messages: "a summary")
    build(
        stream("cut", finish_reason="length", usage=(100, 3)),
        stream("cut again", finish_reason="length", usage=(100, 3)),
    )
    session = ChatSession()
    for n in range(4):
        session.conversation.add_user(f"q{n}")
        session.conversation.add_assistant(f"a{n}")
    presets.update("test", "test", Preset(base_url="u", model="m", parameters=_max(500)))

    session.ask("go on", fakes.RecordingView())

    assert session.conversation.messages[-1].content == "cut again"


# ------------------------------------------------------- background reports


def test_a_background_command_that_ended_rides_along_with_the_next_message(
    build, monkeypatch
):
    monkeypatch.setattr("vollama.tools.shell.jobs.notes", lambda: "exec_1 finished.")
    build(stream("noted"))
    session = ChatSession()
    view = fakes.RecordingView()

    session.ask("hi", view)

    note = session.conversation.messages[0]
    assert note.content == "exec_1 finished."
    assert note.extra["background"] is True
    assert view.of("notice") == [("exec_1 finished.",)]


def _max(tokens):
    from vollama.config import parameters

    values = parameters.defaults()
    values["max_tokens"]["value"] = tokens
    return values


class Node:
    """A retrieved chunk, as `describe_sources` reads one."""

    def __init__(self, text, score, metadata=None):
        self.text = text
        self.score = score
        self.metadata = metadata or {}


class FakeIndex:
    """An index that hands back one pretend chunk, however it is asked."""

    def __init__(self):
        self.asked = []

    def ready(self):
        return True

    def filenames(self):
        return ["book.txt"]

    def prompt(self, question):
        self.asked.append(question)
        return f"Context information is below. the chunk. Query: {question}"

    def search(self, question):
        self.asked.append(question)
        return "file_name: book.txt: the chunk"

    def sources(self):
        return [Node("the chunk", 0.5)]


def test_the_model_can_search_the_index_without_the_tools_checkbox(build, isolated):
    """Search reads an index the user loaded; it touches nothing on the machine.

    Behind the same gate as shell commands, asking a question about a book
    would mean turning on file writes to do it.
    """
    isolated.tools = False
    build(
        stream("", tool_calls=[fakes.call("search", '{"query": "who wrote it"}')]),
        stream("It was written by someone."),
    )
    session = ChatSession()
    session.index = FakeIndex()
    view = fakes.RecordingView()

    session.ask("who wrote it?", view)

    assert [tool.name for tool in session.tools] == ["search"]
    assert session.index.asked == ["who wrote it"]
    assert "the chunk" in view.of("tool_result")[0][0]
    assert view.of("tool_called")[0][0] == 'Searched the documents for "who wrote it"'
    assert view.text() == "It was written by someone."


def test_clearing_the_index_takes_the_search_tool_with_it(build, isolated):
    """The only way to stop offering search, since nothing else gates it."""
    isolated.tools = False
    build(stream("an answer"))
    session = ChatSession()
    session.index = FakeIndex()

    assert session.clear_index() is True
    assert session.clear_index() is False

    session.ask("who wrote it?", fakes.RecordingView())
    assert session.tools == []


def test_a_search_the_model_asked_for_is_shown_as_context(build, isolated):
    """Show Context, for the retrieval the user did not type themselves."""
    isolated.show_context = True
    build(
        stream("", tool_calls=[fakes.call("search", '{"query": "who wrote it"}')]),
        stream("an answer"),
    )
    session = ChatSession()
    session.index = FakeIndex()
    view = fakes.RecordingView()

    session.ask("who wrote it?", view)

    assert "similarity 0.50" in view.of("notice")[0][0]


def test_an_empty_retrieval_answer_is_explained_rather_than_left_blank():
    """A retrieval prompt can outgrow the context however short the question is.

    A server that truncates an oversized prompt answers with nothing and no
    error, and silence in the transcript reads as the app not having sent
    anything at all.
    """
    session = ChatSession()
    session.index = FakeIndex()
    session.generating = True
    view = fakes.RecordingView()

    session._answer_from_index(
        "a question", fakes.FakeClient(stream("")), presets.get("test"), view
    )

    assert "answered nothing" in view.of("notice")[0][0]


def test_a_retrieval_answer_that_arrived_is_not_explained():
    session = ChatSession()
    session.index = FakeIndex()
    session.generating = True
    view = fakes.RecordingView()

    session._answer_from_index(
        "a question", fakes.FakeClient(stream("an answer")), presets.get("test"), view
    )

    assert view.text() == "an answer"
    assert view.of("notice") == []


def test_a_retrieval_turn_sends_the_prompt_and_keeps_only_the_question():
    """The chunks belong to this question, so they must not reach the history.

    They go out in the request and the reply comes back through the ordinary
    streaming path, which is what keeps the reasoning, the usage numbers and
    the finish reason a response synthesizer used to throw away.
    """
    session = ChatSession()
    session.index = FakeIndex()
    session.generating = True
    session.conversation.add_user("a question")
    llm = fakes.FakeClient(
        [
            fakes.chunk(
                delta={"content": "an answer", "reasoning_content": "thinking"},
                finish_reason="stop",
            ),
            fakes.usage_chunk(120, 30),
        ]
    )

    session._answer_from_index(
        "a question", llm, presets.get("test"), fakes.RecordingView()
    )

    sent = llm.requests[0]
    assert len(sent) == 1 and "the chunk" in sent[0].content
    assert [m.content for m in session.conversation.messages] == [
        "a question",
        "an answer",
    ]
    assert session.conversation.messages[-1].extra["reasoning"] == (
        "thinking"
    )
    assert session.usage.prompt_tokens == 120
    assert session.finish_reason == "stop"


def test_a_retrieval_prompt_too_big_for_the_window_is_refused_before_sending():
    """The synthesizer used to pack the chunks to fit; nothing does now."""
    session = ChatSession()
    session.index = FakeIndex()
    session.generating = True
    llm = fakes.FakeClient()

    preset = presets.get("test")
    preset.context_window = 4
    with pytest.raises(DocumentError, match="does not fit"):
        session._answer_from_index("a question", llm, preset, fakes.RecordingView())
    assert llm.requests == []


def test_a_new_chat_keeps_the_index_and_drops_the_conversation():
    """New Chat is about the conversation; re-indexing a book is not part of it."""
    session = ChatSession("be brief")
    session.index = object()
    session.conversation.add_user("something")

    kept = session.index
    session.restart("be thorough")

    assert session.index is kept
    assert [m.content for m in session.conversation.messages] == ["be thorough"]
