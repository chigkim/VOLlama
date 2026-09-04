#!/bin/sh
set -e
rm -rf __pycache__
rm -rf build
rm -rf dist
uv pip uninstall playwright selenium

# See build.sh: the path is asked for rather than written down, so the two
# scripts cannot drift onto different Python versions again.
NLTK_CACHE=$(python -c 'import pathlib, llama_index.core
print(pathlib.Path(llama_index.core.__file__).parent / "_static" / "nltk_cache")')
[ -d "$NLTK_CACHE" ] || { echo "build-debug.sh: no nltk_cache at '$NLTK_CACHE'" >&2; exit 1; }

pyinstaller --add-data="send.wav:." --add-data="receive.wav:." --add-data "$NLTK_CACHE:llama_index/core/_static/nltk_cache" VOLlama.py
