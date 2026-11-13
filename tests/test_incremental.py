import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from manager import sync
from manager.library import prepare
from test_upload_remote import card


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.card = self.root / 'card'
        self.stage = self.root / 'stage'
        self.card.mkdir()
        self.stage.mkdir()
        self.volume = dict(card(), FileSystem='FAT32')
        self.discovery = patch('manager.cards.discover_cards', return_value=[self.volume])
        self.cardroot = patch('manager.cards.card_root', return_value=self.card)
        self.discovery.start()
        self.cardroot.start()

    def tearDown(self):
        self.discovery.stop()
        self.cardroot.stop()
        self.temporary.cleanup()

    def tracks(self, payloads):
        result = []
        for index, payload in enumerate(payloads):
            source = self.root / ('source-%d-%d.mp3' % (index, len(payload)))
            source.write_bytes(payload)
            result.append({'source': str(source), 'title': 'Song %d' % index, 'artist': 'Artist', 'duration_ms': 1000})
        return result

    def seed(self, payloads):
        prepare(self.tracks(payloads), self.card)
        (self.card / 'personal-notes.txt').write_text('keep me')

    def test_unchanged_files_are_reused_without_modification(self):
        self.seed([b'AAA', b'BBBB'])
        prepare(self.tracks([b'AAA', b'BBBB']), self.stage)
        before = (self.card / 'mp3/0001.mp3').stat().st_mtime_ns
        plan = sync.analyze(self.stage, self.volume)
        self.assertEqual(len(plan.keep), 2)
        self.assertEqual(plan.copies, [])
        sync.apply(self.stage, self.volume, plan)
        self.assertEqual((self.card / 'mp3/0001.mp3').stat().st_mtime_ns, before)
        self.assertEqual((self.card / 'personal-notes.txt').read_text(), 'keep me')

    def test_reordering_renames_existing_audio_without_copying(self):
        self.seed([b'AAA', b'BBBB'])
        prepare(self.tracks([b'BBBB', b'AAA']), self.stage)
        plan = sync.analyze(self.stage, self.volume)
        self.assertEqual(len(plan.renames), 2)
        self.assertEqual(plan.copies, [])
        sync.apply(self.stage, self.volume, plan)
        self.assertEqual((self.card / 'mp3/0001.mp3').read_bytes(), b'BBBB')
        self.assertEqual((self.card / 'mp3/0002.mp3').read_bytes(), b'AAA')

    def test_add_remove_and_preserve_unrelated_files(self):
        self.seed([b'AAA', b'BBBB'])
        prepare(self.tracks([b'AAA', b'NEW-DATA']), self.stage)
        plan = sync.analyze(self.stage, self.volume)
        self.assertEqual(len(plan.keep), 1)
        self.assertEqual(len(plan.copies), 1)
        sync.apply(self.stage, self.volume, plan)
        self.assertEqual((self.card / 'mp3/0002.mp3').read_bytes(), b'NEW-DATA')
        self.assertTrue((self.card / 'personal-notes.txt').exists())

    def test_failure_restores_original_audio_and_metadata(self):
        self.seed([b'AAA', b'BBBB'])
        old_meta = (self.card / 'library.json').read_bytes()
        prepare(self.tracks([b'BBBB', b'NEW-DATA']), self.stage)
        plan = sync.analyze(self.stage, self.volume)
        original_digest = sync.cards.digest
        def digest(path):
            if str(path).startswith(str(self.card)) and str(path).endswith('0002.mp3'):
                raise IOError('simulated card read failure')
            return original_digest(path)
        with patch('manager.cards.digest', side_effect=digest):
            with self.assertRaises(IOError):
                sync.apply(self.stage, self.volume, plan)
        self.assertEqual((self.card / 'mp3/0001.mp3').read_bytes(), b'AAA')
        self.assertEqual((self.card / 'mp3/0002.mp3').read_bytes(), b'BBBB')
        self.assertEqual((self.card / 'library.json').read_bytes(), old_meta)

    def test_card_changes_after_confirmation_are_rejected(self):
        self.seed([b'AAA'])
        prepare(self.tracks([b'AAA']), self.stage)
        plan = sync.analyze(self.stage, self.volume)
        (self.card / 'mp3/0001.mp3').write_bytes(b'CHANGED')
        with self.assertRaises(ValueError):
            sync.apply(self.stage, self.volume, plan)

    def test_path_escape_is_refused(self):
        with self.assertRaises(ValueError):
            sync.inside(self.card, '../outside.mp3')

    def test_layout_migration_renames_audio_and_copies_catalog(self):
        self.seed([b'AAA', b'BBBB'])
        with patch('manager.library.manifest', side_effect=ValueError('metadata budget')):
            prepare(self.tracks([b'AAA', b'BBBB']), self.stage)
        plan = sync.analyze(self.stage, self.volume)
        self.assertEqual(len(plan.renames), 2)
        self.assertEqual(plan.obsolete, set())
        sync.apply(self.stage, self.volume, plan)
        self.assertEqual((self.card / '01/001.mp3').read_bytes(), b'AAA')
        from manager.library import validate_device_file
        self.assertEqual(validate_device_file(self.card / 'library.json')['version'], 2)

    def test_only_obsolete_managed_audio_is_removed(self):
        self.seed([b'AAA', b'BBBB'])
        (self.card / 'mp3/9999.mp3').write_bytes(b'unmanaged')
        prepare(self.tracks([b'AAA']), self.stage)
        plan = sync.analyze(self.stage, self.volume)
        self.assertEqual(plan.obsolete, {'mp3/0002.mp3'})
        sync.apply(self.stage, self.volume, plan)
        self.assertFalse((self.card / 'mp3/0002.mp3').exists())
        self.assertEqual((self.card / 'mp3/9999.mp3').read_bytes(), b'unmanaged')
