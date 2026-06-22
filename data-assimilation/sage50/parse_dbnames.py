"""
Read dbnames.cfg (Btrieve file) to find existing named database entries.
Looks for known strings (demodata, defaultdb) to understand record format.
"""
import sys
import re

dbnames_path = r'C:\Program Files (x86)\Pervasive Software\PSQL\DBNamesDirectory\dbnames.cfg'

with open(dbnames_path, 'rb') as f:
    data = f.read()

print("File size: %d bytes" % len(data))
print("First 16 bytes: %s" % data[:16].hex())

# Search for known database names
known = [b'demodata', b'defaultdb', b'tempdb', b'pervasivesysdb', b'DEMODATA', b'DEFAULTDB']
for name in known:
    idx = data.find(name)
    if idx >= 0:
        # Show context around the match
        start = max(0, idx - 32)
        end = min(len(data), idx + 128)
        chunk = data[start:end]
        print("\nFound '%s' at offset %d (0x%x):" % (name.decode(), idx, idx))
        print("  Hex: %s" % chunk.hex())
        # Show printable chars
        printable = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print("  Txt: %s" % printable)

# Find all null-terminated strings >= 5 chars
print("\n--- All strings in file (len>=6) ---")
strings = re.findall(rb'[\x20-\x7e]{6,}', data)
for s in strings:
    decoded = s.decode('ascii', errors='replace')
    if any(kw in decoded.lower() for kw in ['data', 'path', 'sage', 'name', 'psql', 'pervasive', 'c:\\']):
        print("  '%s'" % decoded)
