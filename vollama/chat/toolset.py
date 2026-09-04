"""What the model may call in one turn, and the two separate gates on it.

The five tools in `tools.registry` act on this machine, so they are behind the
Tools checkbox, which is off by default. Search only reads an index the user
built and asked to load, so it is offered whenever there is one: gating it
behind the same checkbox would mean turning on shell commands and file writes
in order to ask a question about a book.

This is the layer that can compose the two, because the index is the chat's and
the registry is below it. `rag.search` therefore hands out plain functions and
a schema, and the `Tool` record is made here.
"""

import functools

from vollama.chat import client
from vollama.rag import search
from vollama.tools import registry


def for_turn(index):
    """The tools to offer this turn, as `Tool` records.

    The machine tools come first, because their schemas never change: a server
    caching the prompt prefix keeps that cache when a document is indexed,
    which rewrites the search tool's description with the new file names.
    """
    tools = list(registry.REGISTRY) if client.tools_enabled() else []
    if index is not None and index.ready():
        tools.append(searching(index))
    return tools


def searching(index):
    """The search tool over `index`.

    Free, for the same reason `read` is: looking something up is not the kind
    of progress the round budget exists to limit, and a search that spent a
    round would leave a model nine turns to answer from what it found.
    """
    return registry.Tool(
        schema=search.schema(index),
        run=functools.partial(search.run, index),
        summarize=search.summarize,
        free=True,
    )


# Every tool a call in the history might have to be described as, whatever is
# loaded now. A chat reopened has no index, and the search it contains still
# has to read the way it did when it ran.
DESCRIBED = (*registry.REGISTRY, searching(None))
