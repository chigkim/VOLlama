rmdir/s /q __pycache__
rmdir/s /q build
rmdir/s /q dist
rmdir/s /q pyinstaller
uv pip uninstall -y pyinstaller
git clone --depth 1 https://github.com/pyinstaller/pyinstaller
cd pyinstaller\bootloader
python ./waf all --target-arch=64bit
cd ..
uv pip install .
cd ..
