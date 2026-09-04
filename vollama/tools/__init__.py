"""What the model is allowed to do to this machine.

Three modules, no cycles between them:

    workspace   what a path means, and whether it names something we may touch
    shell       running a command, and the background jobs that outlive a call
    files       reading, writing and editing text files
    registry    the five tools as one list, and the way chat calls them

`shell` and `files` are peers: neither imports the other, and both take their
path rules from `workspace`. `registry` is the only thing above them.
"""
