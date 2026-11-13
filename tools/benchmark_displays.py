"""Run on Pico via mpremote; compares main-only and combined UI frame times."""
import time
from machine import Pin, I2C
import config
from display import OLED
from player import Player
from ui import UI


def make(settings, height, freq, page_mode=False):
    bus, sda, scl, address = settings
    return OLED(I2C(bus, sda=Pin(sda), scl=Pin(scl), freq=freq),
                height, address, page_mode=page_mode)


big = make(config.MAIN_I2C, 64, config.MAIN_I2C_FREQ)
small = make(config.MINI_I2C, 32, config.MINI_I2C_FREQ, config.MINI_PAGE_MODE)
p = Player({}, lambda c, v: None, time.ticks_ms)
for name, mini in (('main only', None), ('both screens', small)):
    ui = UI(big, mini)
    start = time.ticks_us()
    for frame in range(30):
        p.selection = (frame // 5) % 4
        ui.draw(p, time.ticks_ms())
    duration = time.ticks_diff(time.ticks_us(), start) / 30000
    print(name, 'ms/frame:', duration)
print('Small bus speed:', config.MINI_I2C_FREQ, 'page mode:', config.MINI_PAGE_MODE)
