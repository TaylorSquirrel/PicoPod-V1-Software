"""Device-manifest validation shared by MicroPython and the desktop uploader."""
import json
import os
try:
    from indexed import validate_index_header, DiskCatalog
except ImportError:
    from firmware.indexed import validate_index_header, DiskCatalog


def validate_catalog(data):
    if isinstance(data, dict) and data.get('version') == 2:
        return validate_index_header(data)
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported device library format')
    tracks = data.get('tracks')
    if not isinstance(tracks, list):
        raise ValueError('Device library must contain a tracks list')
    if 'port' in data or any(isinstance(t, dict) and ('source' in t or 'uid' in t) for t in tracks):
        raise ValueError('This is the PC saved library, not the device library. Select library.json from the exported SD card.')
    ids = set()
    for track in tracks:
        if not isinstance(track, dict):
            raise ValueError('Invalid device song entry')
        number = track.get('id')
        if type(number) is not int or not 1 <= number <= 3000 or number in ids:
            raise ValueError('Invalid or duplicate device track ID')
        ids.add(number)
        if not isinstance(track.get('title'), str) or not isinstance(track.get('artist'), str):
            raise ValueError('Invalid song title or artist')
        if type(track.get('duration_ms')) is not int or track['duration_ms'] <= 0:
            raise ValueError('Invalid song duration')
        if 'file' in track and track['file'] != 'mp3/%04d.mp3' % number:
            raise ValueError('Song filename does not match its track ID')
    playlists = data.get('playlists', [])
    if not isinstance(playlists, list):
        raise ValueError('Invalid playlists list')
    names = set()
    for playlist in playlists:
        if not isinstance(playlist, dict):
            raise ValueError('Invalid playlist entry')
        name = playlist.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 64 or name.lower() in names:
            raise ValueError('Invalid or duplicate playlist name')
        names.add(name.lower())
        members = playlist.get('tracks')
        if not isinstance(members, list) or any(type(i) is not int or i not in ids for i in members):
            raise ValueError('Playlist references a missing device track')
    return data


def load_catalog(path, max_bytes=48000):
    with open(path) as source:
        if os.stat(path)[6] > max_bytes:
            header = source.read(512).replace(' ', '').replace('\n', '').replace('\r', '')
            if '"source":' in header or '"uid":' in header:
                raise ValueError('PC saved library uploaded. Upload the exported SD card library.json instead.')
            raise ValueError('Device library exceeds metadata budget')
        data = json.load(source)
    validate_catalog(data)
    if data['version'] == 2:
        normalized = str(path).replace('\\', '/')
        directory = normalized.rsplit('/', 1)[0] if '/' in normalized else '.'
        return DiskCatalog(data, directory).library()
    return data


def cleanup_catalogs(active=None, directory='.'):
    """Remove only generated, unreferenced catalog blobs after a valid boot."""
    for name in os.listdir(directory):
        if (name != active and len(name) == 44 and name.startswith('catalog-') and name.endswith('.bin')
                and all(ch in '0123456789abcdef' for ch in name[8:-4])):
            os.remove(directory.rstrip('/\\') + '/' + name)
