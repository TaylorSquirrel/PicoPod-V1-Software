"""Inspect the caught exception when PicoPod has returned to the friendly REPL."""
import time
import serial

with serial.Serial('COM4', 115200, timeout=0.2) as port:
    port.write(b"print('LAST_ERROR', repr(globals().get('error', None)))\r")
    time.sleep(0.5)
    print(port.read(4096).decode('utf-8', 'replace'))
    port.write(b"import sys; sys.print_exception(error) if globals().get('error') else None\r")
    time.sleep(0.5)
    print(port.read(4096).decode('utf-8', 'replace'))
