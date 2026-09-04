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
git apply lib-win.patch   # Windows
git apply lib-mac.patch   # Mac
```

### Building
```bash
build-pyinstaller.bat  # Windows: PyInstaller setup
build.bat              # Windows: final build
./build.sh             # Mac/Linux
build-debug.bat/.sh    # Debug builds (retain console)
```

### Running from source
```bash
python VOLlama.py
```

### Tests
```bash
pip install -r requirements-dev.txt
python -m pytest
```
The suite imports no wxPython and reaches no network. `tests/conftest.py` points the settings store at a temporary directory for every test, so nothing can touch the real `settings.json`.

## Architecture

The package is laid out as its layers, and imports only ever point downward.

```
VOLlama.py                    entry point: logging, wx.App, ChatWindow, MainLoop
vollama/
  errors.py                   VOLlamaError, ConfigError, DocumentError
  resources.py                paths to bundled files, frozen or from source
  config/    store, settings, presets, parameters, prompts
  tools/     workspace, shell, files, registry
  rag/       documents, index
  speech/    sapi, mac, screen_reader, silent
  chat/      view, conversation, client, streaming, compaction, session
  ui/        window, transcript, preset_manager, rag_dialog, speech_dialog,
             errors, update
tests/
```

| Layer | Owns | Depends on |
| --- | --- | --- |
| `config` | what the user has set | nothing else here |
| `tools` | what the model may do to this machine | `config` |
| `rag` | documents, embeddings, retrieval | `config` |
| `speech` | turning text into sound | `config` |
| `chat` | the conversation and the turn loop | `config`, `tools`, `rag` |
| `ui` | wxPython | everything above |

**Nothing below `ui` imports wx**, and `ui/transcript.py` is the only module that calls `wx.CallAfter`. That rule is the point of the layout; `python -c "import vollama.chat.session, sys; print('wx' in sys.modules)"` checks it.

One message flows like this:

```
prompt + Attachments      ui.window.on_send        (GUI thread)
  ▼
ChatSession.ask(...)      worker thread, no wx
  ├─ config.presets.require_active() → chat.client.build()
  ├─ rag.documents resolves the attachments
  ├─ stream reply → tools.registry.call(...) → send results back → repeat
  └─ compaction when the window fills, on a refusal, or on a cut-off reply
  ▼
