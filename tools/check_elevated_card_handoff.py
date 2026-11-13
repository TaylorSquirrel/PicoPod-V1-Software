"""Read-only UAC test of the exact normal-user/elevated helper result handoff."""
from manager.cards import discover_cards, select_card, run_card_helper

card = select_card(discover_cards())
result = run_card_helper(card, mode='Validate')
assert result.get('ok') and result.get('dryRun')
assert result.get('action') == ('clear' if card['FileSystem'] == 'FAT32' else 'format')
print('PASS: elevated process completed, normal app read the result; read-only action:', result['action'])
