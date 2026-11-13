"""Browse Settings on the actual player without saving changes or powering off."""
import queue
import time
from manager.live import DeviceClient

client = DeviceClient('COM4')
def wait_screen(screen):
    end = time.monotonic() + 4
    while time.monotonic() < end:
        try:
            event = client.events.get(timeout=0.3)
        except queue.Empty:
            continue
        if event.get('type') == 'disconnected':
            raise RuntimeError(event['message'])
        if event.get('type') == 'frame' and event.get('screen') == screen:
            return
    raise RuntimeError('Did not reach ' + screen)

try:
    client.wait_connected()
    for _ in range(5):
        client.send('back')
    client.send('rotate', delta=-10)
    client.send('rotate', delta=4)
    client.send('select')
    wait_screen('settings')
    client.send('select')
    wait_screen('main_settings')
    client.send('select')
    wait_screen('setting_value')
    client.send('back')
    client.send('back')
    client.send('back')
    wait_screen('home')
    print('PASS: real Settings/menu/value navigation; no settings saved or power actions triggered')
finally:
    client.close()