ui.transcript.TranscriptView   marshals onto the GUI thread
```

### The three abstractions

- **`ChatView`** (`chat/view.py`) — the port the session reports through. Its methods name the *decisions* the presentation layer makes, which is what keeps policy on the right side of the line: whether reasoning is shown, whether the reply is spoken, where a sentence ends for TTS, and how a token count reads all live in `ui/transcript.py`. One real implementation, one in the tests.
- **`Tool`** (`tools/registry.py`) — an OpenAI function schema paired with what runs it, how to summarize a call in one transcript line, and whether it counts against the round budget. Five instances, composed in one list.
- **`Preset`** (`config/presets.py`) — the unit of configuration, with one `validate()` used by both the editor and the chat.

Nothing else is abstracted: one provider path, no repositories or services, no speech base class (a `Protocol` documents the contract), no event bus, no DI container.

## Configuration

`config/settings.py` holds a `Settings` dataclass whose fields *are* the schema — the defaults, the types, and the JSON key names, all in one place. `settings.json` is that dataclass written out field for field.

**Saving is explicit.** Call `settings.save()` after a change. The previous design saved on every attribute assignment, which silently failed whenever a nested value (a preset) changed, and needed a helper whose body was `settings.presets = settings.presets`.

`SETTINGS_VERSION` is 1. A file that says anything else is refused rather than migrated: the app reports it and tells the user to choose Reset Settings, and **leaves the old file on disk** so an API key can still be recovered from it.

`config/store.py` owns the file. It writes to a temporary file and renames, sets mode `0600`, and encrypts the api keys with a Fernet key **stored in the same file** — that is obfuscation, not secrecy, and the module says so. The fields to encrypt are listed explicitly rather than matched by a substring of their names.

`config/presets.py` owns the rules as well as the shape: `create` refuses a taken name, `update` renames, `delete` promotes the first of what is left, `replace` writes the whole list at once, `active_name()` corrects a stale pointer. The GUI calls these rather than deciding again. `Preset` has **no default base URL** — an empty preset must fail `validate()`; the suggested starting URL belongs to the editor.

`ui/preset_manager.py` is the one place presets are edited. It is **the toolbar's own preset button**, moved into a dialog that can act on what the button names: the same menu of preset names, with New, Duplicate and Delete under them, above the Connection, Parameters and System Prompt pages for whichever preset it is showing. One widget doing one job in the place where the job can be finished, rather than a second set of controls next to a list. The toolbar's menu keeps the preset names and a way in here, since switching preset is the part worth one keystroke. Edits live on copies, so Cancel discards the lot, and OK hands the whole list to `presets.replace` — which is why that function exists: an entry that is no longer in the list is a deletion, and two presets swapping names is one write instead of a rename that has to dodge the other.

`config/parameters.py` holds the parameter schema as a dict, `SCHEMA`. `None` means *not sent*, which is why `Model.Client` exists (below). The preset editor builds its controls from the schema, so adding a parameter is an edit to that table.

`config/prompts.py` is the system-prompt library over `prompts.csv`, using stdlib `csv`. pandas is no longer a dependency.

## Chat

`chat/client.py` builds one `Client` (an `OpenAILike` subclass) from the active preset on every request. Only names in `OPENAI_PARAMS` are forwarded, since `additional_kwargs` are spread as top-level kwargs into `chat.completions.create()` and an unknown name raises.

`Client` exists for one parameter. llama_index puts `temperature` into every request unconditionally — a constructor field with a default of 0.1 rather than part of `additional_kwargs` — so an empty Temperature box still sent 0.1, overriding the server's own default and failing outright on models that have deprecated the parameter. Whether the preset set one is read off `additional_kwargs`, since that dict is what actually goes out.

`chat/streaming.py` is the only module that knows the shape of a streamed chunk. Servers answer with pydantic models or plain dicts, so every read goes through `field()`. Gemini's thinking models sign every function call and carry the signature as `tool_calls[i].extra_content.google.thought_signature`; send a call back without it and the next request is refused with *Function call is missing a thought_signature*, killing every turn in which the model calls a tool. It is lost twice over by default — the openai library parses the unknown key into `model_extra`, and llama_index's fragment merge copies only the fields it knows — so `collect_extras()` reads it off the raw chunks, keyed by the call's own `index`, and `tool_calls_of()` puts it back. `to_openai_message_dict()` spreads `additional_kwargs`, so it reaches the wire unchanged.

`chat/conversation.py` holds two different things, which is the whole point of the module. `messages` is the entire chat and never loses anything — transcript, Save, alt+up. `outgoing()` is what goes on the wire and *is* allowed to leave things out:

- The summary is spliced in for everything before `summary_at`, as a `role="user"` message marked `additional_kwargs={"summary": True}` — a model told it wrote the summary itself repeats it.
- Tool calls and results older than `KEEP_TOOL_TURNS` (1) are dropped, or every command's output is resent forever. A call and its result go together, since a call the server cannot match to a result makes the whole history unusable; an assistant message that only carried a call goes with them, one that also spoke keeps its text.
- `environment` (what the machine looks like) is added as a system message of its own after the preset's, and only when tools are on. Left out of the compaction request, for the same reason that request drops the tool list.

### Tool calling

Opt-in through `settings.tools` (default false), because small local models call tools badly and some endpoints ignore `tools` entirely. Global rather than a preset field: it answers "do I want the model touching this machine right now", which changes mid-chat.

`ChatSession._converse` loops: stream a reply, run any tool calls, send the results back, up to `registry.MAX_TOOL_ROUNDS` (10) and `MAX_TOOL_CALLS` (40). Tools marked `free` (`poll`, `read`) do not spend a round — waiting on a build, or reading the files you are about to change, is not the progress the budget limits — and `MAX_TOOL_CALLS` is the ceiling free calls cannot slip past.

**Every tool call must get a matching tool message**, even one that is not run (round cap hit, user pressed stop). A dangling tool call makes the whole history unusable to the server.

Anything that walks `conversation.messages` has to cope with tool rounds: `clear_last()` truncates from the last user message, `reviewable()` keeps alt+up off tool results and off the empty assistant message carrying a call, and `to_json`/`load_json` round-trip `additional_kwargs` so `tool_call_id`s survive.

There is **no confirm-before-run dialog**, for commands or for file writes. The Chat menu checkbox is the only gate; the trust boundary is stated once, at the top of `tools/registry.py`.

### Compaction

A chat that outgrows `context_window()` gets truncated by the server without anyone being told, so `_compact_if_full` runs after every completed turn: if the usage the server reported (or the `token_counter` fallback) is at least `compaction.COMPACT_AT` (0.8) of the window, the model is asked for a handoff summary of itself.

The summary replaces nothing. It is held on the `Conversation` and spliced in by `outgoing()`, so the transcript, Save and alt+up keep the whole chat. `reset_context()` clears it wherever `messages` is replaced wholesale.

The summary request goes through a **client built without tools** rather than by mutating a shared client's `additional_kwargs` and putting them back — a model left holding a tool list runs something instead of writing prose.

Three triggers, one path:

1. **Usage** — the threshold above.
2. **A refusal.** `ChatSession._send` wraps the request; `compaction.overflowed()` recognizes the rejection and it compacts and retries once. There is no standard wording, so `OVERFLOW` is a list of what servers actually send, ported from pi's `overflow.ts`. `NOT_OVERFLOW` is checked first, because a server that is rate limiting you can word it like an overflow — Bedrock's throttling message is "Too many tokens, please wait before trying again".
3. **A reply that ended early with no error.** `compaction.truncated()` covers a `finish_reason` of `length` with fewer tokens than `max_tokens` asked for, and an empty reply whose prompt filled 99% of the window, which is what a server that truncates an oversized prompt instead of refusing it produces. `_recover()` drops the truncated assistant message, compacts, and lets the loop send again — once per turn. The message stays in the transcript, because the user has already read it.

Two things make the retries work. `_start()` pulls the first chunk itself and re-attaches it with `itertools.chain`, because `stream_chat` is lazy and without this a rejection surfaces halfway through displaying a reply. And the overflow path compacts only up to `halfway()`, a user-message boundary about midway, because summarizing everything would send the server the same history it just refused; `halfway()` returns None when fewer than two of your messages remain, and the original server error is what propagates then.

Manual compaction is Edit > Compact Conversation (ctrl+shift+K).

## Tools

`tools/workspace.py` owns what a path means — `working_dir()`, `resolve()`, `checked()` — for both `shell` and `files`, which are peers and do not import each other. `settings.workdir` is validated on use rather than on being set, since a folder picked in an earlier session can be gone by the time a command runs in it.

`tools/registry.py` composes the five `Tool` records, calls them, describes them for the transcript, and builds `environment()`. Every failure comes back as **text**, never an exception: the model is the one who reads it, and a raise would end the turn over a mistyped argument name.

### read, write and edit

`tools/files.py` exists for one reason: doing these through `run` means the file's own text has to survive a heredoc or a shell-quoted Python string literal first, which is where a small model fails *silently* — you get a file containing a literal `\n`, or one truncated at an unescaped quote, rather than an error. As a tool parameter the same text is one JSON string, escaped by the layer that is good at it. This is also why `run` takes a shell command and not Python source. That argument is strongest for `write` and `edit`; `read` is in for the paging (`MAX_LINES` 2000, `MAX_BYTES` 50 KB, with a `Use offset=N to continue.` footer).

`edit` adds a guarantee rather than a convenience. Every edit in a call is located against the **original** text and checked — empty, missing, ambiguous, overlapping — before any of them is written, so an unclear match leaves the file untouched and the model is told which edit and why. `replace_all` is the model saying it meant every occurrence. `text.replace(old, new)` in `run` changes every occurrence and `replace(old, new, 1)` changes an arbitrary one; either way the file is already wrong. The result carries a `difflib` diff (`DIFF_CONTEXT` 2, capped at `MAX_DIFF`).

`load()` reads with universal newlines and hands back the ending the file actually had, so `old_text` is always written with plain `\n` and a CRLF file is not converted by being edited. A leading BOM comes off and `save()` puts it back, since an invisible character on line 1 makes a correct `old_text` fail with nothing in the error to explain it. Non-UTF-8 and files with a NUL byte are refused rather than mangled.

`read` deliberately returns **unnumbered** text, unlike Claude Code's Read: a line-number prefix would break `edit`'s exact matching. A line longer than `MAX_LINE` (2000) is cut off with a marker, and the footer warns once that a cut line is no longer the file's text — `MAX_BYTES` cannot do this job, because it stops *before* the line that would exceed it and a minified file used to come back whole.

Two fallbacks after exact matching, and only two:

- `unescape()` turns a literal backslash-n back into a line break (ported from gemini-cli's `unescapeStringForGeminiBug`) and says so in the result. `write` does not get it: content legitimately containing `\n`, like Python source, must survive untouched.
- `fold_match()` handles the characters a model cannot see it got wrong — a curly quote for a straight one, an en dash for a hyphen, a zero-width space from a copy out of HTML, trailing whitespace. `fold()` builds a folded copy alongside a map back to the original characters; a match is looked up in folded space, translated to the original's own offsets, and **verified by folding the original slice again**. The replacement is spliced into the original text, so the file's own characters survive everywhere the edit does not replace them, and an ambiguous mapping refuses the whole call. This is openclaw's `buildNfkcBoundaries` / `translateFuzzySpan` shape, fail-closed check included.

Tabs and spaces are deliberately **not** made equivalent, and that is where the ladder stops. Folding them would let an `old_text` indented with spaces match a file indented with tabs, after which `new_text`, written exactly as sent, silently mixes the file's indentation. Everything past this point on other harnesses' ladders (line-trimmed, whitespace-normalized, indentation-flexible, block-anchor) buys matches at the price of occasionally editing the wrong region; hermes' own threshold history went 0.10/0.30 → 0.50/0.70 and 50%-of-lines → all-lines-at-0.80, all in the tightening direction.

An `old_text` that matches nothing is answered with the lines that came closest rather than "not found", ported from hermes' `find_closest_lines()`. `nearest()` scores the first non-blank line against every line of the file and shows `SUGGESTIONS` (3) windows of `SNIPPET_LINES` (20), deduplicated. It anchors on one line rather than sliding the whole block, because comparing a twenty-line window against every position in a nine-thousand-line file takes forty seconds and anchoring takes a third of one. When the closest window differs in whitespace only, `visible()` prints both with `→` for a tab and `·` for a space. Otherwise `divergence()` names the *kind* — `the indentation differs: you sent 4 spaces, the file has 1 tab`, `the escaping differs`, or `they first differ at column N` with a caret. "It must match exactly" tells the model the rule, which it already knew; what it does not know is which of the two lines is wrong and how. `kind()` reports escaping only when the backslashes are the *whole* difference. This is openclaw's `describeCandidateDifference()`.

An `old_text` identical to its `new_text` is refused by name before anything is located. An edit whose `old_text` is *gone* and whose `new_text` is already there is a different thing — an edit that has already landed, usually from a retried batch, and hermes' trajectory mining has it as the commonest patch failure. `applied()` answers it as a success-shaped no-op: the edit is skipped, the rest of the batch is applied, and the result says which. Uniqueness of `new_text` is the guard against reading a coincidence as a landed edit. `locate()` raises `NotFound` rather than a plain `ValueError` so only a no-match, not an ambiguous match, can take this path.

An `old_text` that matches *too much* is answered with where, not with a count: `ambiguous()` lists up to `SITES` (5) as `line N: <the line>`. A bare "found 8 occurrences" leaves the model to find them itself, which it does by reading the whole file again and sending the same edit. An `old_text` that is nothing but whitespace is refused by name.

`edits_of()` reads the argument out of the shapes a model actually sends: the array as a JSON string, one edit as a bare object, the whole thing wrapped in a second `edits` key.

`workspace.checked()` refuses two paths that parse as files but are not. `device()` catches Windows' reserved names (`nul`, `con`, `com1`, …, extension stripped, since `con.txt` is the console too) and, on POSIX only, anything under `/dev/`: writing one reports success and throws the text away, and reading a character device never returns. Each platform's rule applies only on that platform. A missing file gets `suggest()`, which runs `difflib.get_close_matches` over the parent directory listing we already had to read.

`write` refuses content that says the rest of the file goes here instead of containing it, before the path is resolved: `write` replaces the whole file, so a model that abbreviates one destroys it, and the damage is silent. `placeholder()` is gemini-cli's detector and its narrowness is the point — `commentary()` requires the line to be a *comment*, it must contain an ellipsis, and what is left after both are stripped must be in the closed set `OMISSIONS`. So `# ... rest of the code unchanged ...` is refused while `print("...")` and a bare `# ...` are not.

