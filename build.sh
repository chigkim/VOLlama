#!/bin/sh
pyinstaller -F --onefile --noconsole --add-data="send.wav:." --add-data="receive.wav:." --add-data="default-parameters.json:." VOLlama.py