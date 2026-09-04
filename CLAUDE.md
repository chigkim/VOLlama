# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VOLlama is an accessible desktop chat client for LLM interaction, built with wxPython and designed with accessibility-first principles. It talks to any OpenAI-compatible server (Ollama, llama.cpp, LM Studio, vLLM, OpenAI, Gemini's OpenAI endpoint, ...) through a single code path, with features like RAG, multimodal support, and comprehensive screen reader compatibility.

A **preset** is the unit of configuration: it owns base URL, API key, model, `context_window`, system prompt, and generation parameters. `context_window` is a preset field because it describes one model on one server; its consumers are compaction and RAG prompt sizing. Presets live inside the encrypted `settings.json`; there is no separate API settings dialog and no per-provider branching.

## Development Commands

### Setup Environment
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Mac/Linux (Python 3.12 required for Mac)
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Platform-Specific Patches
```bash
# Windows
git apply lib-win.patch

# Mac
git apply lib-mac.patch
```

### Building
```bash
# Windows
build-pyinstaller.bat  # PyInstaller setup
build.bat              # Final build

# Mac/Linux  
./build.sh

# Debug builds (retain console)
build-debug.bat/.sh
```

### Running from Source
```bash
python VOLlama.py
```

## Architecture Overview

### Core Components
- **VOLlama.py**: Main application with wxPython ChatWindow UI
- **Model.py**: Central LLM interaction layer, handles all provider communication
- **Settings.py**: Encrypted configuration management with JSON persistence
- **RAG.py**: LlamaIndex-based retrieval-augmented generation implementation
- **Speech.py**: Platform-specific TTS (AVFoundation/SAPI) for accessibility
- **Compact.py**: The handoff prompt and the threshold that decide when a conversation is summarized in place
- **Tools.py**: The `run` and `poll` tools the model can call: run a shell command in a subprocess, return its output, and keep long runs going in the background. Also the registry (`TOOLS`, `FUNCTIONS`, `FREE`, `call`, `describe`) that `Model.py` talks to, so `Files.py`'s tools are reached through it
- **Files.py**: The `read`, `write` and `edit` tools, and `working_dir()`, which resolves a relative path for all five

### UI Dialogs
- **PresetDialog.py**: Tabbed preset editor (Connection / Parameters / System Prompt). `SERVERS` is the list behind the Connection page's Base URL "Choose..." button: name and base URL only, since every entry takes the same OpenAI-compatible path and the list is a typing shortcut, not a provider switch.
- **RAGParameterDialog.py**: RAG-specific settings, including the global embedding endpoint

### Key Design Patterns
- **MVC-like separation**: Model.py handles business logic, VOLlama.py manages UI
- **Threading model**: Background threads for LLM calls with streaming callbacks
- **Single provider path**: one `OpenAILike` client for every endpoint, configured from the active preset
- **Settings singleton**: Global configuration with automatic encryption

### Accessibility Architecture
- Full screen reader compatibility through wxPython accessibility hooks
- Keyboard-only navigation with comprehensive shortcuts
- Audio feedback system (send.wav/receive.wav) 
- Platform-native TTS integration

### RAG Implementation
- Embeddings via `OpenAILikeEmbedding` against the global `embedding_base_url` / `embedding_api_key` / `embedding_model` settings (default model `EmbeddingGemma`)
- Vector storage through LlamaIndex with multiple synthesis modes
- Document processing supports PDF, DOCX, TXT, EPUB, HTML
- Configurable chunking, similarity thresholds, and response modes

### Multimodal Support
- Image attachment and encoding for vision models
- Base64 encoding pipeline for multimodal LLM requests
- Support for llama3.2-vision and similar vision-language models

## Key Dependencies
- **wxPython**: Cross-platform GUI framework
- **openai**: Model listing for the preset editor's "Choose..." button
- **llama-index-***: RAG, embeddings, and the `OpenAILike` LLM client
- **pyinstaller**: Standalone executable creation
- **sounddevice/soundfile**: Audio feedback system
- **transformers**: Model tokenization and utilities
- **cryptography**: API key encryption

## Development Notes

