"""MicroPython firmware for Pico 1 / Pico W / Pico 2 / Pico 2 W."""
import time
import json
import sys
import os
import gc
import math
import micropython
import framebuf
import machine
from machine import Pin, I2C, UART
import config
from display import OLED
from dfplayer import DFPlayer, AudioStartup
from diagnostics import record
from player import Player
from ui import UI
from remote import Remote
from catalog import load_catalog, cleanup_catalogs
from status import StatusLED, IdleScreen, DisplayLink
from settings import SettingsStore, SleepTimer, DEFAULTS
from power import shutdown


class Clock:
    # Convert wrap-safe ticks into a monotonic counter.
    def __init__(self):
        self.previous = time.ticks_ms()
        self.total = 0

    def __call__(self):
        current = time.ticks_ms()
        self.total += time.ticks_diff(current, self.previous)
        self.previous = current
        return self.total


class Button:
    def __init__(self, gpio, now):
        self.pin = Pin(gpio, Pin.IN, Pin.PULL_UP)
        self.raw = self.stable = self.pin.value()
        self.changed = now()
        self.now = now

    def poll(self):
        raw = self.pin.value()
        if raw != self.raw:
            self.raw, self.changed = raw, self.now()
        if self.stable != raw and self.now() - self.changed >= 30:
            self.stable = raw
            return raw == 0
        return False


class Encoder:
    # IRQ captures every edge while I2C transfers block the main loop.
    TABLE = (0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0)

    def __init__(self):
        self.a = Pin(config.ENCODER_A, Pin.IN, Pin.PULL_UP)
        self.b = Pin(config.ENCODER_B, Pin.IN, Pin.PULL_UP)
        self.previous = self.a.value() * 2 + self.b.value()
        self.count = 0
        self.remainder = 0
        self.a.irq(self.edge, trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, hard=True)
        self.b.irq(self.edge, trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, hard=True)

    def edge(self, pin):
        current = self.a.value() * 2 + self.b.value()
        self.count += self.TABLE[self.previous * 4 + current]
        self.previous = current

    def poll(self):
        import machine
        state = machine.disable_irq()
        count = self.count
        self.count = 0
        machine.enable_irq(state)
        self.remainder += count
        magnitude = abs(self.remainder) // config.ENCODER_STEPS
        steps = -magnitude if self.remainder < 0 else magnitude
        self.remainder -= steps * config.ENCODER_STEPS
        return -steps if config.ENCODER_REVERSE else steps


