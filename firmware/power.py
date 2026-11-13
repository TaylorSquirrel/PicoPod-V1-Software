"""Orderly audio/display shutdown. Hardware power removal requires a switch."""


def shutdown(action, df, main, mini, status, encoder, pixel, now, sleep_ms, reset, suspend):
    if action not in ('reboot', 'poweroff'):
        raise ValueError('Invalid power action')
    df.queue = []
    df.send(0x06, 0)
    df.send(0x16, 0)
    df.send(0x0C if action == 'reboot' else 0x0A, 0)
    deadline = now() + 2000
    while df.queue and now() < deadline:
        df.poll()
        sleep_ms(20)
    if df.queue:
        raise RuntimeError('Audio shutdown command timed out')
    sleep_ms(100)  # Let the final UART frame finish before disabling peripherals.
    main.set_on(False)
    mini.set_on(False)
    if pixel:
        pixel[0] = (0, 0, 0)
        pixel.write()
    status.pin.value(0)
    encoder.a.irq(handler=None)
    encoder.b.irq(handler=None)
    if action == 'reboot':
        reset()
    else:
        df.uart.deinit()
        suspend()
