"""Exact framebuffer mirroring and controls without interrupting MicroPython."""
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
import serial

PREFIX = b'@POD '


class DeviceClient:
    def __init__(self, port, stream=True):
        self.port, self.stream = port, stream
        self.events = queue.Queue(maxsize=32)
        self.commands = queue.Queue(maxsize=32)
        self.stop = threading.Event()
        self.connected = threading.Event()
        self.error = None
        self.hello_message = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def publish(self, message):
        if self.events.full():
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
        self.events.put_nowait(message)

    def send(self, cmd, **values):
        if self.error:
            raise RuntimeError(self.error)
        self.commands.put_nowait(dict(cmd=cmd, **values))

    def wait_connected(self, timeout=5):
        if not self.connected.wait(timeout) or self.error:
            raise RuntimeError(self.error or 'PicoPod did not reply. Install the latest firmware and close other serial apps.')

    def run(self):
        try:
            with serial.Serial(self.port, 115200, timeout=0.1, write_timeout=1) as port:
                start, last_heartbeat, last_reply = time.monotonic(), -100, time.monotonic()
                data = bytearray()
                while not self.stop.is_set():
                    t = time.monotonic()
                    if not self.connected.is_set() and t - start > 5:
                        raise RuntimeError('No PicoPod reply. Install updated firmware; close Thonny and other serial apps.')
                    if self.connected.is_set() and self.stream and t - last_reply > 15:
                        raise RuntimeError('PicoPod stopped replying or was disconnected.')
                    if t - last_heartbeat >= 1:
                        cmd = {'cmd': 'stream', 'enabled': True} if self.connected.is_set() and self.stream else {'cmd': 'hello'}
                        port.write(PREFIX + json.dumps(cmd).encode() + b'\n')
                        last_heartbeat = t
                    while not self.commands.empty():
                        port.write(PREFIX + json.dumps(self.commands.get_nowait()).encode() + b'\n')
                    chunk = port.read(4096)
                    data.extend(chunk)
                    while b'\n' in data:
                        line, _, rest = data.partition(b'\n')
                        data = bytearray(rest)
                        at = line.find(PREFIX)
                        if at < 0:
                            continue
                        try:
                            message = json.loads(line[at + len(PREFIX):])
                        except (ValueError, UnicodeError):
                            continue
                        if message.get('type') == 'hello' and message.get('protocol') == 1:
                            self.hello_message = message
                            self.connected.set()
                        last_reply = t
                        self.publish(message)
                    if len(data) > 8192:
                        data.clear()
                try:
                    port.write(PREFIX + b'{"cmd":"stream","enabled":false}\n')
                except serial.SerialException:
                    pass
        except Exception as error:
            self.error = str(error)
            self.publish({'type': 'disconnected', 'message': self.error})
            self.connected.set()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError('USB connection is still closing. Try again in a moment.')


def verify_pico(port):
    client = DeviceClient(port, stream=False)
    try:
        client.wait_connected()
        return client.hello_message
    finally:
        client.close()


