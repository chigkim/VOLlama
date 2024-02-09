# Change log

* Attach image for vision-language model like Llava
* Create multiline prompt with Control(Command)+Enter
* Set system message in advance menu
* Delete model  in advance menu
* Persistent Settings for system message and host address
* Save and recall chat history
* Focus model list: Control(Command)+L

## Copy model in advance menu

It lets you duplicate an existing model through modelfile, and you can use it like preset with different name and parameters like temperature, repeat penalty, Maximum length to generate, context length, etc. It does not duplicate the model weight files, so you won't wasting your storage space even if you duplicate and create bunch.

See [modelfile](https://github.com/ollama/ollama/blob/main/docs/modelfile.md) for more detail.

It is very important for Mac users to turn off smart quotes before opening copy model dialog. If you see left double quotation mark instead of quotation mark in modelfile, that means you have smart quotes on.

* MacOS 13 Ventura or later: System settings > Keyboard > Edit input sorce > turn off smart quotes
* Before Ventura: System preferences > keyboard > text > uncheck smart quotes
