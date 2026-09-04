"""Turning streamed chunks into something the rest of the chat layer can use."""

from tests import fakes
from vollama.chat import streaming


class Model:
    """Something with a `model_dump`, which is what the library hands back."""

    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


def test_a_chunk_is_read_the_same_whether_it_is_parsed_or_not():
    """A fixture in a test has to be the thing the reader sees at run time."""
    raw = fakes.text_chunk("hi")
    assert streaming.plain(Model(raw)) == raw
    assert streaming.plain(raw) == raw


def test_text_and_reasoning_arrive_on_different_keys():
    assert streaming.text_of(fakes.text_chunk("hello")) == ("hello", "")
    assert streaming.text_of(fakes.reasoning_chunk("hmm")) == ("", "hmm")


def test_reasoning_is_read_under_either_of_its_two_names():
    assert streaming.text_of(fakes.chunk(delta={"reasoning": "hmm"})) == ("", "hmm")


def test_a_chunk_with_no_choices_is_not_a_failure():
    """The extra chunk `include_usage` adds carries an empty list."""
    assert streaming.text_of(fakes.usage_chunk(10, 5)) == ("", "")
    assert streaming.finish_reason(fakes.usage_chunk(10, 5)) == ""


def test_usage_is_read_off_the_chunk_that_carries_it():
    assert streaming.usage_of(fakes.text_chunk("hi")) is None
    assert streaming.usage_of(fakes.usage_chunk(120, 30)) == (120, 30, 0)
    assert streaming.usage_of(fakes.usage_chunk(120, 30, 100)) == (120, 30, 100)


def test_the_finish_reason_survives_the_usage_chunk_that_follows_it():
    """The usage chunk has an empty choices list, so the caller keeps the last
    non-empty answer rather than reading the final chunk."""
    stream = [
        fakes.text_chunk("hi"),
        fakes.text_chunk("", finish_reason="length"),
        fakes.usage_chunk(10, 5),
    ]
    seen = ""
    for chunk in stream:
        seen = streaming.finish_reason(chunk) or seen
    assert seen == "length"


# ------------------------------------------------------------------ tool calls


def test_a_call_split_across_chunks_is_joined_back_together():
    calls = streaming.Calls()
    calls.add(fakes.chunk(delta={"tool_calls": [{"index": 0, "id": "abc"}]}))
    calls.add(
        fakes.chunk(delta={"tool_calls": [{"index": 0, "function": {"name": "run"}}]})
    )
    for piece in ('{"command":', ' "ls"}'):
        calls.add(
            fakes.chunk(
                delta={"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}
            )
        )
    assert calls.done() == [
        {
            "id": "abc",
            "type": "function",
            "function": {"name": "run", "arguments": '{"command": "ls"}'},
        }
    ]


def test_fragments_of_two_calls_are_told_apart_by_their_index():
    """They interleave, so the order they arrive in is not the order they are in."""
    calls = streaming.Calls()
    calls.add(fakes.call_chunk("poll", "", id="b", index=1))
    calls.add(fakes.call_chunk("run", "", id="a", index=0))
    calls.add(
        fakes.chunk(
            delta={"tool_calls": [{"index": 1, "function": {"arguments": "{}"}}]}
        )
    )
    calls.add(
        fakes.chunk(
            delta={"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]}
        )
    )
    assert [call["function"]["name"] for call in calls.done()] == ["run", "poll"]
    assert [call["id"] for call in calls.done()] == ["a", "b"]


def test_a_tool_call_with_no_name_is_not_a_call():
    calls = streaming.Calls()
    fragment = {"index": 0, "id": "x", "function": {"arguments": "{}"}}
    calls.add(fakes.chunk(delta={"tool_calls": [fragment]}))
    assert calls.done() == []


def test_a_call_with_no_id_is_given_one():
    calls = streaming.Calls()
    calls.add(fakes.call_chunk("poll", "{}", id=None))
    assert calls.done()[0]["id"] == "call_0"


def test_a_thought_signature_survives_the_stream_it_arrived_in():
    """Without this the next request is refused outright, so every turn in which
    the model calls a tool dies on its second request."""
    signature = {"google": {"thought_signature": "sig-a"}}
    calls = streaming.Calls()
    calls.add(fakes.call_chunk("run", "{}", id="c1"))
    calls.add(fakes.text_chunk("thinking"))
    calls.add(
        fakes.chunk(delta={"tool_calls": [{"index": 0, "extra_content": signature}]})
    )
    assert calls.done()[0]["extra_content"] == signature


def test_signatures_follow_their_own_call_and_not_the_order_they_arrived_in():
    calls = streaming.Calls()
    calls.add(fakes.call_chunk("poll", "{}", id="b", index=1, extra_content="second"))
    calls.add(fakes.call_chunk("run", "{}", id="a", index=0, extra_content="first"))
    assert [call["extra_content"] for call in calls.done()] == ["first", "second"]


def test_no_signature_means_no_key_at_all():
    """It is only ever added when a server actually sent one."""
    calls = streaming.Calls()
    calls.add(fakes.call_chunk("run", "{}"))
    assert "extra_content" not in calls.done()[0]
