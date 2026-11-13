import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from firmware.catalog import load_catalog
from firmware.dfplayer import AudioStartup, DFPlayer
from firmware.indexed import audio_path, IdRange, FileIds
from firmware.player import Player
from manager.library import build_bundle, prepare, validate_device_file
from manager import cards
from manager.app import App
from manager.uploader import check_catalog_capacity
from test_picopod import FakeUART
from test_upload_remote import card


class IndexedCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        tracks = [{'title': 'Song %05d' % i, 'artist': 'Artist %03d' % (i % 100), 'duration_ms': 180000} for i in range(1, 25001)]
        cls.meta = build_bundle(tracks, [{'name': 'Boundary mix', 'tracks': [255, 256, 25000]}], cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.library = load_catalog(str(self.root / 'library.json'))
        self.disk = self.library['catalog_object']
        self.time = 0
        self.commands = []
        self.player = Player(self.library, lambda c, v: self.commands.append((c, v)), lambda: self.time)

    def tearDown(self):
        self.disk.close()

    def test_all_25000_tracks_fit_indexed_bundle_and_page_cache_is_bounded(self):
        self.assertEqual(self.meta['track_count'], 25000)
        self.assertLess(self.meta['catalog']['size'], 1200000)
        self.assertEqual(validate_device_file(self.root / 'library.json')['version'], 2)
        for number in range(1, 25001, 79):
            self.assertEqual(self.disk.by_id[number]['title'], 'Song %05d' % number)
        self.assertLessEqual(len(self.disk.cache), 3)
        self.assertTrue(all(len(page[1]) <= 16 for page in self.disk.cache.values()))

    def test_numbered_paths_and_folder_uart_boundaries(self):
        self.assertEqual(audio_path(1), '01/001.mp3')
        self.assertEqual(audio_path(255), '01/255.mp3')
        self.assertEqual(audio_path(256), '02/001.mp3')
        self.assertEqual(audio_path(25000), '99/010.mp3')
        p = self.player
        p.select()
        p.selection = 25000
        p.select()
        self.assertIsInstance(p.queue, IdRange)
        self.assertEqual(self.commands[-1], (0x0F, 0x630A))
        p.back()
        self.assertEqual(p.items()[25000], 'Song 25000')

    def test_playlist_order_and_artist_filter_are_disk_backed(self):
        p = self.player
        p.rotate(1)
        p.select()
        p.select()
        self.assertIsInstance(p.context_ids, FileIds)
        self.assertEqual(list(p.context_ids), [255, 256, 25000])
        p.selection = 1
        p.select()
        self.assertEqual(self.commands[-1], (0x0F, 0x01FF))
        p.back()
        p.back()
        p.back()
        p.selection = 2
        p.select()
        p.select()
        self.assertIsInstance(p.context_ids, FileIds)
        self.assertEqual(len(p.context_ids), 250)

    def test_shuffle_uses_compact_16bit_ids(self):
        p = self.player
        p.select()
        p.select()
        self.assertEqual(len(p.queue), 25000)
        self.assertEqual(p.queue.itemsize, 2)
        self.assertEqual(len(set(p.queue)), 25000)

    def test_more_than_25000_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                build_bundle([{}] * 25001, [], temporary)

    def test_corrupt_catalog_is_rejected_before_activation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = copy.deepcopy(self.meta)
            binary = bytearray((self.root / data['catalog']['file']).read_bytes())
            binary[8] ^= 1
            (root / data['catalog']['file']).write_bytes(binary)
            (root / 'library.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'checksum'):
                load_catalog(str(root / 'library.json'))

    def test_pc_upload_stages_the_sidecar_before_activating_descriptor(self):
        app = App.__new__(App)
        seen = []
        def remote(port, arguments):
            seen.append(arguments)
            self.assertEqual(arguments[:2], ['fs', 'cp'])
            self.assertEqual(Path(arguments[2]).name, self.meta['catalog']['file'])
            self.assertIn(':library.new.json', arguments)
            self.assertIn('load_catalog', arguments[arguments.index('exec') + 1])
            # The temporary JSON is alive until the transfer completes.
            json_files = [Path(value) for value in arguments if str(value).endswith('library.json') and not str(value).startswith(':')]
            self.assertEqual(len(json_files), 1)
            self.assertEqual(json.loads(json_files[0].read_text())['track_count'], 25000)
        app.remote = remote
        with patch('manager.app.verify_pico', return_value={'indexed_catalog': 2, 'storage_free': 1200000, 'active_catalog': None}):
            app.upload_metadata('COM4', self.root / 'library.json')
        self.assertEqual(len(seen), 1)


class IndexedUploadTests(unittest.TestCase):
    def test_flash_capacity_is_checked_before_card_erasure(self):
        metadata = {'version': 2, 'catalog': {'size': 240000, 'file': 'catalog-example.bin'}}
        for device in (None, {'indexed_catalog': 1}, {'indexed_catalog': 2, 'storage_free': 1000}):
            with self.assertRaises(ValueError):
                check_catalog_capacity(device, metadata)
        check_catalog_capacity({'indexed_catalog': 2, 'storage_free': 500000}, metadata)
    def test_folder_audio_and_binary_are_copied_and_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.mp3'
            source.write_bytes(b'audio copy test')
            staging, target = root / 'staging', root / 'target'
            staging.mkdir()
            target.mkdir()
            tracks = [{'title': 'A', 'artist': 'B', 'duration_ms': 1000, 'source': str(source)}] * 2
            with patch('manager.library.manifest', side_effect=ValueError('metadata budget')):
                data = prepare(tracks, staging, playlists=[{'name': 'Mix', 'tracks': [2, 1]}])
            self.assertEqual(data['version'], 2)
            self.assertEqual((staging / '01/002.mp3').read_bytes(), source.read_bytes())
            volume = dict(card(), FileSystem='FAT32')
            with patch('manager.cards.discover_cards', return_value=[volume]), patch('manager.cards.card_root', return_value=target):
                cards.copy_staged(staging, volume)
            self.assertEqual((target / '01/002.mp3').read_bytes(), source.read_bytes())
            validate_device_file(target / 'library.json')

    def test_idle_playback_does_not_send_background_uart_commands(self):
        uart = FakeUART()
        t = [1000]
        df = DFPlayer(uart, lambda: t[0])
        df.send(0x12, 1)
        df.poll()
        for _ in range(1000):
            t[0] += 100
            df.poll()
        self.assertEqual(len(uart.output), 1)

    def test_zero_counter_can_use_sd_presence_reply(self):
        t = [0]
        commands = []
        startup = AudioStartup(lambda c, v: commands.append((c, v)), lambda: t[0], 0)
        startup.update()
        startup.event(0x48, 0, 10)
        self.assertEqual(commands[-1], (0x3F, 0))
        startup.event(0x3F, 2, 10)
        t[0] = 600
        startup.update()
        self.assertTrue(startup.ready)
