"""One-time migration from a connected exported card; never formats or writes to it."""
from manager.cards import discover_cards, select_card, card_root
from manager.state import LibraryStore, DEFAULT_PATH
from manager.recovery import recover_export

cards = discover_cards()
if not cards:
    print('No connected PICOPOD card; existing songs can be added once in the updated app.')
else:
    card = select_card(cards)
    store = LibraryStore()
    state = store.load()
    if store.blocked or state['tracks'] or state['playlists']:
        print('Existing saved PC library preserved; no migration needed.')
    else:
        songs, playlists = recover_export(card_root(card), store, DEFAULT_PATH.parent / 'recovered-music')
        print('Recovered %d songs and %d playlists into the saved PC library. Card unchanged.' % (songs, playlists))
