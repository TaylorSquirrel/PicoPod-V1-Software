"""Non-audio test of live USB mirroring and navigation on the connected Pico."""
import queue
import time
from manager.live import DeviceClient


def frame(client, predicate=lambda message: True, timeout=4):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            message = client.events.get(timeout=0.2)
        except queue.Empty:
            continue
        if message.get('type') == 'disconnected':
            raise RuntimeError(message['message'])
        if message.get('type') == 'frame' and predicate(message):
            return message
    raise RuntimeError('No matching live frame received')


client = DeviceClient('COM4')
try:
    client.wait_connected()
    initial = frame(client)
    assert len(initial['main']) == 2048 and len(initial['mini']) == 1024
    for _ in range(4):
        client.send('back')
    client.send('rotate', delta=-10)
    frame(client, lambda value: value['screen'] == 'home' and value['selection'] == 0)
    client.send('rotate', delta=1)
    frame(client, lambda value: value['screen'] == 'home' and value['selection'] == 1)
    client.send('rotate', delta=-1)
    client.send('select')
    frame(client, lambda value: value['screen'] == 'songs')
    client.send('back')
    frame(client, lambda value: value['screen'] == 'home')
    print('PASS: USB handshake, exact two-screen frames, rotate/select/back on real Pico')
finally:
    client.close()
