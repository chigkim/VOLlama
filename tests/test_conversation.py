"""The conversation: what is kept, and what is sent.

The distinction these tests exist to protect: `messages` never loses anything,
`outgoing()` is allowed to.
"""

from vollama.chat.conversation import BACKGROUND, REASONING, SUMMARY, Conversation
from vollama.chat.message import Message


def turn(conversation, question, answer):
    conversation.add_user(question)
    conversation.add_assistant(answer)


def roles(messages):
    return [message.role for message in messages]


def texts(messages):
    return [message.content for message in messages]


# ------------------------------------------------------------ system prompt


def test_the_system_prompt_is_first_and_replaced_rather_than_repeated():
    conversation = Conversation("be brief")
    conversation.add_user("hello")
    conversation.set_system("be thorough")
    assert roles(conversation.messages) == ["system", "user"]
    assert conversation.messages[0].content == "be thorough"


def test_an_empty_system_prompt_removes_the_one_that_was_there():
    conversation = Conversation("be brief")
    conversation.set_system("")
    assert conversation.messages == []


# ---------------------------------------------------------- old tool rounds


def tool_round(conversation, said, result):
    call = {"id": "c1", "type": "function", "function": {"name": "run", "arguments": "{}"}}
    conversation.add_assistant(said, [call])
    conversation.add_tool_result("c1", "run", result)


def test_the_tool_rounds_of_older_turns_are_not_resent():
    conversation = Conversation()
    conversation.add_user("first")
    tool_round(conversation, "", "old output")
    conversation.add_assistant("done")
    conversation.add_user("second")
    tool_round(conversation, "", "new output")

    sent = conversation.outgoing()
    assert "old output" not in texts(sent)
    assert "new output" in texts(sent)
    # And nothing was actually thrown away.
    assert "old output" in texts(conversation.messages)


def test_an_older_assistant_message_keeps_its_words_and_loses_its_call():
    conversation = Conversation()
    conversation.add_user("first")
    tool_round(conversation, "let me look", "output")
    conversation.add_user("second")

    kept = [m for m in conversation.outgoing() if m.role == "assistant"]
    assert texts(kept) == ["let me look"]
    assert not kept[0].extra.get("tool_calls")


def test_a_call_and_its_result_are_always_sent_together():
    conversation = Conversation()
    conversation.add_user("first")
    tool_round(conversation, "", "output")
    conversation.add_user("second")

    sent = conversation.outgoing()
    calls = sum(1 for m in sent if m.extra.get("tool_calls"))
    results = sum(1 for m in sent if m.role == "tool")
    assert calls == results


# --------------------------------------------------------------- the summary


def test_the_summary_replaces_the_old_turns_only_on_the_way_out():
    conversation = Conversation("system")
    turn(conversation, "one", "1")
    turn(conversation, "two", "2")
    conversation.compacted("what happened", upto=3)

    sent = conversation.outgoing()
    assert roles(sent) == ["system", "user", "user", "assistant"]
    assert sent[1].content == "what happened"
    # As a message from the user: a model told it wrote this repeats it.
    assert sent[1].role == "user"
    assert sent[1].extra[SUMMARY] is True
    assert len(conversation.messages) == 5


def test_resetting_the_context_forgets_the_summary():
    conversation = Conversation()
    turn(conversation, "one", "1")
    conversation.compacted("summary", upto=1)
    conversation.reset_context()
    assert "summary" not in texts(conversation.outgoing())


def test_halfway_lands_on_a_message_of_the_user_s_own():
    conversation = Conversation()
    for n in range(4):
        turn(conversation, f"q{n}", f"a{n}")
    at = conversation.halfway()
    assert conversation.messages[at].role == "user"


def test_halfway_gives_up_when_there_is_only_one_turn_left_to_cut():
    conversation = Conversation()
    turn(conversation, "only", "one")
    assert conversation.halfway() is None


def test_one_enormous_message_is_not_worth_compacting():
    conversation = Conversation()
    conversation.add_user("a very long question")
    assert not conversation.compactable()
    conversation.add_assistant("answer")
    assert conversation.compactable()


# ---------------------------------------------------------- the environment


def test_the_environment_goes_after_the_system_prompt_and_only_when_given():
    conversation = Conversation("be brief")
    conversation.add_user("hello")
    assert roles(conversation.outgoing()) == ["system", "user"]
    with_environment = conversation.outgoing("this machine")
    assert roles(with_environment) == ["system", "system", "user"]
    assert with_environment[1].content == "this machine"


# -------------------------------------------------------------- editing


def test_clearing_the_last_message_takes_its_whole_turn_with_it():
    conversation = Conversation("system")
    turn(conversation, "first", "1")
    conversation.add_user("second")
    tool_round(conversation, "", "output")
    conversation.add_assistant("answer")

    assert conversation.clear_last() == "second"
    assert texts(conversation.messages) == ["system", "first", "1"]


def test_clearing_an_empty_conversation_is_harmless():
    assert Conversation().clear_last() == ""


