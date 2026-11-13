"""Incremental FAT32 library sync with verified reuse and rollback on errors."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import uuid
from manager import cards
from manager.library import validate_device_file
from firmware.indexed import DiskCatalog


def inside(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe card path')
    base = Path(root).absolute()
    target = base / relative
    resolved_base, resolved_target = base.resolve(), target.resolve()
    if resolved_target == resolved_base or not resolved_target.is_relative_to(resolved_base):
        raise ValueError('Path escapes the confirmed card')
    # Preserve the original volume GUID for operations; resolving it may produce
    # a drive-letter alias which Windows could later assign to another device.
    return target


def signature(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


@dataclass
class SyncPlan:
    desired: dict
    existing: dict
    keep: set
    renames: dict
    copies: list
    obsolete: set


def analyze(staging, card, progress=lambda message: None):
    current = cards.same_card(card, cards.select_card(cards.discover_cards()))
    if current['FileSystem'] != 'FAT32':
        raise ValueError('Incremental updates require FAT32')
    root, staging = cards.card_root(card), Path(staging)
    if any(p.name.startswith('.picopod-update-') for p in root.iterdir()):
        raise ValueError('An interrupted card update folder exists. Its backups were preserved; recover it before syncing again.')
    meta = validate_device_file(staging / 'library.json')
    disk = DiskCatalog(meta, str(staging)) if meta['version'] == 2 else None
    desired = {}
    try:
        for track in disk.tracks if disk else meta['tracks']:
            relative = track['file']
            source = staging / relative
            desired[relative] = {'hash': cards.digest(source), 'size': source.stat().st_size, 'title': track['title']}
    finally:
        if disk:
            disk.close()
    existing = {}
    for folder in root.iterdir():
        name = folder.name
        if name.lower() == 'mp3':
            pattern = r'\d{4}\.mp3'
        elif re.fullmatch(r'\d{2}', name) and 1 <= int(name) <= 99:
            pattern = r'\d{3}\.mp3'
        else:
            continue
        if not folder.is_dir() or folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)():
            raise ValueError('Unsafe or invalid audio folder: ' + name)
        for path in folder.iterdir():
            if not re.fullmatch(pattern, path.name, re.IGNORECASE):
                continue
            if not 1 <= int(path.stem) <= (3000 if name.lower() == 'mp3' else 255):
                continue
            relative = path.relative_to(root).as_posix()
            if os.name == 'nt':
                relative = relative.lower()
            path = inside(root, relative)
            if not path.is_file():
                raise ValueError('Audio filename is not a regular file: ' + relative)
            before = signature(path)
            progress('Checking existing ' + relative)
            digest = cards.digest(path)
            if before != signature(path):
                raise ValueError('Card contents changed during analysis')
            existing[relative] = {'hash': digest, 'signature': before}
    keep = {relative for relative, data in desired.items() if relative in existing and existing[relative]['hash'] == data['hash']}
    donors = {}
    for relative, data in existing.items():
        if relative not in keep:
            donors.setdefault(data['hash'], []).append(relative)
    renames, copies = {}, []
    for relative, data in desired.items():
        if relative in keep:
            continue
        options = donors.get(data['hash'], [])
        if options:
            renames[relative] = options.pop()
        else:
            copies.append(relative)
    required = sum(((desired[p]['size'] + 32767) // 32768) * 32768 for p in copies)
    required += sum(p.stat().st_size for p in staging.iterdir() if p.is_file()) + 4 * 1024**2
    if shutil.disk_usage(root).free < required:
        raise ValueError('Not enough free space for a safe incremental update. Free space on the card before retrying; no files were changed.')
    cards.same_card(card, cards.select_card(cards.discover_cards()))
    return SyncPlan(desired, existing, keep, renames, copies, set(existing) - set(desired) - set(renames.values()))


def apply(staging, card, plan, progress=lambda message: None):
    current = cards.same_card(card, cards.select_card(cards.discover_cards()))
    if current['FileSystem'] != 'FAT32':
        raise ValueError('Card filesystem changed; sync stopped')
    root, staging = cards.card_root(card), Path(staging)
    for relative, data in plan.existing.items():
        path = inside(root, relative)
        if not path.exists() or signature(path) != data['signature']:
            raise ValueError('Card contents changed after confirmation. Please analyze again.')
    work_relative = '.picopod-update-' + uuid.uuid4().hex
    work = inside(root, work_relative)
    work.mkdir()
    journal = []
    committed = False
    meta = validate_device_file(staging / 'library.json')
    old_catalog = None
    old_meta = root / 'library.json'
    if old_meta.is_file():
        try:
            old_catalog = json.loads(old_meta.read_text(encoding='utf-8')).get('catalog', {}).get('file')
        except (ValueError, AttributeError):
            pass

    def move(source, target):
        source, target = inside(root, source), inside(root, target)
        if target.exists():
            raise FileExistsError(str(target))
        target.parent.mkdir(exist_ok=True)
        source.rename(target)
        journal.append(('move', source, target))

    def backup(relative):
        target = inside(root, relative)
        if target.exists():
            if not target.is_file():
                raise ValueError('Expected a regular card file: ' + relative)
            move(relative, work_relative + '/backup-%d' % len(journal))

    def copy_verified(relative, destination=None):
        destination = destination or relative
        source, target = staging / relative, inside(root, destination)
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            raise FileExistsError(str(target))
        with source.open('rb') as src, target.open('xb') as dst:
            journal.append(('create', target, None))
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if cards.digest(source) != cards.digest(target):
            raise IOError('Verification failed: ' + destination)

    try:
        staged_donors = {}
        for index, (target, donor) in enumerate(plan.renames.items()):
            temporary = work_relative + '/donor-%d.mp3' % index
            move(donor, temporary)
            staged_donors[target] = temporary
        for relative in plan.desired:
            if relative in plan.keep:
                progress('Unchanged: ' + plan.desired[relative]['title'])
                continue
            backup(relative)
            if relative in staged_donors:
                progress('Renaming: ' + plan.desired[relative]['title'])
                move(staged_donors[relative], relative)
            else:
                progress('Copying and verifying: ' + plan.desired[relative]['title'])
                copy_verified(relative)
        if meta['version'] == 2:
            name = meta['catalog']['file']
            if not (inside(root, name).is_file() and cards.digest(staging / name) == cards.digest(inside(root, name))):
                backup(name)
                copy_verified(name)
        # Swap metadata only after every expected song/catalog is present.
        backup('library.json')
        copy_verified('library.json', work_relative + '/library.json')
        move(work_relative + '/library.json', 'library.json')
        committed = True
    except Exception:
        failed = False
        for operation, source, target in reversed(journal):
            try:
                if operation == 'create':
                    if source.exists():
                        source.unlink()
                elif target.exists():
                    if source.exists():
                        failed = True
                    else:
                        target.rename(source)
            except OSError:
                failed = True
        if failed:
            (work / 'recovery.json').write_text(json.dumps([(kind, str(a), str(b) if b else None) for kind, a, b in journal]), encoding='utf-8')
            progress('Rollback incomplete; backups preserved in ' + work_relative)
        else:
            work.rmdir()
            progress('Incremental update rolled back; original card library restored.')
        raise
    if committed:
        for relative in plan.obsolete:
            path = inside(root, relative)
            if path.is_file():
                path.unlink()
        if isinstance(old_catalog, str) and re.fullmatch(r'catalog-[0-9a-f]{32}\.bin', old_catalog) and old_catalog != meta.get('catalog', {}).get('file'):
            path = inside(root, old_catalog)
            if path.is_file():
                path.unlink()
        # Flat, app-created backup directory; never recurse into arbitrary paths.
        for path in work.iterdir():
            checked = inside(root, path.relative_to(root))
            if not checked.is_file():
                raise ValueError('Unexpected entry in sync backup folder; preserved for recovery')
            checked.unlink()
        work.rmdir()
    progress('Incremental sync verified; FAT32 and unrelated card files preserved.')
    return root / 'library.json'