`write` parses Python, JSON, YAML and TOML before writing, and `introduced()` reports only an error the write would *add* — a file that already fails to parse is usually the reason the model is writing it. JSON, YAML and TOML fail closed, since they exist to be read by another program and a broken one stops that program several tool calls later; Python is written with a warning, since a model writing a module in pieces has a reason to leave it briefly unparseable. A missing parser disables its check rather than refusing the write. `edit` runs the same check, and a fail-closed extension is refused with the diff the edit *would* have made.

A refused binary file is named: `describe_bytes()` reads the first bytes against a table of signatures and `read` answers `is not text: PNG image, 4.9 KB`. The guess only ever words an error, never a decision, so calling a .docx a zip archive is fine — it still tells the model whether it asked for the wrong path or the right one in the wrong tool.

### run and poll

`tools/shell.py`'s `run` is stateless by design, like the shell tools in pi, opencode, codex and openclaw. Three affordances stand in for a session: a `workdir` parameter (validated first), a description that tells the model to run a venv's interpreter by path rather than activating it, and background jobs.

`command` is a shell command, not Python source. Every model that can call tools was trained on traces where this slot holds `git status`, and a `subprocess.run(..., capture_output=True, text=True)` wrapper costs sixty tokens and a class of mistakes a shell does not have. Worse, Python past one line needs real line breaks and exact indentation inside a JSON string — the failure `files.py` exists to prevent, reintroduced one tool over. Python is still reachable by the better road: `write` the script, then `run` the file. All six harnesses surveyed ship a shell here.

