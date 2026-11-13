import json
from pathlib import Path
import tempfile
import unittest
from manager.state import LibraryStore, playlist_manifest, remove_songs
from manager.library import manifest, prepare
from manager.recovery import recover_export


def song(uid, source='C:/Music/song.mp3'):
    return {'uid': uid, 'source': source, 'title': 'Song ' + uid, 'artist': 'Artist', 'duration_ms': 3000}


class SavedLibraryTests(unittest.TestCase):
    def test_songs_playlists_and_order_survive_new_store(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'library-state.json'
            original = LibraryStore(path)
            original.load()
            tracks = [song('a'), song('b')]
            playlists = [{'uid': 'mix', 'name': 'Pocket mix', 'tracks': ['b', 'a']}]
            original.save(tracks, playlists, 'COM4')
            restored = LibraryStore(path).load()
            self.assertEqual(restored['tracks'], tracks)
            self.assertEqual(restored['playlists'], playlists)
            self.assertEqual(restored['port'], 'COM4')

    def test_removing_song_preserves_remaining_playlist_mapping(self):
        tracks = [song('a'), song('b'), song('c')]
        playlists = [{'uid': 'mix', 'name': 'Mix', 'tracks': ['c', 'a', 'b']}]
        tracks, playlists = remove_songs(tracks, playlists, {'a'})
        self.assertEqual(playlist_manifest(tracks, playlists), [{'name': 'Mix', 'tracks': [2, 1]}])
        self.assertEqual(manifest(tracks, playlist_manifest(tracks, playlists))['playlists'][0]['tracks'], [2, 1])

    def test_reordered_library_rebuilds_ids_without_changing_members(self):
        tracks = [song('b'), song('a')]
        playlists = [{'uid': 'mix', 'name': 'Mix', 'tracks': ['a', 'b']}]
        self.assertEqual(playlist_manifest(tracks, playlists)[0]['tracks'], [2, 1])

    def test_corrupt_primary_recovers_backup_and_preserves_good_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'library-state.json'
            store = LibraryStore(path)
            store.load()
            store.save([song('a')], [])
            store.save([song('a'), song('b')], [])
            path.write_text('interrupted or damaged JSON', encoding='utf-8')
            recovery = LibraryStore(path)
            restored = recovery.load()
            self.assertEqual(restored['tracks'], [song('a')])
            self.assertIn('Recovered', recovery.warning)
            recovery.save(restored['tracks'], restored['playlists'])
            self.assertEqual(json.loads(recovery.backup.read_text())['tracks'], [song('a')])

    def test_bad_primary_and_backup_are_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'library-state.json'
            path.write_text('broken', encoding='utf-8')
            store = LibraryStore(path)
            store.load()
            with self.assertRaises(RuntimeError):
                store.save([], [])
            self.assertEqual(path.read_text(), 'broken')

    def test_second_window_cannot_silently_overwrite_newer_library(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'library-state.json'
            first, second = LibraryStore(path), LibraryStore(path)
            first.load()
            second.load()
            first.save([song('a')], [])
            with self.assertRaises(RuntimeError):
                second.save([song('b')], [])
            self.assertEqual(LibraryStore(path).load()['tracks'], [song('a')])

    def test_export_writes_playlists_in_matching_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'original.mp3'
            source.write_bytes(b'copy test bytes')
            tracks = [song('a', str(source)), song('b', str(source))]
            playlists = [{'uid': 'mix', 'name': 'My mix', 'tracks': ['b', 'a']}]
            target = root / 'export'
            target.mkdir()
            prepare(tracks, target, playlists=playlist_manifest(tracks, playlists))
            exported = json.loads((target / 'library.json').read_text())
            self.assertEqual(exported['playlists'], [{'name': 'My mix', 'tracks': [2, 1]}])
            self.assertNotIn('uid', exported['tracks'][0])

    def test_invalid_playlist_ids_and_duplicate_names_refused(self):
        for playlists in [[{'name': 'Mix', 'tracks': [2]}],
                          [{'name': 'Mix', 'tracks': [1]}, {'name': 'mix', 'tracks': []}]]:
            with self.assertRaises(ValueError):
                manifest([song('a')], playlists)

    def test_missing_original_still_restores_as_a_remembered_song(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = LibraryStore(Path(temporary) / 'state.json')
            store.load()
            store.save([song('a', 'missing-original.mp3')], [])
            self.assertEqual(LibraryStore(store.path).load()['tracks'][0]['source'], 'missing-original.mp3')

    def test_recover_card_export_copies_songs_locally_and_keeps_playlists(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'original.mp3'
            source.write_bytes(b'audio copy test')
            card = root / 'card'
            card.mkdir()
            prepare([song('a', str(source))], card, playlists=[{'name': 'Mix', 'tracks': [1]}])
            original_manifest = (card / 'library.json').read_bytes()
            store = LibraryStore(root / 'userdata' / 'state.json')
            cache = root / 'userdata' / 'music'
            self.assertEqual(recover_export(card, store, cache), (1, 1))
            restored = LibraryStore(store.path).load()
            self.assertEqual(Path(restored['tracks'][0]['source']).read_bytes(), source.read_bytes())
            self.assertEqual(playlist_manifest(restored['tracks'], restored['playlists']), [{'name': 'Mix', 'tracks': [1]}])
            self.assertEqual((card / 'library.json').read_bytes(), original_manifest)
            with self.assertRaises(ValueError):
                recover_export(card, LibraryStore(store.path), cache)
