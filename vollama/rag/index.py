"""The vector index: building it, storing it, and answering from it.

llama_index is configured through a process-wide `Settings` object. That global
is confined to this module — the chunk sizes, the embedding model and the
context window are set here, where they are used, and the chat client is passed
in as an argument rather than left on the global for something else to find.
Before, the chat layer set four retrieval fields on it that it had no business
knowing about.

All of it comes from the active preset, which is what a server is, embedding
endpoint included.
"""

import logging

from llama_index.core import (
    Document,
    Settings,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.embeddings.openai_like import OpenAILikeEmbedding

from vollama.config import presets
from vollama.errors import DocumentError
from vollama.rag import documents

log = logging.getLogger(__name__)

# Chunks embedded per request. One request per chunk is a round trip per
# paragraph, which is most of the time spent indexing a book.
BATCH = 32

# What a retrieval question goes out as. llama_index's own default wording,
# because that is what these models have been tuned against; assembling it here
# is what lets the answer come back through the ordinary chat path, with the
# reasoning, the usage numbers and the finish reason that a response
# synthesizer throws away.
PROMPT = """Context information is below.
---------------------
{context}
---------------------
Given the context information and not prior knowledge, answer the query.
Query: {question}
"""

# Between one retrieved chunk and the next. A blank line, as llama_index packs
# them, so a chunk ending mid-sentence does not read as the start of the next.
SEPARATOR = "\n\n"


class RagIndex:
    """One index over one set of documents, and questions asked of it."""

    def __init__(self):
        self.index = None
        self.retrieved = []
        self._configure()

    @staticmethod
    def _configure():
        """Point llama_index at the active preset's embedding endpoint.

        Read once here, when the index is created, and not again: an index is
        built with one embedding model, and re-embedding a question with
        another because the user switched preset mid-chat would compare vectors
        that are not comparable. Switching preset therefore changes what the
        *next* index is built with, and Top K and the cutoff, which are
        arithmetic over what is already stored.
        """
        preset = presets.retrieval()
        Settings.embed_model = OpenAILikeEmbedding(
            api_base=preset.embedding_base_url,
            api_key=preset.embedding_api_key or "none",
            model_name=preset.embedding_model,
        )
        Settings.chunk_size = preset.chunk_size
        Settings.chunk_overlap = preset.chunk_overlap
        Settings.context_window = preset.context_window

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

    def prompt(self, question):
        """The question and the chunks closest to it, as one prompt to send.

        Retrieval is all this layer does with a question: what to do with the
        answer belongs to the chat, which is the point of handing back a prompt
        rather than a stream. A question nothing matches is reported as such
        instead of being answered from the model's own memory with no sources
        behind it.
        """
        self.retrieved = self.retrieve(question)
        if not self.retrieved:
            raise DocumentError(
                "Nothing in the index is close enough to that question. Lower "
                "the similarity cutoff or index more documents."
            )
        return PROMPT.format(context=self.context(), question=question)

    def filenames(self):
        """The documents in the index, as far as it recorded where they came from.

        A page indexed by URL is named by its address; text indexed directly
        is named by nothing, so this is allowed to come back empty. An index
        whose contents cannot be named is still worth searching.
        """
        if not self.ready():
            return []
        names = set()
        for node in self.index.docstore.docs.values():
            name = node.metadata.get("file_name") or node.metadata.get("file_path")
            if name:
                names.add(str(name))
        return sorted(names)

    def search(self, question):
        """The passages closest to `question`, as text, for the search tool.

        The same retrieval `prompt()` does with none of the wording around it:
        a tool result is context handed to a model that asked for it itself, so
        there is nothing left to instruct it to do with it. Nothing found is ""
        rather than an error, because the tool has to answer the model in words
        of its own.
        """
        self.retrieved = self.retrieve(question)
        return self.context() if self.retrieved else ""

    def context(self):
        """The retrieved chunks as the model should read them.

        Labelled by `header` rather than by `MetadataMode.LLM`, which renders
        whichever metadata llama_index kept and has no idea there is a score. A
        chunk the model can see is a distant match is one it can say it is
        unsure of, rather than reading every passage as equally true.
        """
        return SEPARATOR.join(
            f"{header(node, number)}\n{node.text}"
            for number, node in enumerate(self.retrieved, 1)
        )

    def retrieve(self, question):
        """The chunks closest to the question, with the cutoff applied.

        A retriever rather than a query engine in "no_text" mode. That mode
        still builds a response synthesizer, and llama_index builds that one
        without the llm it was handed, so it falls back to the process-wide
        `Settings.llm` — which resolves to OpenAI and raises "No API key found
        for OpenAI" no matter what the preset points at. Retrieving does not
        need a model at all.
        """
        preset = presets.retrieval()
        nodes = self.index.as_retriever(
            similarity_top_k=preset.similarity_top_k
        ).retrieve(question)
        cutoff = SimilarityPostprocessor(similarity_cutoff=preset.similarity_cutoff)
        return cutoff.postprocess_nodes(nodes, query_str=question)

    def sources(self):
        """The chunks the last answer was built from."""
        return self.retrieved


def _as_document(text, source):
    return [Document(text=text, metadata={"file_name": source})]


def origin(node):
    """Where a chunk came from, or "" if the index did not record it.

    Two keys, because the two readers record it under different ones: a file
    gets `file_path`, and a page indexed by URL gets `file_name` holding its
    address. The page is a PDF reader's, and only some files have one.
    """
    metadata = node.metadata or {}
    where = str(metadata.get("file_path") or metadata.get("file_name") or "")
    page = metadata.get("page_label")
    return f"{where}, page {page}" if where and page else where


def header(node, number):
    """The line above one chunk: which it is, where it is from, how close it is.

    One line for both readers of a retrieval. The model needs the source to
    cite it and the score to weigh it; the user reading Show Context is
    checking those same two things against the answer they were given.
    """
    parts = [f"Context {number}"]
    where = origin(node)
    if where:
        parts.append(where)
    if node.score is not None:
        parts.append(f"similarity {node.score:.2f}")
    return ", ".join(parts)


def describe_sources(nodes):
    """The retrieved chunks, for the Show Context setting.

    The header the model was given, over text with its whitespace collapsed:
    this goes out as one transcript notice, where a chunk's own line breaks
    would read as the boundaries between messages.
    """
    lines = []
    for number, node in enumerate(nodes, 1):
        text = " ".join(node.text.split())
        lines.append(f"{header(node, number)}: {text}")
    return "\n".join(lines) or "Nothing was retrieved."
