"""What the model may call in one turn, and the two separate gates on it.

The five tools in `tools.registry` act on this machine, so they are behind the
Tools checkbox, which is off by default. Search only reads an index the user
built and asked to load, so it is offered whenever there is one: gating it
behind the same checkbox would mean turning on shell commands and file writes
in order to ask a question about a book.

This is the layer that can compose the two, because the index is the chat's and
the registry is below it. `rag.search` therefore hands out plain functions and
a schema, and the `Tool` record is made here.

Both gates are read here and nowhere else, `environment()` included: what the
machine looks like is only told to a model that can act on it, which is the same
question as whether to offer the five, and answering it in two modules is how
the two answers come apart.
"""

import functools

from vollama.config.settings import settings
from vollama.rag import search
from vollama.tools import registry


def for_turn(index):
    """The tools to offer this turn, as `Tool` records.

    The machine tools come first, because their schemas never change: a server
    caching the prompt prefix keeps that cache when a document is indexed,
    which rewrites the search tool's description with the new file names.
    """
    tools = list(registry.REGISTRY) if settings.tools else []
    if index is not None and index.ready():
        tools.append(searching(index))
    return tools


def environment():
    """What to tell the model about this machine, or None when it cannot act.

    Left out unless the machine tools are on, for the same reason the summary
    request drops the tool list: a model still being told how to run commands
    writes commands rather than prose.
    """
    return registry.environment() if settings.tools else None


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
