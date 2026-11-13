"""Framed, checksummed UART protocol with bounded buffering and command pacing."""


def packet(command, value=0):
    data = bytearray([0x7E, 0xFF, 6, command, 0, value >> 8, value & 255, 0, 0, 0xEF])
    checksum = (-sum(data[1:7])) & 0xFFFF
    data[7], data[8] = checksum >> 8, checksum & 255
    return data


class DFPlayer:
    def __init__(self, uart, now, debug=False):
        self.uart, self.now, self.debug = uart, now, debug
        self.buffer = bytearray()
        self.queue = []
        self.last_send = -1000

    def send(self, command, value=0):
        if command == 0x06:
            self.queue = [p for p in self.queue if p[0] != 0x06]
        elif command in (0x12, 0x0F):
            self.queue = [p for p in self.queue if p[0] not in (0x12, 0x0F, 0x0D, 0x0E)]
        elif command in (0x0D, 0x0E):
            self.queue = [p for p in self.queue if p[0] not in (0x0D, 0x0E)]
        if len(self.queue) >= 32:
            raise RuntimeError('DFPlayer command queue full')
        self.queue.append((command, value))

    def poll(self):
        if self.queue and self.now() - self.last_send >= 120:
            command, value = self.queue.pop(0)
            self.uart.write(packet(command, value))
            self.last_send = self.now()
            if self.debug:
                print('DF TX %02x %d' % (command, value))
        if self.uart.any():
            self.buffer.extend(self.uart.read(min(128, self.uart.any())) or b'')
        events = []
        consumed = 0
        while len(self.buffer) - consumed >= 10:
            if self.buffer[consumed] != 0x7E:
                consumed += 1
                continue
            p = self.buffer[consumed:consumed + 10]
            if (p[1] != 0xFF or p[2] != 6 or p[9] != 0xEF or
                    ((-sum(p[1:7])) & 65535) != (p[7] << 8 | p[8])):
                consumed += 1
                continue
            consumed += 10
            event = (p[3], p[5] << 8 | p[6])
            events.append(event)
            if self.debug:
                print('DF RX %02x %d' % event)
        # MicroPython bytearray does not support item/slice deletion. Compact
        # once after parsing; preserve any partial packet for the next poll.
        if consumed:
            self.buffer = self.buffer[consumed:]
        return events


class AudioStartup:
    """Wait for SD discovery without blocking menus or waiting for UART ACKs."""
    def __init__(self, send, now, boot_delay=6000):
        self.send, self.now = send, now
        self.probe_at = now() + boot_delay
        self.ready_at = None
        self.ready = False
        self.started = now()
        self.source_selected = False

    def event(self, command, value, volume):
        if command == 0x48 and value == 0 and self.source_selected and self.ready_at is None and not self.ready:
            self.send(0x3F, 0)  # Some clones wrap file counts at 256; check SD presence.
        online = (command == 0x48 and value > 0) or (command == 0x3F and value & 2)
        if online and self.source_selected and self.ready_at is None and not self.ready:
            self.send(0x06, volume)
            self.send(0x11, 0)  # Queue/repeats belong to PicoPod.
            self.send(0x19, 1)
            self.ready_at = self.now() + 600

    def update(self):
        if self.ready:
            return
        t = self.now()
        if self.ready_at is not None:
            if t >= self.ready_at:
                self.ready = True
            return
        if t < self.probe_at:
            return
        if not self.source_selected:
            self.send(0x09, 2)
            self.source_selected = True
            self.probe_at = t + 500
        else:
            self.send(0x48, 0)
            self.probe_at = t + 2500

    def message(self):
        return 'Audio starting' if self.now() - self.started < 15000 else 'Check SD / UART'
