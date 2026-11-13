import json
from pathlib import Path
import tempfile
import unittest
from firmware.player import Player
from firmware.dfplayer import DFPlayer, AudioStartup, packet
from firmware.ui import UI
from manager.library import prepare, manifest, read_track


LIBRARY = {'tracks': [
    {'id': 1, 'title': 'One', 'artist': 'A', 'duration_ms': 10000},
    {'id': 2, 'title': 'Two', 'artist': 'B', 'duration_ms': 20000},
    {'id': 3, 'title': 'Three', 'artist': 'A', 'duration_ms': 30000}],
    'playlists': [{'name': 'Mix', 'tracks': [3, 1]}]}


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.time = 0
        self.commands = []
        self.p = Player(LIBRARY, lambda c, v: self.commands.append((c, v)), lambda: self.time)

    def start(self):
        self.p.select()
        self.p.rotate(1)
        self.p.select()

    def test_back_preserves_playback_and_selection(self):
        self.start()
        self.time = 4500
        self.p.back()
        self.assertEqual((self.p.screen, self.p.selection), ('songs', 1))
        self.p.back()
        self.assertEqual(self.p.screen, 'home')
        self.assertTrue(self.p.playing)
        self.assertEqual(self.p.elapsed(), 4500)
        self.assertEqual(self.commands, [(0x12, 1)])

    def test_pause_clock(self):
        self.start()
        self.time = 2000
        self.p.toggle()
        self.time = 12000
        self.assertEqual(self.p.elapsed(), 2000)
        self.p.toggle()
        self.time = 15000
        self.assertEqual(self.p.elapsed(), 5000)

    def test_all_repeat_and_duplicate_finish(self):
        self.start()
        for expected in [2, 3, 1]:
            self.time += 2000
            self.p.finished()
            self.assertEqual(self.p.current, expected)
            self.p.finished()
            self.assertEqual(self.p.current, expected)

    def test_repeat_one(self):
        self.start()
        self.p.repeat = 'one'
        self.time = 3000
        self.p.finished()
        self.assertEqual(self.p.current, 1)
        self.assertEqual(self.p.elapsed(), 0)

    def test_repeat_off_and_restart(self):
        self.start()
        self.p.position = 2
        self.p.play_current()
        self.p.repeat = 'off'
        self.time = 3000
        self.p.finished()
        self.assertFalse(self.p.playing)
        self.p.toggle()
        self.assertTrue(self.p.playing)
        self.assertEqual(self.commands[-1], (0x12, 3))

    def test_pause_does_not_trigger_busy_finish(self):
        self.start()
        self.time = 1500
        self.p.busy(True)
        self.p.toggle()
        self.p.busy(False)
        self.time = 3000
        self.p.busy(False)
        self.assertEqual(self.p.current, 1)

    def test_busy_finish(self):
        self.start()
        self.time = 1500
        self.p.busy(True)
        self.time = 10000
        self.p.busy(False)
        self.time += 300
        self.p.busy(False)
        self.assertEqual(self.p.current, 2)

    def test_missing_busy_reports_error(self):
        self.start()
        self.time = 9000
        self.p.busy(False)
        self.assertFalse(self.p.playing)
        self.assertTrue(self.p.error)

    def test_volume_bounds(self):
        self.start()
        self.p.control = 3
        self.p.select()
        self.p.rotate(100)
        self.assertEqual(self.p.volume, 30)
        self.p.back()
        self.assertEqual(self.p.screen, 'now')
        self.assertFalse(self.p.volume_mode)

    def test_playlist_order(self):
        self.p.rotate(1)
        self.p.select()
        self.p.select()
        self.p.rotate(1)
        self.p.select()
        self.assertEqual(self.p.queue, [3, 1])
        self.assertEqual(self.p.current, 3)

    def test_artist_filter(self):
        self.p.rotate(2)
        self.p.select()
        self.p.select()
        self.assertEqual(self.p.context_ids, [1, 3])

    def test_shuffle_keeps_all_ids(self):
        self.p.select()
        self.p.select()
        self.assertTrue(self.p.shuffle)
        self.assertEqual(sorted(self.p.queue), [1, 2, 3])

    def test_empty_library(self):
        p = Player({}, lambda c, v: None, lambda: 0)
        p.select()
        p.select()
        self.assertIsNone(p.current)


class FakeUART:
    def __init__(self):
        self.input = bytearray()
        self.output = []

    def any(self):
        return len(self.input)

    def read(self, count):
        data = self.input[:count]
        del self.input[:count]
        return data

    def write(self, data):
        self.output.append(data)


