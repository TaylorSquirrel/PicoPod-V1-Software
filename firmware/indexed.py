"""Paged compressed catalog: bounded RAM even with 25,000 songs."""
import json
import struct
import io
import hashlib
import binascii

MAX_SONGS = 25000
MAX_INDEX_BYTES = 1200000
PAGE_SIZE = 16
MAX_PAGE_BYTES = 8192


def audio_path(number):
    if not 1 <= number <= MAX_SONGS:
        raise ValueError('Song ID outside 1–25000')
    return '%02d/%03d.mp3' % ((number - 1) // 255 + 1, (number - 1) % 255 + 1)


def validate_index_header(data):
    count = data.get('track_count')
    c = data.get('catalog')
    if data.get('layout') != 'folders255' or type(count) is not int or not 1 <= count <= MAX_SONGS or not isinstance(c, dict):
        raise ValueError('Invalid indexed device library')
    filename = c.get('file', '')
    if not isinstance(filename, str) or not filename.startswith('catalog-') or not filename.endswith('.bin') or len(filename) > 64 or any(ch not in 'abcdefghijklmnopqrstuvwxyz0123456789-.' for ch in filename):
        raise ValueError('Invalid catalog filename')
    size = c.get('size')
    if type(size) is not int or not 4 <= size <= MAX_INDEX_BYTES:
        raise ValueError('Indexed metadata exceeds Pico 1 flash budget')
    digest = c.get('sha256', '')
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in '0123456789abcdef' for ch in digest):
        raise ValueError('Invalid catalog checksum')
    for name in ('tracks', 'artists', 'playlists'):
        table = c.get(name)
        if not isinstance(table, dict) or type(table.get('count')) is not int or not 0 <= table['count'] <= MAX_SONGS:
            raise ValueError('Invalid catalog table')
        pages = (table['count'] + PAGE_SIZE - 1) // PAGE_SIZE
        if type(table.get('index')) is not int or not 4 <= table['index'] <= size or table['index'] + pages * 8 > size:
            raise ValueError('Catalog index outside file')
    if c['tracks']['count'] != count:
        raise ValueError('Catalog track count mismatch')
    return data


class IdRange:
    def __init__(self, count, start=1):
        self.count, self.start = count, start

    def __len__(self):
        return self.count

    def __iter__(self):
        for index in range(self.count):
            yield self[index]

    def __getitem__(self, index):
        if isinstance(index, slice):
            if index.start is None and index.stop is None and index.step is None:
                return self
            raise ValueError('Only full ID range slices supported')
        if index < 0:
            index += self.count
        if not 0 <= index < self.count:
            raise IndexError(index)
        return self.start + index


class FileIds:
    def __init__(self, disk, offset, count):
        if type(offset) is not int or type(count) is not int or not 0 <= count <= MAX_SONGS or not 4 <= offset <= disk.size or offset + count * 2 > disk.size:
            raise ValueError('Invalid catalog song list')
        self.disk, self.offset, self.count = disk, offset, count

    def __len__(self):
        return self.count

    def __iter__(self):
        for index in range(self.count):
            yield self[index]

    def __getitem__(self, index):
        if isinstance(index, slice):
            if index.start is None and index.stop is None and index.step is None:
                return self
            raise ValueError('Only full song-list slices supported')
        if index < 0:
            index += self.count
        if not 0 <= index < self.count:
            raise IndexError(index)
        value = struct.unpack('<H', self.disk.read(self.offset + index * 2, 2))[0]
        if not 1 <= value <= self.disk.count:
            raise ValueError('Catalog has invalid song reference')
        return value


class Rows:
    def __init__(self, disk, kind, count):
        self.disk, self.kind, self.count = disk, kind, count

    def __len__(self):
        return self.count

    def __iter__(self):
        for index in range(self.count):
            yield self[index]

    def __getitem__(self, index):
        if index < 0:
            index += self.count
        if not 0 <= index < self.count:
            raise IndexError(index)
        if self.kind == 'tracks':
            return self.disk.track(index + 1)
        row = self.disk.row('playlists' if self.kind == 'playlist_names' else self.kind, index)
        if self.kind in ('artists', 'playlist_names'):
            return row[0]
        return {'name': row[0], 'tracks': FileIds(self.disk, row[1], row[2])}


