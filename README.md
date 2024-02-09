# VOLlama
An accessible chat client for Ollama

## Instruction

You need to first [setup Ollama](https://ollama.ai/) and download a model on Ollama before you can use this.

For Windows users Docker is probably the easiest way to get Ollama going:

1. [install Docker](https://docs.docker.com/get-docker/)
2. Run the following command In command line to install Ollama: `docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama`
3. Run the following command to download a model replace zephyr with [different models](https://ollama.ai//library): `docker exec -it ollama ollama pull zephyr`
4. Run VOLlama.exe

## Shortcuts

* Control+m: focusses on model list
* Control(Command)+Enter: new line
* Esc: change focus to prompt

If you're running Ollama on another machine, you can set the host address from the dvance menu.

## Copy model in advance menu

It allows to duplicate an existing model through modelfile, and you can use it like preset with different name and parameters like temperature, repeat penalty, Maximum length to generate, context length, etc. It does not duplicate the model weight files, so you won't wasting your storage space even if you duplicate and create bunch.

See [modelfile](https://github.com/ollama/ollama/blob/main/docs/modelfile.md) for more detail.

It is very important for Mac users to turn off smart quotes before opening copy model dialog. If you see left double quotation mark instead of quotation mark in modelfile, that means you have smart quotes on.

*macOS 13 Ventura or later: System settings > Keyboard > Edit input sorce > turn off smart quotes
* Before Ventura: System preferences > keyboard > text > uncheck smart quotes

