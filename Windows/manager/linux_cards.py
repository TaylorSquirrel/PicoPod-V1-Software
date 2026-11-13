"""Linux removable-card discovery and UDisks2 preparation (no shell commands)."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess

IDENTITY = ('Device', 'PartUUID', 'DiskUniqueId', 'Offset', 'Size', 'DiskSize', 'DeviceNumber')


def run(arguments):
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=180)
    except FileNotFoundError as error:
        raise RuntimeError('Linux card support requires lsblk, udisksctl and gdbus. Install util-linux, udisks2 and GLib tools.') from error
    if result.returncode:
        raise RuntimeError('Linux card operation failed: ' + (result.stderr.strip() or result.stdout.strip()))
    return result.stdout


def descendants(node):
    yield node
    for child in node.get('children', []):
        yield from descendants(child)


def parse(data):
    cards = []
    for disk in data.get('blockdevices', []):
        if disk.get('type') != 'disk':
            continue
        nodes = list(descendants(disk))
        parts = [p for p in nodes if p.get('type') == 'part']
        protected = any(m and (m in ('/', '[SWAP]') or m.startswith('/boot') or m.startswith('/usr') or m.startswith('/var'))
                        for p in nodes for m in (p.get('mountpoints') or []))
        for part in parts:
            if part.get('label') != 'PICOPOD':
                continue
            cards.append(dict(Platform='linux', Device=part.get('path'), DriveLetter=part.get('path'),
                              Label='PICOPOD', FileSystem=('FAT32' if part.get('fstype') == 'vfat' and str(part.get('fsver')).upper() == 'FAT32' else part.get('fstype') or 'unknown'),
                              PartUUID=part.get('partuuid'), DiskUniqueId=disk.get('wwn') or disk.get('serial'),
                              DiskSerial=disk.get('serial'), DeviceNumber=part.get('maj:min'),
                              Offset=part.get('start'), Size=int(part.get('size') or 0), DiskSize=int(disk.get('size') or 0),
                              MountPoints=[m for m in part.get('mountpoints') or [] if m],
                              Removable=bool(disk.get('rm')), BusType=disk.get('tran'),
                              ReadOnly=bool(disk.get('ro') or part.get('ro')), Protected=protected,
                              PartitionCount=len(parts), HasChildren=bool(part.get('children'))))
    return cards


def discover():
    return parse(json.loads(run(['lsblk', '--json', '--bytes', '--paths', '--output',
                                 'NAME,PATH,TYPE,LABEL,FSTYPE,FSVER,SIZE,RM,RO,MOUNTPOINTS,PARTUUID,SERIAL,TRAN,MAJ:MIN,START,WWN'])))


def validate(card):
    if card.get('Label') != 'PICOPOD' or not card.get('Removable') or card.get('BusType') not in ('usb', 'mmc'):
        raise ValueError('PICOPOD must be a removable USB/SD card.')
    if card.get('ReadOnly') or card.get('Protected') or card.get('PartitionCount') != 1 or card.get('HasChildren'):
        raise ValueError('System, read-only, layered and multi-partition disks cannot be used here.')
    if not 64 * 1024**2 <= card.get('Size', 0) <= card.get('DiskSize', 0) <= 32 * 1024**3:
        raise ValueError('Use a microSD card from 64 MB up to 32 GB.')
    if not re.fullmatch(r'/dev/(?:sd[a-z]+[1-9][0-9]*|mmcblk[0-9]+p[1-9][0-9]*)', str(card.get('Device', ''))):
        raise ValueError('Unsupported Linux card partition path.')
    if not card.get('PartUUID') or not card.get('DiskUniqueId') or not card.get('DeviceNumber'):
        raise ValueError('The reader did not provide a reliable partition and disk identity.')
    return card


def current(expected):
    from manager.cards import select_card, same_card
    return same_card(expected, select_card(discover()))


def mount(card):
    card = current(card)
    if not card['MountPoints']:
        run(['udisksctl', 'mount', '--block-device', card['Device']])
        card = current(card)
    return card


def root(card):
    card = current(card)
    mounts = card['MountPoints']
    if len(mounts) != 1:
        raise ValueError('Mount the PICOPOD partition before uploading.')
    path = PurePosixPath(mounts[0])
    if not path.is_absolute() or len(path.parts) < 3 or '..' in path.parts:
        raise ValueError('Unsafe card mount point.')
    target = Path(str(path))
    if not os.path.ismount(target) or os.stat(target).st_dev != os.stat(card['Device']).st_rdev:
        raise ValueError('Card mount no longer matches the confirmed partition.')
    return target


def prepare(expected, confirmed=False):
    if confirmed is not True:
        raise ValueError('Erasing the card requires explicit confirmation.')
    actual = current(expected)
    if actual['FileSystem'] != expected['FileSystem']:
        raise ValueError('Card filesystem changed after confirmation.')
    if actual['FileSystem'] == 'FAT32':
        return mount(actual)  # Never format an existing FAT32 card.
    for command in ('udisksctl', 'gdbus', 'mkfs.fat'):
        if not shutil.which(command):
            raise RuntimeError('Install udisks2, GLib tools and dosfstools before formatting (missing ' + command + '). Card unchanged.')
    if actual['MountPoints']:
        run(['udisksctl', 'unmount', '--block-device', actual['Device']])
    actual = current(expected)
    if actual['MountPoints']:
        raise ValueError('Card is still mounted. Formatting stopped.')
    # UDisks authenticates through the desktop's polkit agent. Fixed arguments
    # force FAT32; never run a user-provided command or format a whole disk.
    name = Path(actual['Device']).name
    object_path = '/org/freedesktop/UDisks2/block_devices/' + name
    run(['gdbus', 'call', '--system', '--dest', 'org.freedesktop.UDisks2',
         '--object-path', object_path, '--method', 'org.freedesktop.UDisks2.Block.Format',
         'vfat', "{'label': <'PICOPOD'>, 'mkfs-args': <['-F', '32']>}"])
    actual = current(expected)
    if actual['FileSystem'] != 'FAT32':
        raise RuntimeError('FAT32 verification failed after formatting. Upload stopped.')
    return mount(actual)
