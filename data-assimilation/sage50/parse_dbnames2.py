"""
Deep analysis of dbnames.cfg to find the planigli entry and its database name.
"""
import re

dbnames_path = r'C:\Program Files (x86)\Pervasive Software\PSQL\DBNamesDirectory\dbnames.cfg'
with open(dbnames_path, 'rb') as f:
    data = f.read()

# Find planigli path entry
planigli_path = b'C:\\SAGEDATA\\PLANIGLI'
idx = data.find(planigli_path)
print("planigli path found at offset: 0x%x (%d)" % (idx, idx))

# Show large context around it
if idx >= 0:
    start = max(0, idx - 64)
    end = min(len(data), idx + 128)
    chunk = data[start:end]
    print("Context hex:")
    for i in range(0, len(chunk), 16):
        line = chunk[i:i+16]
        hexpart = ' '.join('%02x' % b for b in line)
        txtpart = ''.join(chr(b) if 32 <= b < 127 else '.' for b in line)
        print("  %04x: %-48s  %s" % (start + i, hexpart, txtpart))

# Now find the DEMODATA record for comparison
demodata_path = b'C:\\PROGRAMDATA\\PERVASIVE SOFTWARE\\PSQL\\DEMODATA'
idx2 = data.find(demodata_path)
print("\ndemodata path found at offset: 0x%x (%d)" % (idx2, idx2))
if idx2 >= 0:
    start2 = max(0, idx2 - 64)
    end2 = min(len(data), idx2 + 80)
    chunk2 = data[start2:end2]
    print("Context hex:")
    for i in range(0, len(chunk2), 16):
        line = chunk2[i:i+16]
        hexpart = ' '.join('%02x' % b for b in line)
        txtpart = ''.join(chr(b) if 32 <= b < 127 else '.' for b in line)
        print("  %04x: %-48s  %s" % (start2 + i, hexpart, txtpart))

# Search for PLANIGLI name (any case)
for pattern in [b'PLANIGLI', b'planigli', b'Planigli']:
    positions = [m.start() for m in re.finditer(re.escape(pattern), data)]
    print("\n'%s' found at offsets: %s" % (pattern.decode(), positions))

# Find all database NAME entries (padded 20-char names pattern)
# Based on DEMODATA pattern: 20 bytes padded with spaces
print("\n--- Scanning for 20-char padded name entries ---")
for offset in range(0, len(data) - 20, 1):
    chunk = data[offset:offset+20]
    # Check if it looks like a padded name: starts with uppercase, rest is uppercase/spaces
    if (chunk[0:1].upper() == chunk[0:1] and
        65 <= chunk[0] <= 90 and  # starts A-Z
        all(65 <= b <= 90 or b == 32 for b in chunk) and
        chunk[-1:] == b' '):  # ends with space
        name = chunk.rstrip(b' ').decode('ascii', errors='?')
        if len(name) >= 4:
            print("  0x%x: '%s'" % (offset, name))
