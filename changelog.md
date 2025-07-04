# Change log

## v0.5.0

* You can specify a direct URL to an image when using the **attach URL** feature.
* The prompt field now accepts both Shift+Enter and Ctrl+Enter for a new line.
* Changed "Speak response" to "Read response" in the chat menu, so it now uses "R" as the accelerator on Windows.
* Typo fix

## v0.4.0

* You can now attach multiple images at once.

# # v0.3.2

* It displays presets in alphabetical order.
* Removed deprecated parameters for Ollama: penalize_newline, mirostat, mirostat_tau, mirostat_eta, tfs_z
* When temperature is not set, llama-index-llms-ollama sends none as temperature value in order to use the default temperature set by the model.

## v0.3.1

* Fixed the bug where selecting a preset doesn't set the system message.
* Selecting a preset starts a new chat.

## v0.3.0

* Use Chat > Presets to save server type, model, system message, and generation parameters.
* Press Ctrl/Cmd+p to quickly switch between your favorite presets.
* Settings aren't saved to a preset until you click Save in the Preset menu.

## v0.2.2

* Correctly map num_predict to max_tokens.
* Important: Set num_predict to a positive value, such as 1024.
* Parameters (except num_ctx) can be left empty to use the engine’s default values.
* The system message can be empty to use the model’s default.
* You can now specify the num_gpu parameter to set the number of layers loaded to the GPU for Ollama.

## v0.2.1

* Fixed the bug for follow up question with image
* No longer throws an error when there's no settings.
* Image, document, and URL uploaded mid generation don't get cleared.
* Only clear prompt when you press escape and you were focused on a previous message.
* List all models returned from server
* Upgrade dependencies
* Other minor bug fixes and performance improvements

## v0.2.0

* Attach URL: CTRL+U
* Increased Timeout for Ollama and OpenAILike to 1 hour
* Min_p sampling
* Minor UI Fixed
* Provided patch to work with latest dependencies

## v0.1.4-beta.3

* OpenAILike Api for OpenAI Compatible platform such as openrouter.ai
* Moved host from advance menu to Api settings
* If you use Ollama in another machine, please reset the address for Ollama in Chat Menu> API Settings> Ollama > Base Url.

## v0.1.4-beta.2

* Added edit menu and moved clear and copy from chat menu to edit menu.
* Added models on chat menu.
*     When create a new prompt, it saves automatically.
* On prompt manager, changed duplicate to new, and replace to save.
* When opening prompt manager on Mac, it now correctly selects the current prompt.

## v0.1.4-beta.1

* Prompt manager
* Import [Awesome ChatGPT Prompts](https://github.com/f/awesome-chatgpt-prompts)
* Partial support for GPT-4O: Throws an error in some cases but ignore the error.
* Able to attach entire document for long context model.

## v0.1.3

* Shortcut for API Settings: Control+(or Command)+Shift+A
* Creates indexes for only supported file types.

## v0.1.2

* Remove single file package to speed up load time.

## v0.1.1

* Clearer status message
* Created  an accessible status label for Mac.

## v0.1.0

* Reports progress during embedding.
* Deploy 3 different web readers to retrieve webpages better.
* Fixed a bug for configure voice not opening in some situations.
* Default parameters match default parameters from llama.cpp.
* Fixed file types when opening a file to index.
* Clear last message clears last user message as well as model's response.
* Editing the message history does not move the history cursor to the bottom, so you can keep editing another message.
* Pressing esc moves history cursor to the bottom for new message.
* Fixed incorrect history cursor when there's a system message.
* Changed send button to edit when editing history.
* Paste last cleared user message into the prompt for editing or simply resending.
* Edit history: alt+(or option on mac)+up/down
* Embedding with Ollama
* Make sure to download nomic-embed-text: ollama pull nomic-embed-text
* If you have saved index, you need to index and save again.
* Support for OpenAI and Gemini
* Better error message if no text found from semantic search.
* Able to index individual files
* Fixed bug when index gets reset when changing model
* Token counter on the status bar for RAG.
* Fixed response mode not working.
* Output similarity score for each chunk.
* Able to save and load index
* Rag settings include: chunk_size, chunk_overlap, similarity_top_k, similarity_cutoff, show_context, ragResponseMode
* Different response Modes for RAG
* Option to display context sent to RAG system
* Epub reader
* Global settings improvement
* [Retrieval-Augmented Generation](https://blogs.nvidia.com/blog/what-is-retrieval-augmented-generation/) (RAG): See below for instruction on how to use it.
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

## Download