The cross-platform problem is answered the way gemini-cli and openclaw answer it: name the invocation instead of leaving it to be guessed. `shell()` is `cmd.exe /c` on Windows (COMSPEC if set) and `/bin/sh -c` elsewhere, and `invocation()` renders it into both the tool description and `environment()`, so the model is told *"It is run as `cmd.exe /c <command>`"* and writes `dir` rather than `ls`. cmd rather than PowerShell for startup cost and quoting; `/bin/sh` rather than `$SHELL` because POSIX runs everywhere and fish is not POSIX.

`spawn()` passes `shell=True` with the command as a string rather than `shell() + [command]`, though the two mean the same invocation: a list goes through `list2cmdline` on Windows, which backslash-escapes the quotes inside the command, and `cmd` does not read backslash as an escape.

stderr is merged into stdout at the pipe, so `run` returns one stream in the order the process wrote it. Two pipes and two reader threads can only reconstruct the order the *reader* got there. The split is also worth less than it looks: `pytest`, `git`, `pip`, `npm`, every progress bar and most compilers write ordinary output to stderr, so a separate `stderr:` block regularly held nothing wrong while reading as an error. Naming *what* went wrong is the exit code's job.

The pipe is binary and `decode()` reads it a line at a time: UTF-8 first, then the OEM codepage from `GetOEMCP()` on Windows, then UTF-8 with replacement. `text=True` cannot do this, because one codec has to be chosen before anything has been read and on Windows there is no right answer — `git` and Python write UTF-8 while `cmd`'s built-ins write OEM, so `dir` on a folder with an accent came back full of replacement marks. `chcp 65001` is not the fix: it needs a console, and jobs start with `CREATE_NO_WINDOW`. Per line is safe because `readline` splits on a newline byte, which never appears inside a multi-byte UTF-8 character.

