"""The run tool: run a shell command in a separate process and report its output.

A shell rather than Python source, which is what this was, for two reasons.
Every model that can call tools was trained on traces where the command slot
holds `git status`, not `subprocess.run(["git", "status"], ...)`, so Python is
off-distribution in exactly the place accuracy matters. And Python beyond one
line needs real line breaks and exact indentation inside a JSON string, which is
the failure Files.py exists to prevent, reintroduced one tool over. Shell
commands are flat, so they do not have it.

Python is still reachable and now by the better road: write the script with the
write tool, then run the file. The source goes through the tool that already
escapes it properly instead of being folded into a -c argument.


Tool calling is opt-in per preset, because most small local models handle it
badly and some endpoints ignore the tools parameter entirely.

A call that finishes quickly reports as you would expect. One that does not
hands back a session id and keeps running, so a build or a test suite does not
have to fit inside one tool call. The model reattaches with the poll tool.
"""

import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import date

import Files
from Files import working_dir
from Settings import settings

WINDOWS = platform.system() == "Windows"

# How long a call waits before handing back a session id instead of a result.
# Short, because the whole turn is blocked until it returns.
YIELD_SECONDS = 10

# Total runtime a job gets before it is killed, whether or not anyone polls it.
DEFAULT_TIMEOUT = 300
MAX_TIMEOUT = 3600

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

# How much of a running job's output we hold on to. Bigger than MAX_OUTPUT
# because it is read in pieces, a poll at a time.
MAX_BUFFER = 200000

# Running jobs allowed at once. The oldest is killed to make room, so a model
# that forgets to poll cannot fill the machine with processes.
MAX_JOBS = 8

# How long a finished job stays readable after its completion was reported.
FINISHED_TTL = 600
SWEEP_SECONDS = 5

# A ceiling on calls of any kind in one turn, free ones included. Without it a
# model that only ever reads never spends a round and the turn never ends.
MAX_TOOL_CALLS = 40

# How many times in a row the model may call a tool before we stop looping.
# Polls and reads do not count: waiting on a job, or looking at the files it is
# about to change, is not progress the budget is there to limit.
MAX_TOOL_ROUNDS = 10

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
        "Run a shell command and return its output, stdout and stderr both. "
        + dialect
        + "Every call is a fresh shell, so a cd, a variable or an export does "
        "not carry over to the next one: chain related steps into a single "
        "command with &&. To run somewhere else, pass workdir rather than "
        "beginning with cd. To use a virtual environment, do not activate it: "
        f"run its interpreter by path, {venv}. Nothing can answer a prompt, "
        "since the command has no input; pass the flag that skips it, such as "
        "-y. For more Python than fits on one line, write it to a file with "
        "the write tool and run that file, rather than passing source to -c. "
        f"A command still running after {YIELD_SECONDS} seconds keeps going in "
        "the background and returns a session id instead of a result; read it "
        "with poll."
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
                        f"to {DEFAULT_TIMEOUT}."
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

TOOLS = [RUN_TOOL, POLL_TOOL] + Files.TOOLS


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


def environment():
    """What the model cannot work out for itself before its first command.

    Only the working directory and the date move, and the date only once a day,
    so a server that caches the prompt prefix keeps the cache until you choose a
    new folder, which is the one time it should be thrown away anyway.
    """
    return (
        "Environment for the tools:\n"
        f"Working directory, which relative paths are taken from: {working_dir()}\n"
        f"Platform: {platform.platform()}\n"
        f"Shell running your command: {invocation()}\n"
        f"Python on PATH: {python_version()} at {interpreter()}\n"
        f"Today's date: {date.today():%Y-%m-%d, %A}\n"
        "A project may use a different Python from the one above, under uv or "
        "in a .venv. Check for one before assuming its packages are installed."
    )


