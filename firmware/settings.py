"""Saved device preferences and the on-device Settings menu."""
import json
import os

TIMEOUTS = (10, 15, 30, 45, 60, 120, 0)
DEFAULTS = {'main_timeout': 30, 'main_brightness': 50, 'mini_enabled': True,
            'mini_timeout': 0, 'mini_brightness': 50, 'default_volume': 15, 'status_led': True}


def checked(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid settings file')
    result = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        value = data.get(key, default)
        if key.endswith('_timeout'):
            valid = type(value) is int and value in TIMEOUTS
        elif key.endswith('_brightness'):
            valid = type(value) is int and 1 <= value <= 100
        elif key == 'default_volume':
            valid = type(value) is int and 0 <= value <= 30
        else:
            valid = type(value) is bool
        if not valid:
            raise ValueError('Invalid device setting: ' + key)
        result[key] = value
    return result


class SettingsStore:
    def __init__(self, path='settings.json'):
        self.path = path

    def load(self):
        try:
            with open(self.path) as source:
                return checked(json.load(source))
        except OSError:
            return dict(DEFAULTS)

    def save(self, values):
        values = checked(values)
        temporary = self.path + '.new'
        with open(temporary, 'w') as output:
            json.dump(values, output)
            output.flush()
        getattr(os, 'replace', os.rename)(temporary, self.path)


class SleepTimer:
    def __init__(self, now):
        self.now, self.deadline = now, None

    def arm(self, minutes):
        if type(minutes) is not int or not 0 <= minutes <= 60:
            raise ValueError('Sleep timer must be Off or 1–60 minutes')
        self.deadline = self.now() + minutes * 60000 if minutes else None

    def expired(self):
        return self.deadline is not None and self.now() >= self.deadline


class SettingsMenu:
    SCREENS = ('settings', 'main_settings', 'mini_settings', 'setting_value', 'confirm_power')

    def __init__(self):
        self.values = dict(DEFAULTS)
        self.values['sleep_minutes'] = 0
        self.on_change = None
        self.on_power = None
        self.key = None
        self.choices = []
        self.labels = []
        self.action = None

    def title(self, screen):
        return {'settings': 'Settings', 'main_settings': 'Main display', 'mini_settings': 'Secondary',
                'setting_value': 'Choose value', 'confirm_power': 'Confirm action'}[screen]

    def rows(self, screen):
        v = self.values
        def timeout(key):
            return '%ds' % v[key] if v[key] else 'Never'
        if screen == 'settings':
            return ['Main display', 'Secondary', 'Boot vol: %d' % v['default_volume'],
                    'Sleep: %s' % ('%d min' % v['sleep_minutes'] if v['sleep_minutes'] else 'Off'),
                    'Status LED: ' + ('On' if v['status_led'] else 'Off'), 'Reboot', 'Power off']
        if screen == 'main_settings':
            return ['Off: ' + timeout('main_timeout'), 'Bright: %d%%' % v['main_brightness']]
        if screen == 'mini_settings':
            return ['Enabled: ' + ('On' if v['mini_enabled'] else 'Off'), 'Off: ' + timeout('mini_timeout'),
                    'Bright: %d%%' % v['mini_brightness']]
        if screen == 'setting_value':
            return self.labels
        return ['Cancel', 'Reboot now' if self.action == 'reboot' else 'Power off now']

    def edit(self, player, key):
        self.key = key
        if key.endswith('_timeout'):
            self.choices = list(TIMEOUTS)
            self.labels = ['Never' if not value else '%d seconds' % value for value in self.choices]
        elif key.endswith('_brightness'):
            self.choices = list(range(1, 101))
            self.labels = ['%d%%' % value for value in self.choices]
        elif key in ('mini_enabled', 'status_led'):
            self.choices, self.labels = [True, False], ['On', 'Off']
        elif key == 'default_volume':
            self.choices = list(range(31))
            self.labels = [str(value) for value in self.choices]
        else:
            self.choices = list(range(61))
            self.labels = ['Off'] + ['%d minutes' % value for value in range(1, 61)]
        player.enter('setting_value')
        player.selection = self.choices.index(self.values[key])

    def select(self, player):
        screen, selected = player.screen, player.selection
        if screen == 'settings':
            if selected < 2:
                player.enter('main_settings' if selected == 0 else 'mini_settings')
            elif selected < 5:
                self.edit(player, ('default_volume', 'sleep_minutes', 'status_led')[selected - 2])
            else:
                self.action = 'reboot' if selected == 5 else 'poweroff'
                player.enter('confirm_power')
        elif screen in ('main_settings', 'mini_settings'):
            keys = ('main_timeout', 'main_brightness') if screen == 'main_settings' else ('mini_enabled', 'mini_timeout', 'mini_brightness')
            self.edit(player, keys[selected])
        elif screen == 'setting_value':
            key, old = self.key, self.values[self.key]
            self.values[key] = self.choices[selected]
            try:
                if self.on_change:
                    self.on_change(key, self.values[key])
            except Exception:
                self.values[key] = old
                raise
            player.back()
        elif screen == 'confirm_power':
            if selected == 1 and self.on_power:
                self.on_power(self.action)
            player.back()
