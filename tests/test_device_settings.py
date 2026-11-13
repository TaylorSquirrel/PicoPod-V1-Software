from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from firmware.settings import SettingsStore, SleepTimer, DEFAULTS, checked
from firmware.player import Player
from firmware.power import shutdown
from firmware.status import IdleScreen, StatusLED, DisplayLink
from test_status import Pin, Frame, Device


class DeviceSettingsTests(unittest.TestCase):
    def test_settings_survive_repeated_save_and_sleep_timer_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SettingsStore(str(Path(temporary) / 'settings.json'))
            self.assertEqual(store.load(), DEFAULTS)
            values = dict(DEFAULTS, default_volume=8, main_timeout=120, mini_enabled=False, sleep_minutes=3)
            store.save(values)
            store.save(dict(values, main_timeout=0))
            restored = store.load()
            self.assertEqual(restored['default_volume'], 8)
            self.assertEqual(restored['main_timeout'], 0)
            self.assertFalse(restored['mini_enabled'])
            self.assertNotIn('sleep_minutes', restored)

    def test_invalid_preferences_are_rejected(self):
        for change in ({'main_timeout': 9}, {'default_volume': 31}, {'mini_enabled': 1}, {'main_brightness': 0}):
            with self.assertRaises(ValueError):
                checked(dict(DEFAULTS, **change))

    def test_settings_navigation_commit_and_default_volume_is_boot_only(self):
        player = Player({}, lambda c, v: None, lambda: 0)
        changed = []
        player.settings.on_change = lambda k, v: changed.append((k, v))
        player.selection = 4
        player.select()
        self.assertEqual(player.screen, 'settings')
        player.selection = 2
        player.select()
        player.selection = 7
        player.select()
        self.assertEqual(player.settings.values['default_volume'], 7)
        self.assertEqual(player.volume, 15)
        self.assertEqual(changed, [('default_volume', 7)])
        self.assertEqual(player.screen, 'settings')

    def test_power_actions_require_confirmation(self):
        player = Player({}, lambda c, v: None, lambda: 0)
        actions = []
        player.settings.on_power = actions.append
        player.selection = 4
        player.select()
        player.selection = 6
        player.select()
        self.assertEqual(player.screen, 'confirm_power')
        player.select()
        self.assertEqual(actions, [])
        player.select()
        player.selection = 1
        player.select()
        self.assertEqual(actions, ['poweroff'])

    def test_timer_deadline_and_off(self):
        t = [0]
        timer = SleepTimer(lambda: t[0])
        timer.arm(1)
        t[0] = 59999
        self.assertFalse(timer.expired())
        t[0] = 60000
        self.assertTrue(timer.expired())
        timer.arm(0)
        self.assertFalse(timer.expired())
        timer.arm(60)
        with self.assertRaises(ValueError):
            timer.arm(61)

    def test_led_disable_does_not_disable_errors(self):
        pin = Pin()
        status = StatusLED(pin, lambda: 0)
        status.update(healthy_on=False)
        self.assertEqual(pin.values[-1], 0)
        status.update(other_error=True, healthy_on=False)
        self.assertEqual(pin.values[-1], 1)

    def test_disabled_display_does_not_connect_and_brightness_is_commanded_once(self):
        calls = []
        device = Device()
        link = DisplayLink(lambda: calls.append(1) or device, Frame(), lambda: 0, lambda e, c: None, 'secondary', enabled=False)
        self.assertEqual(calls, [])
        link.poll()
        link.set_brightness(100)
        link.set_brightness(100)
        self.assertEqual(device.commands[-2:], [0x81, 255])
        idle = IdleScreen(lambda: 999999, 0)
        self.assertTrue(idle.awake())

    def test_shutdown_stops_audio_before_standby_and_blanks_peripherals(self):
        for action, final in [('poweroff', 0x0A), ('reboot', 0x0C)]:
            t, sent, events = [0], [], []
            class DF:
                queue = []
                uart = SimpleNamespace(deinit=lambda: events.append('uart off'))
                def send(self, c, v):
                    self.queue.append((c, v))
                def poll(self):
                    sent.append(self.queue.pop(0))
            df = DF()
            main = SimpleNamespace(set_on=lambda v: events.append(('main', v)))
            mini = SimpleNamespace(set_on=lambda v: events.append(('mini', v)))
            status = SimpleNamespace(pin=SimpleNamespace(value=lambda v: events.append(('led', v))))
            encoder = SimpleNamespace(a=SimpleNamespace(irq=lambda **kw: None), b=SimpleNamespace(irq=lambda **kw: None))
            shutdown(action, df, main, mini, status, encoder, None, lambda: t[0], lambda ms: t.__setitem__(0, t[0]+ms),
                     lambda: events.append('reset'), lambda: events.append('suspend'))
            self.assertEqual(sent, [(6, 0), (0x16, 0), (final, 0)])
            self.assertIn(('main', False), events)
            self.assertIn('reset' if action == 'reboot' else 'suspend', events)
