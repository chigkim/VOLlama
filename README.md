# VOLlama

Accessible Chat Client for Ollama

## Instructions

To use VOLlama, you must first set up Ollama and download a model from Ollama's library. Follow these steps:

Download and install [Ollama](https://ollama.ai/).

You will need a model to generate text. Execute the command below in terminal (or command-line on Windows) to download a model. If you prefer to use a [different model](https://ollama.ai/library), replace `llama3` with your chosen model.
```
ollama pull llama3
```

Optionally, If you want to utilize the image description feature, you need to download a multimodal (vision+language) model.
```
ollama pull llava
```

There are also llava:13b and llava:34b which have higher accuracy but require more storage, memory, and computing power.

Optionally, If you want to utilize the retrieval-augmented generation feature, you need to download `nomic-embed-text` for embedding.
```
ollama pull nomic-embed-text
```

Finally, [download the latest](https://github.com/chigkim/VOLlama/releases/) and run VOLlama.

For Mac, VOLlama is not notarized by Apple, so you need to allow to run in system settings > privacy and security.

VOLlama may take a while to load especially on Mac, so be patient. You'll eventually hear "VOLlama is starting."

If you want responses to be read aloud automatically, you can enable the "Speak Response with System Voice" option from the chat menu.

If you are operating Ollama on a different machine, configure the host address in Chat menu > API Settings > Ollama > Base URL.

## Shortcuts

Shortcuts for all the features can be found in the menu bar. Here are exceptions:

* Control(or Command)+Enter: Insert a new line.
* Esc: Shift focus to the prompt.

## Image Description

In order to ask a multimodal model questions about an image:

1. choose a multimodal model from the toolbar (control+l.)
2. Attach an image file from the chat menu (or control+i.)
3. Type your question like "Can you describe the image?" on the prompt field and send it.

## Generation Parameter Values

This table lists the generation parameters available in VOLlama, along with their descriptions, types, and default values:

| Parameter | Description | Value Type | Default Value |
|---------------------|-----------------------------------------------------------------------------------------------------|------------|---------------|
| num_ctx | Sets the size of the context window used to generate the next token. Depends on the model's limit. | int | 4096 |
| num_predict | Maximum number of tokens to predict during text generation. Use -1 for infinite, -2 to fill context.| int | -1 |
| temperature | Adjusts the model's creativity. Higher values lead to more creative responses. Range: 0.0-2.0. | float | 0.8 |
| repeat_penalty | Penalizes repetitions. Higher values increase the penalty. Range: 0.0-2.0. | float | 1.0 |
| repeat_last_n | How far back the model checks to prevent repetition. 0 = disabled, -1 = num_ctx. | int | 64 |
| top_k | Limits the likelihood of less probable responses. Higher values allow more diversity. Range: -1-100 | int | 40 |
| top_p | Works with top_k to manage diversity of responses. Higher values lead to more diversity. Range: 0.0-1.0. | float | 0.95 |
| tfs_z | Tail free sampling reduces the impact of less probable tokens. Higher values diminish this impact. | float | 1.0 |
| typical_p | Sets a minimum likelihood threshold for considering a token. Range: 0.0-1.0. | float | 1.0 |
| presence_penalty | Penalizes new tokens based on their presence so far. Range: 0.0-1.0. | float | 0.0 |
| frequency_penalty | Penalizes new tokens based on their frequency so far. Range: 0.0-1.0. | float | 0.0 |
| mirostat | Enables Mirostat sampling to control perplexity. 0 = disabled, 1 = Mirostat, 2 = Mirostat 2.0. | int | 0 |
| mirostat_tau | Balances between coherence and diversity of output. Lower values yield more coherence. Range: 0.0-10.0. | float | 5.0 |
| mirostat_eta | Influences response speed to feedback in text generation. Higher rates mean quicker adjustments. Range: 0.0-1.0. | float | 0.1 |
| num_keep | Number of tokens to keep unchanged at the beginning of generated text. | int | 0 |
| penalize_newline | Whether to penalize the generation of new lines. | bool | True |
| stop | Triggers the model to stop generating text when this pattern is encountered. List strings separated by ", ". | string Array | empty |
| seed | Sets the random number seed for generation. Specific numbers ensure reproducibility. -1 = random. | int | -1 |

## [Retrieval-Augmented Generation](https://blogs.nvidia.com/blog/what-is-retrieval-augmented-generation/)

To retrieve a document and ask questions about it, follow these steps:

Note: It retrieves only snippets of text relevant to your question, so full summaries are not available.

1. Go to Rag menu > index a URL.
2. Enter `https://bbc.com/`.
3. Wait until the document is indexed.
4. In the message field, type `/q What are some positive news for today?` without the quotes. Prefacing your message with `/q` triggers processing your prompt with RAG using LlamaIndex.
5. You can also index a folder with documents in it, including all subfolders. It will index all accessible documents, such as PDFs, TXT files, and DOCs.

## Rag Settings

This section describes the parameters related to the Retrieval-Augmented Generation (RAG) feature:

| Parameter | Description | Value Type | Default Value |
|---------------------|-----------------------------------------------------------------------------------------------------|------------|---------------|
| show_context | When enabled, displays the text chunks sent to the model. | bool | False |
| chunk_size | Determines the size of text chunks for indexing. | int | 1024 |
| chunk_overlap | Specifies the overlap between the start and end of each chunk. | int | 20 |
| similarity_top_k | Number of the most relevant chunks fed to the model. | int | 2 |
| similarity_cutoff | The threshold for filtering out less relevant chunks. Setting too high may exclude all chunks. | float | 0.0 |
| response_mode | Determines how RAG synthesizes responses. | string | refine |

## response modes

* refine: create and refine an answer by sequentially going through each retrieved text chunk. This makes a separate LLM call per retrieved chunk. Good for more detailed answers.
* compact (default): similar to refine but compact the chunks beforehand, resulting in less LLM calls.
* tree_summarize: Query the LLM using the summary_template prompt as many times as needed so that all concatenated chunks have been queried, resulting in as many answers that are themselves recursively used as chunks in a tree_summarize LLM call and so on, until there?s only one chunk left, and thus only one final answer.
* simple_summarize: Truncates all text chunks to fit into a single LLM prompt. Good for quick summarization purposes, but may lose detail due to truncation.
* accumulate: Given a set of text chunks and the query, apply the query to each text chunk while accumulating the responses into an array. Returns a concatenated string of all responses. Good for when you need to run the same query separately against each text chunk.
* compact_accumulate: The same as accumulate, but will ?compact? each LLM prompt similar to compact, and run the same query against each text chunk.

## Copy Model in Advanced Menu

This feature allows you to duplicate an existing model via a model file, enabling you to use it as a preset with a different name and parameters (e.g., temperature, repeat penalty, maximum generation length, context length). It does not duplicate the model's weight files, thus conserving storage space even with multiple duplicates.

For more details, see [modelfile](https://github.com/ollama/ollama/blob/main/docs/modelfile.md).

For Mac users, it is crucial to disable smart quotes before opening the copy model dialog. If your model file displays a left double quotation mark instead of a straight quotation mark, smart quotes are enabled.

- **MacOS 13 Ventura or later**: Go to System Settings > Keyboard > Edit Input Source > turn off smart quotes.
- **Before Ventura**: Navigate to System Preferences > Keyboard > Text > uncheck smart quotes.

## Docker (Optional)

If you prefer to run Ollama using Docker, follow the instructions below:

Install Ollama by executing the following command in the command line:
```
docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
```

Download a model to generate text. Replace `llama3` with your desired model if you wish to use a [different model](https://ollama.ai/library):
```
docker exec ollama ollama pull llama3
```

Optionally, If you wish to use the retrieval-augmented generation feature, download `nomic-embed-text` for embedding:
```
docker exec ollama ollama pull nomic-embed-text
```

To stop Ollama, use the following command:
```
docker stop ollama
```

To restart Ollama, use the command below:
```
docker start ollama
```
