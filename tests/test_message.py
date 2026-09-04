"""The message type, and what of it reaches the wire."""

import base64

import pytest

from vollama.chat import client
from vollama.chat.message import Message, image_url, sniff
from vollama.errors import DocumentError

PNG = b"\x89PNG\r\n\x1a\n" + b"rest of the file"


def test_a_plain_message_is_a_role_and_its_content():
    assert Message("user", "hello").to_wire() == {"role": "user", "content": "hello"}


def test_what_we_remember_about_a_message_is_never_sent():
    """The whole reason `to_wire` is a whitelist.

    The serializer this replaced spread the extras into the request, so a key
    invented here to hold the model's thinking went out to the server as a
    field of the message unless it was stripped again first.
    """
    message = Message(
        "assistant", "42", extra={"reasoning": "let me count", "summary": True}
    )
    assert message.to_wire() == {"role": "assistant", "content": "42"}


def test_an_assistant_that_only_made_a_call_sends_no_content():
    """A server will not take "" as the message a tool call came with."""
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "run", "arguments": "{}"},
    }
    wire = Message("assistant", "", extra={"tool_calls": [call]}).to_wire()
    assert wire["content"] is None
    assert wire["tool_calls"] == [call]


def test_an_assistant_that_spoke_as_well_keeps_its_words():
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "run", "arguments": "{}"},
    }
    wire = Message("assistant", "let me look", extra={"tool_calls": [call]}).to_wire()
    assert wire["content"] == "let me look"


def test_a_tool_call_is_passed_through_with_its_vendor_fields():
    """One of them is Gemini's thought signature, and a call without it is refused."""
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "run", "arguments": "{}"},
        "extra_content": {"google": {"thought_signature": "sig"}},
    }
    wire = Message("assistant", "", extra={"tool_calls": [call]}).to_wire()
    assert wire["tool_calls"][0]["extra_content"] == call["extra_content"]


def test_serializing_does_not_hand_out_the_live_calls():
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "run", "arguments": "{}"},
    }
    message = Message("assistant", "", extra={"tool_calls": [call]})
    message.to_wire()["tool_calls"][0]["id"] = "changed"
    assert message.extra["tool_calls"][0]["id"] == "c1"


def test_tool_calls_on_anything_but_an_assistant_are_not_sent():
    """`add_user`'s marker keys share the dict; only an assistant makes calls."""
    wire = Message("user", "hello", extra={"tool_calls": [{"id": "c1"}]}).to_wire()
    assert "tool_calls" not in wire


def test_a_tool_result_names_the_call_it_answers():
    wire = Message("tool", "output", extra={"tool_call_id": "c1"}).to_wire()
    assert wire == {"role": "tool", "content": "output", "tool_call_id": "c1"}


def test_an_image_makes_the_content_a_list_of_parts():
    message = Message("user", "what is this", images=["data:image/png;base64,AAA"])
    wire = message.to_wire()
    assert wire["content"] == [
        {"type": "text", "text": "what is this"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
    ]


def test_a_copy_does_not_share_its_extras():
    message = Message("tool", "output", extra={"tool_call_id": "c1"})
    copied = message.copy()
    copied.extra["tool_call_id"] = "c2"
    assert message.extra["tool_call_id"] == "c1"
    assert copied == Message("tool", "output", extra={"tool_call_id": "c2"})


# --------------------------------------------------------------------- images


def test_an_image_is_inlined_as_a_data_url():
    """A local server cannot fetch a picture from the internet."""
    url = image_url("picture.png", PNG)
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == PNG


def test_the_type_is_read_off_the_bytes_when_the_name_does_not_say():
    assert image_url("download", PNG).startswith("data:image/png;")


def test_something_that_is_not_a_picture_is_refused_by_name():
    with pytest.raises(DocumentError, match="notes.txt"):
        image_url("notes.txt", b"just some words")


@pytest.mark.parametrize(
    "content, kind",
    [
        (PNG, "image/png"),
        (b"\xff\xd8\xff\xe0", "image/jpeg"),
        (b"GIF89a", "image/gif"),
        (b"BM\x00\x00", "image/bmp"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"not a picture", ""),
    ],
)
def test_sniffing_the_formats_a_model_takes(content, kind):
    assert sniff(content) == kind


# ------------------------------------------------------------- counting text


def test_the_estimate_counts_the_words_and_the_calls():
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "run", "arguments": '{"command": "ls"}'},
    }
    messages = [
        Message("user", "what is in here"),
        Message("assistant", "", extra={"tool_calls": [call]}),
    ]
    assert client.count_messages(messages) > client.count("what is in here")


def test_an_image_is_not_counted_as_the_string_it_is_sent_as():
    """Counted as words it is a large number that is not an estimate of anything."""
    plain = Message("user", "what is this")
    with_image = Message("user", "what is this", images=[image_url("p.png", PNG * 100)])
    assert client.count_messages([with_image]) == client.count_messages([plain])
