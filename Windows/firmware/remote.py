"""Bounded JSON-over-USB controls. No eval, file access, or reset commands."""
import json
import sys
import select
import binascii
import os

PREFIX = '@POD '


class Remote:
    def __init__(self, now, player, ready, displays, stdin=None, emit=None, poller=None, on_interaction=None):
        self.now, self.player, self.ready, self.displays = now, player, ready, displays
        self.stdin = stdin or sys.stdin
        self.emit = emit or (lambda value: print(PREFIX + json.dumps(value)))
        self.poller = poller or select.poll()
        self.poller.register(self.stdin, 1)  # POLLIN; also permits injected Windows test pollers.
        self.line = ''
        self.discarding = False
        self.stream_until = 0
        self.last_frame = -10000
        self.quiet = False
        self.on_interaction = on_interaction

    def handle(self, request):
        token = request.get('id')
        try:
            cmd = request.get('cmd')
            p = self.player
            if cmd in ('rotate', 'select', 'back', 'toggle', 'next', 'previous', 'volume', 'quiet') and self.on_interaction:
                self.on_interaction()
            if cmd == 'hello':
                try:
                    storage = os.statvfs('/')
                    free = storage[0] * storage[3]
                except (OSError, AttributeError):
                    free = None
                catalog = self.player.catalog
                self.emit({'type': 'hello', 'protocol': 1, 'id': token, 'ready': self.ready(),
                           'indexed_catalog': 2, 'storage_free': free,
                           'active_catalog': catalog.meta['file'] if catalog else None})
                return
            if cmd == 'stream':
                self.stream_until = self.now() + 2500 if request.get('enabled', True) else 0
                if not request.get('enabled', True):
                    self.quiet = False
            elif cmd == 'quiet':
                enabled = request.get('enabled')
                if type(enabled) is not bool:
                    raise ValueError('Quiet mode requires true or false')
                self.quiet = enabled
                if enabled:
                    self.stream_until = self.now() + 2500
            elif cmd == 'rotate':
                delta = request.get('delta', 0)
                if type(delta) is not int or not -10 <= delta <= 10:
                    raise ValueError('Rotation must be an integer from -10 to 10')
                p.rotate(delta)
            elif cmd == 'back':
                p.back()
            elif cmd == 'select':
                if p.screen in ('songs', 'now') and not self.ready():
                    raise ValueError('Audio not ready')
                p.select()
            elif cmd in ('toggle', 'next', 'previous', 'volume'):
                if not self.ready():
                    raise ValueError('Audio not ready')
                if cmd == 'toggle':
                    p.toggle()
                elif cmd in ('next', 'previous'):
                    p.skip(1 if cmd == 'next' else -1)
                else:
                    volume = request.get('value')
                    if type(volume) is not int or not 0 <= volume <= 30:
                        raise ValueError('Volume must be an integer from 0 to 30')
                    p.volume = volume
                    p.send(0x06, volume)
            else:
                raise ValueError('Unknown command')
            self.emit({'type': 'ack', 'id': token, 'quiet': self.quiet})
        except (ValueError, TypeError, KeyError, RuntimeError) as error:
            self.emit({'type': 'error', 'id': token, 'message': str(error)})

    def poll(self):
        if self.quiet and self.now() >= self.stream_until:
            self.quiet = False
        # One-byte reads after POLLIN are essential on MicroPython USB stdin.
        for _ in range(128):
            if not self.poller.poll(0):
                break
            char = self.stdin.read(1)
            if not char:
                break
            if char in ('\n', '\r'):
                line, self.line = self.line, ''
                discarded, self.discarding = self.discarding, False
                if line.startswith(PREFIX) and not discarded:
                    try:
                        request = json.loads(line[len(PREFIX):])
                        if not isinstance(request, dict):
                            raise ValueError('Expected object')
                        self.handle(request)
                    except (ValueError, TypeError) as error:
                        self.emit({'type': 'error', 'message': str(error)})
            elif not self.discarding:
                self.line += char
                if len(self.line) > 512:
                    self.line = ''
                    self.discarding = True

    def frame(self):
        t = self.now()
        if self.quiet and self.player.playing:
            return
        if t >= self.stream_until or t - self.last_frame < 160:
            return
        main, mini = self.displays()
        p = self.player
        awake = getattr(main, 'on', True)
        display_error = 'main' if getattr(main, 'fault', False) else ('secondary' if mini and getattr(mini, 'fault', False) else None)
        mini_awake = mini is not None and getattr(mini, 'on', True)
        if not self.player.settings.values['mini_enabled'] and display_error == 'secondary':
            display_error = None
        self.emit({'type': 'frame', 'main': binascii.hexlify(main.buffer if awake else bytes(len(main.buffer))).decode(),
                   'mini': binascii.hexlify((getattr(mini, 'sent_buffer', None) or mini.buffer) if mini_awake else bytes(len(mini.buffer))).decode() if mini else None,
                   'screen': p.screen, 'selection': p.selection, 'control': p.control,
                   'repeat': p.repeat, 'shuffle': p.shuffle,
                   'playing': p.playing, 'title': (p.track() or {}).get('title', ''),
                   'elapsed_ms': p.elapsed(), 'volume': p.volume, 'error': p.error, 'ready': self.ready(),
                   'main_awake': awake, 'mini_awake': mini_awake, 'display_error': display_error})
        self.last_frame = t
