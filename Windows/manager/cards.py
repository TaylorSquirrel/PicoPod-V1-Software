"""Windows-only, identity-checked card preparation and verified copying."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid
from manager.paths import APP_ROOT, ASSET_ROOT

if os.name == 'nt':
    from ctypes import wintypes
else:
    wintypes = None

SCRIPT = ASSET_ROOT / 'manager' / 'cards.ps1'
IDENTITY = ('DriveLetter', 'UniqueId', 'DiskNumber', 'DiskUniqueId', 'DiskSerial',
            'PartitionNumber', 'Offset', 'Size', 'DiskSize')
JOB_ROOT = APP_ROOT / 'userdata' / 'card-jobs'


class HelperTimeout(RuntimeError):
    pass


class ShellExecuteInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)] if wintypes is not None else []


def launch_helper(arguments, timeout=180):
    """Wait for the elevated helper, rather than racing a newly visible file."""
    if os.name != 'nt':
        raise RuntimeError('Automatic card preparation is supported on Windows only.')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = 'runas'
    info.lpFile = powershell()
    info.lpParameters = subprocess.list2cmdline(arguments)
    info.nShow = 0
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == 1223:
            raise RuntimeError('Card preparation cancelled at the Windows administrator prompt. No upload was performed.')
        raise OSError(code, 'Windows could not launch the card preparation helper')
    if not info.hProcess:
        raise RuntimeError('Windows did not return a process handle for the card helper.')
    try:
        deadline = time.monotonic() + timeout
        while True:
            status = kernel.WaitForSingleObject(info.hProcess, 200)
            if status == 0:
                break
            if status != 258:
                raise ctypes.WinError(ctypes.get_last_error())
            if time.monotonic() > deadline:
                raise HelperTimeout('Card preparation is taking longer than expected and may still be running. Do not retry until it finishes. Job diagnostics were preserved.')
        exit_code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return exit_code.value
    finally:
        kernel.CloseHandle(info.hProcess)


def read_helper_result(path):
    for attempt in range(15):
        try:
            result = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if not isinstance(result, dict) or 'ok' not in result:
                raise ValueError('The helper did not write a completion status')
            return result
        except (PermissionError, ValueError) as error:
            if attempt == 14:
                raise RuntimeError('Could not read the completed card preparation result. The card may already be prepared; no songs were copied. Diagnostics: ' + str(path)) from error
            time.sleep(0.1)


def run_card_helper(expected, mode='Prepare', job_root=None):
    if mode not in ('Prepare', 'Validate'):
        raise ValueError('Invalid helper mode')
    job = Path(job_root or JOB_ROOT) / uuid.uuid4().hex
    job.mkdir(parents=True)
    expected_file, result_file = job / 'expected.json', job / 'result.json'
    expected_file.write_text(json.dumps(expected), encoding='utf-8')
    # Create under the normal user's identity and keep this same file/ACL when
    # the elevated helper writes it. Job files remain available for diagnosis.
    result_file.write_text('{}', encoding='utf-8')
    result_file.read_text(encoding='utf-8')  # Fail before preparation if inaccessible.
    arguments = ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(SCRIPT),
                 '-Mode', mode, '-ExpectedFile', str(expected_file), '-ResultFile', str(result_file)]
    exit_code = launch_helper(arguments)
    result = read_helper_result(result_file)
    if not result.get('ok') or exit_code:
        raise RuntimeError('Card preparation failed: ' + result.get('error', 'Helper exited without a successful result. See ' + str(job)))
    return result


def powershell():
    if os.name != 'nt':
        raise RuntimeError('Automatic card formatting is supported on Windows only.')
    return str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')


def discover_cards():
    if os.name == 'posix':
        from manager.linux_cards import discover
        return discover()
    result = subprocess.run([powershell(), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(SCRIPT), '-Mode', 'List'], capture_output=True,
                            encoding='utf-8-sig', errors='replace', timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Could not inspect SD cards: ' + (result.stderr.strip() or result.stdout.strip()))
    data = json.loads(result.stdout)
    return data if isinstance(data, list) else [data]


def validate_card(card):
    if card.get('Platform') == 'linux':
        from manager.linux_cards import validate
        return validate(card)
    if not re.fullmatch(r'[D-Z]', str(card.get('DriveLetter', ''))):
        raise ValueError('PICOPOD must have a removable drive letter D: through Z:.')
    if card.get('Label') != 'PICOPOD' or card.get('DriveType') != 'Removable':
        raise ValueError('PICOPOD must be a removable card, not a fixed disk.')
    if card.get('BusType') not in ('USB', 'SD', 'MMC'):
        raise ValueError('PICOPOD is not connected through a supported card reader.')
    if card.get('IsBoot') is not False or card.get('IsSystem') is not False or card.get('PartitionCount') != 1:
        raise ValueError('System disks and cards with multiple partitions cannot be formatted here.')
    if not 64 * 1024**2 <= card.get('Size', 0) <= card.get('DiskSize', 0) <= 32 * 1024**3:
        raise ValueError('Use a microSD card from 64 MB up to 32 GB.')
    if not card.get('UniqueId') or not card.get('DiskUniqueId'):
        raise ValueError('The card reader did not provide a reliable disk identity.')
    if not re.fullmatch(r'\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\', card['UniqueId']):
        raise ValueError('The card reader did not provide a usable volume GUID.')
    return card


def select_card(cards):
    if not cards:
        raise ValueError('No SD card named PICOPOD was found. Put it in a computer card reader and give it the label PICOPOD.')
    if len(cards) != 1:
        raise ValueError('More than one PICOPOD card is connected. Disconnect the extras before uploading.')
    return validate_card(cards[0])


def same_card(expected, actual):
    validate_card(actual)
    fields = IDENTITY
    if expected.get('Platform') == 'linux':
        from manager.linux_cards import IDENTITY as fields
    if actual.get('Platform') != expected.get('Platform') or any(actual.get(field) != expected.get(field) for field in fields):
        raise ValueError('The card changed after confirmation. Nothing further will be written.')
    return actual


def card_root(card):
    validate_card(card)
    if card.get('Platform') == 'linux':
        from manager.linux_cards import root
        return root(card)
    # Write through the confirmed GUID, not a drive letter which can be reused
    # by Windows if the user disconnects the reader during a transfer.
    return Path(card['UniqueId'])


def preflight_sources(tracks, card):
    if not tracks:
        raise ValueError('Add MP3 files before uploading.')
    total = 0
    allocated = 0
    for track in tracks:
        source = Path(track['source']).resolve(strict=True)
        on_card = (any(source.is_relative_to(Path(m).resolve()) for m in card.get('MountPoints', []))
                   if card.get('Platform') == 'linux' else
                   source.drive.upper().rstrip(':') == card['DriveLetter'] or
                   source.drive.casefold() == card['UniqueId'].rstrip('\\').casefold())
        if on_card:
            raise ValueError('A source song is on the card that would be erased. Copy your originals to the PC first.')
        if source.suffix.lower() != '.mp3' or not source.is_file():
            raise ValueError('Invalid source MP3: ' + str(source))
        size = source.stat().st_size
        total += size
        allocated += ((size + 32767) // 32768) * 32768
    if allocated + 8 * 1024**2 > card['Size']:
        raise ValueError('The selected songs will not fit on the card.')
    return total


def prepare_action(card):
    return 'clear' if card.get('FileSystem', '').upper() == 'FAT32' else 'format'


def prepare_card(expected, confirmed=False):
    if expected.get('Platform') == 'linux':
        from manager.linux_cards import prepare
        return prepare(expected, confirmed)
    if confirmed is not True:
        raise ValueError('Erasing the card requires explicit confirmation.')
    actual = same_card(expected, select_card(discover_cards()))
    if actual.get('FileSystem') != expected.get('FileSystem'):
        raise ValueError('Card filesystem changed after confirmation. Confirm the target again.')
    run_card_helper(expected)
    actual = same_card(expected, select_card(discover_cards()))
    if actual.get('FileSystem') != 'FAT32':
        raise RuntimeError('Card is not FAT32 after preparation. Upload stopped.')
    return actual


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.digest()


def copy_staged(staging, card, progress=lambda message: None):
    last_check = [-100]
    def check_target(force=False):
        if not force and time.monotonic() - last_check[0] < 10:
            return
        actual = same_card(card, select_card(discover_cards()))
        if actual.get('FileSystem') != 'FAT32':
            raise ValueError('PICOPOD is no longer FAT32. Upload stopped.')
        last_check[0] = time.monotonic()
    check_target(True)
    target, staging = card_root(card), Path(staging)
    if shutil.disk_usage(target).free < sum(((p.stat().st_size + 32767) // 32768) * 32768 for p in staging.rglob('*') if p.is_file()) + 4 * 1024**2:
        raise ValueError('Not enough space after formatting.')
    from manager.library import validate_device_file
    library = validate_device_file(staging / 'library.json')
    disk = None
    def copy_verified(relative, label):
        source, destination = staging / relative, target / relative
        destination.parent.mkdir(exist_ok=True)
        progress('Copying and verifying ' + label)
        with source.open('rb') as src, destination.open('xb') as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if digest(source) != digest(destination):
            raise IOError('Verification failed for ' + destination.name)
    try:
        if library['version'] == 2:
            from firmware.indexed import DiskCatalog
            disk = DiskCatalog(library, str(staging))
            tracks = disk.tracks
        else:
            tracks = library['tracks']
        for track in tracks:
            check_target()
            copy_verified(Path(track['file']), track['title'])
        if disk:
            copy_verified(Path(library['catalog']['file']), 'indexed library metadata')
    finally:
        if disk:
            disk.close()
    check_target(True)
    metadata = (staging / 'library.json').read_bytes()
    with (target / 'library.json').open('xb') as output:
        output.write(metadata)
        output.flush()
        os.fsync(output.fileno())
    if (target / 'library.json').read_bytes() != metadata:
        raise IOError('Card metadata verification failed.')
    return target / 'library.json'
