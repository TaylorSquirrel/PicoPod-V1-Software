"""GUI entry point with file-based error logging on Linux."""
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
            output.write(''.join(traceback.format_exception(kind, error, tb)) + '\n')
    except OSError:
        pass
    messagebox.showerror('PicoPod error', str(error) + '\nDetails: ' + str(log))

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
