"""Run with mpremote to test UART parsing on MicroPython, not just CPython."""
from dfplayer import DFPlayer, packet


class UART:
    def __init__(self):
        self.input = b''

    def any(self):
        return len(self.input)

    def read(self, count):
        result = self.input[:count]
        self.input = self.input[count:]
        return result

    def write(self, data):
        return len(data)


uart = UART()
df = DFPlayer(uart, lambda: 10000)
good = packet(0x3D, 6)
bad = packet(0x3D, 2)
bad[7] ^= 1
uart.input = b'noise' + bad + good[:5]
assert df.poll() == []
uart.input = good[5:]
assert df.poll() == [(0x3D, 6)]
for _ in range(100):
    uart.input = packet(0x48, 6) + packet(0x3D, 1) + packet(0x3D, 1)
    assert df.poll() == [(0x48, 6), (0x3D, 1), (0x3D, 1)]
assert len(df.buffer) == 0
print('PASS: MicroPython UART noise, partial packets, SD replies and 200 completion events')

from player import Player
clock = [0]
library = {'tracks': [
    {'id': 1, 'title': 'Test one', 'duration_ms': 2000},
    {'id': 2, 'title': 'Test two', 'duration_ms': 2000}]}
for repeat in ('all', 'one', 'off'):
    sent = []
    p = Player(library, lambda command, value: sent.append((command, value)), lambda: clock[0])
    p.queue = [1, 2]
    p.play_current()
    p.repeat = repeat
    for _ in range(20):
        clock[0] += 3000
        uart.input = packet(0x3D, p.current) + packet(0x3D, p.current)
        for command, value in df.poll():
            if command == 0x3D:
                p.finished()
    assert p.playing == (repeat != 'off')
    if repeat == 'one':
        assert p.current == 1
    elif repeat == 'off':
        assert p.current == 2
    print('PASS: parsed end events through playback state, loop', repeat)
