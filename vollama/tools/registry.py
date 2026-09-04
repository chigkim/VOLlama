"""The five tools as one list, and the only way the chat layer reaches them.

A `Tool` pairs the OpenAI function schema the model reads with the three things
the application needs alongside it: what to run, how to say what was run in one
line of transcript, and whether the call counts against the turn's budget.
Before this the registry was a dictionary of functions plus a set of names plus
a `describe` that asked which module a tool had come from; now a tool that is
added is added in one place, and nothing has to be told about it twice.

**Trust boundary.** Everything below this module acts on the user's machine
with the user's own privileges, and there is no confirm-before-run dialog for
commands or for file writes. The single gate is `settings.tools`, the Tools
checkbox on the Chat menu, which is off by default and which `chat.client`
consults when it decides whether to send this list at all. That is a deliberate
product decision for a single-user desktop tool: a prompt on every call trains
the user to say yes. It is stated here because a reader of the tool modules
should not have to infer it from their absence.
"""

import json
import platform
from dataclasses import dataclass
from datetime import date
from typing import Callable

from vollama.tools import files, shell
from vollama.tools.workspace import working_dir

# How many times in a row the model may call a tool before the turn ends.
# Free calls do not count: waiting on a build, or reading the files it is about
# to change, is not the kind of progress the budget exists to limit.
MAX_TOOL_ROUNDS = 10

# A ceiling on calls of any kind in one turn, free ones included. Without it a
# model that only ever reads never spends a round and the turn never ends.
MAX_TOOL_CALLS = 40


@dataclass(frozen=True)
class Tool:
    """One tool: what the model is told, what runs, and what the user sees."""

    schema: dict
    run: Callable[..., str]
    summarize: Callable[[dict], str]
    free: bool = False

    @property
    def name(self):
        return self.schema["function"]["name"]


REGISTRY = (
    Tool(shell.RUN_TOOL, shell.run, shell.summarize_run),
    Tool(shell.POLL_TOOL, shell.poll, shell.summarize_poll, free=True),
    Tool(files.READ_TOOL, files.read, files.summarize_read, free=True),
    Tool(files.WRITE_TOOL, files.write, files.summarize_write),
    Tool(files.EDIT_TOOL, files.edit, files.summarize_edit),
)

BY_NAME = {tool.name: tool for tool in REGISTRY}

# What goes into the request, when tools are on.
TOOLS = [tool.schema for tool in REGISTRY]


def is_free(name):
    """Whether this call is one that does not spend a round."""
    tool = BY_NAME.get(name)
    return bool(tool and tool.free)


def arguments_of(raw):
    """The arguments of a tool call as a dictionary, or a string saying why not.

    The model sends them as a JSON string. Broken JSON is an answer to give it,
    not a reason to end the turn, so the failure is worded rather than raised.
    """
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except ValueError as e:
        return f"Could not read the arguments as JSON: {e}"
    if not isinstance(parsed, dict):
        return "The arguments must be a JSON object."
    return parsed


def call(name, raw_arguments):
    """Run the tool the model asked for and return its result as text.

    Every failure comes back as text, because the model is the one who has to
    read it and act on it. A tool that raised would end the turn instead, which
    is the wrong answer to a mistyped argument name.
    """
    tool = BY_NAME.get(name)
    if not tool:
        return f"There is no tool named {name}."
    arguments = arguments_of(raw_arguments)
    if isinstance(arguments, str):
        return arguments
    try:
        return tool.run(**arguments)
    except TypeError as e:
        return f"Wrong arguments for {name}: {e}"


def describe(name, raw_arguments):
    """The one line the transcript shows for a call."""
    arguments = arguments_of(raw_arguments)
    if isinstance(arguments, str):
        return str(raw_arguments)
    tool = BY_NAME.get(name)
    if not tool:
        return f"{name} {json.dumps(arguments)}"
    return tool.summarize(arguments)


def environment():
    """What the model cannot work out for itself before its first command.

    Only the working directory and the date move, and the date only once a day,
    so a server that caches the prompt prefix keeps that cache until the user
    picks a new folder, which is the one time it should be thrown away anyway.
    """
    return (
        "Environment for the tools:\n"
        f"Working directory, which relative paths are taken from: {working_dir()}\n"
        f"Platform: {platform.platform()}\n"
        f"Shell running your command: {shell.invocation()}\n"
        f"Python on PATH: {shell.python_version()} at {shell.interpreter()}\n"
        f"Today's date: {date.today():%Y-%m-%d, %A}\n"
        "A project may use a different Python from the one above, under uv or "
        "in a .venv. Check for one before assuming its packages are installed."
    )
