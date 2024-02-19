rmdir/s /q __pycache__
rmdir/s /q build
rmdir/s /q dist
pip uninstall -y pyinstaller
git clone --depth 1 https://github.com/pyinstaller/pyinstaller
cd pyinstaller\bootloader
python ./waf all --target-arch=64bit
cd ..
pip install .
