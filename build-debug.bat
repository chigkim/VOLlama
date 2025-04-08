rmdir/s /q __pycache__
rmdir/s /q build
rmdir/s /q dist
pip uninstall -y playwright selenium
pyinstaller --add-data "send.wav;." --add-data "receive.wav;." --add-data "default-parameters.json;." --add-data ".venv/Lib/site-packages/llama_index/core/_static/nltk_cache;llama_index/core/_static/nltk_cache" VOLlama.py