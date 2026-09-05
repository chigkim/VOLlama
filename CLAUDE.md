# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VOLlama is an accessible desktop chat client for LLM interaction, built with wxPython and designed with accessibility-first principles. It talks to any OpenAI-compatible server (Ollama, llama.cpp, LM Studio, vLLM, OpenAI, Gemini's OpenAI endpoint, ...) through a single code path, with features like RAG, multimodal support, and comprehensive screen reader compatibility.

A **preset** is the unit of configuration: it owns base URL, API key, model, `context_window`, system prompt, generation parameters, and the embedding endpoint and retrieval settings. `context_window` is a preset field because it describes one model on one server; its consumers are compaction and RAG prompt sizing. The retrieval settings are preset fields for the same reason: a preset *is* a server, and the endpoint serving the chat model is usually the one serving the embedding model. Presets live inside the encrypted `settings.json`; there is no separate API settings dialog and no per-provider branching.

## Development Commands

### Setup Environment
```bash
uv sync
```
`pyproject.toml` is the one dependency list; there is no `requirements.txt`. It pins `requires-python = "==3.14.*"` and `.python-version` names 3.14.7, so `uv sync` fetches that interpreter itself. `uv.lock` is committed, so a sync reproduces the exact versions. The dev group (pytest, pyinstaller) installs by default; `uv sync --no-dev` leaves it out.

### Building
```bash
.venv\Scripts\activate  # or source .venv/bin/activate
build.bat               # Windows: final build
./build.sh              # Mac/Linux
build-debug.bat/.sh     # Debug builds (retain console)
```
`uv sync` installs PyInstaller, so building needs nothing else. `build-pyinstaller.bat` is the optional step for a bootloader compiled here rather than the published one — it needs a C toolchain, and the next `uv sync` puts the wheel back over it. README.md says who wants that and why.

### Running from source
```bash
uv run vollama          # the installed command
uv run python VOLlama.py  # the same thing, with a console to watch
```

### Tests
```bash
uv run python -m pytest tests
```
The suite imports no wxPython and reaches no network. `tests/conftest.py` points the settings store at a temporary directory and hands `settings` a clean object through `Settings.adopt`, so nothing can touch the real `settings.json`.

## Architecture

The package is laid out as its layers, and imports only ever point downward.

