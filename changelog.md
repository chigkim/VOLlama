# Change log

* Token counter on the status bar for RAG.
* Fixed response mode not working.
* Output similarity score for each chunk.
* Able to save and load index
* Rag settings include: chunk_size, chunk_overlap, similarity_top_k, similarity_cutoff, show_context, ragResponseMode
* Different response Modes for RAG
* Option to display context sent to RAG system
* Epub reader
* Global settings improvement
* [Retrieval-Augmented Generation](https://blogs.nvidia.com/blog/what-is-retrieval-augmented-generation/) (RAG): See below for insturction on how to use it.
* Many bug fixes
* Generation parameters in advance menu
* Voice and rate gets saved into persistent settings
* Changed from NSSpeechSynthesizer to AVSpeechSynthesizer to avoid random crash
* Status bar and stats (Accessible in Windows only)
* Check for update
* Fixed message order.
* Checkbox Speak response in chat menu
* Start speaking during generation
* ESC: stop generating and speaking and focus to prompt
* Configure voice (Windows only)
* Confirmation before delete a model.
* Attach image: Control(Command)+I
* Create multiline prompt with Control(Command)+Enter
* Set system message in advance menu
* Delete model  in advance menu
* Persistent Settings for system message and host address
* Save and recall chat history
* Focus model list: Control(Command)+L

## [Retrieval-Augmented Generation](https://blogs.nvidia.com/blog/what-is-retrieval-augmented-generation/)

* Go to Chat menu > Attach url or press Control(Command)+U.
* Enter https://www.apple.com/apple-vision-pro/
* Wait until the document is indexed.
* In the message field, type "/q What can you do with Vision Pro?" without the quotes.
* Putting "/q " in the beginning of your messsage triggers LlamaIndex to kick in.
* You can also index a folder with documents in them. It'll index all the documents it can index such as pdf, txt, docs, etc including inside all the sub folders.

## Copy model in advance menu

It lets you duplicate an existing model through modelfile, and you can use it like preset with different name and parameters like temperature, repeat penalty, Maximum length to generate, context length, etc. It does not duplicate the model weight files, so you won't wasting your storage space even if you duplicate and create bunch.

See [modelfile](https://github.com/ollama/ollama/blob/main/docs/modelfile.md) for more detail.

It is very important for Mac users to turn off smart quotes before opening copy model dialog. If you see left double quotation mark instead of quotation mark in modelfile, that means you have smart quotes on.

* MacOS 13 Ventura or later: System settings > Keyboard > Edit input sorce > turn off smart quotes
* Before Ventura: System preferences > keyboard > text > uncheck smart quotes
