# VOLlama
An accessible chat client for Ollama

## Instructions

To use VOLlama, you must first set up Ollama and download a model from Ollama's library. Follow these steps:

For Windows users, Docker is likely the most straightforward method to install Ollama:

First, [install Docker](https://docs.docker.com/get-docker/).

Run the command below in the command line to install Ollama:
```
docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
```

To download a model, execute the command below, replacing `openhermes` with a [different model](https://ollama.ai/library) as needed:
```
docker exec ollama ollama pull openhermes
```

Finally, Run VOLlama.exe

## Shortcuts

* Control (Command) + L: Focus on the model list.
* Control (Command) + Enter: Insert a new line.
* Esc: Shift focus to the prompt.

If you're operating Ollama on a different machine, you can configure the host address in the advanced menu.

## [Retrieval-Augmented Generation](https://blogs.nvidia.com/blog/what-is-retrieval-augmented-generation/)

* Go to Chat menu > Attach url or press Control(Command)+U.
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

