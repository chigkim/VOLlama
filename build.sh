#!/bin/sh
rm -rf __pycache__
rm -rf build
rm -rf dist
uv pip uninstall playwright selenium
pyinstaller --noconsole --add-data="send.wav:." --add-data="receive.wav:." --add-data="default-parameters.json:." --add-data ".venv/Lib/python3.13/site-packages/llama_index/core/_static/nltk_cache:llama_index/core/_static/nltk_cache" VOLlama.py