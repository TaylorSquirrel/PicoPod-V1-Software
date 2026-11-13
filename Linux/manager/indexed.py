"""Build compressed on-flash metadata and folder addressing for large libraries."""
import hashlib
import json
from pathlib import Path
import struct
import uuid
import zlib
from firmware.indexed import MAX_SONGS, MAX_INDEX_BYTES, PAGE_SIZE, MAX_PAGE_BYTES, validate_index_header


def build_index(tracks, playlists, destination):
    if not 1 <= len(tracks) <= MAX_SONGS:
        raise ValueError('PicoPod supports 1–25,000 songs per card')
    groups = {}
    for number, track in enumerate(tracks, 1):
        if not isinstance(track['title'], str) or not isinstance(track['artist'], str) or len(track['title']) > 256 or len(track['artist']) > 256:
            raise ValueError('Device titles and artist names must be at most 256 characters')
        if type(track['duration_ms']) is not int or track['duration_ms'] <= 0:
            raise ValueError('Invalid song duration')
        groups.setdefault(track['artist'], []).append(number)
    names = sorted(groups)
    artist_ids = {name: index for index, name in enumerate(names)}
    identity = uuid.uuid4().hex
    destination = Path(destination)
    filename = 'catalog-' + identity + '.bin'
    path = destination / filename
    tables = {}
    with path.open('xb') as output:
        output.write(b'PPC2')
        artist_rows = []
        for name in names:
            ids = groups[name]
            artist_rows.append([name, output.tell(), len(ids)])
            for number in ids:
                output.write(struct.pack('<H', number))
        playlist_rows = []
        used = set()
        for playlist in playlists or []:
            name = playlist['name'].strip()
            if not name or len(name) > 64 or name.casefold() in used:
                raise ValueError('Playlist names must be unique and 1–64 characters long')
            used.add(name.casefold())
            ids = playlist['tracks']
            if len(ids) > MAX_SONGS or any(type(i) is not int or not 1 <= i <= len(tracks) for i in ids):
                raise ValueError('Invalid playlist song IDs')
            playlist_rows.append([name, output.tell(), len(ids)])
            for number in ids:
                output.write(struct.pack('<H', number))
        def table(kind, rows):
            pages = []
            for start in range(0, len(rows), PAGE_SIZE):
                raw = json.dumps(rows[start:start + PAGE_SIZE], ensure_ascii=True, separators=(',', ':')).encode()
                if len(raw) > MAX_PAGE_BYTES:
                    raise ValueError('A metadata page is too large for Pico 1 RAM. Shorten exceptionally long titles/artist names before uploading.')
                compressed = zlib.compress(raw, 9)
                pages.append((output.tell(), len(compressed)))
                output.write(compressed)
            offset = output.tell()
            for entry in pages:
                output.write(struct.pack('<II', *entry))
            tables[kind] = {'count': len(rows), 'index': offset}
        table('tracks', [[t['title'], artist_ids[t['artist']], t['duration_ms']] for t in tracks])
        table('artists', artist_rows)
        table('playlists', playlist_rows)
    size = path.stat().st_size
    if size > MAX_INDEX_BYTES:
        raise ValueError('Compressed metadata exceeds Pico 1 flash budget; shorten metadata or use a smaller library. No card erase is needed to resolve this.')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    data = {'version': 2, 'library_id': identity, 'layout': 'folders255', 'track_count': len(tracks),
            'catalog': dict(tables, file=filename, size=size, sha256=digest)}
    validate_index_header(data)
    return data
