"""VOLlama: an accessible desktop chat client for OpenAI-compatible servers.

The package is laid out as its layers, and imports only ever point downward:

    config   what the user has set. Depends on nothing else here.
    tools    what the model may do to this machine. Depends on config.
    rag      documents, embeddings and retrieval. Depends on config.
    speech   turning text into sound on this platform. Depends on config.
    chat     the conversation and the turn loop. Depends on config and tools.
    ui       wxPython. Depends on everything above.

Nothing below `ui` imports wx, and `ui.transcript` is the only module that
marshals work onto the GUI thread. That is the rule the layout exists to make
visible: you can check it by listing the directory.
"""

# The build number, compared against the newest GitHub release to offer an
# update. One number, incremented per release; the tag it is read out of may be
# spelled however the release was named.
BUILD = 72
