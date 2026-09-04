"""The turn loop: tool rounds, budgets, stopping, and the two retries.

Everything here runs against a fake client and a recording view, which is the
whole point of the `ChatView` port: this is the most intricate logic in the
project and none of it needs a window to exercise.
"""

import pytest

from tests import fakes
from vollama.chat import client as client_module
from vollama.chat import compaction
from vollama.chat.session import ChatSession
from vollama.config import presets
from vollama.config.presets import Preset


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

    def fake_call(name, arguments):
        calls.append((name, arguments))
        return f"{name} ran"

    monkeypatch.setattr("vollama.tools.registry.call", fake_call)
    return calls


def stream(text, tool_calls=None, finish_reason=None, usage=(10, 5)):
    """One prepared reply: some text, then the usage chunk a server ends with.

    Tool calls are on every chunk because that is what llama_index does: it
    merges the streamed fragments as they arrive, so each chunk carries the
    calls accumulated so far.
    """
    return [
        fakes.Chunk(
            delta=text,
            tool_calls=tool_calls,
            raw=fakes.Raw([fakes.Choice(finish_reason=finish_reason)]),
        ),
        fakes.Chunk(
            tool_calls=tool_calls, raw=fakes.Raw([], fakes.Usage(*usage))
        ),
    ]


# ------------------------------------------------------------- a plain turn


def test_a_plain_turn_records_the_question_and_the_answer(build):
    build(stream("hello there"))
    session = ChatSession()
    view = fakes.RecordingView()

    session.ask("hi", view)

    assert [m.content for m in session.conversation.messages] == ["hi", "hello there"]
    assert view.text() == "hello there"
    assert view.of("finished") == [()]


def test_the_cost_of_the_turn_is_reported(build):
    build(stream("hi", usage=(120, 8)))
    session = ChatSession()
    view = fakes.RecordingView()

    session.ask("hi", view)

    stats = view.of("stats")[0][0]
    assert (stats.prompt_tokens, stats.completion_tokens) == (120, 8)
    assert stats.total_tokens == 128


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
    assert session.conversation.messages[2].additional_kwargs["tool_call_id"] == "call_1"
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
    build(stream("about to run", [fakes.call("run", "{}")]))
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
    assert note.additional_kwargs["background"] is True
    assert view.of("notice") == [("exec_1 finished.",)]


def _max(tokens):
    from vollama.config import parameters

    values = parameters.defaults()
    values["max_tokens"]["value"] = tokens
    return values


def test_a_new_chat_keeps_the_index_and_drops_the_conversation():
    """New Chat is about the conversation; re-indexing a book is not part of it."""
    session = ChatSession("be brief")
    session.index = object()
    session.conversation.add_user("something")

    kept = session.index
    session.restart("be thorough")

    assert session.index is kept
    assert [m.content for m in session.conversation.messages] == ["be thorough"]
