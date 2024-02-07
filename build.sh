#!/bin/sh
pyinstaller -F --onefile --noconsole --add-data="send.wav:." --add-data="receive.wav:." VOLlama.py