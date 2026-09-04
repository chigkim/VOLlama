"""The vector index: building it, storing it, and answering from it.

llama_index is configured through a process-wide `Settings` object. That global
is confined to this module — the chunk sizes, the embedding model and the
context window are set here, where they are used, and the chat client is passed
in as an argument rather than left on the global for something else to find.
Before, the chat layer set four retrieval fields on it that it had no business
knowing about.
"""

import logging

from llama_index.core import (
    Settings,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.embeddings.openai_like import OpenAILikeEmbedding

from vollama.config import presets
from vollama.config.settings import settings
from vollama.errors import DocumentError
from vollama.rag import documents

log = logging.getLogger(__name__)

# Chunks embedded per request. One request per chunk is a round trip per
# paragraph, which is most of the time spent indexing a book.
BATCH = 32

# How llama_index may turn retrieved chunks into an answer. Listed here rather
# than in the dialog that offers them, since it is this module that passes the
# choice on and would be the thing to break if the list were wrong.
RESPONSE_MODES = (
    "refine",
    "compact",
    "tree_summarize",
    "simple_summarize",
    "accumulate",
    "compact_accumulate",
)


class RagIndex:
    """One index over one set of documents, and questions asked of it."""

    def __init__(self):
        self.index = None
        self.response = None
        self._configure()

    @staticmethod
    def _configure():
        """Point llama_index at the embedding endpoint and the chunk sizes.

        The embedding endpoint is a global setting rather than a preset field
        because an index is built with one embedding model: re-embedding it
        because the chat model changed would silently invalidate every vector
        already stored.
        """
        Settings.embed_model = OpenAILikeEmbedding(
            api_base=settings.embedding_base_url,
            api_key=settings.embedding_api_key or "none",
            model_name=settings.embedding_model,
        )
        Settings.chunk_size = settings.chunk_size
        Settings.chunk_overlap = settings.chunk_overlap
        Settings.context_window = presets.context_window()

    def ready(self):
        return self.index is not None

    # ------------------------------------------------------------- building

    def build(self, source, progress):
        """Index a folder, a list of files, or a URL. `progress` reports steps."""
        progress("Loading...")
        if isinstance(source, str) and source.startswith("http"):
            pages = documents.fetch_page(source)
            loaded = _as_document(pages, source)
        else:
            loaded = documents.load(source)
        nodes = Settings.node_parser(loaded)
        if not nodes:
            raise DocumentError(f"There was no text to index in {source}.")
        self._embed(nodes, progress)
        self.index = VectorStoreIndex(nodes=nodes)
        return len(nodes)

    @staticmethod
    def _embed(nodes, progress):
        """Give every chunk its vector, a batch of requests at a time."""
        for start in range(0, len(nodes), BATCH):
            batch = nodes[start : start + BATCH]
            progress(f"Creating embeddings for {start + len(batch)}/{len(nodes)}")
            vectors = Settings.embed_model.get_text_embedding_batch(
                [node.get_content(metadata_mode="embed") for node in batch]
            )
            # strict: a provider that returns fewer vectors than texts would
            # otherwise leave chunks silently unembedded.
            for node, vector in zip(batch, vectors, strict=True):
                node.embedding = vector

    # -------------------------------------------------------------- storage

    def load(self, folder):
        self.index = load_index_from_storage(
            StorageContext.from_defaults(persist_dir=folder)
        )

    def save(self, folder):
        if not self.ready():
            raise DocumentError("There is no index to save yet.")
        self.index.storage_context.persist(persist_dir=folder)

    # ------------------------------------------------------------- querying

    def query(self, question, llm):
        """Stream an answer built from the chunks closest to the question.

        Retrieved first on purpose, without writing anything, so that a question
        nothing matches is reported as such instead of being answered from the
        model's own memory with no sources behind it.
        """
        if not self.retrieve(question):
            raise DocumentError(
                "Nothing in the index is close enough to that question. Lower "
                "the similarity cutoff or index more documents."
            )
        self.response = self.index.as_query_engine(
            llm=llm,
            similarity_top_k=settings.similarity_top_k,
            node_postprocessors=self._filters(),
            response_mode=settings.response_mode,
            streaming=True,
        ).query(question)
        return self.response.response_gen

    def retrieve(self, question):
        """The chunks closest to the question, with the cutoff applied.

        A retriever rather than a query engine in "no_text" mode. That mode
        still builds a response synthesizer, and llama_index builds that one
        without the llm it was handed, so it falls back to the process-wide
        `Settings.llm` — which resolves to OpenAI and raises "No API key found
        for OpenAI" no matter what the preset points at. Retrieving does not
        need a model at all.
        """
        nodes = self.index.as_retriever(
            similarity_top_k=settings.similarity_top_k
        ).retrieve(question)
        for each in self._filters():
            nodes = each.postprocess_nodes(nodes, query_str=question)
        return nodes

    @staticmethod
    def _filters():
        return [SimilarityPostprocessor(similarity_cutoff=settings.similarity_cutoff)]

    def sources(self):
        """The chunks the last answer was built from."""
        return self.response.source_nodes if self.response else []


def _as_document(text, source):
    from llama_index.core import Document

    return [Document(text=text, metadata={"file_name": source})]


def describe_sources(nodes):
    """The retrieved chunks and their scores, for the Show Context setting."""
    lines = []
    for number, node in enumerate(nodes, 1):
        text = " ".join(node.text.split())
        lines.append(f"Context {number}, similarity {node.score:.2f}: {text}")
    return "\n".join(lines) or "Nothing was retrieved."
