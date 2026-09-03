# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VOLlama is an accessible desktop chat client for LLM interaction, built with wxPython and designed with accessibility-first principles. It talks to any OpenAI-compatible server (Ollama, llama.cpp, LM Studio, vLLM, OpenAI, Gemini's OpenAI endpoint, ...) through a single code path, with features like RAG, multimodal support, and comprehensive screen reader compatibility.

A **preset** is the unit of configuration: it owns base URL, API key, model, system prompt, and generation parameters. `context_window` is a global setting, edited in RAG Settings, because RAG prompt sizing is its only consumer. Presets live inside the encrypted `settings.json`; there is no separate API settings dialog and no per-provider branching.

## Development Commands

### Setup Environment
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Mac/Linux (Python 3.12 required for Mac)
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Platform-Specific Patches
```bash
# Windows
git apply lib-win.patch

# Mac
git apply lib-mac.patch
```

### Building
```bash
# Windows
build-pyinstaller.bat  # PyInstaller setup
build.bat              # Final build

# Mac/Linux  
./build.sh

# Debug builds (retain console)
build-debug.bat/.sh
```

### Running from Source
```bash
python VOLlama.py
```

## Architecture Overview

### Core Components
- **VOLlama.py**: Main application with wxPython ChatWindow UI
- **Model.py**: Central LLM interaction layer, handles all provider communication
- **Settings.py**: Encrypted configuration management with JSON persistence
- **RAG.py**: LlamaIndex-based retrieval-augmented generation implementation
- **Speech.py**: Platform-specific TTS (AVFoundation/SAPI) for accessibility

### UI Dialogs
- **PresetDialog.py**: Tabbed preset editor (Connection / Parameters / System Prompt)
- **RAGParameterDialog.py**: RAG-specific settings, including the global embedding endpoint and context window

### Key Design Patterns
- **MVC-like separation**: Model.py handles business logic, VOLlama.py manages UI
- **Threading model**: Background threads for LLM calls with streaming callbacks
- **Single provider path**: one `OpenAILike` client for every endpoint, configured from the active preset
- **Settings singleton**: Global configuration with automatic encryption

### Accessibility Architecture
- Full screen reader compatibility through wxPython accessibility hooks
- Keyboard-only navigation with comprehensive shortcuts
- Audio feedback system (send.wav/receive.wav) 
- Platform-native TTS integration

### RAG Implementation
- Embeddings via `OpenAILikeEmbedding` against the global `embedding_base_url` / `embedding_api_key` / `embedding_model` settings (default model `EmbeddingGemma`)
- Vector storage through LlamaIndex with multiple synthesis modes
- Document processing supports PDF, DOCX, TXT, EPUB, HTML
- Configurable chunking, similarity thresholds, and response modes

### Multimodal Support
- Image attachment and encoding for vision models
- Base64 encoding pipeline for multimodal LLM requests
- Support for llama3.2-vision and similar vision-language models

## Key Dependencies
- **wxPython**: Cross-platform GUI framework
- **openai**: Model listing for the preset editor's "Choose..." button
- **llama-index-***: RAG, embeddings, and the `OpenAILike` LLM client
- **pyinstaller**: Standalone executable creation
- **sounddevice/soundfile**: Audio feedback system
- **transformers**: Model tokenization and utilities
- **cryptography**: API key encryption

## Development Notes

### Model Integration
`Model.init_llm()` builds one `OpenAILike` client from the active preset on every request. Only parameters in `Model.OPENAI_PARAMS` are forwarded; anything else in the schema stays local, since `additional_kwargs` are spread as top-level kwargs into `chat.completions.create()` and unknown names raise `TypeError`.

### Settings
`Settings.SETTINGS_VERSION` is 1. There is no migration from older files: a settings file whose version differs or that lacks `Settings.REQUIRED_KEYS` is flagged `version = 0`, and VOLlama tells the user to choose Reset Settings and configure from scratch.

`DotDict` only autosaves on attribute assignment, so mutating a nested dict in place does not reach disk. Use `save_presets()` (or reassign `settings.presets`) after editing a preset.

### Configuration Management
Settings are automatically encrypted (API keys) and stored in JSON format. The Settings class provides singleton access to configuration throughout the application.

### Build Process
PyInstaller creates self-contained executables with embedded Python runtime, audio files, and NLTK data. Platform-specific patches handle library compatibility issues.

### Accessibility Requirements
All new UI components must support keyboard navigation and provide appropriate accessibility labels for screen readers. Audio feedback should be added for important state changes.