### Model Integration
`Model.init_llm()` builds one client from the active preset on every request. Only parameters in `Model.OPENAI_PARAMS` are forwarded; anything else in the schema stays local, since `additional_kwargs` are spread as top-level kwargs into `chat.completions.create()` and unknown names raise `TypeError`.

A blank box in the Parameters tab has to mean *not sent*, not *sent as our idea of a default*, so `Model.Client` subclasses `OpenAILike` to drop `temperature` when the preset did not set one. llama_index puts it into every request unconditionally, as a constructor field with a default of 0.1 rather than part of `additional_kwargs`, which both overrides whatever the server would have chosen and fails outright on a model that has deprecated the parameter. It is the only one that leaks in this way; `max_tokens`, `logprobs`, `modalities` and the rest are all omitted when unset. `Client` reads whether the preset set one off `additional_kwargs` rather than from a flag of its own, since that dict is what actually goes out and the two cannot then drift apart.

### Tool Calling
Tool calling is opt-in, through `settings.tools` (default false), because small local models
call tools badly and some endpoints ignore `tools` entirely. It is a global setting on the Chat
menu rather than a preset field: it answers "do I want the model touching this machine right
now", which changes mid-chat, not "what server is this". When on, `init_llm()` puts
`Tools.TOOLS` into `additional_kwargs`, which the OpenAI client spreads into
`chat.completions.create()`.

`Model.ask()` loops: stream a reply, run any tool calls, send the results back, up to
`Tools.MAX_TOOL_ROUNDS` (10) and `Tools.MAX_TOOL_CALLS` (40). Streaming still works — `_stream_chat` merges streamed tool-call
fragments into the final chunk's `message.additional_kwargs["tool_calls"]`. Calls named in
`Tools.FREE` (`poll`, `read`) do not increment `rounds`: waiting on a build, or looking at the
files you are about to change, is not the kind of progress the budget exists to limit.
`MAX_TOOL_CALLS` is the ceiling free calls cannot slip past — without it a model that only ever
reads never spends a round and the turn never ends.

Every tool call must get a matching tool message, even one that is not run (round cap hit, user
pressed stop). A dangling tool call makes the whole history unusable to the server.

A tool call also has to go back with whatever the server hung off it, not just the parts the
OpenAI schema names. Gemini's thinking models sign every function call and its
OpenAI-compatible endpoint carries the signature as
`tool_calls[i].extra_content.google.thought_signature`; send the call back without it and the
next request is refused with `Function call is missing a thought_signature`, so every turn in
which the model calls a tool dies on the second request. It is lost by default twice over: the
openai library parses an unknown key into the model's extras rather than a field, and
`update_tool_calls()` merges the streamed fragments by copying the fields it knows about into
the first fragment's object. So `collect_extras()` reads `extra_content` off the raw chunks
itself and `tool_calls_of()` puts it back, keyed by the call's own `index` because the field can
arrive on any fragment of any call in progress. `to_openai_message_dict()` spreads
`additional_kwargs` into the outgoing message, so a call dict carrying `extra_content` reaches
the wire unchanged. The key is only added when a server actually sent one.

`outgoing()` is what actually goes to the server: tool calls and their results older than
`KEEP_TOOL_TURNS` (1) of your messages are dropped, since otherwise every call's output is
resent on every later request and a few chatty commands eat the context window. A call and
its result are dropped together, and an assistant message that only carried a call goes with
them; one that also said something keeps the text. `Model.messages` itself stays whole, so
the transcript, save and alt+up are unaffected.

Anything that walks `Model.messages` has to cope with tool rounds: `clearLast` truncates from the
last user message, alt+up/down skips tool results and the empty assistant message carrying a call,
and save/load round-trips `additional_kwargs` so `tool_call_id`s survive.

There is **no confirm-before-run dialog**, for commands or for file writes. The Chat menu
checkbox is the only gate.

#### read, write and edit
`Files.py` exists for one reason: doing these through `run` means the file's own text has to
survive a heredoc or a shell-quoted Python string literal first, which is where a small model
fails *silently* — you get a file containing a literal `\n`, or one truncated at an unescaped
quote, rather than an error. As a tool parameter the same text is one JSON string, escaped by
the layer that is good at it. This is also why `run` takes a shell command and not Python
source: the escaping problem belongs in one place, and this is the place it is solved. That argument is strongest for `write`
and `edit`; `read` is in for the paging (`MAX_LINES` 2000, `MAX_BYTES` 50 KB, with a
`Use offset=N to continue.` footer) rather than for escaping.

