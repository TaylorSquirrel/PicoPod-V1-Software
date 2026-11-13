import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from firmware.player import Player
from firmware.remote import Remote
from firmware.ui import UI
from manager import cards
from manager.live import frame_rows
from manager.uploader import execute_upload, UploadPlan
from manager.library import prepare
from test_picopod import BoundsDisplay, LIBRARY


def card():
    return {'DriveLetter': 'E', 'UniqueId': '\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\',
            'DiskNumber': 2, 'DiskUniqueId': 'SD-card-1234', 'DiskSerial': '1234',
            'PartitionNumber': 1, 'PartitionCount': 1, 'Offset': 1048576,
            'Size': 8 * 1024**3, 'DiskSize': 8 * 1024**3 + 1048576,
            'Label': 'PICOPOD', 'FileSystem': 'exFAT', 'DriveType': 'Removable',
            'BusType': 'USB', 'IsBoot': False, 'IsSystem': False}


class CardSafetyTests(unittest.TestCase):
    def test_only_one_removable_named_card(self):
        self.assertEqual(cards.select_card([card()])['DriveLetter'], 'E')
        for candidates in [[], [card(), card()]]:
            with self.assertRaises(ValueError):
                cards.select_card(candidates)

    def test_rejects_system_fixed_large_and_multi_partition_disks(self):
        for field, value in [('IsBoot', True), ('IsSystem', True), ('DriveType', 'Fixed'),
                             ('PartitionCount', 2), ('DiskSize', 64 * 1024**3),
                             ('Label', 'OTHER'), ('DriveLetter', 'C'), ('BusType', 'NVMe'),
                             ('UniqueId', 'E:\\'), ('DiskUniqueId', '')]:
            target = dict(card(), **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                cards.validate_card(target)

    def test_changed_identity_refused(self):
        for field in cards.IDENTITY:
            actual = card()
            actual[field] = 99 if isinstance(actual[field], int) else 'changed'
            with self.subTest(field=field), self.assertRaises(ValueError):
                cards.same_card(card(), actual)

    @patch('manager.cards.discover_cards')
    def test_no_format_without_confirmation(self, discover):
        with self.assertRaises(ValueError):
            cards.prepare_card(card())
        discover.assert_not_called()

    @patch('manager.cards.discover_cards', return_value=[])
    def test_missing_card_fails_before_elevation(self, discover):
        with self.assertRaises(ValueError):
            cards.prepare_card(card(), confirmed=True)

    def test_empty_missing_and_oversized_sources_fail(self):
        with self.assertRaises(ValueError):
            cards.preflight_sources([], card())
        with self.assertRaises(FileNotFoundError):
            cards.preflight_sources([{'source': 'missing-song-12345.mp3'}], card())

    @patch('manager.uploader.verify_pico')
    @patch('manager.uploader.cards.prepare_card')
    @patch('manager.uploader.cards.copy_staged')
    def test_pipeline_order_and_matching_metadata(self, copy, format_card, verify):
        calls = []
        verify.side_effect = lambda port: calls.append('pico')
        format_card.side_effect = lambda expected, confirmed: calls.append('format') or card()
        copy.side_effect = lambda *args: calls.append('copy')
        temporary = tempfile.TemporaryDirectory()
        staging = Path(temporary.name)
        (staging / 'library.json').write_text('{"version":1,"tracks":[],"playlists":[]}')
        plan = UploadPlan(card(), 'COM4', temporary, 2, 1234)
        execute_upload(plan, lambda port, path: calls.append(('metadata', path.name)), confirmed=True)
        self.assertEqual(calls, ['pico', 'format', 'copy', ('metadata', 'library.json')])
        self.assertFalse(staging.exists())

    @patch('manager.uploader.verify_pico', side_effect=RuntimeError('Pico missing'))
    @patch('manager.uploader.cards.prepare_card')
    def test_pico_failure_does_not_erase_card(self, format_card, verify):
        temporary = tempfile.TemporaryDirectory()
        plan = UploadPlan(card(), 'COM4', temporary, 1, 1234)
        with self.assertRaises(RuntimeError):
            execute_upload(plan, Mock(), confirmed=True)
        format_card.assert_not_called()

    @patch('manager.uploader.verify_pico')
    @patch('manager.uploader.cards.prepare_card', side_effect=RuntimeError('Format failed'))
    def test_format_failure_does_not_upload_metadata(self, format_card, verify):
        plan = UploadPlan(card(), 'COM4', tempfile.TemporaryDirectory(), 1, 1234)
        (Path(plan.staging.name) / 'library.json').write_text('{"version":1,"tracks":[],"playlists":[]}')
        upload = Mock()
        with self.assertRaises(RuntimeError):
            execute_upload(plan, upload, confirmed=True)
        upload.assert_not_called()

    def test_real_copy_and_hash_verification_in_temporary_folders(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'original.mp3'
            source.write_bytes(b'example MP3 bytes for copy validation')
            staging, target = root / 'staging', root / 'target'
            staging.mkdir()
            target.mkdir()
            prepare([{'source': str(source), 'title': 'Example', 'artist': 'Artist', 'duration_ms': 1000}], staging)
            volume = dict(card(), FileSystem='FAT32')
            with patch('manager.cards.discover_cards', return_value=[volume]), patch('manager.cards.card_root', return_value=target):
                metadata = cards.copy_staged(staging, volume)
                self.assertEqual((target / 'mp3/0001.mp3').read_bytes(), source.read_bytes())
                self.assertEqual(metadata.read_bytes(), (staging / 'library.json').read_bytes())
                with self.assertRaises(FileExistsError):
                    cards.copy_staged(staging, volume)

    @patch('manager.cards.discover_cards')
    def test_non_fat32_copy_target_refused(self, discover):
        discover.return_value = [card()]
        with self.assertRaises(ValueError):
            cards.copy_staged('not-used', card())


class FakePoll:
    def __init__(self, source):
        self.source = source

    def register(self, *args):
        pass

    def poll(self, timeout):
        return [(0, 1)] if self.source.tell() < len(self.source.getvalue()) else []


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.time = 5000
        self.output = []
        self.commands = []
        self.p = Player(LIBRARY, lambda c, v: self.commands.append((c, v)), lambda: self.time)
        self.stdin = io.StringIO('')
        main, mini = Mock(buffer=bytearray(1024)), Mock(buffer=bytearray(512), sent_buffer=None)
        self.remote = Remote(lambda: self.time, self.p, lambda: True, lambda: (main, mini),
                             stdin=self.stdin, emit=self.output.append, poller=FakePoll(self.stdin))

    def test_controls_change_real_player_state(self):
        self.remote.handle({'cmd': 'select', 'id': 1})
        self.remote.handle({'cmd': 'rotate', 'delta': 1})
        self.remote.handle({'cmd': 'select'})
        self.assertTrue(self.p.playing)
        self.assertEqual(self.commands[-1], (0x12, 1))
        self.remote.handle({'cmd': 'back'})
        self.assertEqual(self.p.screen, 'songs')
        self.assertTrue(self.p.playing)

    def test_unknown_and_invalid_commands_are_errors(self):
        for request in [{'cmd': 'exec'}, {'cmd': 'rotate', 'delta': 100}, {'cmd': 'volume', 'value': 31}]:
            self.remote.handle(request)
            self.assertEqual(self.output[-1]['type'], 'error')

    def test_stream_expires_and_frames_are_exact_size(self):
        self.remote.frame()
        self.assertEqual(self.output, [])
        self.remote.handle({'cmd': 'stream'})
        self.remote.frame()
        self.assertEqual(len(self.output[-1]['main']), 2048)
        self.assertEqual(len(self.output[-1]['mini']), 1024)
        count = len(self.output)
        self.time += 3000
        self.remote.frame()
        self.assertEqual(len(self.output), count)

    def test_quiet_diagnostic_stops_frames_and_expires_safely(self):
        self.p.playing = True
        self.remote.handle({'cmd': 'quiet', 'enabled': True})
        count = len(self.output)
        self.remote.frame()
        self.assertEqual(len(self.output), count)
        self.time += 3000
        self.remote.poll()
        self.assertFalse(self.remote.quiet)
        self.remote.handle({'cmd': 'quiet', 'enabled': True})
        self.remote.handle({'cmd': 'stream', 'enabled': False})
        self.assertFalse(self.remote.quiet)

    def test_bounded_input_discards_overlong_line_then_recovers(self):
        source = io.StringIO('@POD ' + 'x' * 600 + '\n@POD {"cmd":"hello"}\n')
        self.remote.stdin = source
        self.remote.poller = FakePoll(source)
        for _ in range(8):
            self.remote.poll()
        self.assertEqual(self.output[-1]['type'], 'hello')
        self.assertLessEqual(len(self.remote.line), 512)

    def test_live_pixels_decode_vertical_page_layout(self):
        pixels = bytearray(512)
        pixels[0] = 1
        rows = frame_rows(pixels.hex(), 32)
        self.assertTrue(rows[0].startswith('{#ffffff #07100e'))
        self.assertTrue(rows[1].startswith('{#07100e #07100e'))
        with self.assertRaises(ValueError):
            frame_rows('00', 32)

    def test_activity_bars_stay_in_header_and_footer_has_no_wave(self):
        display = BoundsDisplay(64)
        rectangles = []
        original = display.fill_rect
        display.fill_rect = lambda x, y, w, h, c: (rectangles.append((x, y, w, h)), original(x, y, w, h, c))
        self.p.playing = True
        UI(display, BoundsDisplay(32)).draw(self.p, 5000)
        bars = [r for r in rectangles if r[0] in (116, 120, 124) and r[2] == 2 and r[1] < 10]
        self.assertEqual(len(bars), 3)
        self.assertTrue(all(y >= 0 and y + h == 9 for x, y, w, h in bars))
        self.assertFalse(any(y >= 58 for x, y, w, h in rectangles))
