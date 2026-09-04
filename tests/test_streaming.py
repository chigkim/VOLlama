"""Turning streamed chunks into something the rest of the chat layer can use."""

from tests import fakes
from vollama.chat import streaming


def test_text_and_reasoning_arrive_on_different_keys():
    chunk = fakes.Chunk(delta="hello", additional_kwargs={"thinking_delta": "hmm"})
    assert streaming.text_of(chunk) == ("hello", "hmm")


def test_a_plain_string_chunk_is_text():
    assert streaming.text_of("retrieved") == ("retrieved", "")


def test_usage_is_read_off_the_chunk_that_carries_it():
    assert streaming.usage_of(fakes.text_chunk("hi")) is None
    assert streaming.usage_of(fakes.usage_chunk(120, 30)) == (120, 30)


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


def test_tool_calls_are_read_off_the_last_chunk():
    chunk = fakes.Chunk(
        tool_calls=[fakes.call("run", '{"command": "ls"}', id="abc")]
    )
    assert streaming.tool_calls_of(chunk) == [
        {
            "id": "abc",
            "type": "function",
            "function": {"name": "run", "arguments": '{"command": "ls"}'},
        }
    ]


def test_a_tool_call_with_no_name_is_not_a_call():
    chunk = fakes.Chunk(tool_calls=[{"id": "x", "function": {"arguments": "{}"}}])
    assert streaming.tool_calls_of(chunk) == []


def test_a_call_with_no_id_is_given_one():
    chunk = fakes.Chunk(tool_calls=[{"function": {"name": "poll", "arguments": "{}"}}])
    assert streaming.tool_calls_of(chunk)[0]["id"] == "call_0"


def signature_chunk(index, signature):
    """A fragment carrying Gemini's thought signature, as its endpoint sends it."""
    return fakes.Chunk(
        raw=fakes.Raw(
            [
                fakes.Choice(
                    delta={
                        "tool_calls": [
                            {
                                "index": index,
                                "extra_content": {"google": {"thought_signature": signature}},
                            }
                        ]
                    }
                )
            ]
        )
    )


def test_a_thought_signature_survives_the_stream_it_arrived_in():
    """Without this the next request is refused outright, so every turn in which
    the model calls a tool dies on its second request."""
    extras = {}
    streaming.collect_extras(signature_chunk(0, "sig-a"), extras)
    streaming.collect_extras(fakes.text_chunk("thinking"), extras)
    final = fakes.Chunk(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "run", "arguments": "{}"}}])

    call = streaming.tool_calls_of(final, extras)[0]
    assert call["extra_content"] == {"google": {"thought_signature": "sig-a"}}


def test_signatures_follow_their_own_call_and_not_the_order_they_arrived_in():
    extras = {}
    streaming.collect_extras(signature_chunk(1, "second"), extras)
    streaming.collect_extras(signature_chunk(0, "first"), extras)
    final = fakes.Chunk(
        tool_calls=[
            {"index": 0, "id": "a", "function": {"name": "run", "arguments": "{}"}},
            {"index": 1, "id": "b", "function": {"name": "poll", "arguments": "{}"}},
        ]
    )
    calls = streaming.tool_calls_of(final, extras)
    assert calls[0]["extra_content"]["google"]["thought_signature"] == "first"
    assert calls[1]["extra_content"]["google"]["thought_signature"] == "second"


def test_no_signature_means_no_key_at_all():
    """It is only ever added when a server actually sent one."""
    chunk = fakes.Chunk(tool_calls=[fakes.call("run", "{}")])
    assert "extra_content" not in streaming.tool_calls_of(chunk, {})[0]


def test_fields_are_read_off_objects_and_dictionaries_alike():
    assert streaming.field({"a": 1}, "a") == 1
    assert streaming.field(fakes.Choice(finish_reason="stop"), "finish_reason") == "stop"
    assert streaming.field({}, "missing", "default") == "default"
