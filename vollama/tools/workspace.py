"""What a path means to the tools, and whether it names something we may touch.

The rules are here rather than in `files` because `shell` needs them too: both
tools take a relative path from the same place, and having the shell tool
import that from the file tool put the dependency between two peers the wrong
way round.

Trust boundary: none of this is a sandbox, and it is not trying to be. A path
is resolved and checked for the two shapes that are not files at all; an
absolute path anywhere on the machine is allowed on purpose, because the point
of the tools is to work on the user's own files. What gates them is the Tools
checkbox on the Chat menu, which is off by default.
"""

import difflib
import os

from vollama.config.settings import settings

# Paths that parse as a file and are not one. Writing to a Windows reserved
# name talks to a device instead of the disk and reports success; reading a
# character device under /dev never returns.
DEVICES = (
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)


def working_dir():
    """Where a relative path is taken from. What the Chat menu's CD shows.

    Checked on the way out rather than when it is set, since a directory chosen
    in an earlier session can be gone, or on a drive that is not mounted, by
    the time a command runs in it.
    """
    chosen = (settings.workdir or "").strip()
    if chosen and os.path.isdir(chosen):
        return chosen
    return os.getcwd()


def resolve(path):
    """The absolute path the model meant, relative to the working directory."""
    path = os.path.expanduser((path or "").strip())
    if not path:
        raise ValueError("No path was given.")
    if not os.path.isabs(path):
        path = os.path.join(working_dir(), path)
    return os.path.normpath(path)


def device(full):
    """Whether this path names a device rather than a file on disk.

    Each platform's rule applies only on that platform. /dev is an ordinary
    folder name on Windows, where a top level dev folder is where a good many
    people keep their code, and nul is an ordinary filename on Linux.
    """
    if os.name == "nt":
        # con.txt is the console too, so the extension comes off first.
        return os.path.basename(full).split(".")[0].lower() in DEVICES
    return full.startswith("/dev/")


def suggest(full):
    """Names in the same folder close to the one asked for, as a sentence.

    A wrong path is usually wrong by a character or a plural, and the answer is
    in the directory listing we already had to read to know the file is missing.
    """
    parent = os.path.dirname(full) or "."
    try:
        names = os.listdir(parent)
    except OSError:
        return ""
    close = difflib.get_close_matches(os.path.basename(full), names, n=3, cutoff=0.6)
    return " Did you mean " + ", ".join(close) + "?" if close else ""


def checked(path, must_exist=True):
    """Turn a path into one we can act on, or raise saying why we cannot."""
    full = resolve(path)
    if device(full):
        raise ValueError(
            f"{full} is a device, not a file. Reading one may never return and "
            "writing one throws the text away, so it is refused here. Use run "
            "if you really mean the device."
        )
    if os.path.isdir(full):
        raise ValueError(f"{full} is a directory, not a file.")
    if must_exist and not os.path.exists(full):
        raise ValueError(
            f"There is no file at {full}. Relative paths are taken from "
            f"{working_dir()}.{suggest(full)}"
        )
    return full


def checked_directory(path):
    """A directory a command may run in, or the working directory for nothing.

    Through `resolve` like every other path, so a relative directory means the
    same thing in `run`'s workdir as it does in `read`'s path. It did not
    before, and two meanings for a relative path inside one toolset is a trap
    rather than a feature.

    Raises ValueError with the message the model should read if it named one
    that is not there.
    """
    if not str(path or "").strip():
        return working_dir()
    full = resolve(path)
    if not os.path.isdir(full):
        raise ValueError(
            f"There is no directory {full}, so the command did not run. "
            "Pass an existing directory as workdir, or leave it out."
        )
    return full
