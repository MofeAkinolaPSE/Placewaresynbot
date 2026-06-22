"""
Parse Sage 50 DDF files (FILE.DDF, FIELD.DDF) directly from binary.
DDF files are Btrieve files with KNOWN fixed-length record schemas.

FILE.DDF  record: Xf$Id(2) + Xf$Name(20) + Xf$Loc(64) + Xf$Flags(2) + Xf$Reserved(2) = 90 bytes
FIELD.DDF record: Xe$Id(2) + Xe$File(2) + Xe$Name(20) + Xe$DataType(2) + Xe$Offset(2) + Xe$Size(2) + Xe$Dec(2) + Xe$Flags(2) = 34 bytes

Since records are fixed-length, we can scan for valid records by looking for
printable ASCII in the name fields.
"""
import struct
import re
import os

PLANIGLI_DIR = r'C:\SageData\planigli'

# Pervasive PSQL DataType codes
DATA_TYPES = {
    0:  'STRING',    1: 'INTEGER', 2: 'FLOAT',    3: 'DATE',
    4:  'TIME',      5: 'DECIMAL', 6: 'MONEY',    7: 'LOGICAL',
    8:  'NUMERIC',   9: 'BFLOAT', 10: 'LSTRING', 11: 'ZSTRING',
    12: 'NOTE',     13: 'LVAR',   14: 'UNSIGNED', 15: 'AUTOINCREMENT',
    16: 'BIT',      17: 'NUMERICSTRING', 18: 'CURRENCY', 19: 'TIMESTAMP',
    20: 'BLOBBING', 21: 'IDENTITY',
}

def is_valid_name(raw):
    """Check if bytes look like a valid table/field name (A-Z0-9_$, space-padded)."""
    try:
        s = raw.decode('ascii', errors='strict')
        return bool(re.match(r'^[A-Za-z_$][A-Za-z0-9_$# ]*$', s.rstrip()))
    except Exception:
        return False

def parse_file_ddf(path):
    """Parse FILE.DDF → {table_id: (table_name, dat_file_loc)}"""
    REC_SIZE = 90
    with open(path, 'rb') as f:
        data = f.read()
    tables = {}
    for offset in range(0, len(data) - REC_SIZE, 1):
        chunk = data[offset:offset + REC_SIZE]
        xf_id    = struct.unpack_from('<H', chunk, 0)[0]
        xf_name  = chunk[2:22]
        xf_loc   = chunk[22:86]
        if xf_id == 0 or xf_id > 5000:
            continue
        if not is_valid_name(xf_name):
            continue
        name_str = xf_name.decode('ascii', errors='?').rstrip()
        loc_str  = xf_loc.decode('ascii', errors='?').split('\x00')[0].strip()
        if len(name_str) < 2 or not loc_str.upper().endswith('.DAT'):
            continue
        tables[xf_id] = (name_str, loc_str)
    # Deduplicate by id (take first occurrence)
    return tables

def parse_field_ddf(path):
    """Parse FIELD.DDF → {table_id: [{name, type, offset, size, dec}]}"""
    REC_SIZE = 34
    with open(path, 'rb') as f:
        data = f.read()
    fields = {}
    for offset in range(0, len(data) - REC_SIZE, 1):
        chunk = data[offset:offset + REC_SIZE]
        xe_id      = struct.unpack_from('<H', chunk, 0)[0]
        xe_file    = struct.unpack_from('<H', chunk, 2)[0]
        xe_name    = chunk[4:24]
        xe_dtype   = struct.unpack_from('<H', chunk, 24)[0]
        xe_offset  = struct.unpack_from('<H', chunk, 26)[0]
        xe_size    = struct.unpack_from('<H', chunk, 28)[0]
        xe_dec     = struct.unpack_from('<H', chunk, 30)[0]
        xe_flags   = struct.unpack_from('<H', chunk, 32)[0]
        if xe_id == 0 or xe_id > 50000 or xe_file == 0 or xe_file > 5000:
            continue
        if not is_valid_name(xe_name):
            continue
        name_str = xe_name.decode('ascii', errors='?').rstrip()
        if len(name_str) < 2:
            continue
        type_name = DATA_TYPES.get(xe_dtype, 'TYPE_%d' % xe_dtype)
        if xe_file not in fields:
            fields[xe_file] = {}
        key = (xe_offset, name_str)
        if key not in fields[xe_file]:
            fields[xe_file][key] = {
                'id': xe_id, 'name': name_str, 'type': type_name,
                'offset': xe_offset, 'size': xe_size, 'dec': xe_dec
            }
    # Convert dicts to sorted lists
    result = {}
    for fid, fdict in fields.items():
        result[fid] = sorted(fdict.values(), key=lambda x: x['offset'])
    return result

print("=== Parsing FILE.DDF ===")
file_ddf = os.path.join(PLANIGLI_DIR, 'FILE.DDF')
tables = parse_file_ddf(file_ddf)
print("Found %d tables:" % len(tables))
# Show target tables
target_names = ['JrnlRow', 'JrnlHdr', 'InventoryCosts', 'Chart', 'Vendor', 'Customer',
                'LineItem', 'BankRec', 'TaxCode', 'Budget']
for tid, (name, loc) in sorted(tables.items(), key=lambda x: x[1][0].lower()):
    marker = " <<< TARGET" if any(t.lower() in name.lower() for t in target_names) else ""
    print("  [%4d] %-25s  %s%s" % (tid, name, loc, marker))

print("\n=== Parsing FIELD.DDF ===")
field_ddf = os.path.join(PLANIGLI_DIR, 'FIELD.DDF')
all_fields = parse_field_ddf(field_ddf)
print("Found field definitions for %d tables" % len(all_fields))

# Show fields for key tables
target_tids = [tid for tid, (name, _) in tables.items()
               if any(t.lower() in name.lower() for t in target_names)]
for tid in sorted(target_tids):
    if tid in tables:
        tname, tloc = tables[tid]
        flist = all_fields.get(tid, [])
        print("\n[%d] %s (%s) — %d fields:" % (tid, tname, tloc, len(flist)))
        for f in flist:
            print("  offset=%4d size=%3d %-12s %-20s %s" % (
                f['offset'], f['size'], f['type'], f['name'],
                ('dec=%d' % f['dec']) if f['dec'] else ''))
