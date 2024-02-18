# VOLlama
An accessible chat client for Ollama

## Instructions

To use VOLlama, you must first set up Ollama and download a model from Ollama's library. Follow these steps:

First install [Ollama](https://ollama.com/).

To download a model, execute the command below, replacing `openhermes` with a [different model](https://ollama.ai/library) as needed:
```
ollama pull openhermes
```

Finally, Run VOLlama.exe

## Shortcuts

On Mac, press command key instead of control key.

* Control+L: Focus on the model list.
* Control+Enter: Insert a new line.
* Esc: Shift focus to the prompt.

If you're operating Ollama on a different machine, you can configure the host address in the advanced menu.

## [Retrieval-Augmented Generation](https://blogs.nvidia.com/blog/what-is-retrieval-augmented-generation/)

* Go to Rag menu > Attach url.
* Enter https://www.apple.com/apple-vision-pro/
* Wait until the document is indexed.
* In the message field, type "/q What can you do with Vision Pro?" without the quotes.
* Putting "/q " in the beginning of your messsage triggers LlamaIndex to kick in.
* You can also index a folder with documents in them. It'll index all the documents it can index such as pdf, txt, docs, etc including inside all the sub folders.

## Copy Model in Advanced Menu

This feature allows you to duplicate an existing model via a modelfile, enabling you to use it as a preset with a different name and parameters (such as temperature, repeat penalty, maximum generation length, context length, etc.). It does not duplicate the model's weight files, conserving storage space even with multiple duplicates.

For more details, see [modelfile](https://github.com/ollama/ollama/blob/main/docs/modelfile.md).

For Mac users, it's crucial to disable smart quotes before opening the copy model dialog. If your modelfile displays a left double quotation mark instead of a straight quotation mark, smart quotes are enabled.

* MacOS 13 Ventura or later: Go to System Settings > Keyboard > Edit Input Source > turn off smart quotes.
* Before Ventura: Navigate to System Preferences > Keyboard > Text > uncheck smart quotes.

## Parameters Values

| Parameter      | Description                                                                                                                                                                                                                                             | Value Type | Default Value |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | -------------------- |
| num_ctx        | Sets the size of the context window used to generate the next token. The max context length depends on the model. | int | 4096 |
| num_predict    | Maximum number of tokens to predict when generating text. -1 = infinite generation, -2 = fill context | int | -1 |
| temperature    | The temperature of the model. Increasing the temperature will make the model answer more creatively. Range: 0.0-2.0. | float | 0.8 |
| repeat_penalty | Sets how strongly to penalize repetitions. A higher value like 1.5 will penalize repetitions more strongly, while a lower value like 0.9 will be more lenient. Range: 0.0-2.0. | float | 1.1 |
| repeat_last_n  | Sets how far back for the model to look back to prevent repetition. 0 = disabled, -1 = num_ctx | int        | 64 |
| top_k          | Reduces the probability of generating nonsense. A higher value like 100 will give more diverse answers, while a lower value like 10 will be more conservative. Range: -1-100 | int | 40 |
| top_p | Works together with top-k. A higher value like 0.95 will lead to more diverse text, while a lower value 0.5 will generate more focused and conservative text. Range: 0.0-1.0. | float | 0.9 |
| tfs_z | Tail free sampling is used to reduce the impact of less probable tokens from the output. A higher value like 2.0 will reduce the impact more, while a value of 1.0 disables this setting. | float | 1.0 |
| typical_p | sets a minimum threshold for how likely a word or phrase needs to be in order to be considered by the model. Range: 0.0-1.0. | float | 1.0 |
| presence_penalty | Penalizes new tokens based on their presence in the text so far. Range: 0.0-1.0. | float | 0.0 |
| frequency_penalty | Penalizes new tokens based on their frequency in the text so far. Range: 0.0-1.0. | float | 0.0 |
| mirostat       | Enable Mirostat sampling for controlling perplexity. 0 = disabled, 1 = Mirostat, 2 = Mirostat 2.0 | int | 0 |
| mirostat_tau | Controls the balance between coherence and diversity of the output. A lower value will result in more focused and coherent text. Range: 0.0-10.0 | float | 5.0 |
| mirostat_eta | Influences how quickly the algorithm responds to feedback from the generated text. A lower learning rate will result in slower adjustments, while a higher learning rate will make the algorithm more responsive. Range: 0.0-1.0 | float | 0.1 |
| num_keep | Number of tokens to keep unchanged at the beginning of the generated text. | int | 0 |
| penalize_newline | Whether to penalize the generation of new lines. | bool | True |
| stop | When this pattern is encountered the LLM will stop generating text and return. List strings separated by ", ". | string Array | empty |
| seed | Sets the random number seed to use for generation. Setting this to a specific number will make the model generate the same text for the same prompt. -1=random | int | -1 |


## Rag Settings

| Parameter      | Description                                                                                                                                                                                                                                             | Value Type | Default Value |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | -------------------- |
| show_context | When checking this option, RAG outputs the chunks sent to model. | bool | False |
| chunk_size | Sets how small you want to break up the text into pieces when indexing. All models have context size that determines how many tokens it can digest. It also defines how many tokens you want to feed the model at a time. | int | 1024 |
| chunk_overlap | Sets how much beginning and end of each chunk should overlap. | int | 20 |
| similarity_top_k | Sets how many chunks you would like to feed to model. Setting similarity_top_k to 10 means you want to feed 10 most relevant chunks to your question. | int | 2 |
| similarity_cutoff | Sets the similarity threshold it uses to filter out less relevant chunks. Setting similarity_cutoff to 0.6 means you don't want to feed chunks with similarity score less than 0.6. Setting this too high could lead to filter out all chunks. | float | 0.0 |
| response_mode | Sets how RAG to synthesize the response. | string | refine |

## response modes

* refine: create and refine an answer by sequentially going through each retrieved text chunk. This makes a separate LLM call per retrieved chunk. Good for more detailed answers.
* compact (default): similar to refine but compact the chunks beforehand, resulting in less LLM calls.
* tree_summarize: Query the LLM using the summary_template prompt as many times as needed so that all concatenated chunks have been queried, resulting in as many answers that are themselves recursively used as chunks in a tree_summarize LLM call and so on, until there’s only one chunk left, and thus only one final answer.
* simple_summarize: Truncates all text chunks to fit into a single LLM prompt. Good for quick summarization purposes, but may lose detail due to truncation.
* accumulate: Given a set of text chunks and the query, apply the query to each text chunk while accumulating the responses into an array. Returns a concatenated string of all responses. Good for when you need to run the same query separately against each text chunk.
* compact_accumulate: The same as accumulate, but will “compact” each LLM prompt similar to compact, and run the same query against each text chunk.