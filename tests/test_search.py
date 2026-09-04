"""Retrieval as a tool: what the model is told, and what it gets back."""

import pytest
from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode

from tests import fakes

from vollama.chat import toolset
from vollama.rag import search
from vollama.rag.index import SEPARATOR, RagIndex
from vollama.tools import registry


@pytest.fixture
def rag(monkeypatch):
    """An index over two named chunks, with nothing real to embed against."""
    monkeypatch.setattr(Settings, "_llm", None)
    index = RagIndex()
    Settings.embed_model = MockEmbedding(embed_dim=2)
    index.index = VectorStoreIndex(
        nodes=[
            TextNode(
                text="the first chunk",
                embedding=[1.0, 0.0],
                metadata={"file_name": "one.txt"},
            ),
            TextNode(
                text="the second chunk",
                embedding=[0.0, 1.0],
                metadata={"file_name": "two.txt"},
            ),
        ]
    )
    return index


# ------------------------------------------------------ what the model is told


def test_the_description_names_what_was_indexed(rag):
    """A model will not search an index it cannot see the contents of."""
    described = search.schema(rag)["function"]["description"]
    assert "one.txt" in described and "two.txt" in described


def test_the_schema_asks_for_a_query_and_nothing_else(rag):
    """Top K and the cutoff are the user's settings, not parameters of a call."""
    assert list(search.schema(rag)["function"]["parameters"]["properties"]) == [
        "query"
    ]


def test_an_index_that_cannot_name_its_documents_is_still_searchable(rag):
    """A URL, or text indexed directly, has no file name to report."""
    rag.index = VectorStoreIndex(
        nodes=[TextNode(text="a page of a website", embedding=[1.0, 0.0])]
    )
    assert search.files(rag) == []
    assert "Indexed:" not in search.schema(rag)["function"]["description"]


def test_the_file_list_is_capped(rag, monkeypatch):
    monkeypatch.setattr(search, "MAX_FILES", 1)
    described = search.schema(rag)["function"]["description"]
    assert "one.txt, and 1 more." in described


# --------------------------------------------------------- what comes back


def test_a_search_returns_the_passages_and_records_them_as_the_sources(rag):
    result = search.run(rag, "a question")

    assert "the first chunk" in result and "the second chunk" in result
    assert "one.txt" in result and "similarity " in result
    assert len(rag.sources()) == 2


def test_nothing_close_enough_is_worded_rather_than_raised(rag):
    """A tool answers the model in words; only the /q path raises."""
    fakes.preset(similarity_cutoff=1.1)

    assert "Nothing in the index is close enough" in search.run(rag, "a question")


def test_a_search_with_no_index_and_a_search_with_no_query_are_both_answered(rag):
    assert "no index loaded" in search.run(None, "a question")
    assert "Give a query" in search.run(rag, "  ")


def test_a_failed_search_costs_a_retry_and_not_the_turn(rag, monkeypatch):
    def broken(question):
        raise ConnectionError("the embedding endpoint refused the connection")

    monkeypatch.setattr(rag, "search", broken)

    assert "The search failed: the embedding endpoint" in search.run(rag, "q")


def test_too_much_is_cut_between_passages_and_says_so(monkeypatch):
    monkeypatch.setattr(search, "MAX_RESULT", 30)
    found = SEPARATOR.join(["a passage", "another passage", "a third"])

    trimmed = search.trim(found)

    assert trimmed.startswith("a passage" + SEPARATOR + "another passage")
    assert "a third" not in trimmed
    assert "too long to include" in trimmed


def test_a_single_passage_too_long_to_show_is_still_cut(monkeypatch):
    monkeypatch.setattr(search, "MAX_RESULT", 10)
    trimmed = search.trim("one passage with no boundary in it at all")
    assert trimmed.startswith("one passag")
    assert "too long to include" in trimmed


def test_the_transcript_line_is_the_query(rag):
    assert registry.describe(
        search.NAME, '{"query": "who wrote it"}', [toolset.searching(rag)]
    ) == 'Searched the documents for "who wrote it"'


def test_a_saved_search_is_described_without_an_index(rag):
    """A chat reopened has no index, and its searches still have to read right."""
    assert (
        registry.describe(search.NAME, '{"query": "x"}', toolset.DESCRIBED)
        == 'Searched the documents for "x"'
    )


# ------------------------------------------------------------------ the gates


def test_search_is_offered_whenever_there_is_an_index(rag, isolated):
    """Independently of the Tools checkbox: it reads, and touches nothing."""
    isolated.tools = False

    offered = toolset.for_turn(rag)

    assert [tool.name for tool in offered] == [search.NAME]


def test_the_machine_tools_stay_behind_the_checkbox(rag, isolated):
    assert toolset.for_turn(None) == []
    isolated.tools = True
    assert [tool.name for tool in toolset.for_turn(None)] == [
        tool.name for tool in registry.REGISTRY
    ]
    assert toolset.for_turn(rag)[-1].name == search.NAME


def test_searching_does_not_spend_a_round(rag):
    """Like read: looking something up is not the progress the budget limits."""
    assert registry.is_free(search.NAME, toolset.for_turn(rag))


def test_an_index_with_nothing_in_it_offers_no_search(isolated):
    isolated.tools = False
    assert toolset.for_turn(RagIndex()) == []