class ById:
    def __init__(self, disk):
        self.disk = disk

    def __contains__(self, number):
        return type(number) is int and 1 <= number <= self.disk.count

    def __getitem__(self, number):
        if number not in self:
            raise KeyError(number)
        return self.disk.track(number)

    def get(self, number, default=None):
        return self[number] if number in self else default


class TitleRows:
    def __init__(self, by_id, ids):
        self.by_id, self.ids = by_id, ids

    def __len__(self):
        return len(self.ids) + 1

    def __getitem__(self, index):
        if index == 0:
            return 'Shuffle all'
        return self.by_id[self.ids[index - 1]]['title']


class DiskCatalog:
    def __init__(self, data, directory='.', verify=True):
        validate_index_header(data)
        self.meta = data['catalog']
        self.size, self.count = self.meta['size'], data['track_count']
        path = directory.rstrip('/\\') + '/' + self.meta['file']
        self.file = open(path, 'rb')
        try:
            if self.file.read(4) != b'PPC2':
                raise ValueError('Invalid catalog signature')
            self.file.seek(0, 2)
            if self.file.tell() != self.size:
                raise ValueError('Catalog file is incomplete')
            if verify:
                self.file.seek(0)
                digest = hashlib.sha256()
                while True:
                    block = self.file.read(4096)
                    if not block:
                        break
                    digest.update(block)
                if binascii.hexlify(digest.digest()).decode() != self.meta['sha256']:
                    raise ValueError('Catalog checksum mismatch')
        except Exception:
            self.file.close()
            raise
        self.cache = {}
        self.all_ids = IdRange(self.count)
        self.tracks = Rows(self, 'tracks', self.count)
        self.artists = Rows(self, 'artists', self.meta['artists']['count'])
        self.playlists = Rows(self, 'playlists', self.meta['playlists']['count'])
        self.playlist_names = Rows(self, 'playlist_names', self.meta['playlists']['count'])
        self.by_id = ById(self)

    def close(self):
        self.file.close()

    def read(self, offset, count):
        if offset < 4 or count < 0 or offset + count > self.size:
            raise ValueError('Catalog read outside file')
        self.file.seek(offset)
        result = self.file.read(count)
        if len(result) != count:
            raise ValueError('Incomplete catalog read')
        return result

    def row(self, kind, index):
        table = self.meta[kind]
        if not 0 <= index < table['count']:
            raise IndexError(index)
        page = index // PAGE_SIZE
        cached = self.cache.get(kind)
        if cached is None or cached[0] != page:
            offset, length = struct.unpack('<II', self.read(table['index'] + page * 8, 8))
            if not 1 <= length <= 32768:
                raise ValueError('Invalid catalog page length')
            compressed = self.read(offset, length)
            try:
                import deflate
            except ImportError:
                import zlib
                raw = zlib.decompress(compressed)
            else:
                with deflate.DeflateIO(io.BytesIO(compressed), deflate.ZLIB) as stream:
                    raw = stream.read(MAX_PAGE_BYTES + 1)
            if len(raw) > MAX_PAGE_BYTES:
                raise ValueError('Catalog page exceeds RAM budget')
            rows = json.loads(raw)
            if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
                raise ValueError('Invalid catalog page')
            self.cache[kind] = (page, rows)
            cached = self.cache[kind]
        return cached[1][index % PAGE_SIZE]

    def track(self, number):
        title, artist, duration = self.row('tracks', number - 1)
        return {'id': number, 'title': title, 'artist': self.row('artists', artist)[0],
                'duration_ms': duration, 'file': audio_path(number)}

    def artist_tracks(self, index):
        row = self.row('artists', index)
        return FileIds(self, row[1], row[2])

    def library(self):
        return {'tracks': self.tracks, 'playlists': self.playlists, 'catalog_object': self}
