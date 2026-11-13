import unittest
from firmware.status import StatusLED, IdleScreen, DisplayLink
from manager.live import frame_rows


class Pin:
    def __init__(self):
        self.values = []

    def value(self, value):
        self.values.append(value)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.time = 0
        self.pin = Pin()
        self.status = StatusLED(self.pin, lambda: self.time)

    def samples(self, faults):
        result = []
        for self.time in range(0, 2000, 100):
            self.status.update(*faults)
            result.append(self.pin.values[-1])
        return result

    def test_healthy_is_on_without_redundant_pin_writes(self):
        self.assertEqual(self.samples((False, False, False)), [1] * 20)
        self.assertEqual(self.pin.values, [1])

    def test_main_fault_one_fast_flash_per_two_seconds(self):
        self.assertEqual(self.samples((True, False, False)), [1] + [0] * 19)

    def test_secondary_fault_two_fast_flashes_per_two_seconds(self):
        self.assertEqual(self.samples((False, True, False)), [1, 0, 1] + [0] * 17)

    def test_general_error_continuous_fast_blink(self):
        self.assertEqual(self.samples((False, False, True)), [1, 0] * 10)

    def test_idle_deadline_and_wake(self):
        idle = IdleScreen(lambda: self.time)
        self.time = 29999
        self.assertTrue(idle.awake())
        self.time = 30000
        self.assertFalse(idle.awake())
        idle.activity()
        self.assertTrue(idle.awake())

    def test_pc_screen_colors_match_panels(self):
        self.assertIn('#ffd84d', frame_rows('ff' * 1024, 64)[0])
        self.assertIn('#ffffff', frame_rows('ff' * 512, 32)[0])


class Frame:
    def __init__(self):
        self.buffer = bytearray(8)


class Device:
    def __init__(self):
        self.buffer = bytearray(8)
        self.commands = []
        self.frames = 0
        self.fail = False

    def command(self, value):
        self.commands.append(value)

    def show(self):
        if self.fail:
            raise OSError('disconnected')
        self.frames += 1

    show_incremental = show


class DisplayLinkTests(unittest.TestCase):
    def test_independent_failure_and_recovery(self):
        t = [0]
        reports = []
        device = Device()
        main = DisplayLink(lambda: device, Frame(), lambda: t[0], lambda e, c: reports.append(c), 'main')
        mini_device = Device()
        mini = DisplayLink(lambda: mini_device, Frame(), lambda: t[0], lambda e, c: reports.append(c), 'secondary')
        device.fail = True
        main.show()
        mini.show()
        self.assertTrue(main.fault)
        self.assertFalse(mini.fault)
        self.assertEqual(mini_device.frames, 1)
        device.fail = False
        t[0] = 1999
        main.poll()
        self.assertTrue(main.fault)
        t[0] = 2000
        main.poll()
        self.assertFalse(main.fault)
        self.assertEqual(len(reports), 1)

    def test_sleep_suppresses_transfers_and_wake_restores_them(self):
        device = Device()
        link = DisplayLink(lambda: device, Frame(), lambda: 0, lambda e, c: None, 'main')
        link.set_on(False)
        link.show()
        self.assertEqual(device.frames, 0)
        self.assertEqual(device.commands, [0xAE])
        link.set_on(True)
        link.show()
        self.assertEqual(device.frames, 1)
        self.assertEqual(device.commands[-1], 0xAF)

    def test_missing_display_at_boot_stays_recoverable(self):
        def missing():
            raise OSError('missing')
        link = DisplayLink(missing, Frame(), lambda: 0, lambda e, c: None, 'secondary')
        self.assertTrue(link.fault)
        link.show_incremental()  # No exception; other screen/control loop can run.