def frame_rows(encoded, height, foreground=None):
    foreground = foreground or ('#ffd84d' if height == 64 else '#ffffff')
    pixels = bytes.fromhex(encoded)
    if len(pixels) != 128 * height // 8:
        raise ValueError('Invalid framebuffer length')
    return ['{' + ' '.join(foreground if pixels[(y // 8) * 128 + x] & (1 << (y & 7)) else '#07100e'
                           for x in range(128)) + '}' for y in range(height)]


class Mirror:
    def __init__(self, root, height, scale=4):
        self.height, self.scale = height, scale
        self.canvas = tk.Canvas(root, width=128 * scale, height=height * scale,
                                bg='#07100e', highlightthickness=1, highlightbackground='#304e48')
        self.canvas.pack(pady=10)
        self.item = self.canvas.create_image(0, 0, anchor='nw')

    def update(self, encoded):
        image = tk.PhotoImage(width=128, height=self.height)
        image.put(' '.join(frame_rows(encoded, self.height)))
        self.image = image.zoom(self.scale)
        self.canvas.itemconfigure(self.item, image=self.image)


class LiveWindow:
    def __init__(self, parent, port):
        self.window = tk.Toplevel(parent)
        self.window.title('PicoPod · Live USB view · ' + port)
        self.window.resizable(False, False)
        self.client = DeviceClient(port)
        self.closed = False
        self.status = tk.StringVar(value='Connecting to PicoPod…')
        ttk.Label(self.window, text='LIVE PICOPOD', font=('Segoe UI', 17, 'bold')).pack(pady=(14, 0))
        self.main = Mirror(self.window, 64)
        self.mini = Mirror(self.window, 32)
        row = ttk.Frame(self.window, padding=8)
        row.pack()
        for title, command in [('← Rotate', lambda: self.send('rotate', delta=-1)),
                               ('Select', lambda: self.send('select')),
                               ('Rotate →', lambda: self.send('rotate', delta=1)),
                               ('Back', lambda: self.send('back'))]:
            ttk.Button(row, text=title, command=command).pack(side='left', padx=4)
        row = ttk.Frame(self.window)
        row.pack()
        for title, cmd in [('Previous', 'previous'), ('Play / pause', 'toggle'), ('Next', 'next')]:
            ttk.Button(row, text=title, command=lambda value=cmd: self.send(value)).pack(side='left', padx=4)
        self.volume = tk.IntVar(value=15)
        ttk.Label(row, text='Volume').pack(side='left', padx=(12, 4))
        tk.Spinbox(row, from_=0, to=30, width=3, textvariable=self.volume).pack(side='left')
        ttk.Button(row, text='Set', command=self.set_volume).pack(side='left', padx=4)
        self.quiet = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.window, text='Quiet audio test: pause screen/stream updates during playback',
                        variable=self.quiet, command=lambda: self.send('quiet', enabled=self.quiet.get())).pack(pady=6)
        ttk.Label(self.window, text='← → rotate · Enter select · Esc back. Audio stays on PicoPod.').pack(pady=8)
        ttk.Label(self.window, textvariable=self.status, wraplength=550).pack(padx=12, pady=(0, 15))
        self.window.bind('<Left>', lambda event: self.send('rotate', delta=-1))
        self.window.bind('<Right>', lambda event: self.send('rotate', delta=1))
        self.window.bind('<Return>', lambda event: self.send('select'))
        self.window.bind('<Escape>', lambda event: self.send('back'))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.timer = self.window.after(60, self.poll)

    def set_volume(self):
        try:
            self.send('volume', value=self.volume.get())
        except tk.TclError:
            self.status.set('Enter a volume from 0 to 30.')

    def send(self, cmd, **values):
        try:
            if not self.client.connected.is_set():
                raise RuntimeError('Still connecting…')
            self.client.send(cmd, **values)
        except (RuntimeError, queue.Full) as error:
            self.status.set(str(error))

    def poll(self):
        latest = None
        while not self.client.events.empty():
            message = self.client.events.get_nowait()
            kind = message.get('type')
            if kind == 'frame':
                latest = message
            elif kind in ('error', 'disconnected'):
                self.status.set(message.get('message', 'USB error'))
            elif kind == 'hello':
                self.status.set('Connected · waiting for live frames…')
            elif kind == 'ack' and message.get('quiet'):
                self.status.set('Quiet test active · screens hold still while playing. Uncheck to restore updates.')
        if latest:
            try:
                self.main.update(latest['main'])
                if latest.get('mini'):
                    self.mini.update(latest['mini'])
                self.status.set(('Display error: ' + latest['display_error'] if latest.get('display_error') else None)
                                or latest.get('error')
                                or ('Main display asleep · use a control to wake it' if not latest.get('main_awake', True) else None)
                                or '%s · %s · %s' %
                                (latest.get('screen'), 'Playing' if latest.get('playing') else 'Paused / idle', latest.get('title', '')))
            except (ValueError, KeyError, tk.TclError) as error:
                self.status.set('Invalid frame: ' + str(error))
        self.timer = self.window.after(60, self.poll)

    def close(self):
        if self.closed:
            return
        self.client.close()
        self.closed = True
        self.window.after_cancel(self.timer)
        self.window.destroy()
