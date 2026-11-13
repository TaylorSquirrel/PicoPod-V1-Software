"""Relocate the ZIP and verify it with Python/Codex removed from the child environment."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
(ROOT / 'userdata').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='portable-check-', dir=ROOT / 'userdata') as temporary:
    destination = Path(temporary)
    with zipfile.ZipFile(ROOT / 'Windows' / 'PicoPod-Windows-x64.zip') as archive:
        assert not any('.venv' in part for name in archive.namelist() for part in Path(name).parts)
        archive.extractall(destination)
    app = destination / 'PicoPod'
    environment = dict(os.environ)
    for key in list(environment):
        if key.upper().startswith('PYTHON') or key.upper() in ('VIRTUAL_ENV', 'TCL_LIBRARY', 'TK_LIBRARY'):
            environment.pop(key)
    environment['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32') + ';' + os.environ['SystemRoot']
    process = subprocess.Popen([str(app / 'PicoPod.exe'), '--self-test'], cwd=app, env=environment,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        code = process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        error = app / 'userdata/startup.log'
        raise RuntimeError(error.read_text(encoding='utf-8') if error.exists() else 'Standalone GUI test timed out')
    result_path = app / 'self-test-result.json'
    if code or not result_path.exists():
        error = app / 'userdata/startup.log'
        raise RuntimeError(error.read_text(encoding='utf-8') if error.exists() else 'Standalone test failed')
    result = json.loads(result_path.read_text())
    assert result['ok'] and result['gui'] and result['firmware']
    assert Path(result['runtime_prefix']).is_relative_to(app)
    assert Path(result['tcl_library']).is_relative_to(app)
    helper = app / '_internal/usb/PicoPodUSB.exe'
    enumeration = subprocess.run([str(helper), 'connect', 'list'], cwd=app, env=environment,
                                 capture_output=True, text=True, timeout=15,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert enumeration.returncode == 0, enumeration.stderr
    print('PASS: extracted ZIP runs from a new folder with no Python/Codex PATH or virtual environment')
    print('PASS: bundled GUI, Tcl/Tk, pixel rendering, firmware assets, USB helper and serial enumeration')
