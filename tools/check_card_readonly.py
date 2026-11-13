"""Run the exact format-target preflight with Mode=Validate. NEVER formats."""
import json
from pathlib import Path
import subprocess
import tempfile
from manager.cards import discover_cards, select_card, powershell, SCRIPT

card = select_card(discover_cards())
with tempfile.TemporaryDirectory(prefix='picopod-readonly-') as temporary:
    expected, result = Path(temporary) / 'expected.json', Path(temporary) / 'result.json'
    expected.write_text(json.dumps(card), encoding='utf-8')
    result.write_text('{}', encoding='utf-8')
    process = subprocess.run([powershell(), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                              '-File', str(SCRIPT), '-Mode', 'Validate', '-ExpectedFile', str(expected),
                              '-ResultFile', str(result)], capture_output=True, text=True, timeout=30,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    data = json.loads(result.read_text(encoding='utf-8-sig')) if result.exists() else {}
    assert process.returncode == 0 and data.get('ok') and data.get('dryRun'), (data, process.stderr)
    print('PASS: Windows card preparation preflight (read-only), proposed action:', data['action'], 'targets:', data.get('targets', 0))