`edit` is the one that adds a guarantee rather than a convenience. Every edit in a call is
located against the **original** text and checked — empty, missing, ambiguous, overlapping —
before any of them is written, so an unclear match leaves the file untouched and the model is
told which edit and why. `replace_all` on one edit is the model saying it meant every
occurrence, so ambiguity stops being an error for that edit only; without it the uniqueness
requirement stands. `text.replace(old, new)` in `run` changes every occurrence and
`replace(old, new, 1)` changes an arbitrary one, and either way the file is already wrong. The
result carries a `difflib` diff (`DIFF_CONTEXT` 2, capped at `MAX_DIFF`) so the model can see it
hit the right place.

`load()` reads with universal newlines and hands back the ending the file actually had, so
`old_text` is always written with plain `\n` and a CRLF file is not converted by being edited.
New files get `\n`. Non-UTF-8 and files with a NUL byte are refused rather than mangled, since
round-tripping them here would corrupt them.

`read` deliberately returns **unnumbered** text, unlike Claude Code's Read: a line-number prefix
would break `edit`'s exact matching, which Claude Code works around by telling the model to strip
it. pi does the same.

A line longer than `MAX_LINE` (2000 characters) is cut off with a marker saying where, and the
footer warns once that a cut line is no longer the file's text. `MAX_BYTES` cannot do this job:
it stops *before* the line that would exceed it, and stopping before the first line would return
nothing, so a minified file used to come back whole. opencode caps each line the same way; pi has
a dedicated first-line path.

When an `old_text` does not match, `edit` tries it once more with `unescape()`, which turns a
literal backslash-n back into a line break (ported from gemini-cli's `unescapeStringForGeminiBug`)
and says so in the result. It is a fallback after exact matching, never a rewrite of the input,
and `write` does not get it — content legitimately containing `\n`, like Python source, must
survive untouched.

After that comes one more fallback and only one: `fold_match()`, for the characters a model
cannot see it got wrong. A curly quote where the file has a straight one, an en dash for a
hyphen, a zero-width space left in by a copy out of HTML, whitespace at the end of a line —
these are the commonest real mismatch, and no amount of re-reading the file fixes them because
the difference is invisible in both directions. `fold()` builds a folded copy of the text
alongside a map from every folded character back to the original character it came from; a match is
looked up in folded space, translated to the original's own offsets, and then **verified by
folding the original slice again**. The replacement is always spliced into the original text,
so the file's own characters survive everywhere the edit does not replace them, and an
ambiguous mapping refuses the whole call rather than editing a guess. This is openclaw's
`buildNfkcBoundaries` / `translateFuzzySpan` shape, including its fail-closed check.

Tabs and spaces are deliberately **not** made equivalent, and that is where this stops. It is
the one difference `visible()` already explains well, and folding it would let an `old_text`
indented with spaces match a file indented with tabs — after which `new_text`, written exactly
as sent, silently mixes the file's indentation. Everything past this point on the other
harnesses' ladders (line-trimmed, whitespace-normalized, indentation-flexible, block-anchor,
context-aware) buys matches at the price of occasionally editing the wrong region, and hermes'
own recorded threshold history is the evidence: its similarity floors went 0.10/0.30 →
0.50/0.70 and its line rule went 50%-of-lines → all-lines-at-0.80, all in the tightening
direction. One stage, verified, is the whole of it here.

`load()` also takes a leading BOM off the front and `save()` puts it back, since an invisible
character on line 1 makes a correct `old_text` fail with nothing in the error to explain it.

