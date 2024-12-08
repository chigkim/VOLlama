#!/bin/sh
rm -rf __pycache__
rm -rf build
rm -rf dist
pip uninstall -y playwright
pyinstaller --add-data="send.wav:." --add-data="receive.wav:." --add-data="default-parameters.json:." --add-data ".venv/Lib/python3.11/site-packages/llama_index/core/_static/nltk_cache:llama_index/core/_static/nltk_cache" VOLlama.py