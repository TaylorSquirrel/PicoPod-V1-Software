"""Playlist editor backed by the manager's automatically saved library."""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import uuid


class PlaylistEditor:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('PicoPod · Playlists')
        self.window.geometry('960x620')
        self.window.minsize(800, 500)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.selected_uid = None
        outer = ttk.Frame(self.window, padding=18)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Playlists', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='Changes save automatically. Upload to apply them on PicoPod.').pack(anchor='w', pady=(0, 12))
        body = ttk.Frame(outer)
        body.pack(fill='both', expand=True)
        left = ttk.Frame(body)
        left.pack(side='left', fill='y', padx=(0, 16))
        self.names = tk.Listbox(left, width=25, exportselection=False)
        self.names.pack(fill='both', expand=True)
        self.names.bind('<<ListboxSelect>>', self.choose)
        for text, action in [('New playlist', self.create), ('Rename', self.rename), ('Delete playlist', self.delete)]:
            ttk.Button(left, text=text, command=action).pack(fill='x', pady=(6, 0))
        right = ttk.Frame(body)
        right.pack(side='left', fill='both', expand=True)
        ttk.Label(right, text='Library — select songs to add').pack(anchor='w')
        self.available = tk.Listbox(right, selectmode='extended', exportselection=False, height=7)
        self.available.pack(fill='both', expand=True, pady=5)
        ttk.Button(right, text='Add selected songs ↓', command=self.add).pack(anchor='w', pady=(0, 8))
        self.heading = tk.StringVar(value='Choose or create a playlist')
        ttk.Label(right, textvariable=self.heading).pack(anchor='w')
        self.members = tk.Listbox(right, selectmode='extended', exportselection=False, height=8)
        self.members.pack(fill='both', expand=True, pady=5)
        row = ttk.Frame(right)
        row.pack(fill='x')
        for text, action in [('Move up', lambda: self.move(-1)), ('Move down', lambda: self.move(1)),
                             ('Remove from playlist', self.remove)]:
            ttk.Button(row, text=text, command=action).pack(side='left', padx=(0, 6))
        ttk.Button(outer, text='Done', command=self.close).pack(anchor='e', pady=(12, 0))
        self.refresh()

    def current(self):
        return next((playlist for playlist in self.app.playlists if playlist['uid'] == self.selected_uid), None)

    def refresh(self, selection=None):
        self.names.delete(0, 'end')
        for index, playlist in enumerate(self.app.playlists):
            self.names.insert('end', '%s (%d)' % (playlist['name'], len(playlist['tracks'])))
            if playlist['uid'] == self.selected_uid:
                self.names.selection_set(index)
        self.available.delete(0, 'end')
        for track in self.app.tracks:
            self.available.insert('end', track['title'] + ' — ' + track['artist'])
        self.refresh_members(selection)

    def refresh_members(self, selection=None):
        self.members.delete(0, 'end')
        playlist = self.current()
        self.heading.set(playlist['name'] + ' — playback order' if playlist else 'Choose or create a playlist')
        songs = {track['uid']: track for track in self.app.tracks}
        if playlist:
            for number, uid in enumerate(playlist['tracks'], 1):
                track = songs[uid]
                self.members.insert('end', '%d. %s — %s' % (number, track['title'], track['artist']))
            for index in selection or []:
                self.members.selection_set(index)

    def choose(self, event=None):
        selected = self.names.curselection()
        if selected:
            self.selected_uid = self.app.playlists[selected[0]]['uid']
            self.refresh_members()

    def name(self, initial=''):
        result = simpledialog.askstring('Playlist name', 'Name (1–64 characters):', initialvalue=initial, parent=self.window)
        if result is None:
            return None
        result = result.strip()
        if not result or len(result) > 64:
            messagebox.showerror('PicoPod', 'Use a name from 1 to 64 characters.', parent=self.window)
            return None
        if any(p['name'].casefold() == result.casefold() and p['uid'] != self.selected_uid for p in self.app.playlists):
            messagebox.showerror('PicoPod', 'A playlist with that name already exists.', parent=self.window)
            return None
        return result

    def changed(self, selection=None):
        self.app.save_state()
        self.refresh(selection)

    def create(self):
        previous = self.selected_uid
        self.selected_uid = None
        name = self.name()
        if name is None:
            self.selected_uid = previous
            return
        self.selected_uid = uuid.uuid4().hex
        self.app.playlists.append({'uid': self.selected_uid, 'name': name, 'tracks': []})
        self.changed()

    def rename(self):
        playlist = self.current()
        if playlist:
            name = self.name(playlist['name'])
            if name is not None:
                playlist['name'] = name
                self.changed()

    def delete(self):
        playlist = self.current()
        if playlist and messagebox.askyesno('Delete playlist', 'Delete “%s”? Your songs will stay in the library.' % playlist['name'],
                                          parent=self.window, default='no'):
            self.app.playlists.remove(playlist)
            self.selected_uid = None
            self.changed()

    def add(self):
        playlist = self.current()
        if not playlist:
            messagebox.showinfo('PicoPod', 'Choose or create a playlist first.', parent=self.window)
            return
        for index in self.available.curselection():
            uid = self.app.tracks[index]['uid']
            if uid not in playlist['tracks']:
                playlist['tracks'].append(uid)
        self.changed()

    def remove(self):
        playlist = self.current()
        if playlist:
            selected = set(self.members.curselection())
            playlist['tracks'] = [uid for index, uid in enumerate(playlist['tracks']) if index not in selected]
            self.changed()

    def move(self, delta):
        playlist = self.current()
        if not playlist:
            return
        selected = set(self.members.curselection())
        indices = sorted(selected, reverse=delta > 0)
        for index in indices:
            target = index + delta
            if 0 <= target < len(playlist['tracks']) and target not in selected:
                playlist['tracks'][index], playlist['tracks'][target] = playlist['tracks'][target], playlist['tracks'][index]
                selected.remove(index)
                selected.add(target)
        self.changed(sorted(selected))

    def close(self):
        self.app.playlist_editor = None
        self.window.destroy()
