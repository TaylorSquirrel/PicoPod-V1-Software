"""MicroPython settings compatibility test; does not change real preferences/audio."""
import os
from settings import SettingsStore, DEFAULTS, SleepTimer
from player import Player

path = 'settings-test-only.json'
assert path not in os.listdir()
store = SettingsStore(path)
try:
    store.save(dict(DEFAULTS, default_volume=9, mini_enabled=False, main_timeout=120))
    store.save(dict(DEFAULTS, default_volume=7, main_timeout=0))
    restored = store.load()
    assert restored['default_volume'] == 7 and restored['main_timeout'] == 0
    p = Player({}, lambda c, v: None, lambda: 0)
    p.selection = 4
    p.select()
    assert p.screen == 'settings'
    p.select()
    assert p.screen == 'main_settings'
    p.selection = 1
    p.select()
    assert p.screen == 'setting_value'
    p.selection = 74
    p.select()
    assert p.settings.values['main_brightness'] == 75
    assert p.screen == 'main_settings'
    t = [0]
    timer = SleepTimer(lambda: t[0])
    timer.arm(1)
    t[0] = 60000
    assert timer.expired()
    print('PASS: saved settings, menu edits and sleep deadline on MicroPython; real settings/audio unchanged')
finally:
    if path in os.listdir():
        os.remove(path)
