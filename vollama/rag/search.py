"""Retrieval as a tool the model calls, rather than a mode the user turns on.

`/q` searches with the user's own wording, once, before the model has seen
anything. A tool lets the model write the query itself, and search again with
better terms when the first result was thin, which is the whole of multi-hop
retrieval for the price of a schema. `/q` stays: it is the only retrieval a
model that calls tools badly, or an endpoint that ignores `tools`, can do.

The call blocks. Retrieval is one embedding request and a vector search, and
the context is what the model asked for and cannot go on without, so there is
nothing here like the shell's background jobs: the call returns with the
passages in it.

How much comes back is not the model's to decide. Top K and the similarity
cutoff already answer "how many passages, and how close" — they are on one
dialog the user can see and change, and a model given the same numbers as
parameters would quietly disagree with what that dialog says. The query is the
one part of a search the model knows better than the user.

Only `run` needs an index. The schema's wording and the transcript's one line
do not, so a chat reopened with nothing loaded still describes the searches it
contains the way it did when they ran.
"""

import logging

from vollama.rag.index import SEPARATOR

log = logging.getLogger(__name__)

NAME = "search"

# How much of one result the model is shown, in characters. A tool result is
# sent once more before `outgoing()` drops it, so a large Top K over large
# chunks would otherwise fill the window twice over. Characters rather than
# tokens because the tokenizer belongs to the chat layer, which is above this
# one, and a cap this generous does not need to be exact.
MAX_RESULT = 20_000

# How many file names the description lists. A model will not search an index
# it cannot see the contents of, but an index over a thousand files cannot say
# so in a prompt that is sent with every message.
MAX_FILES = 30


def schema(index):
    """The function schema, with what is indexed written into its description.

    Told only that a search tool exists, a model either never calls it or calls
    it for things nothing in the index covers. The file names are the cheapest
    description of what was indexed that we already have.
    """
    return {
        "type": "function",
        "function": {
            "name": NAME,
            "description": (
                "Search the user's indexed documents and return the passages "
                "closest to your query. Use it whenever the answer might be in "
                "them, without being asked to, and search again with different "
                "words if what came back does not answer the question. Passages "
                "are matched by meaning rather than by exact words, so write the "
                "query as the sentence you want a passage to look like. How many "
                "come back is the user's own retrieval setting, not a parameter "
                "of this call." + indexed(index)
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to look for, in your own words.",
                    }
                },
                "required": ["query"],
            },
        },
    }


def indexed(index):
    """A sentence naming the documents in the index, or "" if it names none."""
    names = files(index)
    if not names:
        return ""
    shown = ", ".join(names[:MAX_FILES])
    rest = len(names) - MAX_FILES
    return f" Indexed: {shown}" + (f", and {rest} more." if rest > 0 else ".")


def files(index):
    """The documents in the index, or [] when there is no index to ask."""
    return index.filenames() if index is not None and index.ready() else []


def run(index, query=""):
    """The passages closest to `query`, as text for the model to read.

    Every failure is worded rather than raised, like every other tool: the
    model is the one who acts on it, and an embedding endpoint that is down
    should cost a retry, not the whole turn.
    """
    if index is None or not index.ready():
        return "There is no index loaded, so there is nothing to search."
    if not query.strip():
        return "Give a query to search for."
    try:
        found = index.search(query)
    except Exception as e:
        log.exception("The search failed")
        return f"The search failed: {e}"
    if not found:
        return (
            "Nothing in the index is close enough to that query. Try other "
            "words: how close a passage has to be is the similarity cutoff the "
            "user set, not something this search can relax."
        )
    return trim(found)


def trim(found):
    """`found`, cut to what the model is shown, on a boundary between passages.

    Said where the cut happened rather than at the end, so a result missing a
    passage does not read as the whole of what was retrieved. Cutting between
    passages rather than mid-sentence keeps every passage that is shown intact,
    which matters when the model quotes one.
    """
    if len(found) <= MAX_RESULT:
        return found
    kept = found[:MAX_RESULT].rpartition(SEPARATOR)[0]
    return (kept or found[:MAX_RESULT]) + SEPARATOR + (
        "[The remaining passages were too long to include. Search again with a "
        "narrower query, or ask the user to lower Top K or the chunk size on "
        "the preset's RAG page.]"
    )


def summarize(arguments):
    """The one line the transcript shows for a search."""
    query = str(arguments.get("query", "")).strip()
    return f'Searched the documents for "{query}"'
