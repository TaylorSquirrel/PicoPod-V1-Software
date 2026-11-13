"""Portable, atomically saved desktop library with stable song references."""
import hashlib
import json
import os
from pathlib import Path
import uuid
from manager.paths import APP_ROOT

DEFAULT_PATH = APP_ROOT / 'userdata' / 'library-state.json'


def validate(state):
    if state.get('version') != 1 or not isinstance(state.get('tracks'), list) or not isinstance(state.get('playlists'), list):
        raise ValueError('Invalid saved library format')
    ids = set()
    for track in state['tracks']:
        uid = track.get('uid')
        if not isinstance(uid, str) or not uid or uid in ids:
            raise ValueError('Invalid or duplicate saved song identity')
        ids.add(uid)
        if any(not isinstance(track.get(key), str) for key in ('source', 'title', 'artist')):
            raise ValueError('Invalid saved song metadata')
        if type(track.get('duration_ms')) is not int or track['duration_ms'] <= 0:
            raise ValueError('Invalid saved song duration')
    names, playlist_ids = set(), set()
    for playlist in state['playlists']:
        name = playlist.get('name')
        uid = playlist.get('uid')
        if not isinstance(name, str) or not name.strip() or len(name) > 64 or name.casefold() in names:
            raise ValueError('Invalid or duplicate playlist name')
        if not isinstance(uid, str) or not uid or uid in playlist_ids:
            raise ValueError('Invalid playlist identity')
        names.add(name.casefold())
        playlist_ids.add(uid)
        if not isinstance(playlist.get('tracks'), list) or any(song not in ids for song in playlist['tracks']):
            raise ValueError('Playlist references a missing song')
    return state


def playlist_manifest(tracks, playlists):
    """Rebuild DFPlayer IDs for the current export, preserving playlist order."""
    ids = {track['uid']: index for index, track in enumerate(tracks, 1)}
    result = []
    for playlist in playlists:
        try:
            members = [ids[uid] for uid in playlist['tracks']]
        except KeyError as error:
            raise ValueError('Playlist references a song outside this library: ' + playlist['name']) from error
        result.append({'name': playlist['name'], 'tracks': members})
    return result


def remove_songs(tracks, playlists, removed):
    remaining = [track for track in tracks if track['uid'] not in removed]
    updated = [dict(playlist, tracks=[uid for uid in playlist['tracks'] if uid not in removed]) for playlist in playlists]
    return remaining, updated


class LibraryStore:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self.backup = self.path.with_suffix('.bak')
        self.revision = None
        self.warning = None
        self.blocked = False

    def fingerprint(self):
        return hashlib.sha256(self.path.read_bytes()).digest() if self.path.exists() else None

    def load(self):
        self.revision = self.fingerprint()
        errors = []
        for path in (self.path, self.backup):
            if not path.exists():
                continue
            try:
                result = validate(json.loads(path.read_text(encoding='utf-8')))
                if path == self.backup:
                    self.warning = 'Recovered the last saved library from its backup. ' + '; '.join(errors)
                return result
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
                errors.append(path.name + ': ' + str(error))
        if errors:
            self.blocked = True
            self.warning = 'Saved library could not be read; it has been preserved and autosave is disabled. ' + '; '.join(errors)
        return {'version': 1, 'tracks': [], 'playlists': [], 'port': ''}

    def atomic_write(self, path, data):
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def save(self, tracks, playlists, port=''):
        if self.blocked:
            raise RuntimeError('Autosave is disabled because the existing saved library is damaged. Preserve and recover the files in ' + str(self.path.parent))
        if self.fingerprint() != self.revision:
            raise RuntimeError('The saved library changed in another window. Close this window and reopen the manager before editing further.')
        state = validate({'version': 1, 'tracks': tracks, 'playlists': playlists, 'port': port})
        data = json.dumps(state, ensure_ascii=False, indent=2).encode('utf-8')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            old = self.path.read_bytes()
            try:
                validate(json.loads(old))
            except (ValueError, TypeError, KeyError, AttributeError):
                pass  # Never replace a good backup with a corrupt primary file.
            else:
                self.atomic_write(self.backup, old)
        self.atomic_write(self.path, data)
        self.revision = hashlib.sha256(data).digest()
