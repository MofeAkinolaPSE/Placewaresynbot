"""
Patch dbnames.cfg to add PLANIGLI to the shadow page (0x9000 area).

The engine uses shadow paging: 0x6000=main page, 0x9000=shadow page.
PLANIGLI was added to main page but not shadow. Engine reads shadow → can't find PLANIGLI.
Fix: copy the PLANIGLI record from 0x6000 page to the 0x9000 shadow page.

WARNING: Run with psqlWGE STOPPED.
"""
import shutil
import struct

DB_FILE = r'C:\Program Files (x86)\Pervasive Software\PSQL\DBNamesDirectory\dbnames.cfg'
BACKUP  = DB_FILE + '.bak'

with open(DB_FILE, 'rb') as f:
    data = bytearray(f.read())

print("File size: %d bytes" % len(data))

# Source: PLANIGLI record in main page at 0x66e6 (name offset)
# We need to copy the full record: 32 bytes pre + 20 name + 12 post + path + nulls = ~160 bytes
PLANIGLI_NAME_OFFSET = 0x66e6
PLANIGLI_START = PLANIGLI_NAME_OFFSET - 32  # 0x66c6
# Find the path end (null terminator after path)
PATH_START = PLANIGLI_NAME_OFFSET + 20 + 12  # 0x6706
PATH_END = data.index(0, PATH_START)
# Record ends at PATH_END + enough padding to next record boundary
# Looking at spacing between records in the source page:
# PLACEWARELIMTEDDEMO starts at 0x65c1-32=0x65a1, PLANIGLI starts at 0x66c6
# So record size ≈ 0x66c6 - 0x65a1 = 0x125 = 293 bytes
RECORD_SIZE = 0x66c6 - (0x65c1 - 32)  # = 0x125 = 293
print("Source PLANIGLI record: offset=0x%x, record_size=%d" % (PLANIGLI_START, RECORD_SIZE))

src_record = bytes(data[PLANIGLI_START : PLANIGLI_START + RECORD_SIZE])
print("Source record hex (first 40): %s" % src_record[:40].hex())
print("Source path: %s" % src_record[64:64+50].decode('ascii', errors='?').rstrip('\x00').rstrip())

# Target: corresponding offset in shadow page (0x9000 area)
# Shadow page starts 0x3000 bytes after main page
SHADOW_OFFSET = 0x3000
TARGET_OFFSET = PLANIGLI_START + SHADOW_OFFSET  # 0x96c6
print("\nTarget offset in shadow page: 0x%x" % TARGET_OFFSET)
print("Current bytes at target: %s" % bytes(data[TARGET_OFFSET:TARGET_OFFSET+40]).hex())

# Check that target area is zeros (free space) or same data
target_current = bytes(data[TARGET_OFFSET:TARGET_OFFSET + RECORD_SIZE])
if all(b == 0 for b in target_current):
    print("Target is all zeros — safe to write")
elif target_current == src_record:
    print("Target already has the same data — no patch needed!")
else:
    print("Target has different data:")
    print("  %s" % target_current[:40].hex())
    # Find any text in the existing target
    txt = ''.join(chr(b) if 32 <= b < 127 else '.' for b in target_current[:64])
    print("  txt: %s" % txt)
    print("Will overwrite with PLANIGLI record")

# Show what the patch would do (don't write yet — confirm first)
print("\n=== PATCH PREVIEW ===")
print("Would copy %d bytes from 0x%x to 0x%x" % (RECORD_SIZE, PLANIGLI_START, TARGET_OFFSET))
print("Name in target area after patch: %s" % src_record[32:52].decode('ascii', errors='?'))
