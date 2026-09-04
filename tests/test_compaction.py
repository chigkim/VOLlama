"""When a conversation has to be summarized, and how that is recognized."""

import pytest

from tests import fakes
from vollama.chat import compaction


def test_compaction_is_wanted_once_the_window_is_nearly_full():
    window = 1000
    assert not compaction.needed(700, window)
    assert compaction.needed(int(window * compaction.COMPACT_AT), window)


def test_nothing_is_compacted_without_a_window_or_a_count():
    assert not compaction.needed(0, 1000)
    assert not compaction.needed(900, 0)


@pytest.mark.parametrize(
    "message",
    [
        "context_length_exceeded",
        "This model's maximum context length is 8192 tokens",
        "prompt is too long: 210000 tokens > 200000 maximum",
        "input token count 1200000 exceeds the maximum number of tokens allowed",
        "Please reduce the length of the messages",
        "400 status code (no body)",
    ],
)
def test_the_wordings_servers_actually_use_are_recognized(message):
    assert compaction.overflowed(Exception(message))


@pytest.mark.parametrize(
    "message",
    [
        "ThrottlingException: Too many tokens, please wait before trying again",
        "Rate limit reached for gpt-4",
        "429 Too Many Requests",
        "Connection refused",
    ],
)
def test_being_rate_limited_is_not_being_too_long(message):
    """Bedrock words its throttling like an overflow, which is why the
    exclusions are checked first."""
    assert not compaction.overflowed(Exception(message))


def test_a_reply_that_stopped_short_of_the_length_asked_for_was_cut_off():
    assert compaction.truncated("length", output=40, limit=500, prompt=0, window=8192)
    assert not compaction.truncated("length", output=500, limit=500, prompt=0, window=8192)


def test_an_empty_reply_to_a_prompt_that_filled_the_window_was_cut_off():
    """A server that truncates an oversized prompt instead of refusing it leaves
    no room to answer, and reports success."""
    assert compaction.truncated("length", output=0, limit=0, prompt=8150, window=8192)
    assert not compaction.truncated("length", output=0, limit=0, prompt=4000, window=8192)


def test_a_reply_that_simply_ended_was_not_cut_off():
    assert not compaction.truncated("stop", output=10, limit=500, prompt=0, window=8192)


def test_summarizing_asks_the_model_to_hand_over_to_a_copy_of_itself():
    client = fakes.FakeClient(fakes.Reply("  the summary  "))
    summary = compaction.summarize(client, [])
    assert summary == "the summary"
    asked = client.requests[0][-1]
    assert asked.role == "user"
    assert "handoff summary" in asked.content
