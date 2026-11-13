"""Collect distributable apps and complete, private-data-free original source.

Run tools.build_windows first to build the Windows runtime, then this module.
"""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / 'releases'


def zip_folder(folder, target, prefix):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob('*')):
            relative = path.relative_to(folder)
            if not path.is_file() or any(p in ('__pycache__', '.venv', 'userdata') for p in relative.parts) or path.suffix == '.pyc':
                continue
            info = zipfile.ZipInfo((Path(prefix) / relative).as_posix())
            info.create_system = 3
            info.external_attr = (0o100755 if path.suffix == '.sh' else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def main():
    subprocess.run([sys.executable, '-m', 'tools.package_apps'], cwd=ROOT, check=True)
    windows = ROOT / 'Windows/PicoPod-Windows-x64.zip'
    if not windows.is_file():
        raise RuntimeError('Build the Windows runtime first: python -m tools.build_windows')
    RELEASES.mkdir(exist_ok=True)
    shutil.copy2(windows, RELEASES / windows.name)
    zip_folder(ROOT / 'Linux', RELEASES / 'PicoPod-Linux.zip', 'PicoPod')
    source = RELEASES / 'source'
    source.mkdir(exist_ok=True)
    ignored = shutil.ignore_patterns('__pycache__', '*.pyc', '.venv', 'userdata', 'PicoPodPortable', '*.zip', 'self-test-result.json')
    for name in ('firmware', 'manager', 'tests', 'tools', 'Windows', 'Linux'):
        shutil.copytree(ROOT / name, source / name, dirs_exist_ok=True, ignore=ignored)
    for path in ROOT.iterdir():
        if path.is_file() and (path.suffix in ('.md', '.txt', '.pyw', '.cmd', '.vbs') or path.name == '.gitignore'):
            shutil.copy2(path, source / path.name)
    (RELEASES / 'README.md').write_text('''# PicoPod releases

- **PicoPod-Windows-x64.zip**: extract the entire folder, then open `PicoPod.exe`.
  Includes Python/Tk/dependencies and the USB helper. No Codex or Python install needed.
- **PicoPod-Linux.zip**: extract, install Python 3.12+, Tk/venv and the system tools
  listed in its README, then run `sh setup.sh`. Start with `sh run.sh` or the generated
  desktop launcher. Setup needs internet for Python dependencies. This is a Linux
  source/installer package, not a bundled runtime.
- **source/**: original Pico firmware, desktop manager, Windows/Linux launchers,
  tests and packaging tools. Build instructions are in `source/README.md`.

Both apps include firmware installation, metadata upload, live two-screen USB
mirroring/control, offline preview, saved song libraries, playlist editing,
indexed catalogs up to 25,000 songs, and confirmed SD upload. Existing FAT32 cards
use incremental updates; other filesystems require erase confirmation. Hardware,
flash capacity and card-reader identity checks still apply.

Windows was tested after extracting to a new location without Python/Codex on PATH.
Linux card commands have automated fixture/mock coverage; a physical Linux desktop,
authorization prompt and card transfer have not been tested here. See the Linux
README for dependencies and serial permissions. Firmware upload requires an already
installed MicroPython runtime. Original audio and personal saved libraries are
excluded; add your own local MP3s. Unzip into a writable folder.

Rebuild: install `requirements.txt` and `requirements-build.txt` on Windows, run
`python -m tools.build_windows`, then `python -m tools.build_releases`.
`SHA256SUMS.txt` contains checksums of the two ZIP files.
''', encoding='utf-8')
    archives = sorted(RELEASES.glob('*.zip'))
    (RELEASES / 'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in archives), encoding='ascii')
    required = ['manager/app.py', 'manager/live.py', 'manager/playlists.py', 'manager/linux_cards.py', 'firmware/main.py']
    with zipfile.ZipFile(RELEASES / 'PicoPod-Linux.zip') as archive:
        for name in required:
            assert 'PicoPod/' + name in archive.namelist(), name
        assert not any('/userdata/' in name or '/.venv/' in name for name in archive.namelist())
        assert archive.testzip() is None
    with zipfile.ZipFile(RELEASES / windows.name) as archive:
        assert 'PicoPod/PicoPod.exe' in archive.namelist()
        assert 'PicoPod/_internal/firmware/main.py' in archive.namelist()
        assert 'PicoPod/_internal/usb/PicoPodUSB.exe' in archive.namelist()
        assert archive.testzip() is None
    print('Created releases: Windows ZIP, Linux ZIP, complete source, README and SHA256 checksums.')


if __name__ == '__main__':
    main()
