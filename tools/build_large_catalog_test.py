"""Create metadata-only scale-test fixtures, never audio/card files."""
from pathlib import Path
import json
from manager.library import build_bundle

root = Path('userdata/diagnostics/catalog-scale-test')
root.mkdir(parents=True, exist_ok=True)
if (root / 'library.json').exists():
    data = json.loads((root / 'library.json').read_text())
else:
    tracks = [{'title': 'Scale test %05d' % i, 'artist': 'Artist %03d' % (i % 100), 'duration_ms': 180000}
              for i in range(1, 25001)]
    data = build_bundle(tracks, [{'name': 'Boundary mix', 'tracks': [255, 256, 25000]}], root)
print('Scale fixture:', data['track_count'], 'songs;', data['catalog']['size'], 'metadata bytes')
