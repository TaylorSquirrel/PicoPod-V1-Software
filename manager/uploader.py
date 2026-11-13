"""Two-phase upload: reversible staging, then confirmed incremental sync or format."""
from dataclasses import dataclass
from pathlib import Path
import tempfile
from manager import cards
from manager.library import prepare
from manager.live import verify_pico


def check_catalog_capacity(device, library):
    if library.get('version') != 2:
        return
    if not device or device.get('indexed_catalog') != 2:
        raise ValueError('Install the latest PicoPod firmware before uploading a large library. Card unchanged.')
    if device.get('active_catalog') == library['catalog']['file']:
        return
    required = library['catalog']['size'] + 16384
    if device.get('storage_free') is None or device['storage_free'] < required:
        raise ValueError('Not enough Pico flash to stage this indexed library safely. Reduce the library or use a board with more flash. Card unchanged.')


@dataclass
class UploadPlan:
    card: dict
    port: str
    staging: tempfile.TemporaryDirectory
    count: int
    total_bytes: int
    sync: object = None

    def close(self):
        self.staging.cleanup()


def plan_upload(tracks, port, progress=lambda message: None, playlists=None):
    card = cards.select_card(cards.discover_cards())
    if card.get('Platform') == 'linux' and card['FileSystem'] == 'FAT32':
        from manager.linux_cards import mount
        card = mount(card)
    total = cards.preflight_sources(tracks, card)
    progress('Checking PicoPod USB connection…')
    device = verify_pico(port)
    temporary = tempfile.TemporaryDirectory(prefix='picopod-staging-')
    try:
        progress('Staging original songs on the PC before any erase…')
        def staging_progress(message):
            progress('Songs staged on the PC. The card has not been changed.'
                     if message.startswith('Export complete.') else message)
        library = prepare(tracks, temporary.name, staging_progress, playlists=playlists)
        check_catalog_capacity(device, library)
        cards.same_card(card, cards.select_card(cards.discover_cards()))
        sync = None
        if card['FileSystem'] == 'FAT32':
            from manager.sync import analyze
            progress('Analyzing FAT32 card for unchanged songs and safe renames…')
            sync = analyze(temporary.name, card, progress)
        return UploadPlan(card, port, temporary, len(tracks), total, sync)
    except Exception:
        temporary.cleanup()
        raise


def execute_upload(plan, upload_metadata, confirmed=False, progress=lambda message: None):
    if confirmed is not True:
        raise ValueError('No card-update confirmation was provided.')
    phase = 'Pico connection check'
    try:
        device = verify_pico(plan.port)
        from manager.library import validate_device_file
        library = validate_device_file(Path(plan.staging.name) / 'library.json')
        check_catalog_capacity(device, library)
        phase = 'card preparation'
        if plan.sync is not None:
            from manager.sync import apply
            phase = 'incremental song sync'
            progress('Keeping FAT32 and reusing verified existing songs; no erase or format…')
            apply(plan.staging.name, plan.card, plan.sync, progress)
        else:
            progress('Formatting the confirmed PICOPOD card as FAT32. Your operating system may ask for administrator permission…')
            card = cards.prepare_card(plan.card, confirmed=True)
            phase = 'song transfer and verification'
            progress('FAT32 verified. Uploading songs…')
            cards.copy_staged(plan.staging.name, card, progress)
        phase = 'Pico metadata upload'
        progress('Songs verified. Uploading the matching metadata to PicoPod…')
        upload_metadata(plan.port, Path(plan.staging.name) / 'library.json')
        progress('Upload complete. Safely eject the card, power off PicoPod, insert the card into the DFPlayer, then power on.')
    except Exception:
        progress('Stopped during ' + phase + '. ' +
                 ('The songs are already on the card; retry Upload library.json from the card to finish.'
                  if phase == 'Pico metadata upload' else
                  ('The card was not changed.' if phase == 'Pico connection check' else
                   'Card preparation may have removed files. Correct the error before using it.')))
        raise
    finally:
        plan.close()
