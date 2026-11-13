"""Nonblocking LED patterns, idle timing, and independently recoverable displays."""


class StatusLED:
    def __init__(self, pin, now):
        self.pin, self.now = pin, now
        self.last = None
        self.update()

    def update(self, main_error=False, mini_error=False, other_error=False, healthy_on=True):
        t = self.now()
        if main_error:
            value = t % 2000 < 100
        elif mini_error:
            phase = t % 2000
            value = phase < 100 or 200 <= phase < 300
        elif other_error:
            value = t % 200 < 100
        else:
            value = bool(healthy_on)
        if value != self.last:
            self.pin.value(int(value))
            self.last = value


class IdleScreen:
    def __init__(self, now, timeout_ms=30000):
        self.now, self.timeout = now, timeout_ms
        self.last_activity = now()

    def activity(self):
        self.last_activity = self.now()

    def awake(self):
        return self.timeout <= 0 or self.now() - self.last_activity < self.timeout


class DisplayLink:
    """Keep a virtual framebuffer usable when one physical OLED fails."""
    def __init__(self, factory, frame, now, report, role, enabled=True):
        self.factory, self.frame, self.now = factory, frame, now
        self.report, self.role = report, role
        self.buffer = frame.buffer
        self.device = None
        self.fault = False
        self.on = enabled
        self.brightness = None
        self.retry_at = 0
        if enabled:
            self.poll()

    def __getattr__(self, name):
        return getattr(self.frame, name)

    @property
    def sent_buffer(self):
        return getattr(self.device, 'sent_buffer', None) if self.device else None

    def failed(self, error):
        if not self.fault:
            self.report(error, self.role + ' display; reconnecting')
        self.fault = True
        self.device = None
        self.retry_at = self.now() + 2000

    def poll(self):
        if self.device is not None or self.now() < self.retry_at:
            return
        try:
            self.device = self.factory()
            if self.brightness is not None:
                self.device.command(0x81)
                self.device.command(self.brightness * 255 // 100)
            if not self.on:
                self.device.command(0xAE)
            if self.fault:
                print(self.role, 'display recovered')
            self.fault = False
        except OSError as error:
            self.failed(error)

    def set_on(self, enabled):
        enabled = bool(enabled)
        if self.on == enabled:
            return
        self.on = enabled
        if self.device:
            try:
                self.device.command(0xAF if enabled else 0xAE)
            except OSError as error:
                self.failed(error)

    def set_brightness(self, percent):
        if self.brightness == percent:
            return
        self.brightness = percent
        if self.device:
            try:
                self.device.command(0x81)
                self.device.command(percent * 255 // 100)
            except OSError as error:
                self.failed(error)

    def transfer(self, incremental):
        if not self.on or self.device is None:
            return
        try:
            self.device.buffer[:] = self.buffer
            if incremental:
                self.device.show_incremental()
            else:
                self.device.show()
        except OSError as error:
            self.failed(error)

    def show(self):
        self.transfer(False)

    def show_incremental(self):
        self.transfer(True)