```
VOLlama.py                    what PyInstaller builds; calls vollama.__main__
vollama/
  __main__.py                 entry point: logging, settings.load, wx.App, ChatWindow
  errors.py                   VOLlamaError, ConfigError(field), DocumentError
  resources.py                paths to bundled files, frozen or from source
  config/    store, settings, presets, parameters, prompts
  tools/     workspace, content, matching, shell, files, registry
  rag/       documents, index, search
  speech/    sapi, mac, screen_reader, silent
  chat/      view, message, conversation, client, streaming, compaction,
             toolset, session
  ui/        window, transcript, preset_manager, speech_dialog,
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

- **`ChatView`** (`chat/view.py`) — the port the session reports through. Its methods name the *decisions* the presentation layer makes, which is what keeps policy on the right side of the line: whether reasoning is shown, whether the retrieved passages are printed, whether the reply is spoken, where a sentence ends for TTS, and how a token count reads all live in `ui/transcript.py`. The session reports what happened and never reads a display setting. One real implementation, one in the tests.
- **`Tool`** (`tools/registry.py`) — an OpenAI function schema paired with what runs it, how to summarize a call in one transcript line, and whether it counts against the round budget. Five instances, composed in one list.
- **`Preset`** (`config/presets.py`) — the unit of configuration, with one `validate()` used by both the editor and the chat.

Nothing else is abstracted: one provider path, no repositories or services, no speech base class (a `Protocol` documents the contract), no event bus, no DI container.

## Configuration

`config/settings.py` holds a `Settings` dataclass whose fields *are* the schema — the defaults, the types, and the JSON key names, all in one place. `settings.json` is that dataclass written out field for field.

**Saving is explicit.** Call `settings.save()` after a change. The previous design saved on every attribute assignment, which silently failed whenever a nested value (a preset) changed, and needed a helper whose body was `settings.presets = settings.presets`.

**Loading is explicit too.** `settings` starts as the defaults and `settings.load()` reads the file into it through `Settings.adopt`, called once by `VOLlama.main`, which hands the answer to `ChatWindow`. Reading the disk at import time made `import vollama.config.settings` do I/O, made "was the file readable" a module constant the window imported, and left the test fixture resetting a singleton it did not own — `adopt` is now the one way that happens, and `tests/conftest.py` uses it too.

`SETTINGS_VERSION` is 1. A file that says anything else — or one that will not parse — is refused rather than migrated: the app reports it and tells the user to choose Reset Settings, and **leaves the old file on disk** so an API key can still be recovered from it. `Settings.writable` is what makes that true rather than merely intended: `load()` clears it and `save()` then refuses, because otherwise the first menu toggle wrote the defaults over the file the user was told to go and copy a key out of. It is not a dataclass field, since it is a fact about this run and not a setting.

`config/store.py` owns the file. It writes to a temporary file and renames, sets mode `0600`, and encrypts the api keys with a Fernet key **stored in the same file** — that is obfuscation, not secrecy, and the module says so. The fields to encrypt are listed explicitly rather than matched by a substring of their names.

`config/presets.py` owns the rules as well as the shape. There are two ways to write presets and no more: `replace` takes the whole list from the editor — a name no longer in it is a deletion, and it promotes the first of what is left when the active one goes — and `activate` is the toolbar switching between them. `active_name()` corrects a stale pointer. `create`, `update` and `delete` were a second way to do the same thing, called from nowhere but their own tests, and are gone. The GUI calls these rather than deciding again. `Preset` has **no default base URL** — an empty preset must fail `validate()`; the suggested starting URL belongs to the editor. `embedding_base_url` *does* have a default, since `validate()` does not check it and a preset with nothing there can index nothing at all. `retrieval()` is the preset retrieval reads from, falling back to the defaults when nothing is configured, so building an index is not a second place with an opinion about that. `Preset.from_dict` coerces each field by the type it is **declared** with and `to_dict` is `asdict`, so the dataclass is the only place a preset's shape is written down — the same way `Settings` reads itself, where it used to be a hand-written list of thirteen fields in each direction. A value a hand-edited file cannot supply falls back to that field's default rather than failing the load and taking the API keys with it, and the three fields that count something are clamped positive (`POSITIVE`).

Schema changes are absorbed the same way rather than migrated: `Settings.from_dict` drops keys it does not know, `Preset.from_dict` defaults what is missing, and `parameters.checked` drops a value that is not of the kind the schema says. So the retrieval fields could move out of `Settings`, the parameter storage could change shape, and `speakResponse` could become `speak_response`, all without bumping `SETTINGS_VERSION` — an existing file still loads with every preset, URL, model and API key intact, and what it loses is a generation parameter value and one checkbox. Refusing every file, and with it every API key, to save someone retyping a temperature would be the worse trade.

`ui/preset_manager.py` is the one place presets are edited. It is **the toolbar's own preset button**, moved into a dialog that can act on what the button names: the same menu of preset names, with New, Duplicate and Delete under them, above the Connection, Parameters, System Prompt and RAG pages for whichever preset it is showing. One widget doing one job in the place where the job can be finished, rather than a second set of controls next to a list. The toolbar's menu keeps the preset names and a way in here, since switching preset is the part worth one keystroke. Edits live on copies, so Cancel discards the lot, and OK hands the whole list to `presets.replace` — which is why that function exists: an entry that is no longer in the list is a deletion, and two presets swapping names is one write instead of a rename that has to dodge the other. A page that cannot save what is on it raises `Invalid(message, control)`, carrying the field the focus belongs in: the page is the one that knows which of its own controls is wrong, and `_refuse` selects that page and focuses that control without knowing what either holds. `Invalid` is the dialog's **one** failure type — its own checks raise it, `_commit` fills in the page number it was raised from and refuses in one place, and the four actions that have to save first all read `if not self._commit(): return`. A `ConfigError` from `Preset.validate()` becomes one, focusing the control named by `ConfigError.field`; the dialog used to pick that control by searching the error's *sentence* for the word "model". The RAG page is reachable only from here, since the retrieval settings are a preset's; the RAG menu holds the retrieval *actions*, and a second door into one page of this dialog would be a second place to keep working.

`config/parameters.py` holds the parameter schema, `SCHEMA`: one `Parameter(kind, description, range)` per name, where `kind` is the converter and so the single answer to "what type is this value" — `parse` uses it on a typed box and `checked` uses it on what came out of the file. Absent means *not sent*, which is why `options()` and `Client` exist as they do. The preset editor builds its controls from the table, so adding a parameter is an edit to it.

**The schema is never written to disk.** A preset stores `{name: value}` for the parameters it sets. It used to store a copy of the whole schema per preset, so every `settings.json` carried the description and range of every parameter, and three other things were shaped by that: `reconcile()` existed only to repair the drift between the two copies, the editor worked out a value's type from the shape of the last value saved, and it grew a checkbox branch for a boolean parameter the schema has never contained. A description belongs in the program that shows it.

`config/prompts.py` is the system-prompt library over `prompts.csv`, using stdlib `csv`. pandas is no longer a dependency. `_wide_fields()` raises csv's 131072-character field limit to `MAX_FIELD` for our own parsing and puts it back, since the limit is process-wide and the published collection has an entry of 140 KB; a download that still will not parse is a `VOLlamaError` rather than the `_csv.Error` traceback it used to be, since only the request was wrapped.

## Chat

`chat/client.py` builds one `Client` from the active preset on every request, over the `openai` library directly. Only names in `OPENAI_PARAMS` are forwarded, since they go out as top-level fields of the request and a name the server does not know raises rather than being ignored. `options` holds only what the preset actually set: an empty Temperature box has to mean *whatever the server would do on its own*, and sending a default of ours overrides that silently and fails outright on models that have deprecated the parameter.

This was llama_index's `OpenAILike` until it was not worth the four workarounds it needed. `to_openai_message_dict()` spread `additional_kwargs` into the outgoing message, so any key we invented went to the server as a field of it; `temperature` was a constructor field with a default of 0.1 rather than part of `additional_kwargs`, so an empty box still sent 0.1; its merge of the streamed tool-call fragments dropped the vendor fields on them; and a `VideoBlock` reached `raise ValueError(f"Unsupported content block type: ...")`, so attaching a video had never worked. What is asked of the layer is a request of our own messages with our own parameters and a stream read back, which is what the library below it does.

`chat/message.py` is the `Message` that replaced `ChatMessage`: a role, what was said, `extra` for whatever this layer needs to remember, and `images` as data URLs. `to_wire()` is a **whitelist** — the role, the content, an assistant's `tool_calls` and a tool result's `tool_call_id`, and nothing else — so nothing has to be stripped on the way out and a field of our own cannot leak into a request. A tool call is passed through as it arrived, vendor fields and all. `countable()` is the text of a message for the estimate, images left out: what a picture costs is the server's own arithmetic over it, and a base64 string counted as words is a much larger number that only looks like one. Video is not supported at all — Chat Completions has no video part type — and only the picture formats `sniff()` knows are offered in the file dialog.

`count()` and `count_messages()` are the local tokenizer's estimate, used only where the server reported no usage of its own. `ChatSession` keeps the messages the last request went out with (`self.sent`) so there is something to count.

`chat/streaming.py` is the only module that knows the shape of a streamed chunk. `usage_of()` also reads `prompt_tokens_details.cached_tokens`, which `TurnStats.prompt_rate()` subtracts: the server did not process a cached prompt this time, so counting it reports a cache hit as a speed. It is 0 wherever it is not sent — OpenAI fills it in, llama.cpp, Ollama and MLX leave the whole `prompt_tokens_details` out. Every chunk goes through `plain()` first: the library parses the fields it knows into a model and leaves the rest in its extras, so `model_dump()` is what puts a vendor field and a standard one on the same footing — and makes a dict in a test the same thing the reader sees at run time. `Calls` joins the tool-call fragments, which arrive spread over many chunks and interleaved, by the `index` they carry. That is also what keeps Gemini's thought signature: its thinking models sign every function call and carry the signature as `tool_calls[i].extra_content.google.thought_signature`, and a call sent back without it is refused with *Function call is missing a thought_signature*, killing every turn in which the model calls a tool. `Message.to_wire()` passes the call through untouched, so it reaches the wire.

`chat/conversation.py` holds two different things, which is the whole point of the module. `messages` is the entire chat and never loses anything — transcript, Save, alt+up. `outgoing()` is what goes on the wire and *is* allowed to leave things out:

- The summary is spliced in for everything before `summary_at`, as a `role="user"` message marked `extra={"summary": True}` — a model told it wrote the summary itself repeats it.
- Tool calls and results older than `KEEP_TOOL_TURNS` (1) are dropped, or every command's output is resent forever. A call and its result go together, since a call the server cannot match to a result makes the whole history unusable; an assistant message that only carried a call goes with them, one that also spoke keeps its text.
- `environment` (what the machine looks like) is added as a system message of its own after the preset's, and only when tools are on. `chat.toolset.environment()` is what decides that, in the module that owns the same gate for the tools themselves; it used to be a second reader of `settings.tools` living in `chat/client.py`, which is a module about requests and not about permissions. Left out of the compaction request, for the same reason that request drops the tool list.
- The model's own thinking never has to be dropped here. It is stored on the assistant message as `extra["reasoning"]` rather than folded into its content, so the transcript, Save and alt+up keep what the user watched arrive, and `to_wire()`'s whitelist leaves it behind: a reasoning model is meant to think again rather than be handed what it thought last time. `outgoing()` used to strip it by hand, because the serializer below would otherwise have sent it.

### Tool calling

Opt-in through `settings.tools` (default false), because small local models call tools badly and some endpoints ignore `tools` entirely. Global rather than a preset field: it answers "do I want the model touching this machine right now", which changes mid-chat.

**Two gates, not one, and both read in one module.** `chat/toolset.py` composes what a turn offers: the five machine tools when `settings.tools` is on, and `search` whenever an index is loaded. Search only reads an index the user built and asked to load, so putting it behind the same checkbox would mean turning on shell commands and file writes in order to ask a question about a book. The machine tools come first in the list, because their schemas never change and a server caching the prompt prefix should keep that cache when a document is indexed. `registry.find(name, extra)` looks in the turn's own tools before the five, which is how a tool the registry cannot know about — the index is above that layer — is called, described and checked for `free` through the same three functions. `rag/search.py` therefore hands out a schema and plain functions, and the `Tool` record is built in `toolset`, where both layers are in scope. `toolset.DESCRIBED` is the list a re-rendered transcript describes calls against, so a chat reopened with nothing loaded still words the searches it contains the way it did when they ran.

`ChatSession._converse` loops: stream a reply, run any tool calls, send the results back, up to `registry.MAX_TOOL_ROUNDS` (10) and `MAX_TOOL_CALLS` (40). Tools marked `free` (`poll`, `read`) do not spend a round — waiting on a build, or reading the files you are about to change, is not the progress the budget limits — and `MAX_TOOL_CALLS` is the ceiling free calls cannot slip past.

**Every tool call must get a matching tool message**, even one that is not run (round cap hit, user pressed stop). A dangling tool call makes the whole history unusable to the server.

A saved chat is `{"messages": [...]}` with `summary` and `summary_at` beside them when there is a summary. The summary is saved because it is **not** a cache of the messages: it is what the model wrote about them, and a chat compacted five times cannot be sent without one. Saving the messages alone meant reopening sent the whole history, got it refused, and bought a summary again from a different cut point. It is a field of the file rather than a message in the list because it stands in for messages that are all still there. `load_json` reads a bare list as the messages, which is what an older save is, and clamps `summary_at` into the list it was saved beside.

Anything that walks `conversation.messages` has to cope with tool rounds: `clear_last()` truncates from the last user message, `reviewable()` keeps alt+up off tool results and off the empty assistant message carrying a call, and `to_json`/`load_json` round-trip `extra` so `tool_call_id`s survive — under that name, its own: it was written out as `additional_kwargs` after the llama_index field this layer replaced, which left a key in the user's files named for a class the program no longer contains. A chat saved by an earlier build still loads and still reads; what it loses is the link from a call to its result, which `outgoing()` drops from every request but the turn in progress anyway.

There is **no confirm-before-run dialog**, for commands or for file writes. The Chat menu checkbox is the only gate on them; the trust boundary is stated once, at the top of `tools/registry.py`.

Because the checkbox is the only gate, switching it on asks first: `ChatWindow._agreed_to_tools` states that the model runs commands and rewrites files with no confirmation and no undo, and the two buttons are labelled with the answers ("I agree, and I am responsible for any damage" / "I disagree, leave tools off") rather than Yes and No, since a screen reader announcing "Yes" says nothing about what is being agreed to. No is the default, declining puts the checkbox back, and it is asked on every switch-on rather than once and remembered. Switching them off asks nothing.

### Compaction

A chat that outgrows the preset's `context_window` gets truncated by the server without anyone being told, so `_compact_if_full` runs after every completed turn: if the usage the server reported (or `client.count_messages` over what was sent, when it reports none) is at least `compaction.COMPACT_AT` (0.8) of the window, the model is asked for a handoff summary of itself.

The summary replaces nothing. It is held on the `Conversation` and spliced in by `outgoing()`, so the transcript, Save and alt+up keep the whole chat. `reset_context()` clears it wherever `messages` is replaced wholesale.

The summary request goes through a **client built without tools** rather than by taking the tools off a shared client and putting them back — a model left holding a tool list runs something instead of writing prose.

Three triggers, one path:

1. **Usage** — the threshold above.
2. **A refusal.** `ChatSession._send` wraps the request; `compaction.overflowed()` recognizes the rejection and it compacts and retries once. There is no standard wording, so `OVERFLOW` is a list of what servers actually send, ported from pi's `overflow.ts`. `NOT_OVERFLOW` is checked first, because a server that is rate limiting you can word it like an overflow — Bedrock's throttling message is "Too many tokens, please wait before trying again".
3. **A reply that ended early with no error.** `compaction.truncated()` covers a `finish_reason` of `length` with fewer tokens than `max_tokens` asked for, and an empty reply whose prompt filled 99% of the window, which is what a server that truncates an oversized prompt instead of refusing it produces. `_recover()` drops the truncated assistant message, compacts, and lets the loop send again — once per turn. The message stays in the transcript, because the user has already read it.

Two things make the retries work. `_start()` pulls the first chunk itself and re-attaches it with `itertools.chain`, because `stream_chat` is lazy and without this a rejection surfaces halfway through displaying a reply. It also returns the moment the request went out, since the turn's clock has to start there: the first chunk is in hand before anything reads the stream, so a clock started in `_stream` timed generation only and reported the prompt as processed instantly. And the overflow path compacts only up to `halfway()`, a user-message boundary about midway, because summarizing everything would send the server the same history it just refused; `halfway()` returns None when fewer than two of your messages remain, and the original server error is what propagates then.

Manual compaction is Edit > Compact Conversation (ctrl+shift+K).

## Tools

`tools/workspace.py` owns what a path means — `working_dir()`, `resolve()`, `checked()` for a file, `checked_directory()` for a folder — for both `shell` and `files`, which are peers and do not import each other. Every one of them goes through `resolve()`, so a relative path means the same thing in `run`'s `workdir` as in `read`'s `path`; it did not before, and two meanings for a relative path inside one toolset is a trap and not a feature. The Chat menu's Workspace item names it and changes it, greyed out while the tools are off. `settings.workdir` is validated on use rather than on being set, since a folder picked in an earlier session can be gone by the time a command runs in it. With nothing chosen — or with a chosen folder that has gone — the tools work in `default_dir()`, `~/VOLlama` through `expanduser`, which is the right folder on Windows and mac from one name. Not the current directory, which for a frozen build is wherever the launcher happened to start. `ensure_working_dir()` creates it, called when the tools are switched on and again at startup if they were left on, rather than at import: a session that runs no tools should not leave a folder behind, and a failure to create it is reported then rather than surfacing as a command that cannot run.

`tools/registry.py` composes the five `Tool` records, calls them, describes them for the transcript, and builds `environment()`. Every failure comes back as **text**, never an exception: the model is the one who reads it, and a raise would end the turn over a mistyped argument name.

### read, write and edit

`tools/files.py` exists for one reason: doing these through `run` means the file's own text has to survive a heredoc or a shell-quoted Python string literal first, which is where a small model fails *silently* — you get a file containing a literal `\n`, or one truncated at an unescaped quote, rather than an error. As a tool parameter the same text is one JSON string, escaped by the layer that is good at it. This is also why `run` takes a shell command and not Python source. That argument is strongest for `write` and `edit`; `read` is in for the paging (`MAX_LINES` 2000, `MAX_BYTES` 50 KB, with a `Use offset=N to continue.` footer).

The two questions these three ask along the way are modules of their own, because neither of them touches a file: **`tools/content.py`** answers whether content is text and what it is if not, whether it parses as the format its name implies, and whether it says the rest of the file goes here instead of containing it; **`tools/matching.py`** answers where an `old_text` goes and why it did not go anywhere. Both are pure functions over strings and bytes, which is where the interesting algorithms in this layer live — the fold, the anchored near-miss search, the naming of a difference — and they can now be read and tested without a disk. `files.py` is left with exactly one responsibility: reading, writing and editing a file, and the three tool contracts for doing so. `edit` plans through `_plan` (locate every edit against the *original*, or raise), then `_splice`, then `_report`, so the all-or-nothing guarantee is one function and not spread through a hundred lines.

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

A job that outlives its turn has no way to announce itself, since there is no path to inject a message into a finished turn. So `JobTable.notes()` collects jobs that ended unreported and `ChatSession` prepends them as a `role="user"` message marked `extra={"background": True}` — hermes' synthetic user turn. `to_wire()` sends none of `extra`, so the marker never reaches the server; `reviewable()` uses it to keep alt+up off the note and `ui.transcript` renders it as `Background:`. `kill_all()` runs on New Chat and on exit (bound to `EVT_CLOSE` as well as the menu item). Escape does not kill background jobs, since it also just exits edit mode.

It does kill a job still inside its yield window. `shell.cancellation` is a `Cancellation` the session points at its own stop flag **for the length of a turn** (a context manager, so a stop flag from a finished turn cannot answer for the next command). `wait_for()` checks it every `STOP_CHECK` seconds, since `Popen.wait` cannot be interrupted once it is in it. It is a module-level object rather than a parameter of `run` because the registry spreads the model's own arguments into the tool, and the model must not be able to declare itself unstoppable. `poll(wait=...)` uses the same helper but does not kill: giving up on the wait is not giving up on the job.

## RAG

`rag/documents.py` is the one place that knows what can be read: `DOCUMENT_EXTENSIONS` and `IMAGE_EXTENSIONS` (the file dialogs build their filters from them), `load()`, `read_files()`, and `fetch_page()`, which downloads the page once and tries three extractors over that HTML in order, logging each failure rather than swallowing it. How a wx filter is spelled is `ui/window.py`'s own business and used to be written down here, which put a presentation format in the layer furthest from presentation.

The three extractors are three calls — `MainContentExtractor.extract`, `trafilatura.extract`, `BeautifulSoup(...).get_text()` — and were llama_index's `MainContentExtractorReader`, `TrafilaturaWebReader` and `BeautifulSoupWebReader`, which are those same calls each wrapped in a class. Reaching them meant importing `llama_index.readers.web`, whose `__init__` imports all twenty-five of its readers eagerly, so a chat client that reads three kinds of web page depended on playwright, selenium, chromedriver, scrapy, newspaper and firecrawl. The build scripts uninstalled playwright and selenium to keep the package down, which broke that `__init__` until the file was edited by hand again, and the next dependency install undid the edit. Owning the three calls removes the dependency, the uninstall step and the hand-edit together. `BeautifulSoupWebReader` also carried a table of four per-domain scrapers that crawl every linked page of a documentation site; it is keyed on the exact hostname, so it never fired on the `project.readthedocs.io` and `blog.substack.com` addresses anyone actually has, and crawling a whole site is not what attaching a page means.

`_download()` is the only function here that reaches the network, which is what makes the extractors testable without it. It sends a browser `User-Agent`, since a bare python-requests one is refused outright by many sites and each of the three readers sent one of its own, and it falls back to `apparent_encoding` when the response declares no charset — `requests` would otherwise call it ISO-8859-1 and mangle every page not written in Latin-1.

`rag/index.py` confines llama_index's process-wide `Settings` global: the embedding model, chunk sizes and context window are set here, where they are used, and no chat model is resolved here at all. `prompt()` retrieves through `retrieve()` — `as_retriever`, then the cutoff — and formats the chunks and the question into `PROMPT`, llama_index's own default QA wording, which is what these models have been tuned against. **There is no query engine and no response synthesizer.** llama_index builds a synthesizer *without* the llm it was handed, so it falls back to the process-wide global, which resolves to OpenAI and raises "No API key found for OpenAI" however the preset is set up; and it yields bare strings, so a retrieval turn lost the model's reasoning, the usage numbers and the finish reason. Assembling the prompt here instead lets `ChatSession._answer_from_index` send it through the ordinary streaming path, which keeps all three. `header()` labels each chunk with its number, where it came from and its similarity score, and `context()` puts that line above the chunk's own text. Both numbers matter to the model: the source is how it can say where an answer came from, and the score is how it can say it is unsure of a distant passage rather than reading every chunk as equally true. It replaced `MetadataMode.LLM`, which renders whichever metadata llama_index kept — `file_path` for a file, `file_name` for a page indexed by URL, since the two readers record it under different keys — and has no idea there is a score at all. `describe_sources()` writes the same header for Show Context, over text with its whitespace collapsed, so the user is shown the passages the way the model was. `sources()` hands back what the last prompt was built from. Retrieving needs no model at all. Embedding is batched (`BATCH` 32) instead of one request per chunk. The embedding endpoint (`embedding_base_url` / `embedding_api_key` / `embedding_model`, default `EmbeddingGemma`) and the retrieval settings are the active preset's, read through `presets.retrieval()`. What protects an index from being re-embedded with another model is *when* they are read, not where they live: `_configure()` runs only in `RagIndex.__init__`, so switching preset mid-chat changes what the *next* index is built with and leaves `Settings.embed_model` pointing at whatever this one was built with. Top K and the cutoff are read live in `retrieve()`, which is safe because they are arithmetic over vectors that are already stored.

The retrieval prompt goes out on its own, and only the question is kept in the history: the chunks belong to that one question and resending them with every later message would fill the window with them. Nothing packs them to fit any more — the synthesizer used to — so `_check_fits` counts the prompt with `client.count` before sending and refuses one that cannot fit, naming Top K, the chunk size and the context window as the three things to change. That count is a local tokenizer's estimate rather than the server's, so the headroom is generous; the point is to name the cause, not to fill the window to the token. A server that truncates an oversized prompt instead of refusing it answers with nothing and no error, so an empty retrieval reply is explained with the same wording. Compaction does not run after a retrieval turn: what filled the window was the chunks, which were never in the history and will not be in the next request either.

### Retrieval as a tool

`rag/search.py` is the same retrieval offered to the model as a `search` tool, so a question about an indexed document does not have to be prefixed with `/q`. It is offered **whenever an index is loaded**, and not gated on `settings.tools`: it reads documents the user chose and loaded, and nothing else. `/q` stays for the model that calls tools badly and the endpoint that ignores `tools` — without it those have no retrieval at all. RAG > Clear Index (`ChatSession.clear_index`) is how it is turned back off, and the only way: New Chat deliberately keeps the index, so without it retrieval could be started and never stopped. The item is never greyed out — a disabled menu item is one a screen reader reads past without saying why — and answers "Nothing has been indexed yet." instead.

The call **blocks** until the passages are in the result. There is nothing here like the shell's background jobs, and nothing to poll: a tool that returned "searching" would just be a round spent saying so.

- The tool's only parameter is `query`. How many passages come back and how close they have to be are Top K and the similarity cutoff on the preset's RAG page — the user's, not the model's to widen mid-answer, which is why the wording for nothing found says so rather than inviting a retry with a bigger number.
- The description carries the indexed file names, capped at `MAX_FILES` (30), so the model can tell whether the answer is likely to be in there before spending a call. `RagIndex.filenames()` walks the docstore, because that is what knows what is in the index; a reader that cannot name its documents is still searchable.
- `free`, like `read`: looking something up is not the progress the round budget limits.
- `MAX_RESULT` (20,000 characters) with `trim()` cutting on a passage boundary and saying where, rather than a token count — the tokenizer lives in the chat layer above.
- Every failure comes back as text, the same rule as `tools/registry.py`.
- The chunks reach the window and then leave it: `outgoing()` drops tool results older than `KEEP_TOOL_TURNS`, which does for a search what sending the retrieval prompt on its own does for `/q`.
- Show Context reports the sources of a search the model asked for, since that is the retrieval the user has least other way of seeing. It is `settings.show_context`, a checkbox on the RAG menu rather than a preset field: it answers "do I want to see the passages right now", which changes mid-chat and says nothing about which server is in use, and it belongs beside the retrieval it describes.

`RagIndex.search()` is `prompt()` without the wording around it: a tool result is context handed to a model that asked for it itself, so there is nothing left to instruct it to do with it. Nothing found is `""` rather than an exception, because the tool has to answer the model in words.

## Accessibility

- Every control gets an accessible name; two buttons with the same label get different ones (the preset manager's two "Choose..." buttons, and its preset button, which keeps the toolbar's accessible name because it is the same control).
- **A label is created before the control it names.** A screen reader on Windows pairs a field with the static text created before it, not with the one the sizer puts to its left, so a control passed into a row helper already built is announced with the label of the row *above* — the Base URL box read as "Name". This is why `labelled()` — the one helper both `ConnectionPage` and `RetrievalPage` add their fields through — takes something that *builds* the control rather than the control.
- Focus follows the value that changed, not the button that changed it, so a screen reader announces the new value.
- **Native controls, not composite ones.** `wx.SpinCtrlDouble` is the generic implementation on every platform: a container holding a `wx.TextCtrl` and a `wx.SpinButton`. `SetName` names the container while focus lands on the text control inside, so the field is announced without its label, and naming the inner control too does not fix it. `wx.SpinCtrl` is native and is itself the window that takes focus, which is why the similarity cutoff on the RAG page is a plain `wx.TextCtrl` that `RetrievalPage._cutoff()` parses on save: the parsing is cheaper than a field with no name.
- Keyboard-only navigation throughout, with shortcuts declared once on the menu item; toolbar buttons raise that same item's event.
- Audio feedback (`send.wav` / `receive.wav`) for state changes.
- Platform-native TTS, plus a screen-reader output that speaks in the user's own voice and rate. The backends expose `speak`, `stop`, `voices()`, `voice`, `rate` and **open no dialogs and save nothing**; `ui/speech_dialog.py` asks, `speech.create()` applies what was stored last time, and `speech.remember()` applies and stores a new choice. Persisting it used to be inside each backend's own property setters, twice over and with two different answers to a voice the platform refuses — mac saved only what it accepted, sapi saved first and could store a voice it then failed to find. A backend drives the device and nothing else, and `sapi.py` and `mac.py` import nothing from `config`.
- Voices go into a submenu per **language**, not a list and not a tree of identifiers: macOS offers well over a hundred. `speech.voices()` returns `Voice` records (identifier, name, language) rather than identifier strings, because a macOS identifier is neither the voice's name nor searchable — the one Siri voice the system lends to third-party apps is `com.apple.ttsbundle.gryphon-neuralAX_Nora_en-US_premium` and is called "Voice 4". Grouping by identifier namespace sorted voices by *engine* (`eloquence`, `voice.compact`, `speech.synthesis.voice`), so nine Korean voices landed in three places, two of them levels deep behind words naming an implementation detail. `speech.group()` buckets by language and the dialog only turns that into menus; `Voice.within()` drops a name's redundant locale suffix ("Eddy (Korean (South Korea))"), and `Voice.describe()` writes the button's label. A screen reader announces how many items are in the level you are in, which a flat list of a hundred cannot.
- Only the `neuralAX` build of a Siri voice is published to `NSSpeechSynthesizer`, so a Korean Siri voice installed as `ko_KR.minji.gryphon.premium` is offered by no public API — not `availableVoices()`, not `AVSpeechSynthesisVoice`, not `say -v '?'`. Nothing to fix here; don't add a fallback for it.
- `voice` and `rate` stay plain values on the backends. `settings.voice` holds the platform identifier, which is why `described()` keeps a whole SAPI description as the identifier while splitting a name and language out of it for display. Empty means the voice the system would use on its own; the backends that have no voices to offer keep `voice` and `rate` as plain attributes rather than read-only properties, so `create()` does not have to ask which backend it is holding.

New UI components must keep to all of this.

## Conventions

- Comments explain *why*. A comment restating the code is worse than none.
- One canonical implementation per responsibility; no compatibility shims, no migration paths, no version branching.
- `snake_case` throughout, in the settings file as well as in the code: there is no name here fixed by a format, and `speakResponse` and `additional_kwargs` were the last two.
- Domain code raises `VOLlamaError` subclasses with messages written for the user; the UI shows the message and logs the traceback. Tools return their errors as text, because that text is what the model acts on.
- Add a test with the behaviour. `chat`, `config` and `tools` are all testable without a window; if something is not, that is a sign it is in the wrong layer.