def shorten(text):
    """Trim text to MAX_OUTPUT, keeping the head and the tail."""
    if len(text) <= MAX_OUTPUT:
        return text
    head = int(MAX_OUTPUT * HEAD_SHARE)
    tail = MAX_OUTPUT - head
    dropped = len(text) - MAX_OUTPUT
    return (
        text[:head]
        + f"\n\n... {dropped} characters omitted out of {len(text)} total ...\n\n"
        + text[-tail:]
    )


def report(out, err, returncode=None, note=None):
    """Assemble what the model sees from one run."""
    parts = []
    out = (out or "").strip()
    err = (err or "").strip()
    if out:
        parts.append(out)
    if err:
        parts.append(f"stderr:\n{err}")
    if returncode:
        parts.append(f"Exit code: {returncode}")
    if note:
        parts.append(note)
    if not parts:
        return "The command produced no output."
    return shorten("\n".join(parts))


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
        return self.text


class Job:
    """A command that outlived its yield window, and the pipes still feeding it."""

    def __init__(self, id, process, command, timeout):
        self.id = id
        self.process = process
        self.command = command
        self.timeout = timeout
        self.started = time.monotonic()
        self.finished_at = None
        self.killed = False
        self.expired = False  # killed for running past its timeout
        self.reported = False  # has the model been told it finished
        self.lock = threading.Lock()
        self.out = Stream()
        self.err = Stream()
        self.readers = [
            self.reader(process.stdout, self.out),
            self.reader(process.stderr, self.err),
        ]

    def reader(self, pipe, stream):
        def pump():
            try:
                for line in iter(pipe.readline, b""):
                    with self.lock:
                        stream.write(decode(line))
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
        if self.expired:
            return f"was killed after running past its {self.timeout} second limit"
        if self.killed:
            return "was stopped"
        return f"finished with exit code {self.process.returncode}"

    def news(self):
        """Output since the last read, as text."""
        with self.lock:
            out, out_missed = self.out.take()
            err, err_missed = self.err.take()
        missed = out_missed + err_missed
        note = None
        if missed:
            note = f"{missed} characters of earlier output were dropped."
        text = report(out, err, note=note)
        return "" if text == "The command produced no output." else text


registry = {}
registry_lock = threading.Lock()
sweeper = None


def sweep():
    """Kill jobs that ran too long and forget ones nobody needs any more."""
    while True:
        time.sleep(SWEEP_SECONDS)
        with registry_lock:
            jobs = list(registry.values())
        for job in jobs:
            if job.running():
                if job.age() > job.timeout:
                    job.expired = True
                    job.kill()
                continue
            job.settle()
            # Keep it readable until its ending has been reported, so a job
            # that finishes between turns is not lost before anyone looks.
            if job.reported and time.monotonic() - job.finished_at > FINISHED_TTL:
                with registry_lock:
                    registry.pop(job.id, None)


def start_sweeper():
    global sweeper
    if sweeper is None or not sweeper.is_alive():
        sweeper = threading.Thread(target=sweep, daemon=True)
        sweeper.start()


def new_id():
    """A short id that is easy for a model to copy back."""
    n = 1
    while True:
        id = f"exec_{n}"
        if id not in registry:
            return id
        n += 1


def register(job):
    with registry_lock:
        running = [j for j in registry.values() if j.running()]
        while len(running) >= MAX_JOBS:
            oldest = min(running, key=lambda j: j.started)
            oldest.kill()
            running.remove(oldest)
        registry[job.id] = job
    start_sweeper()


def find(session_id):
    """A job by id, or by any unambiguous start of one."""
    with registry_lock:
        if session_id in registry:
            return registry[session_id]
        matches = [j for id, j in registry.items() if id.startswith(session_id)]
    return matches[0] if len(matches) == 1 else None


def kill_all():
    """Stop every background command. Called when the app or the chat ends."""
    with registry_lock:
        jobs = list(registry.values())
        registry.clear()
    for job in jobs:
        job.kill()


