#!/bin/sh
# Sets up once, inside this folder, then starts the demo. Delete the folder to remove everything.
cd "$(dirname "$0")" || exit 1
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) tool=uv/mac-arm/uv ;;
  Darwin-x86_64) tool=uv/mac-intel/uv ;;
  Linux-x86_64) tool=uv/linux/uv ;;
  *) echo "This machine isn't supported: $(uname -s) $(uname -m). Please use the recorded demo."; exit 1 ;;
esac
# A Mac blocks programs that came from a download until they're allowed.
[ "$(uname -s)" = Darwin ] && xattr -dr com.apple.quarantine . 2>/dev/null
chmod +x "$tool"
export UV_CACHE_DIR="$PWD/.setup/cache" UV_PYTHON_INSTALL_DIR="$PWD/.setup/python"
python=.setup/venv/bin/python
if [ ! -f .setup/ready ]; then
  echo "First run: setting up inside this folder. This needs internet and takes a minute or two."
  "$tool" venv --no-config --python 3.12 --python-preference only-managed .setup/venv &&
    "$tool" pip install --no-config --python "$python" -r requirements.txt
  if [ $? -ne 0 ]; then
    echo "Setup failed. Check the internet connection and run this again."
    exit 1
  fi
  "$tool" pip install --no-config --python "$python" -r requirements-voice.txt ||
    echo "No voice on this machine: you can still type to Val."
  "$tool" pip install --no-config --python "$python" -r requirements-export.txt ||
    echo "No IFC or DXF download on this machine. Everything else works."
  touch .setup/ready
fi
exec "$python" run_demo.py "$@"
