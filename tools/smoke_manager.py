"""Hidden-window Tk smoke test; never invokes card formatting."""
import tkinter as tk
import tempfile
from pathlib import Path
from unittest.mock import patch
from manager.app import App
from manager.live import Mirror
from manager.state import LibraryStore

root = tk.Tk()
root.withdraw()
temporary = tempfile.TemporaryDirectory()
app = App(root, store=LibraryStore(Path(temporary.name) / 'state.json'))
root.update()
root.update_idletasks()
assert len(app.buttons) == 10
print('PASS: manager creates all upload/preview controls')
mirror_window = tk.Toplevel(root)
mirror_window.withdraw()
main = Mirror(mirror_window, 64)
small = Mirror(mirror_window, 32)
main.update(bytes([0xAA] * 1024).hex())
small.update(bytes([0x55] * 512).hex())
root.update()
print('PASS: exact-pixel mirrors render both framebuffer sizes')
app.tracks = [{'uid': 'first', 'source': 'missing-original.mp3', 'title': 'First', 'artist': 'Artist', 'duration_ms': 3000},
              {'uid': 'second', 'source': 'missing-original-2.mp3', 'title': 'Second', 'artist': 'Artist', 'duration_ms': 3000}]
app.edit_playlists()
editor = app.playlist_editor
editor.window.withdraw()
with patch('manager.playlists.simpledialog.askstring', return_value='Pocket mix'):
    editor.create()
editor.available.selection_set(0, 1)
editor.add()
editor.members.selection_set(1)
editor.move(-1)
assert app.playlists[0]['tracks'] == ['second', 'first']
restored = LibraryStore(app.store.path).load()
assert restored['playlists'] == app.playlists and restored['tracks'] == app.tracks
editor.close()
print('PASS: playlist creation, adding, reordering and autosave restoration')
mirror_window.destroy()
root.destroy()
temporary.cleanup()