def test_alt_up_lands_only_on_what_somebody_actually_said():
    conversation = Conversation("system")
    conversation.add_user("question")
    tool_round(conversation, "", "output")
    conversation.add_assistant("answer")
    conversation.add_user("a background note", marker=BACKGROUND)

    reviewable = [i for i in range(len(conversation.messages)) if conversation.reviewable(i)]
    assert texts([conversation.messages[i] for i in reviewable]) == ["question", "answer"]


def test_the_first_message_of_a_chat_is_not_an_edit_of_the_system_prompt():
    """What the window asks before it treats a send as an edit.

    A preset with a system prompt puts a message at index 0, and the window
    starts its history mark there, so comparing the mark against the length made
    the first thing ever typed an edit: it vanished and replaced the prompt.
    """
    assert not Conversation("system").reviewable(0)


# ------------------------------------------------------------ saving


def test_a_saved_chat_comes_back_with_its_tool_call_ids():
    conversation = Conversation("system")
    conversation.add_user("question")
    tool_round(conversation, "", "output")

    reloaded = Conversation()
    reloaded.load_json(conversation.to_json())
    assert roles(reloaded.messages) == roles(conversation.messages)
    assert reloaded.messages[-1].extra["tool_call_id"] == "c1"
    assert reloaded.messages[-2].extra["tool_calls"][0]["id"] == "c1"


def test_saving_does_not_hand_out_the_live_message_kwargs():
    conversation = Conversation()
    conversation.add_tool_result("c1", "run", "output")
    saved = conversation.to_json()
    saved["messages"][0]["extra"]["tool_call_id"] = "changed"
    assert conversation.messages[0].extra["tool_call_id"] == "c1"


def test_loading_a_chat_forgets_the_summary_of_a_different_one():
    conversation = Conversation()
    conversation.compacted("old summary", upto=0)
    conversation.load_json({"messages": [{"role": "user", "content": "hello"}]})
    assert conversation.summary == ""
    assert texts(conversation.outgoing()) == ["hello"]


def test_a_message_without_extras_round_trips():
    conversation = Conversation()
    conversation.load_json({"messages": [{"role": "user", "content": "hello"}]})
    assert conversation.to_json() == {
        "messages": [{"role": "user", "content": "hello"}]
    }
    assert isinstance(conversation.messages[0], Message)


def test_a_chat_saved_before_the_summary_was_written_is_a_bare_list():
    """What an older build wrote: the messages were the whole file."""
    conversation = Conversation()
    conversation.load_json([{"role": "user", "content": "hello"}])
    assert texts(conversation.messages) == ["hello"]
    assert conversation.summary == ""


def test_a_compacted_chat_comes_back_compacted():
    """Or a chat compacted five times would be sent in full and refused."""
    conversation = Conversation("system")
    for i in range(4):
        conversation.add_user(f"question {i}")
        conversation.add_assistant(f"answer {i}")
    conversation.compacted("what was said before", upto=5)
    before = texts(conversation.outgoing())

    reloaded = Conversation()
    reloaded.load_json(conversation.to_json())
    assert reloaded.summary == "what was said before"
    assert reloaded.summary_at == 5
    assert texts(reloaded.outgoing()) == before
    assert texts(reloaded.messages) == texts(conversation.messages)


def test_a_summary_is_only_written_out_when_there_is_one():
    conversation = Conversation()
    conversation.add_user("hello")
    assert "summary" not in conversation.to_json()


def test_a_cut_past_the_end_of_a_saved_chat_is_brought_back_to_it():
    """A hand-edited file: the cut is an index into the list saved beside it.

    The whole chat behind the summary is a real state — that is what Compact
    Conversation produces — so the clamp lands on the end rather than refusing.
    """
    conversation = Conversation()
    conversation.load_json(
        {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
            "summary": "summary",
            "summary_at": 99,
        }
    )
    assert conversation.summary_at == 2
    assert texts(conversation.outgoing()) == ["summary"]


def test_a_cut_a_saved_file_cannot_explain_summarizes_nothing():
    conversation = Conversation()
    conversation.load_json(
        {
            "messages": [{"role": "user", "content": "hello"}],
            "summary": "summary",
            "summary_at": "halfway",
        }
    )
    assert conversation.summary_at == 0
    assert texts(conversation.outgoing()) == ["summary", "hello"]


def test_reasoning_is_kept_in_the_history_and_left_out_of_the_request():
    """Worth keeping, not worth sending.

    A reasoning model is supposed to think again rather than be handed what it
    thought last time. It is kept because the transcript, Save and alt+up show
    what the user watched arrive.
    """
    conversation = Conversation()
    conversation.add_user("how many")
    conversation.add_assistant("42", reasoning="let me count")

    assert conversation.messages[-1].extra[REASONING] == "let me count"
    assert all(REASONING not in m.to_wire() for m in conversation.outgoing())
    assert conversation.messages[-1].extra[REASONING] == "let me count"
