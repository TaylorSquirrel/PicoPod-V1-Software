"""Restore an existing PicoPod card export into a new PC library, without erasing."""
import json
from pathlib import Path
import shutil
import uuid
from manager.state import validate


def recover_export(root, store, cache):
    state = store.load()
    if store.blocked or state['tracks'] or state['playlists']:
        raise ValueError('A saved PC library already exists or needs recovery; it will not be replaced.')
    root, cache = Path(root), Path(cache)
    library = json.loads((root / 'library.json').read_text(encoding='utf-8'))
    disk = None
    if library.get('version') == 2:
        from firmware.indexed import DiskCatalog
        disk = DiskCatalog(library, str(root))
        originals = list(disk.tracks)
        original_playlists = [{'name': p['name'], 'tracks': list(p['tracks'])} for p in disk.playlists]
        disk.close()
        maximum = 25000
    elif library.get('version') == 1 and isinstance(library.get('tracks'), list):
        originals, original_playlists = library['tracks'], library.get('playlists', [])
        maximum = 3000
    else:
        raise ValueError('Not a PicoPod card export')
    tracks, sources, ids = [], [], {}
    for original in originals:
        number = original['id']
        if type(number) is not int or not 1 <= number <= maximum or number in ids:
            raise ValueError('Invalid card track ID')
        uid = uuid.uuid4().hex
        source = root / original['file'] if library['version'] == 2 else root / 'mp3' / ('%04d.mp3' % number)
        if not source.is_file():
            raise ValueError('Card export is missing ' + source.name)
        track = {'uid': uid, 'source': str((cache / (uid + '.mp3')).resolve()),
                 'title': original['title'], 'artist': original.get('artist', 'Unknown artist'),
                 'duration_ms': original['duration_ms']}
        tracks.append(track)
        sources.append(source)
        ids[number] = uid
    playlists = []
    for original in original_playlists:
        playlists.append({'uid': uuid.uuid4().hex, 'name': original['name'],
                          'tracks': [ids[number] for number in original['tracks']]})
    validate({'version': 1, 'tracks': tracks, 'playlists': playlists})
    if not tracks:
        raise ValueError('The card export has no songs to restore')
    if shutil.disk_usage(cache.parent if cache.parent.exists() else store.path.parent.parent).free < sum(p.stat().st_size for p in sources) + 1024**2:
        raise ValueError('Not enough PC storage to recover the card library')
    cache.mkdir(parents=True, exist_ok=True)
    for source, track in zip(sources, tracks):
        with source.open('rb') as src, Path(track['source']).open('xb') as dst:
            shutil.copyfileobj(src, dst)
    store.save(tracks, playlists, state.get('port', ''))
    return len(tracks), len(playlists)
