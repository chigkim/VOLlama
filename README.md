# VOLlama

Accessible Chat Client for OpenAI-Compatible LLM Servers

## Usage

VOLlama talks to any server that speaks the OpenAI API: Ollama, llama.cpp, LM Studio, vLLM, OpenAI, Gemini, OpenRouter, and so on. You describe each server with a **preset** that holds its base URL, API key, model, system prompt, and generation parameters.

If you want to run models locally, download and install [Ollama](https://ollama.ai/), then pull a model. Replace `gemma4:e4b-it-qat` if you prefer a [different model](https://ollama.ai/library).
```
ollama pull gemma4:e4b-it-qat
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

* **Connection**: name, base URL, API key, model, and context window.
* **Parameters**: generation parameters for this preset (see the table below).
* **System Prompt**: this preset's system prompt, plus a shared library of saved prompts you can store, reuse, and download from Awesome ChatGPT Prompts. Choosing a saved prompt copies it into the box below; press Enter on the one already highlighted to copy it again after editing the box.

Nothing is saved until you press OK, so Cancel discards every change including new presets, deletions, parameters and prompts. The preset the button is showing when you press OK becomes the active one.

* The "Choose..." button next to Base URL fills the field in with one of the predefined URLs, so you do not have to type it from memory. Any other OpenAI-compatible URL, just type it.
* The "Choose..." next to Model asks that server for its model list and fills in the model field. Servers that do not publish a model list still work, just type the model name.

API keys are encrypted before they are written to disk. Leave the key empty for local servers that do not need one.

## Tools

The Tools checkbox in the Chat menu lets the model read, write and edit files and run commands on your computer. It is off by default and stays where you left it between sessions.

**Commands run and files change without asking you first.** There is no confirmation prompt and no undo. Only turn it on for a model you trust; small local models often call tools badly.

Workspace in the chat menu is the folder the model works in.The default is `VOLlama` in your home folder unless you pick another. It is created when you turn tools on, remembered between sessions, and falls back to the default if it is gone the next time you start.

The workspace is a starting point rather than a sandbox. The model can run a command elsewhere and write outside it.

Escape stops the reply, and stops a command still running in the foreground.

## Shortcuts

Shortcuts for all the features can be found in the menu bar. Here are exceptions:

* Shift+Enter: Insert a new line.
* Escape can be used to Stop, focus to the prompt, and exit the edit mode.

## Image Description

In order to ask a multimodal model questions about an image:

1. Switch to a preset using a multimodal model (control+p.)
2. Attach an image file from the chat menu (or control+i.)
3. Type your question like "Can you describe the image?" on the prompt field and send it.

## Generation Parameter Values

These parameters are sent to the server as OpenAI API options. All of them start empty, and an empty field is not sent at all, so the model uses its own default.

| Parameter | Description | Value Type |
|---------------------|-----------------------------------------------------------------------------------------------------|------------|
| max_tokens | Maximum number of tokens to generate in the response. | int |
| temperature | Adjusts the model's creativity. Higher values lead to more creative responses. Range: 0.0-2.0. | float |
| top_p | Nucleus sampling. Higher values lead to more diverse text, lower values to more focused text. Range: 0.0-1.0. | float |
| presence_penalty | Penalizes new tokens based on their presence so far. Range: -2.0-2.0. | float |
| frequency_penalty | Penalizes new tokens based on their frequency so far. Range: -2.0-2.0. | float |
| stop | Triggers the model to stop generating text when this pattern is encountered. List strings separated by ", ". | string Array |
| seed | Sets the random number seed for generation. Specific numbers ensure reproducibility. | int |
| reasoning_effort | Sets the reasoning effort: none, low, medium, or high. Ignored by models without reasoning. | string |

The context window is not a generation parameter. It sits on the Connection tab of the preset editor, next to the model, because it describes what that model on that server can hold. It is never sent: VOLlama uses it to decide when to compact the conversation, and RAG uses it to work out how many retrieved chunks fit in one prompt.

## Compacting

A long chat eventually stops fitting in the model's context window. When that happens the server either refuses the message or quietly drops the oldest part of the chat, and the model forgets how the conversation started without telling you.

So when a reply uses more than 80 percent of the context window, VOLlama asks the model to summarize the conversation for a copy of itself that will never see the original, and the summary takes the place of everything before it in what gets sent from then on. The chat window says `Compacted:` on the line where it happened. You can also do it at any time from the Edit menu, or with control+shift+K.

If the server refuses a message because the chat is too long, VOLlama compacts and sends it again. Nothing is deleted. The whole chat stays in the window, saves in full, and you can use alt+up to walk back through all the  previous messages. Only what is sent to the model changes. Saving keeps the summary, so a chat you reopen carries on from where it was compacted.

Starting a new chat, or clearing the last message, throws the summary away.

## [Retrieval-Augmented Generation](https://blogs.nvidia.com/blog/what-is-retrieval-augmented-generation/)

To retrieve a document and ask questions about it, follow these steps:

1. Go to Rag menu > index a URL and enter `https://bbc.com/`.
  * You can also index a folder with documents in it, including all subfolders. It will index all accessible documents, such as PDFs, TXT files, and docs.
2. Wait until the document is indexed.
3. In the message field, type `/q What are some positive news for today?` without the quotes. Prefacing your message with `/q` triggers processing your prompt with RAG.
4. You can also just ask your question normally when using a model with toolcall support. While an index is loaded, the model is given a search tool, and it can decide when to look something up. This works whether or not Tools is checked in the Chat menu. That setting covers running commands and editing files on your machine, not searching documents you indexed yourself. `/q` remains for models that ignore tools or call them badly.

Note: RAG retrieves only snippets of text relevant to your question, not full summaries. If you want to see the retrieved context, turn on Show Context on the Rag menu.

## Rag Settings

This section describes the parameters related to the Retrieval-Augmented Generation (RAG) feature. They also belong to a preset, on the RAG page of the Preset Manager.

| Parameter | Description | Value Type |
|---------------------|-----------------------------------------------------------------------------------------------------|------------|
| embedding_base_url | Base URL of the OpenAI-compatible server used for embeddings. | string |
| embedding_api_key | API key for the embedding server. Empty for local servers. | string |
| embedding_model | Model used to embed documents and questions. | string |
| chunk_size | Determines the size of text chunks for indexing. | int |
| chunk_overlap | Specifies the overlap between the start and end of each chunk. | int |
| similarity_top_k | Number of the most relevant chunks fed to the model. | int |
| similarity_cutoff | The threshold for filtering out less relevant chunks. Setting too high may exclude all chunks. | float |

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

## Run from Source

VOLlama uses [uv](https://docs.astral.sh/uv/), which is the only thing you need installed. It fetches the right Python and every dependency itself.

```
git clone https://github.com/chigkim/VOLlama
cd VOLlama
uv run vollama
```

The first run creates the environment and takes a minute; after that it starts faster.

## Build from Source

Building runs PyInstaller inside the environment, so this is the one place the environment is created up front and activated:

### Windows

```
uv sync
.venv\Scripts\activate
build
```

### Mac

```
uv sync
source .venv/bin/activate
./build.sh
```

You will find the app inside `dist` folder.

### Building your own bootloader

The bootloader is the small executable PyInstaller puts at the front of a packaged app to start it. The publicshed pip package can sometimes trigger false positive as a malware.

To build, you need Visual Studio Build Tools on Windows.

```
.venv\Scripts\activate
build-pyinstaller
build
```

`build-pyinstaller` clones PyInstaller, compiles the bootloader with waf, and installs that build over the published one in `.venv`. Running `uv sync` replaces with the published version on pip, so re-run the script after a sync.
