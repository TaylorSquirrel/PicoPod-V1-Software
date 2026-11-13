"""PC-side library preparation. Never formats drives or deletes existing audio."""
import json
import os
from pathlib import Path
import shutil
import uuid
import tempfile
from firmware.catalog import validate_catalog
from firmware.indexed import DiskCatalog, MAX_SONGS, audio_path

MAX_MANIFEST_BYTES = 48000  # Conservative Pico 1 / Pico W (RP2040) metadata budget.


def serialize_manifest(data):
    return json.dumps(data, ensure_ascii=True, separators=(',', ':'))


def validate_device_file(path):
    path = Path(path)
    data = validate_catalog(json.loads(path.read_text(encoding='utf-8')))
    if len(serialize_manifest(data).encode('utf-8')) > MAX_MANIFEST_BYTES:
        raise ValueError('Device library exceeds the 48 KB Pico 1 metadata budget. Re-export a smaller library.')
    if data['version'] == 2:
        disk = DiskCatalog(data, str(path.parent))
        disk.close()
    return data


def read_track(path):
    from mutagen.mp3 import EasyMP3
    path = Path(path).resolve()
    if path.suffix.lower() != '.mp3':
        raise ValueError('Only MP3 is supported in this first version')
    audio = EasyMP3(path)
    return {'uid': uuid.uuid4().hex, 'source': str(path), 'title': str(audio.get('title', [path.stem])[0]),
            'artist': str(audio.get('artist', ['Unknown artist'])[0]),
            'duration_ms': round(audio.info.length * 1000)}


def manifest(tracks, playlists=None):
    if len(tracks) > 3000:
        raise ValueError('This version supports up to 3000 songs')
    clean = []
    for index, track in enumerate(tracks, 1):
        duration = int(track['duration_ms'])
        if duration <= 0:
            raise ValueError('Invalid duration: ' + track['title'])
        clean.append({'id': index, 'title': track['title'], 'artist': track['artist'],
                      'duration_ms': duration, 'file': 'mp3/%04d.mp3' % index})
    exported_playlists = []
    names = set()
    for playlist in playlists or []:
        name = playlist['name'].strip()
        if not name or len(name) > 64 or name.casefold() in names:
            raise ValueError('Playlist names must be unique and 1–64 characters long')
        members = list(playlist['tracks'])
        if any(type(track_id) is not int or not 1 <= track_id <= len(clean) for track_id in members):
            raise ValueError('Playlist contains an invalid song ID: ' + name)
        names.add(name.casefold())
        exported_playlists.append({'name': name, 'tracks': members})
    result = {'version': 1, 'library_id': uuid.uuid4().hex,
              'tracks': clean, 'playlists': exported_playlists}
    if len(serialize_manifest(result).encode('utf-8')) > MAX_MANIFEST_BYTES:
        raise ValueError('Library is too large for the default Pico 1 metadata budget (48 KB).')
    return result


def build_bundle(tracks, playlists, destination):
    if not 1 <= len(tracks) <= MAX_SONGS:
        raise ValueError('PicoPod supports 1–25,000 songs per card')
    if len(tracks) <= 3000:
        try:
            data = manifest(tracks, playlists)
        except ValueError as error:
            if 'metadata budget' not in str(error):
                raise
            data = None
    else:
        data = None
    if data is None:
        from manager.indexed import build_index
        data = build_index(tracks, playlists, destination)
    target = Path(destination) / 'library.json'
    with target.open('x', encoding='utf-8', newline='\n') as output:
        output.write(serialize_manifest(data))
        output.flush()
        os.fsync(output.fileno())
    return data


def prepare(tracks, destination, progress=lambda message: None, playlists=None):
    """Export a new card library. Refuse an occupied mp3 directory to avoid remaps."""
    if not tracks:
        raise ValueError('Add some MP3 files first')
    destination = Path(destination).resolve()
    if not destination.is_dir():
        raise ValueError('Choose an existing SD card or export folder')
    output = destination / 'mp3'
    if output.exists() and any(output.iterdir()):
        raise ValueError('The mp3 folder is not empty. Choose a fresh export folder or a clean card.')
    if (destination / 'library.json').exists():
        raise ValueError('library.json already exists. Choose a fresh export folder.')
    sources = [Path(t['source']).resolve() for t in tracks]
    total = sum(source.stat().st_size for source in sources)
    if shutil.disk_usage(destination).free < total + 1024 * 1024:
        raise ValueError('Not enough free space')
    with tempfile.TemporaryDirectory(prefix='.picopod-metadata-', dir=destination) as temporary:
        library = build_bundle(tracks, playlists, temporary)
        if library['version'] == 2:
            for number in range(1, (len(tracks) - 1) // 255 + 2):
                folder = destination / ('%02d' % number)
                if folder.exists() and any(folder.iterdir()):
                    raise ValueError('Numbered audio folder is not empty. Choose a fresh export folder.')
        # Publish metadata only after audio copies finish.
        for number, (track, source) in enumerate(zip(tracks, sources), 1):
            relative = audio_path(number) if library['version'] == 2 else 'mp3/%04d.mp3' % number
            progress('Copying %05d: %s' % (number, track['title']))
            target = destination / relative
            target.parent.mkdir(exist_ok=True)
            with source.open('rb') as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
        if library['version'] == 2:
            name = library['catalog']['file']
            (Path(temporary) / name).rename(destination / name)
        (Path(temporary) / 'library.json').rename(destination / 'library.json')
    progress('Export complete. Safely eject the card, then upload this library.json to the Pico.')
    return library
