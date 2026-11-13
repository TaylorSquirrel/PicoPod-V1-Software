# Default target: original Pico 1 (RP2040), using standard MicroPython.
# Also supports Pico W, Pico 2 and Pico 2 W without changing this pin map.
# GPIO numbers below are NOT physical header pin numbers.
MAIN_I2C = (1, 6, 7, 0x3C)  # Confirmed big screen: bus, SDA, SCL, address
MINI_I2C = (0, 4, 5, 0x3C)  # Confirmed small screen
MAIN_I2C_FREQ = 400000
MINI_I2C_FREQ = 100000  # Confirmed clear with tools/test_small_oled.py
MINI_PAGE_MODE = True
UART_ID = 0
UART_TX = 0  # through 1k resistor to DFPlayer RX
UART_RX = 1  # from DFPlayer TX
BUSY = 2
ENCODER_A = 10
ENCODER_B = 11
ENCODER_BUTTON = 12
BACK_BUTTON = 13
LED = 16
LED_ENABLED = False  # Enable after confirming a WS2812-compatible RGB LED and wiring.
ENCODER_STEPS = 4  # quadrature transitions per detent; try 2 if necessary
ENCODER_REVERSE = False
DEBUG = True
DF_BOOT_DELAY_MS = 6000
FPS = 25
MAIN_IDLE_MS = 30000
MAX_LIBRARY_BYTES = 48000  # Keep metadata bounded for the Pico 1's smaller RAM.
LIBRARY = 'library.json'
