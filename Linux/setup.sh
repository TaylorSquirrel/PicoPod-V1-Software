#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python create_desktop_launcher.py
echo 'Setup complete. Run ./run.sh or open PicoPod.desktop.'
