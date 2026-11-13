"""Shared 128-pixel monochrome UI for the device and desktop preview."""
import math


def ascii_text(value):
    return ''.join(c if 32 <= ord(c) < 127 else '?' for c in str(value))


def stamp(ms):
    seconds = max(0, int(ms // 1000))
    return '%d:%02d' % (seconds // 60, seconds % 60)


class UI:
    def __init__(self, main, mini):
        self.main, self.mini = main, mini
        self.highlight = 16.0
        self.last_screen = None
        self.last_selection = None
        self.changed_at = 0

    def text(self, d, text, x, y, width, now, selected=True, color=1):
        text = ascii_text(text)
        count = max(1, width // 8)
        if len(text) <= count:
            d.text(text, x, y, color)
        elif selected:
            offset = max(0, (now - self.changed_at - 900) // 160)
            loop = text + '   '
            offset %= len(loop)
            d.text((loop + loop)[offset:offset + count], x, y, color)
        else:
            d.text(text[:max(0, count - 1)] + '~', x, y, color)

    def progress(self, d, p, y):
        track = p.track()
        duration = track.get('duration_ms', 0) if track else 0
        elapsed = p.elapsed()
        d.rect(0, y, 128, 5, 1)
        if duration:
            size = min(124, int(124 * elapsed / duration))
            d.fill_rect(2, y + 2, size, 1, 1)
        d.text(stamp(elapsed), 0, y - 10, 1)
        total = stamp(duration) if duration else '--:--'
        d.text(total, 128 - len(total) * 8, y - 10, 1)

    def icon(self, d, index, x, y, color, playing):
        if index in (0, 1):
            # Previous / next, two triangular chevrons and end bar.
            for dx in range(7):
                h = dx if index == 0 else 6 - dx
                d.vline(x + 3 + dx, y + 7 - h, h * 2 + 1, color)
            d.vline(x + (1 if index == 0 else 11), y + 1, 13, color)
        elif index == 2:
            if playing:
                d.fill_rect(x + 3, y + 2, 3, 11, color)
                d.fill_rect(x + 9, y + 2, 3, 11, color)
            else:
                for dx in range(10):
                    h = (9 - dx) // 2
                    d.vline(x + 3 + dx, y + 7 - h, 2 * h + 1, color)
        elif index == 3:
            d.fill_rect(x + 1, y + 5, 4, 6, color)
            for dx in range(5):
                d.vline(x + 5 + dx, y + 5 - dx, 6 + 2 * dx, color)
            d.vline(x + 12, y + 4, 8, color)
        else:
            d.rect(x + 1, y + 3, 13, 9, color)
            d.hline(x, y + 2, 5, color)
            d.hline(x + 10, y + 13, 5, color)

    def draw(self, p, now):
        if self.last_screen != p.screen or self.last_selection != p.selection:
            self.changed_at = now
            self.last_selection = p.selection
        if self.last_screen != p.screen:
            self.highlight = 16.0
            self.last_screen = p.screen
        d = self.main
        d.fill(0)
        if p.screen == 'now':
            track = p.track()
            self.text(d, track['title'] if track else 'Nothing playing', 0, 0, 128, now)
            self.progress(d, p, 27)
            for i in range(5):
                x = i * 25
                selected = i == p.control
                if selected:
                    d.fill_rect(x, 34, 23, 18, 1)
                self.icon(d, i, x + 4, 35, 0 if selected else 1, p.playing)
            labels = ['Previous', 'Next', 'Pause' if p.playing else 'Play',
                      'Volume %d%s' % (p.volume, '*' if p.volume_mode else ''),
                      'Loop: ' + p.repeat]
            d.text(labels[p.control], 0, 56, 1)
        else:
            title = (p.settings.title(p.screen) if p.screen in p.settings.SCREENS else
                     (p.context if p.screen == 'songs' else {'home': 'PicoPod', 'playlists': 'Playlists', 'artists': 'Artists'}[p.screen]))
            self.text(d, title, 0, 0, 112, now, False)
            if p.playing:
                for i in range(3):
                    height = 2 + int((math.sin(now / 170 + i * 2) + 1) * 3)
                    d.fill_rect(116 + i * 4, 9 - height, 2, height, 1)
            d.hline(0, 11, 128, 1)
            items = p.items()
            top = max(0, p.selection - 2)
            row = p.selection - top
            target = 15 + row * 16
            self.highlight += (target - self.highlight) * 0.45
            d.fill_rect(0, int(self.highlight) - 2, 124, 14, 1)
            if not items:
                d.text('No items yet', 4, 17, 0)
            for index in range(top, min(top + 3, len(items))):
                self.text(d, items[index], 4, 15 + (index - top) * 16,
                          112, now, index == p.selection, 0 if index == p.selection else 1)
            if len(items) > 3:
                h = max(3, int(44 * 3 / len(items)))
                y = 14 + int((44 - h) * p.selection / max(1, len(items) - 1))
                d.fill_rect(126, y, 2, h, 1)
        if p.error:
            d.fill_rect(0, 52, 128, 12, 0)
            self.text(d, p.error, 0, 54, 128, now)
        d.show()
        if self.mini is None:
            return
        d = self.mini
        d.fill(0)
        track = p.track()
        self.text(d, track['title'] if track else 'PicoPod ready', 0, 0, 128, now)
        self.progress(d, p, 25)
        # Small playback indicator in the gap between elapsed and total.
        d.text('>' if p.playing else '=', 60, 15, 1)
        # Small-screen I2C is deliberately slow. Never block the main menu for
        # all four pages when just a clock digit or progress pixel changed.
        getattr(d, 'show_incremental', d.show)()
