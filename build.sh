#!/bin/sh
set -e
rm -rf __pycache__
rm -rf build
rm -rf dist

# Ask the interpreter where the package actually is, rather than naming the
# Python version in the path. A venv's site-packages sits under lib/python3.X,
# so the hard-coded 3.13 broke the moment the venv was rebuilt on 3.14 -- and
# silently, since a missing --add-data source is only a warning: you get an app
# that dies on its first tokenizer call. It also only ever worked because macOS
# matched the ".venv/Lib" spelling case-insensitively.
NLTK_CACHE=$(python -c 'import pathlib, llama_index.core
print(pathlib.Path(llama_index.core.__file__).parent / "_static" / "nltk_cache")')
[ -d "$NLTK_CACHE" ] || { echo "build.sh: no nltk_cache at '$NLTK_CACHE'" >&2; exit 1; }

pyinstaller --noconsole --add-data="send.wav:." --add-data="receive.wav:." --add-data "$NLTK_CACHE:llama_index/core/_static/nltk_cache" VOLlama.py
