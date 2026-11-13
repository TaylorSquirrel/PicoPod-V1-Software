"""Create OS-specific app folders without moving or deleting the working project."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def write(path, text):
    path.write_text(text, encoding='utf-8', newline='\n')


for name in ('Windows', 'Linux'):
    destination = ROOT / name
    destination.mkdir(exist_ok=True)
    for source in ('manager', 'firmware'):
        shutil.copytree(ROOT / source, destination / source, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(ROOT / 'requirements.txt', destination / 'requirements.txt')
    shutil.copy2(ROOT / 'README.md', destination / 'PROJECT_GUIDE.md')

windows = ROOT / 'Windows'
shutil.copy2(ROOT / 'launch_gui.pyw', windows / 'launch_gui.pyw')
for filename in ('Launch PicoPod.vbs', 'Preview PicoPod.vbs'):
    text = (ROOT / filename).read_text()
    preview = ' & " --preview"' if filename.startswith('Preview') else ''
    portable = ('python = files.BuildPath(folder, "PicoPodPortable\\PicoPod.exe")\n'
                'If files.FileExists(python) Then\n'
                '    command = Chr(34) & python & Chr(34)' + preview + '\n'
                '    shell.Run command, 1, False\n'
                '    WScript.Quit\n'
                'End If\n')
    text = text.replace('python = files.BuildPath(folder, ".venv\\Scripts\\pythonw.exe")',
                        portable + 'python = files.BuildPath(folder, ".venv\\Scripts\\pythonw.exe")')
    write(windows / filename, text)
for filename in ('library-state.json', 'library-state.bak'):
    source = ROOT / 'userdata' / filename
    target = windows / 'userdata' / filename
    if source.exists() and not target.exists():
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
write(windows / 'Setup PicoPod.cmd', '''@echo off
cd /d "%~dp0"
if exist ".venv\\Scripts\\python.exe" goto install
where py >nul 2>nul
if errorlevel 1 (python -m venv .venv) else (py -3 -m venv .venv)
if errorlevel 1 goto failed
:install
".venv\\Scripts\\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Open Launch PicoPod.vbs to start the GUI.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.12 or newer with Tcl/Tk support, then retry.
pause
exit /b 1
''')
write(windows / 'README.md', '''# PicoPod for Windows

For another computer, copy **PicoPod-Windows-x64.zip**, extract the entire folder,
then open **PicoPod.exe**. The standalone build includes Python and dependencies;
it requires neither Codex nor a Python installation. Keep `_internal` beside the exe.
**Launch PicoPod.vbs** and **Preview PicoPod.vbs** prefer this bundled build when
present and launch without a terminal window.

The remaining source files are for development. For a source-only installation,
install Python 3.12+ with Tcl/Tk on that PC and run **Setup PicoPod.cmd**. Never copy
a `.venv` between computers: its interpreter paths are machine-specific.

This folder includes the manager, Pico firmware, Windows SD preparation helper,
requirements and launchers. Firmware installation and live USB control work from
this copy. Card erasing still requires its explicit confirmation.

Your saved song list/playlists were copied into `userdata` if available. Original
MP3 locations remain unchanged: the audio collection and Python runtime are not
duplicated. Keep the originals available or add local files on another computer.
This copy saves future changes into its own `userdata` folder.

See **PROJECT_GUIDE.md** for hardware and player instructions.
''')

linux = ROOT / 'Linux'
write(linux / 'launch_linux.py', '''"""GUI entry point with file-based error logging on Linux."""
from pathlib import Path
import os
import sys
import traceback
import tkinter as tk
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

def report(kind, error, tb):
    log = ROOT / 'userdata' / 'startup.log'
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a', encoding='utf-8') as output:
            output.write(''.join(traceback.format_exception(kind, error, tb)) + '\\n')
    except OSError:
        pass
    messagebox.showerror('PicoPod error', str(error) + '\\nDetails: ' + str(log))

tk.Tk.report_callback_exception = lambda self, kind, error, tb: report(kind, error, tb)
try:
    if '--preview' in sys.argv:
        from manager.preview import main
        sys.argv = [sys.argv[0]]
        main()
    else:
        from manager.app import App
        root = tk.Tk()
        App(root)
        root.mainloop()
except Exception:
    report(*sys.exc_info())
''')
write(linux / 'setup.sh', '''#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python create_desktop_launcher.py
echo 'Setup complete. Run ./run.sh or open PicoPod.desktop.'
''')
write(linux / 'run.sh', '''#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
    echo 'Run sh setup.sh first (Python 3, python3-venv and python3-tk are required).'
    exit 1
fi
exec .venv/bin/python launch_linux.py "$@"
''')
write(linux / 'create_desktop_launcher.py', '''from pathlib import Path

root = Path(__file__).resolve().parent
def quote(value):
    return '"' + str(value).replace('\\\\', '\\\\\\\\').replace('"', '\\\\"').replace('`', '\\\\`').replace('$', '\\\\$').replace('%', '%%') + '"'
entry = '[Desktop Entry]\\nType=Application\\nName=PicoPod\\nComment=Pocket music player manager\\nTerminal=false\\nExec=' + quote(root / '.venv/bin/python') + ' ' + quote(root / 'launch_linux.py') + '\\nCategories=AudioVideo;Audio;\\n'
target = root / 'PicoPod.desktop'
target.write_text(entry, encoding='utf-8')
target.chmod(0o755)
''')
write(linux / 'README.md', '''# PicoPod for Linux

Requires Python 3.12+, Tk, venv support and a graphical desktop. On Debian/Ubuntu,
install `python3-tk` and `python3-venv` using your package manager first.

Run from this folder:

```sh
sh setup.sh
sh run.sh
```

For the offline demo: `sh run.sh --preview`. Setup creates **PicoPod.desktop** with
`Terminal=false` for launching just the GUI. Your desktop may require selecting
**Allow Launching** on that file. Keep the folder somewhere writable by your user.

Song management, saved libraries/playlists, offline preview, live USB control and
Pico firmware/metadata uploads are included. Select the Pico's Linux serial device
(usually `/dev/ttyACM0`); your user needs permission to access that device. Depending
on your distribution this uses the `dialout` or `uucp` group, followed by logging
out/in. Close other serial applications before firmware or metadata transfers.

**Upload everything** supports removable PICOPOD cards on Linux too: existing
FAT32 cards use verified incremental updates; other filesystems require explicit
erase confirmation and desktop authorization before FAT32 formatting. Install
`udisks2`, `util-linux`, `dosfstools` and GLib's `gdbus` tool (Debian/Ubuntu:
`libglib2.0-bin`). A running desktop polkit authentication agent is required for
privileged operations. Readers must expose a disk serial/WWN and partition UUID;
system, read-only, layered and multi-partition disks are refused. Card readers
without reliable identities can use **Export only** to an already-mounted FAT32
card, then **Upload library.json** with that exported manifest. Indexed catalogs
are uploaded automatically when their `.bin` file is beside the manifest.

This is a source package with Linux setup/launch scripts, not a bundled Linux
Python runtime. It has not been run on a physical Linux desktop in this session.
Your library starts empty; add MP3s using their Linux paths. State saves locally
under `userdata`. See **PROJECT_GUIDE.md** for the common player/hardware guide.
''')
print('Created Windows and Linux app folders; original project and audio files preserved.')
