#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
    echo 'Run sh setup.sh first (Python 3, python3-venv and python3-tk are required).'
    exit 1
fi
exec .venv/bin/python launch_linux.py "$@"
