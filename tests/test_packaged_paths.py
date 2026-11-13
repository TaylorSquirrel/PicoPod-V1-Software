from pathlib import Path
import unittest
from unittest.mock import patch
from manager import paths


class PortablePathTests(unittest.TestCase):
    def test_frozen_usb_uses_bundled_helper(self):
        with patch.object(paths, 'FROZEN', True), patch.object(paths, 'ASSET_ROOT', Path('bundle')):
            command = paths.usb_command('COM4', ['fs', 'ls'])
            self.assertEqual(command, [str(Path('bundle/usb/PicoPodUSB.exe')), 'connect', 'COM4', 'fs', 'ls'])
            self.assertNotIn('-m', command)

    def test_frozen_preview_uses_app_dispatch(self):
        with patch.object(paths, 'FROZEN', True):
            command = paths.preview_command(['--library', 'songs.json'])
            self.assertEqual(command[1:], ['--preview', '--library', 'songs.json'])

    def test_source_development_commands_still_work(self):
        with patch.object(paths, 'FROZEN', False):
            self.assertEqual(paths.usb_command('COM4', [])[1:], ['-m', 'mpremote', 'connect', 'COM4'])
