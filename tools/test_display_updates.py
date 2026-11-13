"""On-device check of incremental transfer limits using a fake I2C bus."""
from display import OLED


class Bus:
    def __init__(self):
        self.pages = 0

    def writeto(self, address, data):
        pass

    def writevto(self, address, buffers):
        self.pages += 1


bus = Bus()
d = OLED(bus, 32, page_mode=True)
assert bus.pages == 4
assert d.sent_buffer == d.buffer
d.show_incremental()
assert bus.pages == 4
d.fill(1)
for expected in range(5, 9):
    d.show_incremental()
    assert bus.pages == expected
assert d.sent_buffer == d.buffer
d.show_incremental()
assert bus.pages == 8
d.pixel(4, 17, 0)
d.show_incremental()
assert bus.pages == 9
assert d.sent_buffer == d.buffer
print('PASS: no unchanged transfers; one changed page per call; full image converges')
