import copy
import unittest
from unittest.mock import patch
from manager import cards, linux_cards


def fixture():
    return {'blockdevices': [dict(type='disk', path='/dev/sdb', size=8*1024**3,
        rm=True, ro=False, tran='usb', serial='reader-123', mountpoints=[None], children=[
        dict(type='part', path='/dev/sdb1', size=8*1024**3-1024**2,
             label='PICOPOD', fstype='vfat', fsver='FAT32', partuuid='12345678-01',
             start=2048, mountpoints=['/media/atlas/PICOPOD'], **{'maj:min': '8:17'})])]}


class LinuxCardTests(unittest.TestCase):
    def card(self):
        return linux_cards.parse(fixture())[0]

    def test_valid_card_and_fat32_detection(self):
        card = self.card()
        self.assertEqual(cards.validate_card(card)['FileSystem'], 'FAT32')
        data = fixture()
        data['blockdevices'][0]['children'][0]['fsver'] = 'FAT16'
        self.assertNotEqual(linux_cards.parse(data)[0]['FileSystem'], 'FAT32')

    def test_refuses_unsafe_cards(self):
        card = self.card()
        for field, value in [('Removable', False), ('ReadOnly', True), ('Protected', True),
                             ('PartitionCount', 2), ('HasChildren', True), ('DiskUniqueId', None),
                             ('PartUUID', None), ('Device', '/dev/sdb'), ('Size', 100)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                cards.validate_card(dict(card, **{field: value}))

    def test_parser_protects_boot_and_root(self):
        for mount in ('/', '/boot/efi', '/usr', '/var', '[SWAP]'):
            data = fixture()
            data['blockdevices'][0]['children'][0]['mountpoints'] = [mount]
            with self.subTest(mount=mount), self.assertRaises(ValueError):
                cards.validate_card(linux_cards.parse(data)[0])

    def test_identity_change_is_refused(self):
        card = self.card()
        for field in linux_cards.IDENTITY:
            changed = copy.deepcopy(card)
            changed[field] = str(changed[field]) + '-changed'
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError)):
                cards.same_card(card, changed)

    @patch('manager.linux_cards.run')
    def test_confirmation_required_before_any_operation(self, run):
        with self.assertRaises(ValueError):
            linux_cards.prepare(self.card())
        run.assert_not_called()

    def test_fat32_never_formats(self):
        card = self.card()
        with patch('manager.linux_cards.current', return_value=card), patch('manager.linux_cards.run') as run:
            self.assertEqual(linux_cards.prepare(card, True), card)
        run.assert_not_called()

    def test_format_targets_partition_forces_fat32_and_verifies(self):
        expected = dict(self.card(), FileSystem='exfat', MountPoints=[])
        formatted = dict(expected, FileSystem='FAT32')
        mounted = dict(formatted, MountPoints=['/media/atlas/PICOPOD'])
        with patch('manager.linux_cards.current', side_effect=[expected, expected, formatted, formatted, mounted]), \
             patch('manager.linux_cards.run') as run, patch('manager.linux_cards.shutil.which', return_value='/usr/bin/tool'):
            self.assertEqual(linux_cards.prepare(expected, True), mounted)
        command = run.call_args_list[0].args[0]
        self.assertIn('/org/freedesktop/UDisks2/block_devices/sdb1', command)
        self.assertIn("{'label': <'PICOPOD'>, 'mkfs-args': <['-F', '32']>}", command)
        self.assertEqual(run.call_args_list[1].args[0], ['udisksctl', 'mount', '--block-device', '/dev/sdb1'])

    def test_missing_tools_stops_before_formatting(self):
        card = dict(self.card(), FileSystem='exfat')
        with patch('manager.linux_cards.current', return_value=card), patch('manager.linux_cards.shutil.which', return_value=None), \
             patch('manager.linux_cards.run') as run, self.assertRaisesRegex(RuntimeError, 'Card unchanged'):
            linux_cards.prepare(card, True)
        run.assert_not_called()

    def test_format_failure_does_not_continue_to_copy(self):
        card = dict(self.card(), FileSystem='exfat', MountPoints=[])
        with patch('manager.linux_cards.current', return_value=card), patch('manager.linux_cards.shutil.which', return_value='tool'), \
             patch('manager.linux_cards.run', side_effect=RuntimeError('cancelled')), self.assertRaises(RuntimeError):
            linux_cards.prepare(card, True)
