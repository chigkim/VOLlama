"""Retrieval, which must not need a chat model."""

import pytest
from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode

from vollama.errors import DocumentError
from vollama.rag.index import RagIndex


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


def test_the_cutoff_is_applied_to_what_was_retrieved(rag, isolated):
    isolated.similarity_cutoff = 1.1
    assert rag.retrieve("a question") == []


def test_a_question_nothing_matches_is_reported_before_the_model_is_asked(
    rag, isolated
):
    isolated.similarity_cutoff = 1.1
    with pytest.raises(DocumentError, match="close enough"):
        rag.query("a question", llm=None)
    assert Settings._llm is None