`report()` says what a non-zero exit code means. `EXIT_CODES` is the general table (`137` is almost always the machine running out of memory, `127` is not installed or not on PATH) and `BY_PROGRAM` overrides it where the number means something else or nothing wrong at all: `grep`, `rg`, `findstr`, `diff` and `git diff --exit-code` all answer `1` for *no difference found*, and a model that reads that as a failure retries and then doubts the file. `program()` steps over `RUNNERS` and `STEPS` so `uv run pytest` reads as pytest. A negative code is a signal reported as such by `Popen`; `128 + n` is a guess and is hedged.

`shorten()` keeps `HEAD_SHARE` of `MAX_OUTPUT` from the start and the rest from the end. Trimming is of what the model *sees*, not of the output: `capped()` writes the whole thing to `SPILL_DIR` under the temp folder and names that path in the marker where the cut is, so `read` can page through the rest. The middle of a build log is exactly where its first error is. `prune_spills()` drops logs older than `SPILL_TTL` (a day); a full or read-only temp folder just means trimming without a path. Both losses are marked *where they happened* rather than at the end, because output that was cut must not read as output that finished. The tool description says so too, since a model that does not know the log is on disk pipes through `head` and throws away what it cannot then go back for.

A command that backgrounds *itself* escapes all of this, so `detached()` warns. Jobs start as group leaders precisely so killing one kills its children, and a process that detaches leaves that group: `poll` cannot read it, `kill_all()` cannot stop it, and it outlives VOLlama. The model gains nothing — it backgrounds a server to get the shell back, which is what `run` hands over after `YIELD_SECONDS` anyway, as a session that can be read and killed. `unquoted()` strips quoted text first, so `echo "starting the server &"` is not a backgrounded command, and `--help`/`--version` are exempt. `DETACHERS` (`nohup`, `disown`, `setsid`, `Start-Process`) are matched anywhere; `LEADING` holds the one ambiguous word, cmd's `start`, which is also the name of half the npm scripts in existence and so counts only as the first word of a segment and only on Windows; a trailing `&` is checked only off Windows. This is hermes' `_foreground_background_guidance`.

