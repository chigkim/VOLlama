# VOLlama

Accessible Chat Client for OpenAI-Compatible LLM Servers

[Download the latest release](https://github.com/chigkim/VOLlama/releases/)

## Instructions

VOLlama talks to any server that speaks the OpenAI API: Ollama, llama.cpp, LM Studio, vLLM, OpenAI, Gemini, OpenRouter, and so on. You describe each server with a **preset** that holds its base URL, API key, model, system prompt, and generation parameters. Switching "provider" is just switching preset.

If you want to run models locally, download and install [Ollama](https://ollama.ai/), then pull a model. Replace `gemma3:4b-it-qat` if you prefer a [different model](https://ollama.ai/library).
```
ollama pull gemma3:4b-it-qat
```

Optionally, if you want to utilize the retrieval-augmented generation feature, you need an embedding model.
```
ollama pull embeddinggemma
```

Finally, [download the latest](https://github.com/chigkim/VOLlama/releases/) and run VOLlama.

For Mac, VOLlama is not notarized by Apple, so you need to allow to run in system settings > privacy and security.

VOLlama may take a while to load especially on Mac, so be patient. You'll eventually hear "VOLlama is starting."

If you want responses to be read aloud automatically, you can enable the "Speak Response with System Voice" option from the chat menu.

## Presets

On first launch VOLlama asks you to create a preset. After that, press control+p to open the preset menu. It lists your presets, so switching to one is a single keystroke, and it has one other item: Preset Manager. The toolbar button shows the active preset, which is remembered between sessions.

The Preset Manager is where presets are created, edited, copied and deleted. At the top is the same preset button the toolbar has: its menu lists your presets, and below them New, Duplicate and Delete. Under the button are three tabs, editing whichever preset the button names:

* **Connection**: name, base URL, API key, model, and context window. The "Choose..." next to Base URL fills in a server VOLlama knows about; the one next to Model asks that server for its model list and fills in the model field. Servers that do not publish a model list still work, just type the model name.
* **Parameters**: generation parameters for this preset (see the table below).
* **System Prompt**: this preset's system prompt, plus a shared library of saved prompts you can store, reuse, and download from Awesome ChatGPT Prompts. Choosing a saved prompt copies it into the box below; press Enter on the one already highlighted to copy it again after editing the box.

Nothing is saved until you press OK, so Cancel discards every change including new presets, deletions, parameters and prompts. The preset the button is showing when you press OK becomes the active one.

The **Choose...** button next to Base URL fills the field in with one of these, so you do not
have to type it from memory. Any other OpenAI-compatible URL still works, just type it.

| Server | Base URL |
|---|---|
| OpenAI | `https://api.openai.com/v1/` |
| Anthropic | `https://api.anthropic.com/v1/` |
| Google | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| OpenRouter | `https://openrouter.ai/api/v1/` |
| Ollama | `http://localhost:11434/v1/` |
| llama.cpp | `http://localhost:8080/v1/` |
| OMLX | `http://localhost:8000/v1/` |

API keys are encrypted before they are written to disk. Leave the key empty for local servers that do not need one.

## Running Commands

VOLlama can give the model tools that run commands on your computer and read and change
files there. The `run` tool takes a shell command, the same thing you would type in a
terminal, and the model is told which shell it is getting: `cmd` on Windows, `sh` on Mac and
Linux. For anything longer than a line of Python it writes a script file and runs that.
Turn all of it on with the Tools checkbox in the Chat menu.
It is off by default, and it applies to every preset, so switching preset does not turn it
back on or off. It stays where you left it between sessions.

When it is on, the chat shows each call as two lines, both trimmed to 200 characters:

```
Tool: print(6 * 7)
Result: 42
```

Commands run in the folder shown next to **CD** in the Chat menu, which starts as the folder
VOLlama was started in. Choose that menu item to pick a different one, and relative paths in
the model's code follow it. It is remembered between sessions, and if the folder is gone the
next time you start, commands fall back to the folder VOLlama was started in rather than
failing. The model can still run a single command somewhere else without changing this.

While the checkbox is on, the model is also told a few things about your machine that it
would otherwise have to run a command to find out, or would simply guess wrong: the working
directory, your platform and Windows or macOS version, the Python that runs its code and where
that Python is, and today's date. None of this is sent when the checkbox is off.

The code runs in a separate Python process. Its standard output and standard error both
come back to the model as the result, along with the exit code when it is not zero. The
model gets at most 10 rounds of tool calls per message before VOLlama stops and tells it so.
Long output keeps its start and its end, with a line in the middle saying how much was
dropped.

### Reading and writing files

Three more tools come with the same checkbox: `read`, `write` and `edit`. The model could do
all three by writing Python, and that is the problem. Doing it that way means putting the
file's own text inside a Python string, quotes and backslashes and all, and when a model gets
that wrong it does not fail: it writes a file with a literal `\n` in it. As a tool the same
text is sent as plain data, so nothing has to be escaped twice.

`read` returns a text file as it is, with no line numbers added, up to 2000 lines at a time.
When there is more, the last line tells the model which line to ask for next. A line longer
than 2000 characters is cut off and marked, so one minified file cannot fill the model's
context. It refuses files that are not valid UTF-8 rather than mangling them, and names a
binary one it will not read: `is not text: PNG image, 4.9 KB` rather than "binary file".

`write` creates a file, making any missing folders, or replaces one whole. Python, JSON,
YAML and TOML are parsed first, and only a mistake the write would *add* is reported, so a file
that is already broken can still be fixed. A JSON, YAML or TOML file that does not parse is
refused rather than written, because a broken one breaks whatever reads it somewhere else
entirely; a Python file is written with a warning.

`edit` replaces exact pieces of a file, and is the one worth having. The model sends the old
text and the new text, and the old text has to appear exactly once, unless the model says it
means every occurrence. **Every edit in a call is
checked before any of them is written**, so if one piece is missing, or matches three places,
or two edits overlap, nothing is written at all and the model is told which one and why. A
model doing the same thing in Python would have already saved the file before finding out its
match was ambiguous. When the edit succeeds the model gets a diff of what changed, so it can
see it changed the right place.

When a piece is missing, the model is shown the lines in the file that came closest to it rather
than just told it was not found, and when the difference is whitespace alone, both are printed
with tabs and spaces made visible. An edit whose new text is the same as its old text is refused
by name, rather than counted as a success that changed nothing.

Files keep the line endings they already had, so editing a Windows file does not quietly
convert it. New files are written with Unix line endings. Reading does not count against the
round limit, since looking at a file before changing it is not the kind of thing that limit is
there to stop.

A command that is still running after 10 seconds is not killed. It keeps going in the
background and the model gets a session id like `exec_1` instead of a result, so a build or
a test run does not have to fit inside one tool call. The model reads it with a second tool,
`poll`, which returns whatever the command has printed since the last look. Polling does not
count against the round limit, or waiting for a long job would use up the whole
budget. The model can also use `poll` to stop a command or to list everything still running.

A background command is killed after 5 minutes in total unless the model asked for a
different limit, and at most 8 run at once: starting a ninth kills the oldest. Commands that
outlive the message they started in keep going, and the next message you send tells the
model how they ended, with any output you have not seen yet. Starting a new chat or quitting
VOLlama kills them all.

Escape stops the reply, and stops a command that is still in its first ten seconds, before it
has gone to the background: the model is told it was stopped and gets whatever the command
printed before it died. Once a command is in the background Escape leaves it alone, since by
then it belongs to the session rather than to the message that started it, and Escape is also
how you leave the edit box. Use New Chat, or ask the model to stop it, to get rid of those.

Only the message you are on keeps its tool calls. Once you send the next message, the calls
and their output from earlier messages stop being sent to the model, so a few chatty commands
do not fill up its context. What the model said around them stays, and the chat window still
shows everything. The same applies to a file the model read, so it may read a file again in a
later message rather than working from what it saw before, which is the safe thing to do
anyway if you have been editing.

Every call is a fresh shell, so nothing carries over between calls: not a `cd`, not a
variable, not an export. The model is told to chain related steps into one command instead,
to pass a directory to run in rather than starting with `cd`, and to run a virtual
environment's interpreter by path rather than activating it, since activation would not
survive the call. Nothing can answer an interactive prompt either, so it is told to pass the
flag that skips one. The tool description covers all of this, written for the shell your
computer actually has.

**Code runs and files are changed without asking you first.** There is no confirmation
prompt for any of it, so only turn this on for a model and a server you trust. Small local models often call tools badly, and
some servers ignore the tool list entirely, in which case the model just answers normally.

## Shortcuts

Shortcuts for all the features can be found in the menu bar. Here are exceptions:

* Shift+Enter: Insert a new line.
* Alt(Option on Mac)+up/down: review/edit previous/next message
* Escape can be used to Stop, focus to the prompt, and exit the edit mode.

## Image Description

In order to ask a multimodal model questions about an image:

1. Switch to a preset using a multimodal model (control+p.)
2. Attach an image file from the chat menu (or control+i.)
3. Type your question like "Can you describe the image?" on the prompt field and send it.

## Generation Parameter Values

These parameters are sent to the server as OpenAI API options. Leave a field empty to let the model use its own default.

| Parameter | Description | Value Type | Default Value |
|---------------------|-----------------------------------------------------------------------------------------------------|------------|---------------|
| max_tokens | Maximum number of tokens to generate in the response. | int | empty |
| temperature | Adjusts the model's creativity. Higher values lead to more creative responses. Range: 0.0-2.0. | float | empty |
| top_p | Nucleus sampling. Higher values lead to more diverse text, lower values to more focused text. Range: 0.0-1.0. | float | empty |
| presence_penalty | Penalizes new tokens based on their presence so far. Range: -2.0-2.0. | float | empty |
| frequency_penalty | Penalizes new tokens based on their frequency so far. Range: -2.0-2.0. | float | empty |
| stop | Triggers the model to stop generating text when this pattern is encountered. List strings separated by ", ". | string Array | empty |
| seed | Sets the random number seed for generation. Specific numbers ensure reproducibility. | int | empty |
| reasoning_effort | Sets the reasoning effort: none, low, medium, or high. Ignored by models without reasoning. | string | empty |

The context window is not a generation parameter. It sits on the Connection tab of the preset
editor, next to the model, because it describes what that model on that server can hold. It is
never sent: VOLlama uses it to decide when to compact the conversation, and RAG uses it to work
out how many retrieved chunks fit in one prompt.

## Compacting

A long chat eventually stops fitting in the model's context window. When that happens the server
either refuses the message or quietly drops the oldest part of the chat, and the model forgets
how the conversation started without telling you.

So when a reply uses more than 80 percent of the context window, VOLlama asks the model to
summarize the conversation for a copy of itself that will never see the original, and the summary
takes the place of everything before it in what gets sent from then on. The chat window says
`Compacted:` on the line where it happened. You can also do it at any time from the Edit menu, or
with control+shift+K.

Nothing is deleted. The whole chat stays in the window, saves in full, and alt+up still walks back
through every message you sent. Only what is sent to the model changes. A new chat, opening a
saved chat, or clearing the last message throws the summary away.

If the server refuses a message because the chat is too long, VOLlama compacts and sends it
again, once. In that case it summarizes only about half the chat, not all of it, because a summary
request covering the whole chat would carry the same history the server just turned down. Nothing
appears in the chat window until the retry succeeds. If the second attempt fails too, you get the
server's original error.

Not every server reports this as an error. Some accept a chat that is too long, quietly cut the
start off it, and then have no room left to answer, so the reply comes back empty or stops in the
middle of a sentence with nothing to say why. When a reply ends early like that, VOLlama says
`Cut short:` in the chat window, compacts, and asks again, also once. The half reply stays on
screen, since you have already read it, but the model is not given it.

How well this works depends on the model. Set the context window on the preset to what your
server is actually running: too high and the server truncates before VOLlama ever compacts, too
low and it compacts more often than it needs to.

## [Retrieval-Augmented Generation](https://blogs.nvidia.com/blog/what-is-retrieval-augmented-generation/)

To retrieve a document and ask questions about it, follow these steps:

Note: It retrieves only snippets of text relevant to your question, so full summaries are not available.

1. Go to Rag menu > index a URL.
2. Enter `https://bbc.com/`.
3. Wait until the document is indexed.
4. In the message field, type `/q What are some positive news for today?` without the quotes. Prefacing your message with `/q` triggers processing your prompt with RAG using LlamaIndex.
5. You can also index a folder with documents in it, including all subfolders. It will index all accessible documents, such as PDFs, TXT files, and DOCs.
6. You can also just ask your question normally. While an index is loaded, the model is given a search tool listing the indexed file names, and it decides for itself when to look something up. This works whether or not Tools is checked in the Chat menu — that setting covers running commands and editing files on your machine, not searching documents you indexed yourself. `/q` remains for models that ignore tools or call them badly.

## Rag Settings

This section describes the parameters related to the Retrieval-Augmented Generation (RAG) feature. They belong to a preset, on the RAG page of the Preset Manager (control+P): a preset is a server, and the server running your chat model is usually the one running the embedding model. Switching preset does not re-embed an index you have already built; it changes what the next one is built with.

Whether the retrieved chunks are printed with the answer is not a preset setting. It is Show Context, on the Rag menu, since it is a question about what you want to see right now rather than about a server.

| Parameter | Description | Value Type | Default Value |
|---------------------|-----------------------------------------------------------------------------------------------------|------------|---------------|
| chunk_size | Determines the size of text chunks for indexing. | int | 1024 |
| chunk_overlap | Specifies the overlap between the start and end of each chunk. | int | 20 |
| similarity_top_k | Number of the most relevant chunks fed to the model. | int | 2 |
| similarity_cutoff | The threshold for filtering out less relevant chunks. Setting too high may exclude all chunks. | float | 0.0 |
| embedding_base_url | Base URL of the OpenAI-compatible server used for embeddings. | string | http://localhost:11434/v1/ |
| embedding_api_key | API key for the embedding server. Empty for local servers. | string | empty |
| embedding_model | Model used to embed documents and questions. | string | EmbeddingGemma |

## Docker (Optional)

If you prefer to run Ollama using Docker, follow the instructions below:

Install Ollama by executing the following command in the command line:
```
docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
```

Download a model to generate text. Replace `gemma3:4b-it-qat` with your desired model if you wish to use a [different model](https://ollama.ai/library):
```
docker exec ollama ollama pull gemma3:4b-it-qat
```

Optionally, If you wish to use the retrieval-augmented generation feature, download an embedding model:
```
docker exec ollama ollama pull embeddinggemma
```

To stop Ollama, use the following command:
```
docker stop ollama
```

To restart Ollama, use the command below:
```
docker start ollama
```
## Build from Source

### Windows

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
build-pyinstaller
build
```

### Mac

Make sure to use Python 3.12.

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./build.sh
```
