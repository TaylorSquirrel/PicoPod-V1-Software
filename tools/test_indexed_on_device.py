"""Real Pico RAM/navigation test with 25,000 metadata entries; no UART audio."""
import gc
import json
import os
import time
from catalog import load_catalog
from player import Player

gc.collect()
before = gc.mem_free()
data = load_catalog('test-index-library.json')
disk = data['catalog_object']
clock = [10000]
commands = []
p = Player(data, lambda c, v: commands.append((c, v)), lambda: clock[0])
p.select()
assert len(p.items()) == 25001
assert p.items()[25000] == 'Scale test 25000'
p.selection = 25000
p.select()
assert commands[-1] == (0x0F, 0x630A)
p.back()
p.selection = 0
start = time.ticks_ms()
p.select()
assert len(p.queue) == 25000 and sum(p.queue) == 312512500
gc.collect()
print('PASS: 25000-song navigation, folder 99/010 command, complete shuffle')
print('Shuffle ms:', time.ticks_diff(time.ticks_ms(), start), 'RAM used:', before - gc.mem_free(), 'free:', gc.mem_free())
assert len(disk.cache) <= 3
disk.close()
with open('test-index-library.json') as source:
    test_meta = json.load(source)
with open('library.json') as source:
    current_meta = json.load(source)
test_name = test_meta['catalog']['file']
assert current_meta.get('catalog', {}).get('file') != test_name
assert test_name.startswith('catalog-') and test_name.endswith('.bin')
os.remove(test_name)
os.remove('test-index-library.json')
print('Temporary device scale-test metadata removed; actual library unchanged')
