"""Console-free Windows entry point; retain errors when pythonw has no stderr."""
from pathlib import Path
import os
import sys
import traceback

ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
os.chdir(ROOT)


def report(kind, error, tb):
    message = ''.join(traceback.format_exception(kind, error, tb))
    try:
        log = ROOT / 'userdata' / 'startup.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a', encoding='utf-8') as output:
            output.write(message + '\n')
        location = str(log)
    except OSError:
        location = 'The error log could not be written.'
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, str(error) + '\n\nDetails: ' + location, 'PicoPod error', 0x10)


try:
    import tkinter as tk
    tk.Tk.report_callback_exception = lambda self, kind, error, tb: report(kind, error, tb)
    if '--self-test' in sys.argv:
        import json
        import subprocess
        import tempfile
        from manager.app import App
        from manager.state import LibraryStore
        from manager.paths import ASSET_ROOT, usb_command
        from manager.live import Mirror
        import mutagen.mp3
        with tempfile.TemporaryDirectory() as temporary:
            root = tk.Tk()
            root.withdraw()
            app = App(root, store=LibraryStore(Path(temporary) / 'state.json'))
            root.update()
            display = tk.Toplevel(root)
            display.withdraw()
            mirror = Mirror(display, 32)
            mirror.update('00' * 512)
            assert (ASSET_ROOT / 'firmware' / 'main.py').is_file()
            assert (ASSET_ROOT / 'manager' / 'cards.ps1').is_file()
            command = usb_command('list', [])
            # No hardware command: ask the bundled helper for its version only.
            command = command[:1] + ['--version'] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'mpremote', '--version']
            result = subprocess.run(command, capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            assert result.returncode == 0, result.stderr
            output = {'ok': True, 'gui': True, 'pixel_rendering': True, 'firmware': True, 'usb_helper': result.stdout.strip(),
                      'runtime_prefix': sys.prefix, 'tcl_library': root.tk.eval('info library')}
            if getattr(sys, 'frozen', False):
                assert Path(sys.prefix).resolve().is_relative_to(ASSET_ROOT.resolve())
                assert Path(output['tcl_library']).resolve().is_relative_to(ASSET_ROOT.resolve())
            (ROOT / 'self-test-result.json').write_text(json.dumps(output), encoding='utf-8')
            root.destroy()
    elif '--preview' in sys.argv:
        from manager.preview import main
        sys.argv.remove('--preview')
        main()
    else:
        from manager.app import App
        root = tk.Tk()
        App(root)
        root.mainloop()
except Exception:
    report(*sys.exc_info())
