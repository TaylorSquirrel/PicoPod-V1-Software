"""Hardware-independent playback and navigation state (also used by preview)."""
import random
try:
    from indexed import TitleRows
except ImportError:
    from firmware.indexed import TitleRows
try:
    from settings import SettingsMenu
except ImportError:
    from firmware.settings import SettingsMenu


def shuffle_list(items):
    # MicroPython has getrandbits but does not provide random.shuffle.
    for i in range(len(items) - 1, 0, -1):
        bits = 1
        while (1 << bits) <= i:
            bits += 1
        j = random.getrandbits(bits)
        while j > i:
            j = random.getrandbits(bits)
        items[i], items[j] = items[j], items[i]


class Player:
    def __init__(self, library, send, now):
        self.tracks = library.get('tracks', [])
        self.catalog = library.get('catalog_object')
        self.by_id = self.catalog.by_id if self.catalog else {t['id']: t for t in self.tracks}
        self.playlists = library.get('playlists', [])
        self.send = send
        self.now = now
        self.current = None
        self.queue = []
        self.position = 0
        self.playing = False
        self.elapsed_base = 0
        self.started = 0
        self.repeat = 'all'
        self.shuffle = False
        self.volume = 15
        self.history = []
        self.screen = 'home'
        self.selection = 0
        self.control = 2
        self.volume_mode = False
        self.error = ''
        self.context = 'Songs'
        self.context_ids = self.catalog.all_ids if self.catalog else [t['id'] for t in self.tracks]
        self.started_busy = False
        self.busy_high_at = None
        self.last_finish = -10000
        self.ended = False
        self._menu_key = None
        self._menu_items = []
        self._track_id = None
        self._track_record = None
        self.on_shuffle = None
        self.settings = SettingsMenu()

    def elapsed(self):
        elapsed = self.elapsed_base
        if self.playing:
            elapsed += max(0, self.now() - self.started)
        return elapsed

    def track(self):
        if self.current != self._track_id:
            self._track_id, self._track_record = self.current, self.by_id.get(self.current)
        return self._track_record

    def items(self):
        if self.screen in SettingsMenu.SCREENS:
            return self.settings.rows(self.screen)
        # Reuse menu rows between frames; avoid sorting artists/allocating a
        # full list of titles 25 times per second on an RP2040.
        key = (self.screen, id(self.context_ids))
        if key != self._menu_key:
            self._menu_key = key
            self._menu_items = self._build_items()
        return self._menu_items

    def _build_items(self):
        if self.screen == 'home':
            return ['Songs', 'Playlists', 'Artists', 'Now playing', 'Settings']
        if self.screen == 'playlists':
            if self.catalog:
                return self.catalog.playlist_names
            return [p['name'] for p in self.playlists]
        if self.screen == 'artists':
            if self.catalog:
                return self.catalog.artists
            return sorted(set(t.get('artist', 'Unknown artist') for t in self.tracks))
        if self.screen == 'songs':
            if self.catalog:
                return TitleRows(self.by_id, self.context_ids)
            return ['Shuffle all'] + [self.by_id[i]['title'] for i in self.context_ids]
        return []

    def enter(self, screen):
        self.history.append((self.screen, self.selection, self.context, self.context_ids[:]))
        self.screen, self.selection = screen, 0

    def rotate(self, delta):
        if self.screen == 'now':
            if self.volume_mode:
                self.volume = max(0, min(30, self.volume + delta))
                self.send(0x06, self.volume)
            else:
                self.control = (self.control + delta) % 5
        else:
            self.selection = max(0, min(max(0, len(self.items()) - 1), self.selection + delta))

    def select(self):
        if self.screen in SettingsMenu.SCREENS:
            try:
                self.settings.select(self)
            except (OSError, ValueError) as error:
                self.error = 'Setting save failed'
                print('Settings error:', error)
            return
        items = self.items()
        if self.screen == 'home':
            target = ['songs', 'playlists', 'artists', 'now', 'settings'][self.selection]
            if target == 'songs':
                self.context = 'Songs'
                self.context_ids = self.catalog.all_ids if self.catalog else [t['id'] for t in self.tracks]
            self.enter(target)
        elif self.screen == 'playlists' and items:
            p = self.playlists[self.selection]
            self.context, self.context_ids = p['name'], p['tracks'] if self.catalog else [i for i in p['tracks'] if i in self.by_id]
            self.enter('songs')
        elif self.screen == 'artists' and items:
            self.context = items[self.selection]
            self.context_ids = self.catalog.artist_tracks(self.selection) if self.catalog else [t['id'] for t in self.tracks if t.get('artist', 'Unknown artist') == self.context]
            self.enter('songs')
        elif self.screen == 'songs' and self.context_ids:
            self.shuffle = self.selection == 0
            self.queue = self.context_ids[:]
            if self.shuffle:
                if self.on_shuffle:
                    self.on_shuffle()
                if self.catalog:
                    from array import array
                    self.queue = array('H', self.context_ids)
                shuffle_list(self.queue)
            self.position = 0 if self.shuffle else self.selection - 1
            self.repeat = 'all'
            self.play_current()
            self.enter('now')
        elif self.screen == 'now':
            if self.control == 0:
                self.skip(-1)
            elif self.control == 1:
                self.skip(1)
            elif self.control == 2:
                self.toggle()
            elif self.control == 3:
                self.volume_mode = not self.volume_mode
            else:
                self.repeat = {'all': 'one', 'one': 'off', 'off': 'all'}[self.repeat]

    def back(self):
        if self.volume_mode:
            self.volume_mode = False
        elif self.history:
            self.screen, self.selection, self.context, self.context_ids = self.history.pop()
        else:
            self.screen, self.selection = 'home', 0

    def play_current(self):
        if not self.queue:
            return
        self.current = self.queue[self.position]
        self.elapsed_base = 0
        self.started = self.now()
        self.playing = True
        self.started_busy = False
        self.busy_high_at = None
        self.error = ''
        self.ended = False
        if self.catalog:
            folder, track = (self.current - 1) // 255 + 1, (self.current - 1) % 255 + 1
            self.send(0x0F, (folder << 8) | track)
        else:
            self.send(0x12, self.current)  # Legacy /mp3/NNNN.mp3 libraries.

    def toggle(self):
        if self.current is None:
            return
        if self.ended:
            self.play_current()
            return
        if self.playing:
            self.elapsed_base = self.elapsed()
            self.playing = False
            self.send(0x0E, 0)
        else:
            self.started = self.now()
            self.playing = True
            self.busy_high_at = None
            self.send(0x0D, 0)

    def skip(self, delta):
        if not self.queue:
            return
        self.position = (self.position + delta) % len(self.queue)
        self.play_current()

    def finished(self):
        # Ignore stale completion packets while starting/resuming, plus duplicates.
        now = self.now()
        if not self.playing or now - self.started < 1000 or now - self.last_finish < 1000:
            return
        self.last_finish = now
        if self.repeat == 'one':
            self.play_current()
        elif self.position + 1 < len(self.queue):
            self.position += 1
            self.play_current()
        elif self.repeat == 'all':
            if self.shuffle and len(self.queue) > 1:
                if self.on_shuffle:
                    self.on_shuffle()
                previous = self.current
                shuffle_list(self.queue)
                if self.queue[0] == previous:
                    self.queue[0], self.queue[1] = self.queue[1], self.queue[0]
            self.position = 0
            self.play_current()
        else:
            self.elapsed_base = self.elapsed()
            self.playing = False
            self.ended = True

    def busy(self, low):
        if not self.playing or self.now() - self.started < 1000:
            return
        if low:
            self.started_busy = True
            self.busy_high_at = None
        elif self.started_busy:
            if self.busy_high_at is None:
                self.busy_high_at = self.now()
            elif self.now() - self.busy_high_at > 250:
                self.finished()
        elif self.now() - self.started > 8000:
            self.fail('No playback/BUSY')

    def fail(self, message):
        self.elapsed_base = self.elapsed()
        self.playing = False
        self.error = message
