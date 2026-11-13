"""Build a self-contained Windows x64 GUI and isolated USB helper."""
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build' / 'windows'
DIST = ROOT / 'dist' / 'windows'


def build(arguments):
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                    '--distpath', str(DIST), '--workpath', str(BUILD),
                    '--specpath', str(BUILD)] + arguments, cwd=ROOT, check=True)


BUILD.mkdir(parents=True, exist_ok=True)
build(['--onedir', '--console', '--name', 'PicoPodUSB', '--paths', str(ROOT),
       '--collect-submodules', 'mpremote', '--copy-metadata', 'mpremote', str(ROOT / 'tools' / 'usb_entry.py')])
build(['--onedir', '--windowed', '--name', 'PicoPod', '--paths', str(ROOT),
       '--collect-submodules', 'mutagen', '--collect-submodules', 'serial',
       '--add-data', str(ROOT / 'firmware') + ';firmware',
       '--add-data', str(ROOT / 'manager' / 'cards.ps1') + ';manager',
       '--add-data', str(DIST / 'PicoPodUSB') + ';usb',
       str(ROOT / 'launch_gui.pyw')])

portable = ROOT / 'Windows' / 'PicoPodPortable'
shutil.copytree(DIST / 'PicoPod', portable, dirs_exist_ok=True)
readme = '''PicoPod for Windows x64

Extract the WHOLE PicoPod folder and double-click PicoPod.exe.
Python, Tcl/Tk, dependencies and the USB helper are included.
Codex, a Python installation, and a copied .venv are NOT required.
Keep PicoPod.exe and the _internal folder together.
Use a writable location such as Documents (not Program Files).

Songs/playlists save in userdata beside PicoPod.exe. Original MP3s must be
available on this computer; audio files and another user's library are not
included in the downloadable ZIP. Add your local MP3s in the app.
Close older copies of PicoPod and serial apps before USB uploads.
The Windows card helper may request admin permission after card confirmation.

Offline preview is available in the GUI, or PicoPod.exe --preview.
'''
(portable / 'README.txt').write_text(readme, encoding='utf-8')
for name in ('library-state.json', 'library-state.bak'):
    source, target = ROOT / 'Windows' / 'userdata' / name, portable / 'userdata' / name
    if source.exists() and not target.exists():
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
archive = ROOT / 'Windows' / 'PicoPod-Windows-x64.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
    for path in portable.rglob('*'):
        if path.is_file() and 'userdata' not in path.relative_to(portable).parts and path.name != 'self-test-result.json':
            output.write(path, Path('PicoPod') / path.relative_to(portable))
print('Built portable app:', portable)
print('Built transfer ZIP:', archive)
