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

On first launch VOLlama asks you to create a preset. After that, press control+p to open the preset menu, where you can switch presets or choose New, Edit, Duplicate, or Delete. The toolbar button shows the active preset, which is remembered between sessions.

The preset editor has three tabs:

* **Connection**: name, base URL, API key, and model. "Choose..." asks the server for its model list and fills in the model field. Servers that do not publish a model list still work, just type the model name.
* **Parameters**: generation parameters for this preset (see the table below).
* **System Prompt**: this preset's system prompt, plus a shared library of saved prompts you can store, reuse, and download from Awesome ChatGPT Prompts.

Nothing is saved until you press OK, so Cancel discards every change including parameters and prompts.

Example base URLs:

| Server | Base URL |
|---|---|
| Ollama | `http://localhost:11434/v1/` |
| llama.cpp / LM Studio | `http://localhost:8080/v1/` |
| OpenAI | `https://api.openai.com/v1/` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` |

API keys are encrypted before they are written to disk. Leave the key empty for local servers that do not need one.

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

The context window is not a generation parameter and is not part of a preset. It is a global setting in Rag Settings, because RAG is the only thing that uses it.

## [Retrieval-Augmented Generation](https://blogs.nvidia.com/blog/what-is-retrieval-augmented-generation/)

To retrieve a document and ask questions about it, follow these steps:

Note: It retrieves only snippets of text relevant to your question, so full summaries are not available.

1. Go to Rag menu > index a URL.
2. Enter `https://bbc.com/`.
3. Wait until the document is indexed.
4. In the message field, type `/q What are some positive news for today?` without the quotes. Prefacing your message with `/q` triggers processing your prompt with RAG using LlamaIndex.
5. You can also index a folder with documents in it, including all subfolders. It will index all accessible documents, such as PDFs, TXT files, and DOCs.

## Rag Settings

This section describes the parameters related to the Retrieval-Augmented Generation (RAG) feature. The embedding settings are global, so RAG can use a different server than your chat preset.

| Parameter | Description | Value Type | Default Value |
|---------------------|-----------------------------------------------------------------------------------------------------|------------|---------------|
| show_context | When enabled, displays the text chunks sent to the model. | bool | False |
| chunk_size | Determines the size of text chunks for indexing. | int | 1024 |
| chunk_overlap | Specifies the overlap between the start and end of each chunk. | int | 20 |
| similarity_top_k | Number of the most relevant chunks fed to the model. | int | 2 |
| similarity_cutoff | The threshold for filtering out less relevant chunks. Setting too high may exclude all chunks. | float | 0.0 |
| response_mode | Determines how RAG synthesizes responses. | string | compact |
| context_window | How many tokens the model can hold. Match what your server is running. Not sent to the server; used to decide how many retrieved chunks fit in one prompt. | int | 8192 |
| embedding_base_url | Base URL of the OpenAI-compatible server used for embeddings. | string | http://localhost:11434/v1/ |
| embedding_api_key | API key for the embedding server. Empty for local servers. | string | empty |
| embedding_model | Model used to embed documents and questions. | string | EmbeddingGemma |

## response modes

* refine: create and refine an answer by sequentially going through each retrieved text chunk. This makes a separate LLM call per retrieved chunk. Good for more detailed answers.
* compact (default): similar to refine but compact the chunks beforehand, resulting in less LLM calls.
* tree_summarize: Query the LLM using the summary_template prompt as many times as needed so that all concatenated chunks have been queried, resulting in as many answers that are themselves recursively used as chunks in a tree_summarize LLM call and so on, until there?s only one chunk left, and thus only one final answer.
* simple_summarize: Truncates all text chunks to fit into a single LLM prompt. Good for quick summarization purposes, but may lose detail due to truncation.
* accumulate: Given a set of text chunks and the query, apply the query to each text chunk while accumulating the responses into an array. Returns a concatenated string of all responses. Good for when you need to run the same query separately against each text chunk.
* compact_accumulate: The same as accumulate, but will ?compact? each LLM prompt similar to compact, and run the same query against each text chunk.

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
