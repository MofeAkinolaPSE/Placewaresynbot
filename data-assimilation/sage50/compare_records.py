"""Compare raw record bytes of working vs broken entries in dbnames.cfg."""

with open(r'C:\Program Files (x86)\Pervasive Software\PSQL\DBNamesDirectory\dbnames.cfg', 'rb') as f:
    data = f.read()

records = {
    'DEMODATA':            0x612d,
    'PEACHTREEGLOBAL':     0x649c,
    'PLACEWARELIMTEDDEMO': 0x65c1,
    'PLANIGLI':            0x66e6,
}

print("Record comparison (32 bytes before name, name, 12 bytes after):\n")
for name, name_offset in records.items():
    pre  = data[name_offset-32 : name_offset]
    nm   = data[name_offset    : name_offset+20]
    post = data[name_offset+20 : name_offset+32]
    path_start = name_offset + 32
    path_end   = data.find(b'\x00', path_start)
    path       = data[path_start:path_end].decode('ascii', errors='?')

    print("=== %s ===" % name)
    print("  Pre  hex: %s" % pre.hex())
    pre_txt = ''.join(chr(b) if 32 <= b < 127 else '.' for b in pre)
    print("  Pre  txt: %s" % pre_txt)
    print("  Name    : %s" % nm.decode('ascii', errors='?'))
    print("  Post hex: %s" % post.hex())
    print("  Path    : %s" % path)
    print()
