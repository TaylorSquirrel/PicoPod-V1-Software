import copy
import json
from pathlib import Path
import tempfile
import unittest
from firmware.catalog import validate_catalog, load_catalog, cleanup_catalogs
from manager.library import manifest, validate_device_file, serialize_manifest


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.desktop = {'version': 1, 'tracks': [{'uid': 'a', 'source': 'C:/Music/a.mp3',
                        'title': 'A', 'artist': 'Artist', 'duration_ms': 3000}], 'playlists': [], 'port': 'COM4'}
        self.device = manifest(self.desktop['tracks'])

    def test_device_manifest_is_valid(self):
        self.assertEqual(validate_catalog(self.device), self.device)

    def test_pc_saved_library_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, 'PC saved library'):
            validate_catalog(self.desktop)

    def test_oversized_desktop_file_is_identified_before_generic_budget_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'library.json'
            path.write_text(json.dumps(self.desktop) + ' ' * 50000, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'PC saved library'):
                load_catalog(str(path))
            with self.assertRaisesRegex(ValueError, 'PC saved library'):
                validate_device_file(path)

    def test_invalid_ids_metadata_and_playlist_references_are_rejected(self):
        variants = []
        for key, value in [('id', True), ('id', 0), ('title', None), ('artist', []), ('duration_ms', 0), ('file', '../wrong.mp3')]:
            data = copy.deepcopy(self.device)
            data['tracks'][0][key] = value
            variants.append(data)
        duplicates = copy.deepcopy(self.device)
        duplicates['tracks'] *= 2
        variants.append(duplicates)
        missing = copy.deepcopy(self.device)
        missing['playlists'] = [{'name': 'Mix', 'tracks': [2]}]
        variants.append(missing)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_catalog(data)

    def test_correct_manifest_loads_on_device_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'library.json'
            path.write_text(json.dumps(self.device), encoding='utf-8')
            self.assertEqual(load_catalog(str(path)), self.device)
            self.assertEqual(validate_device_file(path), self.device)

    def test_pretty_printed_device_metadata_is_sized_by_compact_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = manifest([dict(self.desktop['tracks'][0], title='A' * 25)] * 282)
            path = Path(temporary) / 'library.json'
            path.write_text(json.dumps(data, indent=6), encoding='utf-8')
            self.assertGreater(path.stat().st_size, 48000)
            self.assertLess(len(serialize_manifest(data)), 48000)
            self.assertEqual(validate_device_file(path), data)

    def test_only_generated_unused_catalogs_are_cleaned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = 'catalog-' + 'a' * 32 + '.bin'
            unused = 'catalog-' + 'b' * 32 + '.bin'
            for name in (active, unused, 'my-music.bin', 'catalog-not-managed.bin'):
                (root / name).write_bytes(b'test')
            cleanup_catalogs(active, str(root))
            self.assertTrue((root / active).exists())
            self.assertFalse((root / unused).exists())
            self.assertTrue((root / 'catalog-not-managed.bin').exists())
