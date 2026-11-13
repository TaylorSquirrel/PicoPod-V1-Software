import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from manager import cards
from test_upload_remote import card


class CardHandoffTests(unittest.TestCase):
    def test_fat32_chooses_clear_other_filesystems_choose_format(self):
        for filesystem in ('FAT32', 'fat32'):
            self.assertEqual(cards.prepare_action(dict(card(), FileSystem=filesystem)), 'clear')
        for filesystem in ('exFAT', 'NTFS', 'FAT', ''):
            self.assertEqual(cards.prepare_action(dict(card(), FileSystem=filesystem)), 'format')

    def test_waits_for_helper_exit_before_reading_precreated_status(self):
        order = []
        with tempfile.TemporaryDirectory() as temporary:
            def launch(arguments):
                result = Path(arguments[arguments.index('-ResultFile') + 1])
                self.assertEqual(result.read_text(), '{}')
                self.assertEqual(arguments[arguments.index('-Mode') + 1], 'Validate')
                order.append('helper exited')
                result.write_text(json.dumps({'ok': True, 'dryRun': True, 'action': 'clear'}))
                return 0
            real_read = cards.read_helper_result
            def read(path):
                self.assertEqual(order, ['helper exited'])
                order.append('read result')
                return real_read(path)
            with patch('manager.cards.launch_helper', side_effect=launch), patch('manager.cards.read_helper_result', side_effect=read):
                result = cards.run_card_helper(card(), mode='Validate', job_root=temporary)
            self.assertTrue(result['ok'])
            self.assertEqual(order, ['helper exited', 'read result'])

    @patch('manager.cards.time.sleep')
    def test_transient_permission_error_is_retried(self, sleep):
        with patch.object(Path, 'read_text', side_effect=[PermissionError('busy'), '{"ok":true}']):
            self.assertEqual(cards.read_helper_result(Path('result.json')), {'ok': True})
        sleep.assert_called_once()

    @patch('manager.cards.time.sleep')
    def test_permanent_permission_error_is_actionable(self, sleep):
        with patch.object(Path, 'read_text', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(RuntimeError, 'card may already be prepared'):
                cards.read_helper_result(Path('result.json'))

    @patch('manager.cards.discover_cards')
    @patch('manager.cards.run_card_helper')
    def test_existing_fat32_prepares_without_changing_filesystem(self, helper, discover):
        target = dict(card(), FileSystem='FAT32')
        discover.return_value = [target]
        self.assertEqual(cards.prepare_card(target, confirmed=True)['FileSystem'], 'FAT32')
        helper.assert_called_once_with(target)

    @patch('manager.cards.discover_cards')
    @patch('manager.cards.run_card_helper')
    def test_filesystem_change_since_confirmation_stops_before_helper(self, helper, discover):
        discover.return_value = [dict(card(), FileSystem='NTFS')]
        with self.assertRaisesRegex(ValueError, 'filesystem changed'):
            cards.prepare_card(dict(card(), FileSystem='FAT32'), confirmed=True)
        helper.assert_not_called()
