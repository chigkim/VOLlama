"""Retrieval, which must not need a chat model."""

import pytest
from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import NodeWithScore, TextNode

from tests import fakes

from vollama.errors import DocumentError
from vollama.rag.index import RagIndex, describe_sources, header, origin


@pytest.fixture
def rag(monkeypatch):
    """An index over two chunks, with nothing real to embed against.

    The vectors are set by hand and the query is embedded by MockEmbedding, so
    no request leaves the machine.
    """
    monkeypatch.setattr(Settings, "_llm", None)
    index = RagIndex()
    Settings.embed_model = MockEmbedding(embed_dim=2)
    nodes = [
        TextNode(text="the first chunk", embedding=[1.0, 0.0]),
        TextNode(text="the second chunk", embedding=[0.0, 1.0]),
    ]
    index.index = VectorStoreIndex(nodes=nodes)
    return index


def test_retrieval_does_not_resolve_a_chat_model(rag):
    """A query engine in "no_text" mode would.

    llama_index builds that synthesizer without the llm it was handed, so it
    reaches for the process-wide `Settings.llm`, which resolves to OpenAI and
    raises "No API key found for OpenAI" whatever the preset points at.
    """
    assert len(rag.retrieve("a question")) == 2
    assert Settings._llm is None


def test_the_cutoff_is_applied_to_what_was_retrieved(rag):
    fakes.preset(similarity_cutoff=1.1)
    assert rag.retrieve("a question") == []


def test_a_question_nothing_matches_is_reported_before_the_model_is_asked(rag):
    fakes.preset(similarity_cutoff=1.1)
    with pytest.raises(DocumentError, match="close enough"):
        rag.prompt("a question")
    assert Settings._llm is None


def test_the_prompt_is_the_question_and_the_chunks_and_needs_no_model(rag):
    """What used to be a response synthesizer's job, done here as text.

    Assembling it rather than handing the question to a query engine is what
    lets the answer come back through the ordinary chat path, and it is why
    nothing in this test resolves an llm.
    """
    prompt = rag.prompt("a question")

    assert "Query: a question" in prompt
    assert "the first chunk" in prompt and "the second chunk" in prompt
    assert prompt.index("the first chunk") < prompt.index("Query:")
    # Sorted, because what comes back is ordered by similarity and the two
    # chunks here are only as far apart as MockEmbedding makes them.
    assert sorted(node.text for node in rag.sources()) == [
        "the first chunk",
        "the second chunk",
    ]
    assert Settings._llm is None


def test_each_chunk_is_labelled_with_where_it_is_from_and_how_close(rag):
    """Both, for both readers.

    The source is how the model can say where an answer came from; the score is
    how it can say it is unsure of a distant one instead of reading every
    passage as equally true.
    """
    rag.index = VectorStoreIndex(
        nodes=[
            TextNode(
                text="the only chunk",
                embedding=[1.0, 0.0],
                metadata={"file_path": "D:/books/one.txt"},
            )
        ]
    )
    prompt = rag.prompt("a question")

    assert "Context 1, D:/books/one.txt, similarity " in prompt
    assert describe_sources(rag.sources()).startswith(
        "Context 1, D:/books/one.txt, similarity "
    )


def test_a_pdf_chunk_names_the_page_it_was_on(rag):
    node = NodeWithScore(
        node=TextNode(
            text="a page",
            metadata={"file_name": "one.pdf", "page_label": "12"},
        ),
        score=0.5,
    )
    assert header(node, 1) == "Context 1, one.pdf, page 12, similarity 0.50"


def test_a_chunk_the_index_could_not_place_is_still_labelled(rag):
    """Text indexed with no metadata: numbered and scored, and that is all."""
    node = NodeWithScore(node=TextNode(text="a page"), score=0.5)
    assert header(node, 2) == "Context 2, similarity 0.50"
    assert origin(node) == ""