An `old_text` that matches nothing is answered with the lines that came closest rather than
with "not found", ported from hermes' `find_closest_lines()`. `nearest()` scores the first
non-blank line of `old_text` against every line of the file and shows `SUGGESTIONS` (3) windows
of `SNIPPET_LINES` (20) around the best of them, deduplicated so three suggestions are not three
views of the same lines. It anchors on one line rather than sliding the whole block, because
comparing a twenty line window against every position in a nine thousand line file takes forty
seconds and anchoring takes a third of one; a block that nearly matches has to start somewhere
that nearly matches. When the closest window differs from what the model sent in whitespace
only, `visible()` prints both with `→` for a tab and `·` for a space, since that is the one
difference a model cannot see in its own output. When the difference is anything else,
`divergence()` names its *kind* rather than restating the rule: `the indentation differs: you
sent 4 spaces, the file has 1 tab`, `the escaping differs`, or `they first differ at column N`
with a caret under it. "It must match exactly" tells the model what the rule is, which it
already knew; what it does not know is which of these two lines is wrong and how, and
indentation and escaping are the two it cannot see by reading either one again. `kind()` reports
escaping only when the backslashes are the *whole* of the difference, since two unrelated lines
usually differ in backslash count too and calling that an escaping problem sends the model after
something that is not wrong. When every line sent matches and only the count or the surrounding
lines differ, it says that instead. This is openclaw's `describeCandidateDifference()`. An `old_text` identical to its `new_text` is
refused by name before anything is located, so a batch with one no-op edit says which one
instead of succeeding quietly.

That refusal is for an edit that would change nothing. An edit whose `old_text` is *gone* and
whose `new_text` is already in the file is a different thing: it is an edit that has already
landed, usually re-sent because a batch was retried, and hermes' trajectory mining has it as the
single commonest patch failure. `applied()` answers that case as a success-shaped no-op — the
edit is skipped, the rest of the batch is applied, and the result says which ones were skipped.
Uniqueness of `new_text` is the guard against reading a coincidence as a landed edit, and it is
a strong one: a fragment long enough to be somebody's `new_text` appears once or not at all.
`locate()` raises `NotFound` rather than a plain `ValueError` so that only a no-match, not an
ambiguous match, can take this path.

An `old_text` that matches *too much* is answered with where, not with a count. `ambiguous()`
lists up to `SITES` (5) of the match sites as `line N: <the line, to SITE_WIDTH>` and says how
many more there are. A bare "found 8 occurrences" leaves the model to find them itself, which it
does by reading the whole file again and then sending the same edit; the line numbers are the
mirror of what `nearest()` does for no match at all.

An `old_text` that is nothing but whitespace is refused by name too, since it cannot say which
part of the file is meant and would otherwise land wherever the first run of spaces is.

`edits_of()` reads the argument out of the shapes a model actually sends: the array as a JSON
string, one edit as a bare object, the whole thing wrapped in a second `edits` key. Each is
unambiguous, so repairing it beats spending a turn on the shape of the argument.

`checked()` refuses two paths that parse as files but are not. `device()` catches Windows'
reserved names (`nul`, `con`, `com1`, …, extension stripped, since `con.txt` is the console too)
and, on POSIX only, anything under `/dev/`: writing one reports success and throws the text
away, and reading a character device never returns. Each platform's rule applies only on that
platform — `/dev` is an ordinary folder name on Windows, where `C:\dev` is where a good many
people keep their code. And a missing file gets `suggest()`, which runs
`difflib.get_close_matches` over the parent directory listing we already had to read to know the
file was missing: a wrong path is usually wrong by a character or a plural.

`write` refuses content that says the rest of the file goes here instead of containing it, before
the path is even resolved. `write` replaces the whole file, so a model that abbreviates one
destroys it, and the damage is silent: the write succeeds and the missing code is noticed when
something else fails to import it. `placeholder()` is gemini-cli's detector and its narrowness is
the point — `commentary()` requires the line to be a *comment*, it must contain an ellipsis, and
what is left after both are stripped must be in the closed set `OMISSIONS`. So
`# ... rest of the code unchanged ...` is refused while `print("...")`, a bare `# ...`, and a
docstring that happens to mention unchanged code are not. The refusal names the line number and
the line, since the model has to find it to fix it.

`write` parses Python, JSON, YAML and TOML before writing them, and `introduced()` reports only
an error the write would *add*: a file that already fails to parse is usually the reason the
model is writing it, and complaining about that error would make the fix and the refusal the
same write. JSON, YAML and TOML fail closed, since they exist to be read by another program and
a broken one stops that program somewhere else entirely, several tool calls later. Python is
written with a warning: a model writing a module in pieces has a reason to leave it briefly
unparseable, and the file it breaks is its own. A missing parser (`yaml`, `tomli`) disables its
check rather than refusing the write. This is hermes' `LINTERS_INPROC` and
`_FAIL_CLOSED_INPROC_EXTS`, with the same split. `edit` runs the same check, since an edit breaks a
config file the same way a rewrite does, and by the time another program trips over it the tool
call that did it is several messages back; a fail-closed extension is refused with the diff the
edit *would* have made, so the model can see what to fix.

