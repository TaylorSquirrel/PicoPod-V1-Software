"""Separate writable portable app data from bundled, read-only program assets."""
from pathlib import Path
import sys

FROZEN = bool(getattr(sys, 'frozen', False))
APP_ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[1]
ASSET_ROOT = Path(getattr(sys, '_MEIPASS', APP_ROOT))


def usb_command(port, arguments):
    if FROZEN:
        return [str(ASSET_ROOT / 'usb' / 'PicoPodUSB.exe'), 'connect', port] + list(arguments)
    return [sys.executable, '-m', 'mpremote', 'connect', port] + list(arguments)


def preview_command(arguments):
    return ([sys.executable, '--preview'] if FROZEN else [sys.executable, '-m', 'manager.preview']) + list(arguments)
