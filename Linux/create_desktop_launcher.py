from pathlib import Path

root = Path(__file__).resolve().parent
def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
entry = '[Desktop Entry]\nType=Application\nName=PicoPod\nComment=Pocket music player manager\nTerminal=false\nExec=' + quote(root / '.venv/bin/python') + ' ' + quote(root / 'launch_linux.py') + '\nCategories=AudioVideo;Audio;\n'
target = root / 'PicoPod.desktop'
target.write_text(entry, encoding='utf-8')
target.chmod(0o755)