A refused binary file is named rather than just refused: `describe_bytes()` reads the first
bytes against a table of signatures and `read` answers `is not text: PNG image, 4.9 KB` instead
of "binary file". The guess only ever words an error, never a decision, so calling a .docx a zip
archive is fine — it still tells the model whether it asked for the wrong path or the right one
in the wrong tool, which have different fixes.

`outgoing()`'s `KEEP_TOOL_TURNS` drops old tool results, so a file read in an earlier message is
not resent and the model re-reads it. That is the right default with edits in between.

`run` is stateless by design, like the shell tools in pi, opencode, codex and openclaw.
Nothing persists between calls, so three affordances stand in for a session: a `workdir`
parameter (passed straight to `Popen(cwd=...)`, validated first so a missing directory reports
instead of raising), a description that tells the model to run a venv's interpreter by path
rather than activating it, and background jobs (below).

`command` is a shell command. It was Python source, on the argument that one dialect works on
both Windows and Mac where `cmd` and `sh` do not, and that was the wrong call for two reasons.
Every model that can call tools was trained on traces where this slot holds `git status`, so
Python source is off-distribution in the one place accuracy matters, and a `subprocess.run(...,
capture_output=True, text=True)` wrapper costs sixty tokens and a class of mistakes a shell does
not have. Worse, Python past one line needs real line breaks and exact indentation inside a JSON
string — the failure `Files.py` exists to prevent, reintroduced one tool over. Python is still
reachable, by the better road: `write` the script, then `run` the file, so the source goes
through the tool that already escapes it. All six harnesses surveyed (codex, opencode, pi,
gemini-cli, hermes, openclaw) ship a shell here, and unanimity that wide is evidence.

The cross-platform problem is answered the way gemini-cli and openclaw answer it: name the
invocation instead of leaving it to be guessed. `shell()` is `cmd.exe /c` on Windows (COMSPEC if
set) and `/bin/sh -c` elsewhere, and `invocation()` renders it into both the tool description and
`environment()`, so the model is told *"It is run as `cmd.exe /c <command>`"* and writes `dir`
rather than `ls`. cmd rather than PowerShell for startup cost and quoting; `/bin/sh` rather than
`$SHELL` because POSIX runs everywhere and fish is not POSIX.

`spawn()` passes `shell=True` with the command as a string rather than `shell() + [command]`,
though the two mean the same invocation. A list goes through `list2cmdline` on Windows, which
backslash-escapes the quotes inside the command, and `cmd` does not read backslash as an escape:
every command with a quoted argument arrives corrupted. `shell()` stays as the description of
what happens.

stderr is merged into stdout at the pipe (`stderr=subprocess.STDOUT`), so `run` returns one
stream in the order the process actually wrote it. Two pipes and two reader threads can only
reconstruct the order the *reader* happened to get there, which is not the same thing. The split
they buy is also worth less than it looks: `pytest`, `git`, `pip`, `npm`, every progress bar and
most compilers write ordinary output to stderr, so a separate `stderr:` block regularly held
nothing wrong while reading to the model as an error, and the actual failure sat somewhere in a
chatty stdout with no sign of when it happened relative to the rest. Naming *what* went wrong is
the exit code's job, not the channel's. `report()` and `Job` therefore carry one `Stream`.

The pipe is binary and `decode()` reads it a line at a time: UTF-8 first, then the OEM
codepage from `GetOEMCP()` on Windows, then UTF-8 with replacement. `text=True` cannot do this,
because one codec has to be chosen before anything has been read, and on Windows there is no
right answer — `git` and the Python we start write UTF-8, while `cmd`'s own built-ins and older
console programs write OEM, so `dir` on a folder with an accent in its name came back full of
replacement marks. `chcp 65001` is not the fix: `chcp` needs a console and the job is started
with `CREATE_NO_WINDOW`, so it fails and takes its output with it. Per line is safe because
`readline` splits on a newline byte, which never appears inside a multi-byte UTF-8 character.
`decode()` also folds CRLF to LF, which `text=True` used to do, but leaves a lone CR alone so a
progress bar stays the one line it was drawn as.