class UARTTests(unittest.TestCase):
    def test_known_volume_packet(self):
        self.assertEqual(packet(6, 15).hex(), '7eff060600000ffee6ef')

    def test_noise_corruption_and_partial_packets(self):
        uart = FakeUART()
        df = DFPlayer(uart, lambda: 0)
        bad = packet(0x3D, 2)
        bad[7] ^= 1
        good = packet(0x3D, 3)
        uart.input.extend(b'noise' + bad + good[:5])
        self.assertEqual(df.poll(), [])
        uart.input.extend(good[5:])
        self.assertEqual(df.poll(), [(0x3D, 3)])

    def test_pacing_and_volume_coalescing(self):
        uart = FakeUART()
        now = [0]
        df = DFPlayer(uart, lambda: now[0])
        df.send(6, 10)
        df.send(6, 20)
        df.send(0x12, 1)
        df.poll()
        self.assertEqual(uart.output, [packet(6, 20)])
        df.poll()
        self.assertEqual(len(uart.output), 1)
        now[0] = 120
        df.poll()
        self.assertEqual(uart.output[-1], packet(0x12, 1))


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.time = 0
        self.commands = []
        self.startup = AudioStartup(lambda c, v: self.commands.append((c, v)), lambda: self.time)

    def test_waits_for_sd_reply_then_configuration_settles(self):
        self.startup.update()
        self.assertEqual(self.commands, [])
        self.time = 6000
        self.startup.update()
        self.assertEqual(self.commands, [(0x09, 2)])
        self.time = 6500
        self.startup.update()
        self.assertEqual(self.commands[-1], (0x48, 0))
        self.startup.event(0x48, 6, 15)
        self.assertFalse(self.startup.ready)
        self.time = 7100
        self.startup.update()
        self.assertTrue(self.startup.ready)
        self.assertEqual(self.commands[-3:], [(6, 15), (0x11, 0), (0x19, 1)])

    def test_missing_or_slow_module_retries_without_blocking(self):
        for self.time in range(0, 30000, 100):
            self.startup.update()
        self.assertFalse(self.startup.ready)
        self.assertLess(len(self.commands), 12)
        self.assertEqual(self.startup.message(), 'Check SD / UART')
        self.startup.event(0x48, 0, 15)
        self.assertIsNone(self.startup.ready_at)
        self.startup.event(0x48, 6, 15)
        self.time += 600
        self.startup.update()
        self.assertTrue(self.startup.ready)

    def test_repeated_end_events_keep_all_loop_modes_drawable(self):
        now = [0]
        p = Player(LIBRARY, lambda c, v: None, lambda: now[0])
        ui = UI(BoundsDisplay(64), BoundsDisplay(32))
        for repeat in ['all', 'one', 'off']:
            p.queue = [1, 2, 3]
            p.position = 0
            p.play_current()
            p.screen = 'now'
            p.repeat = repeat
            for _ in range(100):
                now[0] += 40000
                p.finished()
                p.finished()  # Duplicate UART/BUSY report must not advance twice.
                ui.draw(p, now[0])
            self.assertEqual(p.playing, repeat != 'off')


class ExportTests(unittest.TestCase):
    def test_mp3_metadata_reader(self):
        # MPEG-1 Layer III, 128kbps, 44.1kHz; metadata parsing does not decode audio.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'Original song.mp3'
            path.write_bytes((bytes.fromhex('fffb9064') + bytes(413)) * 100)
            track = read_track(path)
            self.assertEqual(track['title'], 'Original song')
            self.assertEqual(track['artist'], 'Unknown artist')
            self.assertTrue(2500 <= track['duration_ms'] <= 2700)

    def test_export_metadata_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'song.mp3'
            source.write_bytes(b'test audio bytes')
            target = root / 'card'
            target.mkdir()
            track = {'source': str(source), 'title': 'Hello', 'artist': 'Someone', 'duration_ms': 12345}
            result = prepare([track], target)
            self.assertEqual((target / 'mp3/0001.mp3').read_bytes(), source.read_bytes())
            self.assertEqual(json.loads((target / 'library.json').read_text()), result)
            self.assertNotIn('source', result['tracks'][0])
            with self.assertRaises(ValueError):
                prepare([track], target)

    def test_limits(self):
        track = {'title': 'A' * 300, 'artist': 'B', 'duration_ms': 1000}
        with self.assertRaises(ValueError):
            manifest([track] * 500)
        with self.assertRaises(ValueError):
            manifest([dict(track, duration_ms=0)])


class BoundsDisplay:
    def __init__(self, height):
        self.height = height
        self.count = 0

    def fill(self, c):
        pass

    def fill_rect(self, x, y, w, h, c):
        assert x >= 0 and y >= 0 and x + w <= 128 and y + h <= self.height, (x, y, w, h)
        self.count += 1

    rect = fill_rect

    def hline(self, x, y, w, c):
        self.fill_rect(x, y, w, 1, c)

    def vline(self, x, y, h, c):
        self.fill_rect(x, y, 1, h, c)

    def text(self, s, x, y, c):
        self.fill_rect(x, y, len(s) * 8, 8, c)

    def show(self):
        pass


class UITests(unittest.TestCase):
    def test_all_screens_and_controls_fit_displays(self):
        p = Player(LIBRARY, lambda c, v: None, lambda: 2000)
        main, mini = BoundsDisplay(64), BoundsDisplay(32)
        ui = UI(main, mini)
        for screen in ['home', 'songs', 'artists', 'playlists', 'now']:
            p.screen = screen
            for selected in range(max(1, len(p.items()))):
                p.selection = selected
                for control in range(5):
                    p.control = control
                    for playing in [True, False]:
                        p.playing = playing
                        ui.draw(p, 10000)
        self.assertGreater(main.count, 100)
        self.assertGreater(mini.count, 100)


if __name__ == '__main__':
    unittest.main()
