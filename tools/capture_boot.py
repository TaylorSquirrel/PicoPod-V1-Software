"""Restart our firmware in the friendly REPL and capture its startup diagnostics."""
import sys
import time
import serial

with serial.Serial(sys.argv[1] if len(sys.argv) > 1 else 'COM4', 115200, timeout=0.2) as port:
    port.write(b'\x03\x03\x02')
    time.sleep(0.2)
    port.reset_input_buffer()
    port.write(b'\x04')
    end = time.monotonic() + 10
    while time.monotonic() < end:
        data = port.read(4096)
        if data:
            print(data.decode('utf-8', 'replace'), end='', flush=True)
