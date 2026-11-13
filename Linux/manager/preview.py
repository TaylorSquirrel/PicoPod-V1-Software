"""Interactive no-hardware screen preview. Uses the actual firmware UI and state."""
import argparse
import json
import time
import tkinter as tk
from tkinter import ttk
from firmware.player import Player
from firmware.ui import UI


class Screen:
    def __init__(self, root, height, scale=4):
        self.scale = scale
        self.foreground = '#ffd84d' if height == 64 else '#ffffff'
        self.canvas = tk.Canvas(root, width=128 * scale, height=height * scale,
                                bg='#07100e', highlightthickness=1, highlightbackground='#304e48')
        self.canvas.pack(pady=10)

    def color(self, color):
        return self.foreground if color else '#07100e'

    def fill(self, color):
        self.canvas.delete('all')

    def fill_rect(self, x, y, w, h, color):
        s = self.scale
        self.canvas.create_rectangle(x*s, y*s, (x+w)*s, (y+h)*s, fill=self.color(color), outline='')

    def rect(self, x, y, w, h, color):
        self.hline(x, y, w, color)
        self.hline(x, y+h-1, w, color)
        self.vline(x, y, h, color)
        self.vline(x+w-1, y, h, color)

    def hline(self, x, y, w, color):
        self.fill_rect(x, y, w, 1, color)

    def vline(self, x, y, h, color):
        self.fill_rect(x, y, 1, h, color)

    def text(self, text, x, y, color):
        # Same 8px cell spacing as the device; desktop font is an approximation.
        s = self.scale
        for index, char in enumerate(text):
            self.canvas.create_text((x + index*8)*s, y*s, text=char, anchor='nw',
                                    font=('Consolas', -8*s), fill=self.color(color))

    def show(self):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library')
    args = parser.parse_args()
    if args.library:
        from firmware.catalog import load_catalog
        library = load_catalog(args.library)
    else:
        library = {'tracks': [
            {'id': 1, 'title': 'Midnight on the coast', 'artist': 'Demo artist', 'duration_ms': 186000},
            {'id': 2, 'title': 'Small hours', 'artist': 'Demo artist', 'duration_ms': 204000},
            {'id': 3, 'title': 'Paper satellites', 'artist': 'Another artist', 'duration_ms': 159000},
            {'id': 4, 'title': 'The way home', 'artist': 'Another artist', 'duration_ms': 225000}],
            'playlists': [{'name': 'Pocket mix', 'tracks': [1, 3, 4]}]}
    root = tk.Tk()
    root.title('PicoPod · Screen Preview')
    root.configure(bg='#101c24')
    root.resizable(False, False)
    ttk.Label(root, text='PICOPOD  /  MAIN DISPLAY', font=('Consolas', 10)).pack(pady=(18, 0))
    main_display = Screen(root, 64)
    ttk.Label(root, text='ALWAYS-ON  /  NOW PLAYING', font=('Consolas', 10)).pack(pady=(12, 0))
    mini_display = Screen(root, 32)
    status = tk.StringVar(value='Demo audio is simulated · no sound output')
    start = time.monotonic()
    now = lambda: int((time.monotonic() - start) * 1000)
    p = Player(library, lambda cmd, value: status.set('UART 0x%02X  value=%d  (simulated)' % (cmd, value)), now)
    ui = UI(main_display, mini_display)
    row = ttk.Frame(root, padding=10)
    row.pack()
    for title, action in [('↶ Left', lambda: p.rotate(-1)), ('Select', p.select),
                          ('Right ↷', lambda: p.rotate(1)), ('Back', p.back), ('Finish track', p.finished)]:
        ttk.Button(row, text=title, command=action).pack(side='left', padx=4)
    ttk.Label(root, text='Keyboard: ← → rotate · Enter select · Esc back').pack(pady=6)
    ttk.Label(root, textvariable=status).pack(pady=(0, 18))
    root.bind('<Left>', lambda e: p.rotate(-1))
    root.bind('<Right>', lambda e: p.rotate(1))
    root.bind('<Return>', lambda e: p.select())
    root.bind('<Escape>', lambda e: p.back())
    def frame():
        if p.playing and p.track() and p.elapsed() >= p.track()['duration_ms']:
            p.finished()
        ui.draw(p, now())
        root.after(40, frame)
    frame()
    root.mainloop()


if __name__ == '__main__':
    main()