#### Background jobs

The shape is codex's: no `background` parameter, just a deadline. `run` waits `YIELD_SECONDS` (10) and, if the process is still alive, registers it and returns a session id. A job that finishes inside the window is never registered, so the common case costs nothing. `poll` reattaches: status, output since the last look, and optionally wait (up to `MAX_POLL_WAIT`), kill, or list.

A reader thread per job drains the merged pipe into a `Stream`, because a full pipe deadlocks a process nobody is reading. The `Stream` tracks `base` (characters dropped off the front past `MAX_BUFFER`) and `cursor` as absolute offsets, so trimming the front never corrupts the read mark and a poll can say output went missing rather than silently skipping it. `drain()` joins the reader with a deadline, since a grandchild holding the pipe would otherwise block forever.

What normally ends a job is going quiet, not going long. `IDLE_TIMEOUT` (120) is the real limit; `timeout` (`DEFAULT_TIMEOUT` 1800, `MAX_TIMEOUT` 3600) is only the ceiling for a job that never stops talking. Killing on the clock alone got both cases backwards — a build printing steadily for twenty minutes died anyway, while a command wedged on a hidden prompt sat for the full timeout producing nothing — and the model's only recovery from the first was to guess a bigger number and pay for the whole build twice. `Job.status()` words the two deaths differently (`stalled` vs `expired`) because they need different fixes.

`JobTable` owns the jobs, the lock and the one sweeper thread. Killing a `Popen` only kills the direct child, so jobs start as group leaders (`CREATE_NEW_PROCESS_GROUP` on Windows, `start_new_session` elsewhere) and `Job.kill()` uses `taskkill /F /T` or `os.killpg`. `MAX_JOBS` (32) caps what is running; the next one kills the oldest and says which **in its own result**, since `notes()` would otherwise be the model's first word of it a message later. The killed job stays readable.

A job that outlives its turn has no way to announce itself, since there is no path to inject a message into a finished turn. So `JobTable.notes()` collects jobs that ended unreported and `ChatSession` prepends them as a `role="user"` message marked `additional_kwargs={"background": True}` — hermes' synthetic user turn. LlamaIndex drops `additional_kwargs` from user messages, so the marker never reaches the server; `reviewable()` uses it to keep alt+up off the note and `ui.transcript` renders it as `Background:`. `kill_all()` runs on New Chat and on exit (bound to `EVT_CLOSE` as well as the menu item). Escape does not kill background jobs, since it also just exits edit mode.

