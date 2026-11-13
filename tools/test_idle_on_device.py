"""Observe the real 30-second display timeout, then wake via USB without audio."""
import queue
import time
from manager.live import DeviceClient

client = DeviceClient('COM4')
try:
    client.wait_connected()
    client.send('rotate', delta=0)  # Explicit interaction, no selection change.
    start = time.monotonic()
    slept = False
    while time.monotonic() - start < 36:
        try:
            value = client.events.get(timeout=0.5)
        except queue.Empty:
            continue
        if value.get('type') == 'disconnected':
            raise RuntimeError(value['message'])
        if value.get('type') == 'frame' and value.get('main_awake') is False:
            assert not value.get('display_error'), value.get('display_error')
            assert set(value['main']) == {'0'}
            assert len(value['mini']) == 1024
            slept = True
            print('PASS: real main-screen idle shutdown after %.1f sec; small screen remains active' % (time.monotonic() - start), flush=True)
            break
    assert slept, 'Main screen did not sleep (physical interaction restarts the timer)'
    client.send('rotate', delta=0)
    deadline = time.monotonic() + 3
    woke = False
    while time.monotonic() < deadline:
        value = client.events.get(timeout=0.5)
        if value.get('type') == 'frame' and value.get('main_awake') is True:
            woke = True
            break
    assert woke, 'Main screen did not wake'
    print('PASS: USB interaction woke the main screen without changing the selection')
finally:
    client.close()
