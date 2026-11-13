"""Temporary on-device test: mpremote connect COM4 run tools/test_small_oled.py.

Uses SSD1306 page addressing and 100 kHz I2C. Does not modify saved firmware.
Restart the Pico to return to PicoPod. This does not identify the controller.
"""
from machine import Pin, I2C
from display import OLED

bus = I2C(0, sda=Pin(4), scl=Pin(5), freq=100000)
d = OLED(bus, 32)
d.command(0x2E)  # Disable hardware scrolling.
d.command(0x20)
d.command(2)  # Page addressing instead of horizontal addressing.
d.fill(0)
d.rect(0, 0, 128, 32, 1)
d.text('OLED TEST', 8, 5, 1)
d.text('0123456789', 8, 18, 1)
pages = memoryview(d.buffer)
for page in range(4):
    d.command(0xB0 + page)
    d.command(0x00)
    d.command(0x10)
    bus.writevto(0x3C, (b'\x40', pages[page * 128:(page + 1) * 128]))
print('Static page-addressed test sent. Restart to resume PicoPod.')
