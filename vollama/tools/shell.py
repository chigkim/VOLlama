"""run and poll: a shell command in a separate process, and its output.

A shell rather than Python source. Every model that can call tools was trained
on traces where the command slot holds `git status`, not
`subprocess.run(["git", "status"], ...)`, so Python is off-distribution in
exactly the place accuracy matters. And Python beyond one line needs real line
breaks and exact indentation inside a JSON string, which is the failure
`files.py` exists to prevent, reintroduced one tool over. Shell commands are
flat, so they do not have it. Python is still reachable by the better road:
write the script with the write tool, then run the file.

A call that finishes quickly reports as you would expect. One that does not
hands back a session id and keeps running, so a build or a test suite does not
have to fit inside one tool call; the model reattaches with poll. `JobTable`
owns those jobs, and it is the only mutable state in this module.
"""

import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager

from vollama.tools.workspace import valid_directory

WINDOWS = platform.system() == "Windows"

# How long a call waits before handing back a session id instead of a result.
# Short, because the whole turn is blocked until it returns.
YIELD_SECONDS = 10

# Total runtime a job gets before it is killed, whether or not anyone polls it.
# A ceiling rather than the everyday limit: what normally ends a job is going
# quiet, not going long, so this is generous and IDLE_TIMEOUT does the work.
DEFAULT_TIMEOUT = 1800
MAX_TIMEOUT = 3600

# How long a background job may produce nothing at all before it is killed.
# Output is a far better sign of life than elapsed time: a build that prints
# steadily for twenty minutes is working, and a command wedged on a hidden
# prompt is not, however long its timeout still has to run. Killing on the
# clock instead gets both backwards, and the model's only recovery from the
# first case is to guess a bigger number and pay for the whole build twice.
IDLE_TIMEOUT = 120

# How long poll may block waiting for a job to finish.
MAX_POLL_WAIT = 30
# How often a wait stops to see whether the user has given up on it.
STOP_CHECK = 0.25

# How much of the process output is fed back to the model, so a runaway print
# loop cannot blow up the next prompt. Past this we keep the start and the end
# and drop the middle: the start says what the command was doing, and the end
# holds the result and any traceback.
MAX_OUTPUT = 8000
HEAD_SHARE = 0.4

# Where the whole of an output too big to send is kept, so the trimming is only
# of what reaches the model and not of the output itself. The middle of a build
# log is exactly where its first error is, and a model handed the head and the
# tail has no way back to it. With a path it has one, through the read tool it
# already has. How long an unread log is worth keeping around.
SPILL_DIR = "vollama-run-output"
SPILL_TTL = 24 * 60 * 60

# Ways a command puts a process beyond our reach. Jobs start as group leaders so
# that killing one kills its children, but a process that detaches itself leaves
# that group: poll cannot read it, kill_all() on New Chat and on exit cannot stop
# it, and it outlives VOLlama. Warned about rather than refused, since a command
# is occasionally meant to do this.
#
# These mean nothing else wherever they appear, so they are looked for anywhere.
DETACHERS = ("nohup", "disown", "setsid", "start-process")

# cmd's start does detach, but start is also the name of half the npm scripts in
# existence, so it only counts as the first word of a command. npm start must not
# read as one. Windows only, since POSIX has no start, and a trailing & is the
# other way round: it backgrounds on POSIX and is only a separator in cmd, where
# warning about it would be wrong.
LEADING = ("start",) if WINDOWS else ()

# Asking a command what its flags are never backgrounds anything.
NO_DETACH = ("--help", "-h", "--version", "-v")

# How much of a running job's output we hold on to. Bigger than MAX_OUTPUT
# because it is read in pieces, a poll at a time.
MAX_BUFFER = 200000

# Running jobs allowed at once. The oldest is killed to make room, so a model
# that forgets to poll cannot fill the machine with processes. High enough that
# hitting it means something has gone wrong rather than that the work is busy:
# the cost of a parked job is two reader threads and its buffer, not CPU.
MAX_JOBS = 32

# How long a finished job stays readable after its completion was reported.
FINISHED_TTL = 600
SWEEP_SECONDS = 5

