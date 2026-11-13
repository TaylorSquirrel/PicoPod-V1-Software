"""Small SSD1306 I2C framebuffer driver; SSD1306 only (not SH1106)."""
import framebuf


class OLED(framebuf.FrameBuffer):
    def __init__(self, i2c, height, address=0x3C, page_mode=False):
        self.i2c, self.address, self.height = i2c, address, height
        self.page_mode = page_mode
        self.buffer = bytearray(128 * height // 8)
        self.command_buffer = bytearray((0x80, 0))
        self.data_buffers = (b'\x40', self.buffer)
        self.page_buffers = []
        self.sent_buffer = None
        if page_mode:
            view = memoryview(self.buffer)
            self.page_buffers = [(b'\x40', view[p * 128:(p + 1) * 128])
                                 for p in range(height // 8)]
            # Unknown controller RAM at boot: force every page to be cleared.
            self.sent_buffer = bytearray([255] * len(self.buffer))
        super().__init__(self.buffer, 128, height, framebuf.MONO_VLSB)
        for command in (0xAE, 0x20, 2 if page_mode else 0, 0x40, 0xA1, 0xC8, 0xA8, height - 1,
                        0xD3, 0, 0xDA, 0x12 if height == 64 else 2,
                        0xD5, 0x80, 0xD9, 0xF1, 0xDB, 0x30, 0x81, 0x7F,
                        0x2E, 0xA4, 0xA6, 0x8D, 0x14, 0xAF):
            self.command(command)
        self.fill(0)
        self.show()

    def command(self, command):
        self.command_buffer[1] = command
        self.i2c.writeto(self.address, self.command_buffer)

    def show(self):
        if self.page_mode:
            for page, buffers in enumerate(self.page_buffers):
                self._send_page(page)
            return
        for command in (0x21, 0, 127, 0x22, 0, self.height // 8 - 1):
            self.command(command)
        self.i2c.writevto(self.address, self.data_buffers)

    def _send_page(self, page):
        self.command(0xB0 + page)
        self.command(0x00)
        self.command(0x10)
        self.i2c.writevto(self.address, self.page_buffers[page])
        start = page * 128
        for index in range(start, start + 128):
            self.sent_buffer[index] = self.buffer[index]

    def show_incremental(self):
        """Bound small-screen transfer time; leave the bus speed unchanged."""
        if not self.page_mode:
            self.show()
            return
        if self.buffer == self.sent_buffer:
            return
        for index in range(len(self.buffer)):
            if self.buffer[index] != self.sent_buffer[index]:
                self._send_page(index // 128)
                return