A call with no `workdir` gets `Tools.working_dir()`, which is `settings.workdir` or, when that
is empty or no longer a directory, `os.getcwd()`. It is validated on use rather than on being
set, since a folder picked in an earlier session can be gone or on an unmounted drive by the
time a command runs.

`Tools.environment()` is what the model cannot work out before its first command: working
directory, `platform.platform()`, the shell `run` hands the command to, the `python` on PATH
and its version, and the date. `Model.with_environment()` puts it in a system message of its own after the preset's, at
both of `outgoing()`'s return points so it cannot shift `summary_at`, and only when
`tools_enabled()`; `outgoing(env=False)` leaves it out of the summary request, for the same
reason `Compact.summarize()` strips the tool list. The date is date-only on purpose: a
timestamp would invalidate a cached prompt prefix on every request, whereas the working
directory only moves when the user picks a new one, which is when the cache should go anyway.
`python_version()` shells out once and caches, since in a frozen build `interpreter()` is
whatever `python` is on PATH, not the Python running VOLlama. It is what a bare `python` in a
command will be, and says nothing about a project's own Python under uv or a `.venv`, so the
block says so. The Chat menu item labelled `CD <path>` is both the display and the
control: `ChatWindow.showWorkdir()` writes the path into the item's own label, doubling any
`&` so wx does not eat it as a mnemonic marker. `shorten()` keeps `HEAD_SHARE` of
`MAX_OUTPUT` from the start and the rest from the end, with a count of what was dropped in
between, so a traceback at the end of a chatty run survives.

Trimming is of what the model *sees*, not of the output. `capped()` writes the whole thing to
`SPILL_DIR` under the temp folder first and `shorten()` names that path in the marker where the
cut is, so `read` can page through the rest. The middle of a build log is exactly where its
first error is, and head-plus-tail alone left no way back to it; every other harness surveyed
spills to a file for the same reason. `prune_spills()` drops logs older than `SPILL_TTL` (a
day) whenever a new one is written, and a temp folder that is full or read-only just means
trimming without a path, which is what happened before there was one. The spill cannot recover
what `Stream` already dropped off the front of a long-running job's buffer — that loss is
labelled rather than repaired.

Both losses are marked *where they happened* rather than at the end, because output that was
cut must not read as output that finished. `dropped()` words the buffer loss and goes in front
of the text in `Job.news()` and `Stream.all()`, so a traceback missing its beginning says so on
its first line.

The description says so as well, because a model that does not know the whole log is on disk
shortens the output itself: piping through `head` or `tail` throws away the part it cannot then
go back for, and the trimming it is trying to pre-empt would have kept it.

A command that backgrounds *itself* escapes all of this, so `detached()` warns about it in the
result. Jobs start as group leaders precisely so that killing one kills its children, and a
process that detaches leaves that group: `poll` cannot read it, `kill_all()` on New Chat and on
exit cannot stop it, and it outlives VOLlama. The model gains nothing by it either — it
backgrounds a server to get the shell back, which is what `run` hands over after
`YIELD_SECONDS` anyway, as a session that can be read and killed. `unquoted()` strips quoted
text before anything is looked at, so `echo "starting the server &"` is not a backgrounded
command, and `--help`/`--version` are exempt. It is a warning, not a refusal, since a command
is occasionally meant to do this. This is hermes' `_foreground_background_guidance`.

Which words count depends on the platform, in both directions. `DETACHERS` (`nohup`, `disown`,
`setsid`, `Start-Process`) mean nothing else wherever they appear, so they are matched anywhere.
`LEADING` holds the one ambiguous word: cmd's `start` does detach, but `start` is also the name
of half the npm scripts in existence, so it counts only as the first word of a segment and only
on Windows, where alone it exists. A trailing `&` is the reverse — it backgrounds on POSIX and
is merely a separator in `cmd`, so it is checked only off Windows.

