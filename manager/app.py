"""Run from the project root: python -m manager.app"""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from manager.library import read_track, prepare, manifest, validate_device_file, serialize_manifest, build_bundle
from manager.live import verify_pico
from manager.live import LiveWindow
from manager.uploader import plan_upload, execute_upload
from manager.state import LibraryStore, playlist_manifest, remove_songs
from manager.playlists import PlaylistEditor
from manager.paths import APP_ROOT, ASSET_ROOT, usb_command, preview_command

ROOT = APP_ROOT


class App:
    def __init__(self, root, store=None):
        self.root = root
        self.store = store or LibraryStore()
        restored = self.store.load()
        self.tracks = restored['tracks']
        self.playlists = restored['playlists']
        self.playlist_editor = None
        self.messages = queue.Queue()
        self.busy = False
        self.live_window = None
        self.pending_plan = None
        root.title('PicoPod · Library Manager')
        root.geometry('1100x720')
        root.minsize(1000, 580)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Treeview', rowheight=30)
        outer = ttk.Frame(root, padding=24)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='PicoPod', font=('Segoe UI', 28, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='Your music. Two tiny screens. One pocket.', font=('Segoe UI', 11)).pack(anchor='w', pady=(0, 18))
        self.save_status = tk.StringVar(value='Library and playlists save automatically.')
        ttk.Label(outer, textvariable=self.save_status).pack(anchor='w', pady=(0, 8))
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill='x', pady=(0, 12))
        self.buttons = []
        for label, command in [('Add MP3s', self.add), ('Remove selected', self.remove),
                               ('Playlists', self.edit_playlists),
                               ('Export only', self.export), ('Offline preview', self.preview),
                               ('Live PicoPod', self.live), ('Upload everything…', self.quick_upload)]:
            button = ttk.Button(toolbar, text=label, command=command)
            button.pack(side='left', padx=(0, 8))
            self.buttons.append(button)
        self.tree = ttk.Treeview(outer, columns=('id', 'title', 'artist', 'duration', 'status'), show='headings')
        for key, title, width in [('id', 'Track ID', 65), ('title', 'Song', 330), ('artist', 'Artist', 220), ('duration', 'Duration', 90), ('status', 'Source', 100)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width)
        self.tree.pack(fill='both', expand=True)
        ttk.Label(outer, text='Add MP3s → Connect Pico + PICOPOD card in a PC reader → Upload everything… (erase confirmation required)',
                  padding=(0, 14)).pack(anchor='w')
        row = ttk.Frame(outer)
        row.pack(fill='x')
        ttk.Label(row, text='Pico USB port:').pack(side='left')
        self.port = tk.StringVar(value=restored.get('port', ''))
        self.ports = ttk.Combobox(row, textvariable=self.port, width=16)
        self.ports.pack(side='left', padx=8)
        for label, command in [('Refresh', self.refresh), ('Install firmware', self.install), ('Upload library.json', self.upload)]:
            button = ttk.Button(row, text=label, command=command)
            button.pack(side='left', padx=4)
            self.buttons.append(button)
        self.log = tk.Text(outer, height=7, bg='#101c24', fg='#8ce4d6', font=('Consolas', 10), state='disabled')
        self.log.pack(fill='x', pady=(16, 0))
        self.refresh()
        self.root.after(100, self.poll)
        self.write('Ready. Install MicroPython on the Pico before installing PicoPod firmware.')
        self.redraw()
        self.write('Restored %d songs and %d playlists.' % (len(self.tracks), len(self.playlists)))
        if self.store.warning:
            self.write(self.store.warning)
            self.save_status.set('Saved library needs attention — see log.')

    def write(self, message):
        self.log.configure(state='normal')
        self.log.insert('end', str(message) + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def worker(self, function):
        if self.busy:
            return
        if self.playlist_editor is not None:
            self.playlist_editor.close()
        self.busy = True
        for button in self.buttons:
            button.configure(state='disabled')
        def task():
            try:
                function()
            except Exception as error:
                self.messages.put(('error', str(error)))
            finally:
                self.messages.put(('done', None))
        threading.Thread(target=task, daemon=True).start()

    def poll(self):
        while not self.messages.empty():
            kind, data = self.messages.get()
            if kind == 'done':
                self.busy = False
                for button in self.buttons:
                    button.configure(state='normal')
            elif kind == 'tracks':
                self.tracks.extend(data)
                self.save_state()
                self.redraw()
            elif kind == 'plan':
                self.pending_plan = data
            elif kind == 'error':
                self.write('ERROR: ' + data)
                messagebox.showerror('PicoPod', data)
            else:
                self.write(data)
        if self.pending_plan is not None and not self.busy:
            plan, self.pending_plan = self.pending_plan, None
            card = plan.card
            incremental = plan.sync is not None
            preparation = ('keep FAT32 and update its managed music files'
                           if incremental else 'quick-format it as FAT32')
            summary = ('Reuse %d unchanged · rename %d · copy %d · remove %d obsolete managed files.\nUnrelated files are preserved.\n' %
                       (len(plan.sync.keep), len(plan.sync.renames), len(plan.sync.copies), len(plan.sync.obsolete))) if incremental else 'Everything currently on this card will be lost.\n'
            confirmation = (('UPDATE this card?\n\n' if incremental else 'ERASE ALL DATA on this card?\n\n') +
                            f"Target: {card['DriveLetter']}\nLabel: PICOPOD\n"
                            f"Capacity: {card['Size'] / 1024**3:.2f} GiB\n"
                            f"Disk identity: {card['DiskUniqueId']}\n"
                            f"Current filesystem: {card['FileSystem']}\n\n"
                            f"This will {preparation}, synchronize {plan.count} songs, "
                            'verify the copies, and upload their metadata to the Pico.\n\n'
                            + summary + '\nContinue?')
            if messagebox.askyesno('PicoPod — confirm card update' if incremental else 'PicoPod — confirm card erase', confirmation, icon='warning', default='no'):
                self.worker(lambda: execute_upload(plan, self.upload_metadata, confirmed=True,
                                                   progress=lambda msg: self.messages.put(('log', msg))))
            else:
                plan.close()
                self.write('Upload cancelled. The SD card was not changed.')
        self.root.after(100, self.poll)

    def redraw(self):
        self.tree.delete(*self.tree.get_children())
        for index, track in enumerate(self.tracks):
            seconds = track['duration_ms'] // 1000
            self.tree.insert('', 'end', iid=str(index), values=(f'{index + 1:04}', track['title'], track['artist'], f'{seconds // 60}:{seconds % 60:02}',
                                                              'Available' if Path(track['source']).is_file() else 'Missing file'))

    def add(self):
        paths = filedialog.askopenfilenames(filetypes=[('MP3 music', '*.mp3')])
        if not paths:
            return
        existing = {t['source'] for t in self.tracks}
        def task():
            added = []
            for path in paths:
                if str(Path(path).resolve()) in existing:
                    continue
                try:
                    added.append(read_track(path))
                except Exception as error:
                    self.messages.put(('log', f'Skipped {Path(path).name}: {error}'))
            self.messages.put(('tracks', added))
            self.messages.put(('log', f'Added {len(added)} songs.'))
        self.worker(task)

    def remove(self):
        selected = set(map(int, self.tree.selection()))
        removed = {track['uid'] for index, track in enumerate(self.tracks) if index in selected}
        self.tracks, self.playlists = remove_songs(self.tracks, self.playlists, removed)
        if self.playlist_editor is not None:
            self.playlist_editor.refresh()
        self.save_state()
        self.redraw()

    def export(self):
        folder = filedialog.askdirectory(title='Choose clean FAT32 SD card root or new export folder')
        if folder:
            tracks = [dict(track) for track in self.tracks]
            playlists = playlist_manifest(self.tracks, self.playlists)
            self.worker(lambda: prepare(tracks, folder, lambda msg: self.messages.put(('log', msg)), playlists=playlists))

    def refresh(self):
        try:
            from serial.tools.list_ports import comports
            ports = [port.device for port in comports()]
            self.ports['values'] = ports
            if ports and not self.port.get():
                self.port.set(ports[0])
        except ImportError:
            self.write('Install requirements.txt to enable USB port discovery and MP3 metadata.')

    def remote(self, port, arguments):
        command = usb_command(port, arguments)
        result = subprocess.run(command, capture_output=True, text=True, timeout=300,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout or 'USB transfer failed')
        self.messages.put(('log', result.stdout.strip() or 'USB transfer OK'))

    def get_port(self):
        port = self.port.get().strip()
        if not port:
            messagebox.showerror('PicoPod', 'Select the MicroPython USB serial port first.')
        return port

    def install(self):
        port = self.get_port()
        if not port:
            return
        self.close_live()
        def task():
            # main.py is copied last so incomplete installs cannot start the new app.
            files = sorted((ASSET_ROOT / 'firmware').glob('*.py'), key=lambda p: p.name == 'main.py')
            for path in files:
                self.messages.put(('log', 'Installing ' + path.name))
                self.remote(port, ['fs', 'cp', str(path), ':' + path.name])
            self.remote(port, ['reset'])
            self.messages.put(('log', 'Firmware installed. Close other serial apps during transfers.'))
        self.worker(task)

    def upload(self):
        port = self.get_port()
        if not port:
            return
        path = filedialog.askopenfilename(title='Select library.json from the exported card', filetypes=[('Library', '*.json')])
        if not path:
            return
        try:
            validate_device_file(path)
        except Exception as error:
            messagebox.showerror('PicoPod', str(error))
            return
        self.close_live()
        def task():
            self.upload_metadata(port, path)
            self.messages.put(('log', 'Metadata uploaded. Use the matching exported microSD in the DFPlayer.'))
        self.worker(task)

    def upload_metadata(self, port, path):
        data = validate_device_file(path)
        asset = None
        if data['version'] == 2:
            asset = Path(path).parent / data['catalog']['file']
            info = verify_pico(port)
            if not info or info.get('indexed_catalog') != 2:
                raise ValueError('Install the latest firmware before uploading an indexed library.')
            reuse = info.get('active_catalog') == asset.name
            if not reuse and (info.get('storage_free') is None or info['storage_free'] < asset.stat().st_size + 16384):
                raise ValueError('Not enough Pico flash to safely stage the new catalog. Existing library was preserved.')
        with tempfile.TemporaryDirectory(prefix='picopod-metadata-') as temporary:
            payload = Path(temporary) / 'library.json'
            payload.write_text(serialize_manifest(data), encoding='utf-8', newline='\n')
            arguments = []
            if asset is not None and not reuse:
                arguments += ['fs', 'cp', str(asset), ':' + asset.name, '+']
            activate = "import os, config\nfrom catalog import load_catalog\nd=load_catalog('library.new.json', config.MAX_LIBRARY_BYTES)\nc=d.get('catalog_object')\nname=c.meta['file'] if c else ''\nif c: c.close()\nos.rename('library.new.json', 'library.json')\nfor f in os.listdir():\n if f.startswith('catalog-') and f.endswith('.bin') and len(f)==44 and f!=name and all(x in '0123456789abcdef' for x in f[8:-4]): os.remove(f)"
            arguments += ['fs', 'cp', str(payload), ':library.new.json', '+', 'exec', activate, '+', 'reset']
            self.remote(port, arguments)

    def quick_upload(self):
        port = self.get_port()
        if not port:
            return
        if not self.tracks:
            messagebox.showerror('PicoPod', 'Add some MP3 files first.')
            return
        self.close_live()
        tracks = [dict(track) for track in self.tracks]
        playlists = playlist_manifest(self.tracks, self.playlists)
        def task():
            plan = plan_upload(tracks, port, lambda msg: self.messages.put(('log', msg)), playlists=playlists)
            self.messages.put(('plan', plan))
        self.worker(task)

    def close_live(self):
        if self.live_window is not None and not self.live_window.closed:
            self.live_window.close()
        self.live_window = None

    def live(self):
        port = self.get_port()
        if port:
            self.close_live()
            self.live_window = LiveWindow(self.root, port)

    def close(self):
        if self.busy:
            messagebox.showinfo('PicoPod', 'Please wait for the current transfer or format to finish before closing.')
            return
        self.close_live()
        if self.pending_plan:
            self.pending_plan.close()
        if not self.save_state() and not messagebox.askyesno('Close without saving?', 'Your latest edits could not be saved. Close anyway?', default='no'):
            return
        self.root.destroy()

    def save_state(self):
        try:
            self.store.save(self.tracks, self.playlists, self.port.get())
            self.save_status.set('Saved · %d songs · %d playlists' % (len(self.tracks), len(self.playlists)))
            return True
        except (OSError, ValueError, RuntimeError) as error:
            self.save_status.set('NOT SAVED — ' + str(error))
            self.write('Could not save library: ' + str(error))
            messagebox.showerror('PicoPod — library not saved', str(error))
            return False

    def edit_playlists(self):
        if self.playlist_editor is not None:
            self.playlist_editor.window.lift()
        else:
            self.playlist_editor = PlaylistEditor(self)

    def preview(self):
        if self.tracks:
            try:
                directory = ROOT / 'userdata' / 'preview'
                directory.mkdir(parents=True, exist_ok=True)
                # A fresh subdirectory keeps catalog snapshots independent.
                import uuid
                directory = directory / uuid.uuid4().hex
                directory.mkdir()
                build_bundle(self.tracks, playlist_manifest(self.tracks, self.playlists), directory)
                path = directory / 'library.json'
            except (OSError, ValueError) as error:
                messagebox.showerror('PicoPod', str(error))
                return
            arguments = ['--library', str(path)]
        else:
            arguments = []
        subprocess.Popen(preview_command(arguments), cwd=ROOT)


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