It does kill a job still inside its yield window. `shell.cancellation` is a `Cancellation` the session points at its own stop flag **for the length of a turn** (a context manager, so a stop flag from a finished turn cannot answer for the next command). `wait_for()` checks it every `STOP_CHECK` seconds, since `Popen.wait` cannot be interrupted once it is in it. It is a module-level object rather than a parameter of `run` because the registry spreads the model's own arguments into the tool, and the model must not be able to declare itself unstoppable. `poll(wait=...)` uses the same helper but does not kill: giving up on the wait is not giving up on the job.

## RAG

`rag/documents.py` is the one place that knows what can be read: `DOCUMENT_EXTENSIONS` (the file dialogs build their filters from it), `load()`, `read_files()`, and `fetch_page()`, which tries three readers in order and logs each failure rather than swallowing it.

`rag/index.py` confines llama_index's process-wide `Settings` global: the embedding model, chunk sizes and context window are set here, where they are used, and the chat client is **passed in** to `query()` rather than left on the global. Embedding is batched (`BATCH` 32) instead of one request per chunk. The embedding endpoint (`embedding_base_url` / `embedding_api_key` / `embedding_model`, default `EmbeddingGemma`) is a global setting rather than a preset field, because an index is built with one embedding model and re-embedding it because the chat model changed would silently invalidate every stored vector.

## Accessibility

- Every control gets an accessible name; two buttons with the same label get different ones (the preset manager's two "Choose..." buttons, and its preset button, which keeps the toolbar's accessible name because it is the same control).
- **A label is created before the control it names.** A screen reader on Windows pairs a field with the static text created before it, not with the one the sizer puts to its left, so a control passed into a row helper already built is announced with the label of the row *above* — the Base URL box read as "Name". This is why `ConnectionPage._row` and `RagDialog._add` take something that *builds* the control rather than the control.
- Focus follows the value that changed, not the button that changed it, so a screen reader announces the new value.
- Keyboard-only navigation throughout, with shortcuts declared once on the menu item; toolbar buttons raise that same item's event.
- Audio feedback (`send.wav` / `receive.wav`) for state changes.
- Platform-native TTS, plus a screen-reader output that speaks in the user's own voice and rate. The backends expose `speak`, `stop`, `voices()`, `voice`, `rate` and **open no dialogs**; `ui/speech_dialog.py` asks and the window applies.
- Voices go into a submenu per **language**, not a list and not a tree of identifiers: macOS offers well over a hundred. `speech.voices()` returns `Voice` records (identifier, name, language) rather than identifier strings, because a macOS identifier is neither the voice's name nor searchable — the one Siri voice the system lends to third-party apps is `com.apple.ttsbundle.gryphon-neuralAX_Nora_en-US_premium` and is called "Voice 4". Grouping by identifier namespace sorted voices by *engine* (`eloquence`, `voice.compact`, `speech.synthesis.voice`), so nine Korean voices landed in three places, two of them levels deep behind words naming an implementation detail. `speech.group()` buckets by language and the dialog only turns that into menus; `Voice.within()` drops a name's redundant locale suffix ("Eddy (Korean (South Korea))"), and `Voice.describe()` writes the button's label. A screen reader announces how many items are in the level you are in, which a flat list of a hundred cannot.
- Only the `neuralAX` build of a Siri voice is published to `NSSpeechSynthesizer`, so a Korean Siri voice installed as `ko_KR.minji.gryphon.premium` is offered by no public API — not `availableVoices()`, not `AVSpeechSynthesisVoice`, not `say -v '?'`. Nothing to fix here; don't add a fallback for it.
- `voice` and `rate` stay plain values on the backends. `settings.voice` holds the platform identifier, which is why `described()` keeps a whole SAPI description as the identifier while splitting a name and language out of it for display.

New UI components must keep to all of this.

## Conventions

- Comments explain *why*. A comment restating the code is worse than none.
- One canonical implementation per responsibility; no compatibility shims, no migration paths, no version branching.
- `snake_case` throughout. The one exception is `Settings.speakResponse`, whose name is fixed by the settings file format.
- Domain code raises `VOLlamaError` subclasses with messages written for the user; the UI shows the message and logs the traceback. Tools return their errors as text, because that text is what the model acts on.
- Add a test with the behaviour. `chat`, `config` and `tools` are all testable without a window; if something is not, that is a sign it is in the wrong layer.