class VirtualOLED(framebuf.FrameBuffer):
    def __init__(self, height):
        self.buffer = bytearray(128 * height // 8)
        super().__init__(self.buffer, 128, height, framebuf.MONO_VLSB)


def screen(settings, height, frequency=400000, page_mode=False):
    bus, sda, scl, address = settings
    i2c = I2C(bus, sda=Pin(sda), scl=Pin(scl), freq=frequency, timeout=50000)
    result = OLED(i2c, height, address, page_mode=page_mode)
    print('I2C', bus, 'OLED ready at', address)
    return result


def run():
    global active_main
    micropython.alloc_emergency_exception_buf(100)
    print('PicoPod board:', os.uname().machine)
    now = system_clock
    settings_store = SettingsStore()
    settings_error = [False]
    try:
        preferences = settings_store.load()
    except (ValueError, TypeError) as error:
        record(error, 'settings invalid; using defaults')
        preferences = dict(DEFAULTS)
        settings_error[0] = True
    main = DisplayLink(lambda: screen(config.MAIN_I2C, 64, config.MAIN_I2C_FREQ),
                       VirtualOLED(64), now, record, 'main')
    active_main = main
    mini = DisplayLink(lambda: screen(config.MINI_I2C, 32, config.MINI_I2C_FREQ, config.MINI_PAGE_MODE),
                       VirtualOLED(32), now, record, 'secondary', enabled=preferences['mini_enabled'])
    ui = UI(main, mini)
    idle = IdleScreen(now, preferences['main_timeout'] * 1000)
    mini_idle = IdleScreen(now, preferences['mini_timeout'] * 1000)
    def activity():
        idle.activity()
        mini_idle.activity()
        main.set_on(True)
        if p.settings.values['mini_enabled']:
            mini.set_on(True)
    library_error = None
    try:
        library = load_catalog(config.LIBRARY, config.MAX_LIBRARY_BYTES)
        try:
            active_catalog = library.get('catalog_object')
            cleanup_catalogs(active_catalog.meta['file'] if active_catalog else None)
        except OSError as error:
            print('Unused catalog cleanup deferred:', error)
    except OSError:
        library = {'tracks': [], 'playlists': []}
        library_error = 'Upload SD library'
        print('No library.json. Upload from the manager.')
    except ValueError as error:
        record(error, 'library rejected; menus remain available')
        library = {'tracks': [], 'playlists': []}
        library_error = 'Upload SD library'
    df = DFPlayer(UART(config.UART_ID, baudrate=9600, tx=Pin(config.UART_TX),
                       rx=Pin(config.UART_RX)), now, config.DEBUG)
    p = Player(library, df.send, now)
    p.settings.values.update(preferences)
    p.volume = preferences['default_volume']
    sleep_timer = SleepTimer(now)
    pending_power = [None]
    def change_setting(key, value):
        if key == 'sleep_minutes':
            sleep_timer.arm(value)
        else:
            try:
                settings_store.save(p.settings.values)
            except OSError as error:
                record(error, 'settings save')
                raise
            settings_error[0] = False
            if p.error == 'Settings defaults':
                p.error = ''
    p.settings.on_change = change_setting
    def request_power(action):
        pending_power[0] = action
    p.settings.on_power = request_power
    def suspend():
        # Timed wakeups and USB traffic never resume the player. Only a hardware
        # reset/power cycle restarts it. No input polling remains active here.
        while True:
            try:
                machine.lightsleep(60000)
            except KeyboardInterrupt:
                pass
            except (OSError, RuntimeError):
                # Preserve soft-off even if a particular RP2 sleep backend fails.
                time.sleep_ms(1000)
    def shuffle_notice():
        try:
            main.fill(0)
            main.text('Shuffling...', 16, 26, 1)
            main.show()
        except OSError as error:
            record(error, 'shuffle status display')
    p.on_shuffle = shuffle_notice
    del library
    gc.collect()
    print('Free memory after library load:', gc.mem_free())
    busy = Pin(config.BUSY, Pin.IN, Pin.PULL_UP)
    encoder = Encoder()
    select = Button(config.ENCODER_BUTTON, now)
    back = Button(config.BACK_BUTTON, now)
    led = None
    if config.LED_ENABLED:
        import neopixel
        led = neopixel.NeoPixel(Pin(config.LED), 1)
    startup = AudioStartup(df.send, now, config.DF_BOOT_DELAY_MS)
    remote = Remote(now, p, lambda: startup.ready, lambda: (main, mini), on_interaction=activity)
    last_frame, last_debug = -1000, 0
    audio_ready_shown = False
    while True:
        t = now()
        startup.update()
        if not startup.ready:
            p.error = startup.message()
        elif not audio_ready_shown:
            p.error = ''
            audio_ready_shown = True
            print('AUDIO READY')
        if library_error:
            p.error = library_error
        elif settings_error[0]:
            p.error = 'Settings defaults'
        delta = encoder.poll()
        if delta:
            activity()
            p.rotate(delta)
        if select.poll():
            activity()
            audio_action = p.screen in ('songs', 'now')
            if startup.ready or not audio_action:
                p.select()
        if back.poll():
            activity()
            p.back()
        remote.poll()
        if sleep_timer.expired():
            pending_power[0] = 'poweroff'
        if pending_power[0]:
            p.playing = False
            shutdown(pending_power[0], df, main, mini, status_led, encoder, led,
                     now, time.sleep_ms, machine.reset, suspend)
        for command, value in df.poll():
            startup.event(command, value, p.volume)
            if command == 0x3D:
                print('TRACK FINISHED', value, 'current', p.current)
                p.finished()
            elif command == 0x40:
                p.fail('DF error %d' % value)
            elif command == 0x3B and value & 2:
                p.fail('SD card removed')
                startup = AudioStartup(df.send, now, 1000)
                audio_ready_shown = False
        p.busy(busy.value() == 0)
        main.poll()
        values = p.settings.values
        if values['mini_enabled']:
            mini.poll()
        idle.timeout = values['main_timeout'] * 1000
        mini_idle.timeout = values['mini_timeout'] * 1000
        main.set_brightness(values['main_brightness'])
        mini.set_brightness(values['mini_brightness'])
        main.set_on(idle.awake())
        mini.set_on(values['mini_enabled'] and mini_idle.awake())
        other_error = bool(library_error or (p.error and p.error != 'Audio starting'))
        status_led.update(main.fault, mini.fault and values['mini_enabled'], other_error,
                          healthy_on=values['status_led'])
        if t - last_frame >= 1000 // config.FPS:
            if not (remote.quiet and p.playing):
                ui.draw(p, t)
                remote.frame()
            if led:
                level = 2 + int(5 * (1 + math.sin(t / 700)))
                led[0] = (16, 0, 0) if p.error else ((0, level, level) if p.playing else (0, 0, 3))
                led.write()
            last_frame = t
        if config.DEBUG and t - last_debug >= 5000 and not (remote.quiet and p.playing):
            print('STATE', p.screen, 'track', p.current, 'playing', p.playing,
                  'elapsed', p.elapsed(), 'busy', busy.value(), 'free', gc.mem_free())
            last_debug = t
        time.sleep_ms(2)


active_main = None
system_clock = Clock()
status_led = StatusLED(Pin('LED', Pin.OUT), system_clock)
try:
    run()
except Exception as error:
    record(error)
    if active_main is not None:
        try:
            active_main.fill(0)
            active_main.text('PicoPod stopped', 0, 0, 1)
            active_main.text(type(error).__name__[:16], 0, 18, 1)
            active_main.text('last_error.log', 0, 36, 1)
            active_main.show()
        except OSError:
            pass
    # Continue the fatal status indication. Ctrl-C still returns to the USB REPL.
    while True:
        status_led.update(other_error=True)
        time.sleep_ms(20)