def shell():
    """The program that runs a command, and the flag that hands it one.

    This is what spawn() ends up doing through shell=True, spelled out so the
    model can be told exactly what will run its command.

    cmd rather than PowerShell on Windows: it starts in milliseconds where
    PowerShell costs the better part of a second on every call, and its quoting
    rules are the ones a model has seen most. COMSPEC is honoured because a
    machine that has moved cmd has moved it for a reason.

    /bin/sh rather than $SHELL elsewhere. A command written for POSIX sh runs
    under every shell a user might have; the reverse is not true, and $SHELL
    could be fish, whose syntax is its own.
    """
    if WINDOWS:
        return [os.environ.get("COMSPEC") or "cmd.exe", "/c"]
    return ["/bin/sh", "-c"]


def oem_codepage():
    """The codepage a Windows console program writes in, as a codec name."""
    if not WINDOWS:
        return None
    try:
        import ctypes

        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    except Exception:
        return None


FALLBACK = oem_codepage()


def decode(raw):
    """Turn one line of output into text, whatever codepage it arrived in.

    UTF-8 first, since that is what modern tools and the Python we start emit.
    But cmd's own built-ins and older console programs still write the OEM
    codepage, and reading those as UTF-8 turns every accented character into a
    replacement mark: `dir` on a folder with an accent in its name comes back
    unreadable. So they get a second try. Nothing is ever refused; the last
    attempt replaces what it cannot read.

    Lines rather than the whole stream is safe here: readline splits on a
    newline byte, which never appears inside a multi-byte UTF-8 character, so a
    line can never end mid-character.

    A lone carriage return is left alone, so a progress bar stays the one line
    it was drawn as instead of becoming a hundred of them.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
        if FALLBACK:
            try:
                text = raw.decode(FALLBACK)
            except (UnicodeDecodeError, LookupError):
                pass
        if text is None:
            text = raw.decode("utf-8", "replace")
    return text.replace("\r\n", "\n")


def invocation():
    """Exactly how a command is handed to the shell, for the model to read.

    Named in the description rather than left to be guessed, the way gemini-cli
    and openclaw do it: a model told the literal invocation writes for the
    right dialect, where one told "a shell" writes for the one it saw most in
    training and gets ls on Windows.
    """
    program, flag = shell()
    return f"{os.path.basename(program)} {flag} <command>"


def run_description():
    """The run tool description, written for the shell this machine has."""
    if WINDOWS:
        dialect = (
            "It is run as `" + invocation() + "`, so write it for the Windows "
            "command prompt: dir rather than ls, backslashes in paths, %VAR% "
            "for an environment variable. PowerShell is there when you need "
            'it: powershell -NoProfile -Command "...". '
        )
        venv = ".venv\\Scripts\\python.exe"
    else:
        dialect = (
            "It is run as `" + invocation() + "`, so write POSIX shell: pipes, "
            "redirection and quoting all work as usual. "
        )
        venv = ".venv/bin/python"
    return (
        "Run a shell command and return its output: stdout and stderr "
        "together, in the order the command wrote them. "
        + dialect
        + "Every call is a fresh shell, so a cd, a variable or an export does "
        "not carry over to the next one: chain related steps into a single "
        "command with &&. To run somewhere else, pass workdir rather than "
        "beginning with cd. To use a virtual environment, do not activate it: "
        f"run its interpreter by path, {venv}. Nothing can answer a prompt, "
        "since the command has no input; pass the flag that skips it, such as "
        "-y. For more Python than fits on one line, write it to a file with "
        "the write tool and run that file, rather than passing source to -c. "
        "Output too long to send is trimmed in the middle, with the whole of "
        "it kept in a file whose path is named at the cut, so never pipe a "
        "command through head or tail to shorten it: that throws away what "
        "you cannot then go back for. "
        f"A command still running after {YIELD_SECONDS} seconds keeps going in "
        "the background and returns a session id instead of a result; read it "
        "with poll. Waiting costs you nothing, since a command that finishes "
        "sooner returns the moment it does, so do not set a small timeout to "
        f"hurry a long build along. A job is killed if it goes {IDLE_TIMEOUT} "
        "seconds without printing anything, which is what catches a command "
        "stuck waiting for input."
    )


RUN_TOOL = {
    "type": "function",
    "function": {
        "name": "run",
        "description": run_description(),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": f"The command to run, as `{invocation()}`.",
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        f"Seconds the command may run in total, in the "
                        f"background included, before it is killed. Defaults "
                        f"to {DEFAULT_TIMEOUT}, at most {MAX_TIMEOUT}. A "
                        f"ceiling, not a wait: the call returns as soon as the "
                        f"command finishes, so leave it alone unless you know "
                        f"the command needs longer."
                    ),
                },
                "workdir": {
                    "type": "string",
                    "description": (
                        "Directory to run in, for this one call. Leave it out "
                        "to use the working directory the user chose in "
                        "VOLlama, which is where relative paths are taken "
                        "from."
                    ),
                },
            },
            "required": ["command"],
        },
    },
}

POLL_TOOL = {
    "type": "function",
    "function": {
        "name": "poll",
        "description": (
            "Check on a command that run left running in the background. "
            "Returns whether it is still going and any output since the last "
            "poll, so the same output is never sent twice. Call it without a "
            "session id to list every background command."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": (
                        "The session id run returned. Any unambiguous "
                        "start of it works. Leave it out to list all of them."
                    ),
                },
                "wait": {
                    "type": "integer",
                    "description": (
                        f"Seconds to wait for the command to finish before "
                        f"answering. Defaults to 0, which answers at once. At "
                        f"most {MAX_POLL_WAIT}."
                    ),
                },
                "kill": {
                    "type": "boolean",
                    "description": "Stop the command instead of reading it.",
                },
            },
            "required": [],
        },
    },
}

def interpreter():
    """Path to a real Python interpreter.

    In a PyInstaller build sys.executable is VOLlama itself, so running it with
    -c would launch another copy of the app instead of a Python process.
    """
    if getattr(sys, "frozen", False):
        return shutil.which("python") or shutil.which("python3") or "python"
    return sys.executable


_version = ""


def python_version():
    """The version of the interpreter run uses, asked once and remembered.

    Not sys.version: in a PyInstaller build interpreter() is whatever python is
    on PATH, a different install from the one running VOLlama. It is what a
    bare `python` in a command will be, and says nothing about the Python a
    project uses, which the model has to go and find.
    """
    global _version
    if not _version:
        try:
            out = subprocess.run(
                [interpreter(), "-c", "import platform;print(platform.python_version())"],
                capture_output=True,
                text=True,
                timeout=15,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}),
            )
            _version = out.stdout.strip() or "unknown"
        except Exception:
            _version = "unknown"
    return _version


def shorten(text, path=None):
    """Trim text to MAX_OUTPUT, keeping the head and the tail.

    The marker goes where the loss is rather than at the end, so output that
    was cut cannot read as output that finished. When the whole of it was kept
    on disk, the marker says where, at the point the model needs it.
    """
    if len(text) <= MAX_OUTPUT:
        return text
    head = int(MAX_OUTPUT * HEAD_SHARE)
    tail = MAX_OUTPUT - head
    dropped = len(text) - MAX_OUTPUT
    marker = f"... {dropped} characters omitted out of {len(text)} total"
    if path:
        marker += f"; all of it is in {path}, which read can page through"
    return text[:head] + f"\n\n{marker} ...\n\n" + text[-tail:]


def spill_dir():
    """The folder the full logs go in, created if it is not there."""
    path = os.path.join(tempfile.gettempdir(), SPILL_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def prune_spills(directory):
    """Drop logs old enough that nothing is going to read them."""
    cutoff = time.time() - SPILL_TTL
    for name in os.listdir(directory):
        old = os.path.join(directory, name)
        try:
            if os.path.getmtime(old) < cutoff:
                os.remove(old)
        except OSError:
            pass


def spill(text):
    """Keep the whole output on disk and return its path, or None if we cannot."""
    try:
        directory = spill_dir()
        prune_spills(directory)
        handle, path = tempfile.mkstemp(prefix="run-", suffix=".log", dir=directory)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return path
    except OSError:
        # A full or read-only temp folder is not a reason to fail the command;
        # trimming without a path is what happened before there was one.
        return None


def capped(text):
    """What the model sees of an output, with the rest of it left on disk."""
    if len(text) <= MAX_OUTPUT:
        return text
    return shorten(text, spill(text))


def dropped(count):
    """The marker for output that was lost before anyone read it."""
    return (
        f"... {count} characters of output were dropped here: the command "
        f"produced more than {MAX_BUFFER} characters between polls. Redirect "
        "it to a file and read that if you need all of it ...\n"
    )


# What a non-zero exit usually means. A model told only the number spends a
# turn working out whether the command failed or answered, and gets 137 wrong
# every time.
EXIT_CODES = {
    1: "a general error",
    2: "the command was used wrongly, often a bad option or a missing argument",
    126: "the file was found but could not be run",
    127: "command not found: it is not installed, or not on PATH",
    130: "interrupted, SIGINT",
    134: "aborted, SIGABRT, usually an assertion or a panic",
    137: (
        "killed, SIGKILL. On a build, a test run or anything holding a lot of "
        "data this is almost always the machine running out of memory, not a "
        "bug in the command"
    ),
    139: "a segmentation fault",
    143: "terminated, SIGTERM",
}

# Where the number means something else, or means nothing wrong at all. A model
# that reads grep's 1 as a failure retries it, then doubts the file.
BY_PROGRAM = {
    "grep": {1: "no lines matched, which is an answer and not a failure"},
    "rg": {1: "no lines matched, which is an answer and not a failure"},
    "findstr": {1: "no lines matched, which is an answer and not a failure"},
    "ag": {1: "no lines matched, which is an answer and not a failure"},
    "diff": {1: "the files differ, which is an answer and not a failure"},
    "cmp": {1: "the files differ, which is an answer and not a failure"},
    "fc": {1: "the files differ, which is an answer and not a failure"},
    "git": {
        1: (
            "for diff --exit-code or grep, that there was a difference or no "
            "match, which is an answer; otherwise an error, and the message "
            "above says which"
        )
    },
    "pytest": {
        1: "tests failed, which the output above lists",
        2: "the run was interrupted",
        3: "an internal error",
        4: "the command line was wrong",
        5: "no tests were collected, so check the path and the file names",
    },
    "curl": {
        6: "could not resolve the host",
        7: "could not connect to the host",
        22: "the server returned an HTTP error",
        28: "the request timed out",
    },
    "wget": {4: "a network failure", 8: "the server returned an error"},
    "npm": {1: "the script it ran failed; its own output is above"},
    "pip": {1: "the install failed; the reason is in the output above"},
    "test": {1: "the condition was false"},
    "mypy": {1: "type errors were found, which is an answer and not a failure"},
    "ruff": {1: "problems were found, which is an answer and not a failure"},
}

# Words that stand in front of the command that actually ran.
RUNNERS = {"python", "python3", "py", "uv", "uvx", "npx", "poetry", "pipx", "pdm"}
STEPS = {"run", "exec", "m"}


def word(part):
    """One token of a command reduced to the name of the program it names."""
    return os.path.splitext(os.path.basename(part.strip("\"'")))[0].lower()


def program(command):
    """The name of the thing that ran, for reading its exit code by."""
    for part in command.strip().split():
        name = word(part)
        if name in RUNNERS or name in STEPS or name.startswith("-"):
            continue
        return name
    return ""


def explain(command, code):
    """What this exit code probably means, in a few words, or None."""
    if not code:
        return None
    meaning = BY_PROGRAM.get(program(command), {}).get(code)
    if meaning:
        return meaning
    if code < 0:
        # Popen reports a signal as its negative on POSIX, so this one is not a
        # guess the way 128 + n below is.
        return f"killed by signal {-code}"
    meaning = EXIT_CODES.get(code)
    if meaning:
        return meaning
    if 128 < code < 192:
        return f"probably killed by signal {code - 128}"
    return None


# What a command that exited cleanly with both pipes empty reports. It cannot
# be the empty string: a tool message with no content reads to the model as a
# broken tool rather than a quiet success, and some servers refuse to accept
# one at all. Short because it is also what the transcript shows.
NO_OUTPUT = "No output."


def report(out, returncode=None, note=None, command=""):
    """Assemble what the model sees from one run."""
    parts = []
    out = (out or "").strip()
    if out:
        parts.append(out)
    if returncode:
        meaning = explain(command, returncode)
        parts.append(f"Exit code: {returncode}" + (f" ({meaning})" if meaning else ""))
    if note:
        parts.append(note)
    if not parts:
        return NO_OUTPUT
    return capped("\n".join(parts))


class Stream:
    """One pipe's output, with a mark for how much the model has already read.

    Only the tail is kept. Anything dropped from the front is counted so a poll
    can say output went missing rather than quietly skipping it.
    """

    def __init__(self):
        self.text = ""
        self.base = 0  # characters dropped off the front
        self.cursor = 0  # absolute position the model has read up to

    def write(self, chunk):
        self.text += chunk
        if len(self.text) > MAX_BUFFER:
            cut = len(self.text) - MAX_BUFFER
            self.text = self.text[cut:]
            self.base += cut

    def take(self):
        """Everything since the last take, plus how much was lost before it."""
        start = max(self.cursor, self.base)
        missed = start - self.cursor
        text = self.text[start - self.base :]
        self.cursor = self.base + len(self.text)
        return text, missed

    def all(self):
        """The whole buffer, with anything lost off the front said so."""
        if self.base:
            return dropped(self.base) + self.text
        return self.text


class Job:
    """A command that outlived its yield window, and the pipes still feeding it."""

    def __init__(self, process, command, timeout):
        # The id is assigned by the JobTable when the job is registered:
        # a job that finishes inside the yield window is never registered
        # and never needs one.
        self.id = None
        self.process = process
        self.command = command
        self.timeout = timeout
        self.started = time.monotonic()
        self.spoke = self.started  # when it last produced output
        self.finished_at = None
        self.killed = False
        self.expired = False  # killed for running past its timeout
        self.stalled = False  # killed for going quiet
        self.reported = False  # has the model been told it finished
        self.lock = threading.Lock()
        self.out = Stream()
        self.readers = [self.reader(process.stdout, self.out)]

    def reader(self, pipe, stream):
        def pump():
            try:
                for line in iter(pipe.readline, b""):
                    with self.lock:
                        stream.write(decode(line))
                        self.spoke = time.monotonic()
            except Exception:
                pass
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()
        return thread

    def running(self):
        return self.process.poll() is None

    def age(self):
        return time.monotonic() - self.started

    def idle(self):
        """Seconds since it last said anything."""
        with self.lock:
            return time.monotonic() - self.spoke

    def drain(self, seconds=5):
        """Give the readers a moment to finish before we read their buffers.

        A process can exit while a grandchild still holds the pipe, so this
        cannot block forever: whatever arrived by then is what we report.
        """
        deadline = time.monotonic() + seconds
        for thread in self.readers:
            thread.join(max(0, deadline - time.monotonic()))

    def kill(self):
        """Stop the process and everything it started."""
        if not self.running():
            return
        self.killed = True
        try:
            if WINDOWS:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
        except Exception:
            pass
        try:
            self.process.kill()
        except Exception:
            pass

    def settle(self):
        """Note the moment it stopped, once."""
        if self.finished_at is None and not self.running():
            self.finished_at = time.monotonic()

    def status(self):
        if self.running():
            return f"still running after {int(self.age())} seconds"
        # The two deaths get different wording because they need different
        # fixes: one is worth retrying with more room, the other never is.
        if self.stalled:
            return (
                f"produced no output for {IDLE_TIMEOUT} seconds and was killed. "
                "If it was waiting for input it cannot get any here, so pass "
                "the flag that skips the prompt rather than retrying as is"
            )
        if self.expired:
            return (
                f"was killed after running past its {self.timeout} second "
                "limit. It was still producing output, so retry with a larger "
                "timeout if it was genuinely still working"
            )
        if self.killed:
            return "was stopped"
        code = self.process.returncode
        meaning = explain(self.command, code)
        return f"finished with exit code {code}" + (f" ({meaning})" if meaning else "")

    def news(self):
        """Output since the last read, as text."""
        with self.lock:
            out, missed = self.out.take()
        if missed:
            # In front of the output rather than after it, so a diagnostic that
            # lost its beginning cannot read as one that has all of it.
            out = dropped(missed) + out
        text = report(out)
        # poll words this itself, so hand back nothing rather than "No output."
        return "" if text == NO_OUTPUT else text


class JobTable:
    """Every background command, and the thread that tidies them up.

    A class rather than three module globals, so the state has an owner and a
    test can hold a table of its own. There is exactly one in the application,
    created below.
    """

    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()
        self._sweeper = None

    def add(self, job):
        """Register a job, giving it an id, and make room if the table is full.

        Returns the ids it had to kill. run() says so in its own result, since
        notes() would otherwise be the model's first word of it a message
        later, which is too late to be told the build it is waiting on is gone.
        """
        evicted = []
        with self._lock:
            running = [j for j in self._jobs.values() if j.running()]
            while len(running) >= MAX_JOBS:
                oldest = min(running, key=lambda j: j.started)
                oldest.kill()
                running.remove(oldest)
                evicted.append(oldest.id)
            job.id = self._free_id()
            self._jobs[job.id] = job
        self._start_sweeper()
        return evicted

    def _free_id(self):
        """A short id that is easy for a model to copy back. Call under lock."""
        n = 1
        while f"exec_{n}" in self._jobs:
            n += 1
        return f"exec_{n}"

    def find(self, session_id):
        """A job by id, or by any unambiguous start of one."""
        with self._lock:
            if session_id in self._jobs:
                return self._jobs[session_id]
            matches = [j for id, j in self._jobs.items() if id.startswith(session_id)]
        return matches[0] if len(matches) == 1 else None

    def all(self):
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.started)

    def running_count(self):
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.running())

    def listing(self):
        jobs = self.all()
        if not jobs:
            return "There are no background commands."
        lines = ["Background commands:"]
        for job in jobs:
            lines.append(f"{job.id}: {job.status()}. Command: {shorten(job.command)}")
        return "\n".join(lines)

    def notes(self):
        """What to tell the model about jobs that ended while it was not looking.

        A job outliving its turn is reported on the next message rather than
        pushed into the conversation the moment it ends, since there is no way
        to interrupt a turn that has already finished.
        """
        with self._lock:
            waiting = [j for j in self._jobs.values() if not j.reported]
        lines = []
        for job in waiting:
            if job.running():
                continue
            job.settle()
            job.reported = True
            job.drain(1)
            lines.append(f"Background command {job.id} {job.status()}.")
            lines.append(f"Command: {shorten(job.command)}")
            news = job.news()
            lines.append(news if news else "It produced no further output.")
        return "\n".join(lines)

    def kill_all(self):
        """Stop every background command. Called when the app or the chat ends."""
        with self._lock:
            waiting = list(self._jobs.values())
            self._jobs.clear()
        for job in waiting:
            job.kill()

    def _start_sweeper(self):
        if self._sweeper is None or not self._sweeper.is_alive():
            self._sweeper = threading.Thread(target=self._sweep, daemon=True)
            self._sweeper.start()

    def _sweep(self):
        """Kill jobs that went quiet or ran too long, and forget old ones.

        One thread for the whole table rather than a watchdog per job.
        """
        while True:
            time.sleep(SWEEP_SECONDS)
            for job in self.all():
                if job.running():
                    # Quiet first, since that is the usual reason a job is
                    # over: the ceiling is only there for one that never stops
                    # talking.
                    if job.idle() > IDLE_TIMEOUT:
                        job.stalled = True
                        job.kill()
                    elif job.age() > job.timeout:
                        job.expired = True
                        job.kill()
                    continue
                job.settle()
                # Keep it readable until its ending has been reported, so a job
                # that finishes between turns is not lost before anyone looks.
                if job.reported and time.monotonic() - job.finished_at > FINISHED_TTL:
                    with self._lock:
                        self._jobs.pop(job.id, None)


jobs = JobTable()


class Cancellation:
    """Whether the user has given up on what is running.

    A single object the chat session points at its own stop flag for the length
    of a turn, rather than a parameter of run(): the registry spreads the
    model's own arguments into the tool, so anything in the signature is
    something the model could set, and it must not be able to declare itself
    unstoppable.

    Only while a turn is running. Between turns nothing is being waited on, and
    a stop flag left registered from a finished turn would answer for the next
    command anybody starts.
    """

    def __init__(self):
        self._check = None

    @contextmanager
    def watching(self, check):
        previous, self._check = self._check, check
        try:
            yield
        finally:
            self._check = previous

    def requested(self):
        return bool(self._check and self._check())


cancellation = Cancellation()


def wait_for(process, seconds):
    """Wait for the process, giving up early when the user stops generation.

    In short steps rather than one long one: Popen.wait cannot be interrupted
    once it is in it, so a single ten second wait would ignore escape for ten
    seconds. The step is small enough to feel immediate and long enough that
    the loop costs nothing.
    """
    deadline = time.monotonic() + seconds
    while True:
        left = deadline - time.monotonic()
        if left <= 0 or cancellation.requested():
            return
        try:
            process.wait(timeout=min(STOP_CHECK, left))
            return
        except subprocess.TimeoutExpired:
            pass


def spawn(command, workdir):
    """Start the process in its own group, so killing it takes its children."""
    kwargs = {}
    if WINDOWS:
        # Keep a console window from flashing up over the app, and make the
        # process a group leader so taskkill /T can reach what it started.
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    env = dict(os.environ)
    # Set for the Python the command may go on to start, not for the shell:
    # output is decoded as UTF-8, and unbuffered, or nothing shows up until the
    # process exits and a poll on a long run would always come back empty.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen(
        # shell=True rather than shell() + [command], though the two describe
        # the same invocation. A list goes through list2cmdline on Windows,
        # which escapes the quotes inside the command with backslashes, and cmd
        # does not read backslash as an escape: every command containing a
        # quoted argument arrives corrupted. shell=True hands the string to the
        # shell whole, which is the point of a shell tool. shell() stays as the
        # description of what this does, for the model to read.
        command,
        shell=True,
        stdout=subprocess.PIPE,
        # One pipe for both, merged by the kernel in the order the process
        # actually wrote them. Two pipes and two reader threads can only
        # reconstruct the order the reader happened to get there, which is not
        # the same thing. And the split it buys is worth less than it looks:
        # pytest, git, pip, npm, every progress bar and most compilers write
        # ordinary output to stderr, so a separate stderr block regularly holds
        # nothing wrong while reading to the model as an error, and the real
        # failure sits somewhere in a chatty stdout with no sign of when it
        # happened relative to the rest.
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        cwd=workdir,
        **kwargs,
    )


def unquoted(command):
    """The command with quoted text removed, for looking at its structure.

    A keyword inside a string is not the command doing that thing, and
    `echo "starting the server &"` must not read as a backgrounded command.
    Structure only, so the result is never run.
    """
    return re.sub(r"\"[^\"]*\"|'[^']*'", " ", command)


def named(low):
    """The detaching program this command names, or None.

    Each segment is looked at on its own, since what matters for LEADING is
    whether the word is the command being run or an argument to one.
    """
    for segment in re.split(r"&&|\|\||[&|;]", low):
        parts = segment.split()
        if not parts:
            continue
        if word(parts[0]) in LEADING:
            return word(parts[0])
        for part in parts:
            if word(part) in DETACHERS:
                return word(part)
    return None


def detached(command):
    """Why this command puts a process out of reach, or None.

    Reported rather than refused. A model backgrounds a server because it wants
    the shell back, which is the one thing it does not need to do here: run
    already hands the turn back after YIELD_SECONDS and keeps the process as a
    session poll can read and kill_all() can stop. A detached one is a process
    nobody can see and nobody will clean up.
    """
    bare = unquoted(command)
    low = bare.lower()
    if any(flag in low.split() for flag in NO_DETACH):
        return None
    # A trailing & backgrounds on POSIX. && is a separator, and one at the end
    # is a syntax error rather than something we need to allow for.
    if not WINDOWS and re.search(r"(?<!&)&\s*$", bare.rstrip()):
        found = "a trailing &"
    else:
        found = named(low)
    if not found:
        return None
    return (
        f"Warning: this command backgrounds a process itself ({found}), which "
        "puts it outside VOLlama's reach: it is not a session poll can read, it "
        "is not killed on New Chat or when VOLlama closes, and its output is "
        "lost. Run it in the foreground instead. A command still going after "
        f"{YIELD_SECONDS} seconds is backgrounded for you, as a session, which "
        "is what you wanted."
    )


def run(command, timeout=DEFAULT_TIMEOUT, workdir=None):
    """Run command in the shell; return its output, or a session id."""
    if not command or not command.strip():
        return "No command given."
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT
    timeout = min(timeout, MAX_TIMEOUT)
    try:
        workdir = valid_directory(workdir)
    except ValueError as e:
        return str(e)
    try:
        process = spawn(command, workdir)
    except Exception as e:
        return f"Could not run the command: {e}"
    job = Job(process, command, timeout)
    wait_for(process, min(YIELD_SECONDS, timeout))
    if job.running() and cancellation.requested():
        # Stopping generation stops the work it started, but only while we are
        # still the ones waiting on it. Once a command is in the background it
        # belongs to the session, not to the message that began it, and escape
        # is also how you leave the edit box.
        job.kill()
        job.settle()
        job.drain(2)
        with job.lock:
            return report(
                job.out.all(),
                None,
                note="Stopped: the user stopped generation while this was running.",
                command=command,
            )
    if job.running():
        evicted = jobs.add(job)
        news = job.news()
        return "\n".join(
            filter(
                None,
                [
                    f"Still running after {YIELD_SECONDS} seconds, so it was "
                    f"left going in the background. Session: {job.id}",
                    "Read it with poll. It will be killed if it goes "
                    f"{IDLE_TIMEOUT} seconds without producing any output, or "
                    f"after {timeout} seconds in total.",
                    eviction(evicted),
                    detached(command),
                    f"Output so far:\n{news}" if news else None,
                ],
            )
        )
    # Finished inside the window: report it and forget it.
    job.settle()
    job.drain()
    with job.lock:
        # A detached command is the commonest reason one returns instantly, so
        # the warning belongs here most of all.
        return report(
            job.out.all(),
            process.returncode,
            note=detached(command),
            command=command,
        )


def eviction(evicted):
    """What to say about the jobs that were killed to make room for this one."""
    if not evicted:
        return None
    killed = ", ".join(evicted)
    if len(evicted) == 1:
        return (
            f"{MAX_JOBS} commands were already in the background, so {killed} "
            "was killed to make room. Its output is still there to poll."
        )
    return (
        f"{MAX_JOBS} commands were already in the background, so {killed} were "
        "killed to make room. Their output is still there to poll."
    )


def poll(session_id=None, wait=0, kill=False):
    """Report on a background command, optionally waiting for it or killing it."""
    if session_id is None or not str(session_id).strip():
        return jobs.listing()
    job = jobs.find(str(session_id).strip())
    if not job:
        return (
            f"There is no background command {session_id}. It may have "
            "finished long ago, or belonged to an earlier chat. Use poll with "
            "no session id to list the ones that are left."
        )
    if kill:
        job.kill()
        job.settle()
        job.drain(2)
        job.reported = True
        news = job.news()
        return f"Stopped {job.id}." + (f"\n{news}" if news else "")
    try:
        wait = int(wait)
    except (TypeError, ValueError):
        wait = 0
    if wait > 0:
        wait_for(job.process, min(wait, MAX_POLL_WAIT))
    if not job.running():
        job.settle()
        job.drain(2)
        job.reported = True
    news = job.news()
    head = f"{job.id} {job.status()}."
    if not news:
        return head + " No new output."
    # news has been through report already, so trimming again here would only
    # cut the middle out a second time and take the spilled log's path with it.
    return f"{head}\n{news}"


def summarize_run(arguments):
    """The one line the transcript shows for a run call."""
    return str(arguments.get("command") or "")


def summarize_poll(arguments):
    session = arguments.get("session_id") or "all"
    return f"poll {session}" + (" (stop it)" if arguments.get("kill") else "")
