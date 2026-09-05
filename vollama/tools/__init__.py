"""What the model is allowed to do to this machine.

Six modules, no cycles between them:

    workspace   what a path means, and whether it names something we may touch
    content     whether content is text, parses, and is the whole file
    matching    where an old_text goes, and why it did not go anywhere
    shell       running a command, and the background jobs that outlive a call
    files       reading, writing and editing text files
    registry    the five tools as one list, and the way chat calls them

`workspace`, `content` and `matching` depend on nothing here; the last two are
pure functions over text, which is why the interesting algorithms live in them
and can be read without a disk. `shell` and `files` are peers: neither imports
the other, and both take their path rules from `workspace`. `registry` is the
only thing above them.
"""