`report()` also says what a non-zero exit code means. `EXIT_CODES` is the general table
(`137` is almost always the machine running out of memory, `127` is not installed or not on
PATH) and `BY_PROGRAM` overrides it where the number means something else or nothing wrong at
all: `grep`, `rg`, `findstr`, `diff` and `git diff --exit-code` all answer `1` for *no
difference found*, and a model that reads that as a failure retries the command and then
doubts the file. `program()` picks the name to look up by, stepping over `RUNNERS` and `STEPS`
so `uv run pytest` reads as pytest. A negative code is a signal reported as such by `Popen`
and is stated plainly; `128 + n` is a guess and is hedged. This is hermes' table, with its
split between the two.

#### Background jobs
The shape is codex's: no `background` parameter, just a deadline. `run` waits
`YIELD_SECONDS` (10) and, if the process is still alive, registers it and returns a session id
instead of killing it. A job that finishes inside the window is never registered, so the common
case costs nothing. `poll` reattaches: it reports status, hands back output since the last look,
and can wait (up to `MAX_POLL_WAIT`), kill, or list.

A reader thread per job drains the merged pipe into a `Stream`, because a full pipe deadlocks a
process nobody is reading. The `Stream` tracks `base` (characters dropped off the front once it
passes `MAX_BUFFER`) and `cursor` as absolute offsets, so trimming the front never corrupts the
read mark and a poll can say output went missing rather than silently skipping it. `drain()`
joins the reader with a deadline, since a grandchild holding the pipe would otherwise block
forever after the parent exits.

What normally ends a job is going quiet, not going long. `IDLE_TIMEOUT` (120) is the real limit:
the reader stamps `Job.spoke` on every line and the sweeper kills a job that has produced nothing
for that long. `timeout` (`DEFAULT_TIMEOUT` 1800, `MAX_TIMEOUT` 3600) is only the ceiling for a
job that never stops talking. Killing on the clock alone got both cases backwards — a build
printing steadily for twenty minutes was working and died anyway, while a command wedged on a
hidden prompt sat there for the full timeout producing nothing — and the model's only recovery
from the first was to guess a bigger number and pay for the whole build twice. The two deaths are
worded differently in `Job.status()` (`stalled` vs `expired`) because they need different fixes:
one is worth retrying with more room and the other never is, and a bare "timed out" for both is
what makes a model retry the unretryable one. The tool description says so too, since models
under-set timeouts on the assumption that waiting costs something.

Killing a `Popen` only kills the direct child, so jobs start as group leaders
(`CREATE_NEW_PROCESS_GROUP` on Windows, `start_new_session` elsewhere) and `Job.kill()` uses
`taskkill /F /T` or `os.killpg`. One daemon sweeper thread, not a watchdog per job, enforces
`IDLE_TIMEOUT` and the per-job `timeout` ceiling, and drops finished jobs `FINISHED_TTL` after
their end was reported.
`MAX_JOBS` (32) caps what is running; the next one kills the oldest and says which, in its own
result, since `notes()` would otherwise be the model's first word of it a message later — too
late to be told the build it is waiting on is gone. The killed job stays readable, so `poll` and
`notes()` still carry whatever it produced.

A job that outlives its turn has no way to announce itself, since there is no path to inject a
message into a finished turn. So `Tools.notes()` collects jobs that ended unreported and
`Model.ask()` prepends them as a `role="user"` message marked
`additional_kwargs={"background": True}` — hermes' synthetic user turn. LlamaIndex drops
`additional_kwargs` from user messages on the way out, so the marker never reaches the server;
`reviewable()` uses it to keep alt+up off the note and `transcript_lines()` to render it as
`Background:` rather than `You:`. `Tools.kill_all()` runs on New Chat and on exit (bound to
`EVT_CLOSE` as well as the menu item, or the window close button would leak processes). Escape
deliberately does not kill background jobs, since it also just exits edit mode.

It does kill a job still inside its yield window. `Tools.stop_when()` registers a check
(`Model.__init__` passes `lambda: not self.generate`) that `wait_for()` looks at every
`STOP_CHECK` seconds, since `Popen.wait` cannot be interrupted once it is in it and a single
ten second wait would ignore escape for ten seconds. It is a hook rather than a parameter of
`run` because `call()` spreads the model's own arguments into the tool, and the model must
not be able to declare itself unstoppable. `poll(wait=...)` uses the same helper but does not
kill: giving up on the wait is not giving up on the job.