def notes():
    """What to tell the model about jobs that ended while it was not looking.

    Option: a job outliving its turn is reported on the next message rather
    than pushed into the conversation the moment it ends, since there is no
    way to interrupt a finished turn.
    """
    with registry_lock:
        jobs = [j for j in registry.values() if not j.reported]
    lines = []
    for job in jobs:
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


def running_count():
    with registry_lock:
        return sum(1 for j in registry.values() if j.running())


_stop_check = None


def stop_when(check):
    """Register what tells a wait that the user stopped generation.

    A hook rather than a parameter, since call() spreads the model's own
    arguments into the tool: anything in a signature is something the model can
    set, and it must not be able to say it was never stopped.
    """
    global _stop_check
    _stop_check = check


def stopped():
    return bool(_stop_check and _stop_check())


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
        if left <= 0 or stopped():
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
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        env=env,
        cwd=workdir,
        **kwargs,
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
    if workdir is not None:
        workdir = str(workdir).strip() or None
    if workdir and not os.path.isdir(workdir):
        return (
            f"There is no directory {workdir}, so the command did not run. "
            "Pass an existing directory as workdir, or leave it out."
        )
    workdir = workdir or working_dir()
    try:
        process = spawn(command, workdir)
    except Exception as e:
        return f"Could not run the command: {e}"
    with registry_lock:
        id = new_id()
    job = Job(id, process, command, timeout)
    wait_for(process, min(YIELD_SECONDS, timeout))
    if job.running() and stopped():
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
                job.err.all(),
                None,
                note="Stopped: the user stopped generation while this was running.",
            )
    if job.running():
        register(job)
        news = job.news()
        return "\n".join(
            filter(
                None,
                [
                    f"Still running after {YIELD_SECONDS} seconds, so it was "
                    f"left going in the background. Session: {job.id}",
                    "Read it with poll. It will be killed after "
                    f"{timeout} seconds in total.",
                    f"Output so far:\n{news}" if news else None,
                ],
            )
        )
    # Finished inside the window: report it and forget it.
    job.settle()
    job.drain()
    with job.lock:
        return report(job.out.all(), job.err.all(), process.returncode)


def listing():
    with registry_lock:
        jobs = sorted(registry.values(), key=lambda j: j.started)
    if not jobs:
        return "There are no background commands."
    lines = ["Background commands:"]
    for job in jobs:
        lines.append(f"{job.id}: {job.status()}. Command: {shorten(job.command)}")
    return "\n".join(lines)


def poll(session_id=None, wait=0, kill=False):
    """Report on a background command, optionally waiting for it or killing it."""
    if session_id is None or not str(session_id).strip():
        return listing()
    job = find(str(session_id).strip())
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
    return shorten(f"{head}\n{news}")


FUNCTIONS = dict({"run": run, "poll": poll}, **Files.FUNCTIONS)

# Calls that only look at work already started, so they do not count against
# MAX_TOOL_ROUNDS. Otherwise waiting on a build would spend the whole budget.
FREE = {"poll", "read"}


def call(name, arguments):
    """Run the tool the model asked for and return its result as text.

    arguments is the raw JSON string from the tool call. A model that emits
    broken JSON gets told so rather than crashing the turn.
    """
    function = FUNCTIONS.get(name)
    if not function:
        return f"There is no tool named {name}."
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except ValueError as e:
            return f"Could not read the arguments as JSON: {e}"
    if not isinstance(arguments, dict):
        return "The arguments must be a JSON object."
    try:
        return function(**arguments)
    except TypeError as e:
        return f"Wrong arguments for {name}: {e}"


def describe(name, arguments):
    """What the transcript shows for a call: the command, or the raw arguments."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except ValueError:
            return arguments
    if isinstance(arguments, dict):
        if "command" in arguments:
            return str(arguments["command"])
        if name in Files.FUNCTIONS:
            return Files.describe(name, arguments)
        if name == "poll":
            session = arguments.get("session_id") or "all"
            return f"poll {session}" + (" (stop it)" if arguments.get("kill") else "")
    return json.dumps(arguments)