### Compaction
A chat that outgrows `context_window()` gets truncated by the server without anyone being told,
so `Model.maybe_compact()` runs after every completed turn: if `self.used` (the usage the server
reported, or the `token_counter` fallback, both recorded in `showStats`) is at least
`Compact.COMPACT_AT` (0.8) of the window, the model is asked for a handoff summary of itself.

The summary does not replace anything in `Model.messages`. It is held in `self.summary` with
`self.summary_at`, an index into the list, and `outgoing()` splices it in on the way out: system
messages from before the cut, then the summary as a `role="user"` message marked
`additional_kwargs={"summary": True}` (dropped by LlamaIndex, same as `background`), then
everything from the cut on. So the transcript, save and alt+up keep the whole chat, and only the
request changes. `reset_context()` clears it wherever `messages` is replaced wholesale: New Chat,
Open, and `clearLast`.

`Compact.summarize()` strips `tools` from the LLM's `additional_kwargs` for the one call and puts
them back, since a model left holding a tool list tends to run something instead of writing prose.
The call is not streamed. A failure sets the status line and leaves the conversation alone; the
user already has their answer. Compaction is skipped when generation was stopped, and when fewer
than two messages have arrived since the last one, so a single message too big for the window
cannot spin.

The usage threshold is one trigger; a server rejection is the other. `Model.send()` wraps the
request, and when it fails with an error `Compact.overflowed()` recognizes it compacts and tries
once more. There is no standard wording for that rejection and several servers do not say
"context" at all, so `Compact.OVERFLOW` is a list of what they actually send back, ported from
pi's `packages/ai/src/utils/overflow.ts`. `Compact.NOT_OVERFLOW` is checked first, because a
server that is rate limiting you can word it like an overflow: Bedrock's throttling message is
"Too many tokens, please wait before trying again".

A third trigger is a reply that ends early without an error at all. `Compact.truncated()` covers
two shapes of this: a `finish_reason` of `length` with fewer tokens than `max_output()` asked for,
and, when no `max_tokens` is set, an empty reply whose prompt filled 99 percent of the window,
which is what a server that truncates an oversized prompt instead of refusing it produces.
`Model.recover()` drops the truncated assistant message, compacts to `halfway()` and lets `ask()`
send again; a `retried` flag in `ask()` allows this once per turn. The message stays in the
transcript, because the user has already read it. The finish reason only appears on the raw chunk
and only on one chunk of the stream — with `stream_options` the last chunk is the usage one and
its `choices` list is empty — so `finish_reason()` keeps the last non-empty one it saw rather than
reading `data` at the end.

Two things make the retry work. `stream_chat()` is lazy, so `Model.start()` pulls the first chunk
itself and re-attaches it with `itertools.chain`; without that the rejection surfaces halfway
through displaying a reply, too late to retry. And the overflow path compacts only up to
`halfway()`, a user-message boundary about midway, because summarizing everything would send the
server the same history it just refused. `halfway()` returns None when fewer than two of your
messages remain after `summary_at`, since the cut would then land in front of the only one and
summarize nothing. The original server error is what propagates if `halfway()` gives None, if the
summary call itself throws, or if `summary_at` did not move.

Manual compaction is Edit > Compact Conversation (ctrl+shift+K), which runs the same path in a
thread.

### Settings
`Settings.SETTINGS_VERSION` is 1. There is no migration from older files: a settings file whose version differs or that lacks `Settings.REQUIRED_KEYS` is flagged `version = 0`, and VOLlama tells the user to choose Reset Settings and configure from scratch.

`DotDict` only autosaves on attribute assignment, so mutating a nested dict in place does not reach disk. Use `save_presets()` (or reassign `settings.presets`) after editing a preset.

### Configuration Management
Settings are automatically encrypted (API keys) and stored in JSON format. The Settings class provides singleton access to configuration throughout the application.

### Build Process
PyInstaller creates self-contained executables with embedded Python runtime, audio files, and NLTK data. Platform-specific patches handle library compatibility issues.

### Accessibility Requirements
All new UI components must support keyboard navigation and provide appropriate accessibility labels for screen readers. Audio feedback should be added for important state changes.