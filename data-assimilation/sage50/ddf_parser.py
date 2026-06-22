"""ddf_parser.py — Parse Pervasive PSQL DDF files to recover table schema.

Binary format (confirmed by probing actual Sage 50 2013 files):

FILE.DDF — Physical slot = 107 bytes:
  [0]       type byte  (0xFF = deleted, other = live)
  [1-2]     File_Id    (uint16 LE)
  [3-22]    File_Name  (20 bytes, zero-padded)
  [23-104]  File_Loc   (82 bytes, zero-padded, relative path e.g. ".\\CUSTOMER.DAT")
  [105-106] File_Flags (uint16 LE)
  Uses a SLIDING SCAN — data area starts at a non-page-aligned offset inside the file.

FIELD.DDF — Physical slot = 30 bytes, NO deletion byte prefix:
  [0-1]   Field_File    (uint16 LE)  table ID (FK → FILE.DDF)
  [2-21]  Field_Name    (20 bytes, zero-padded)
  [22]    Field_DataType (uint8)
  [23-24] Field_Offset  (uint16 LE)
  [25-26] Field_Size    (uint16 LE)
  [27-28] Field_Dec     (uint16 LE)
  [29]    padding / unused
  Uses a SLIDING SCAN — data section starts deep into the file (B-tree index preceding it).
"""
from __future__ import annotations

import logging
import os
import struct
from typing import Dict, List, Optional

log = logging.getLogger("ddf_parser")

# DDF meta-table IDs (X$File, X$Field, X$Index, etc.) — skip their fields
_META_TABLE_MAX_ID = 10

# ---------------------------------------------------------------------------
# Schema types
# ---------------------------------------------------------------------------

class FieldDef:
    __slots__ = ("name", "type", "offset", "size", "dec")

    def __init__(self, name: str, type_code: int, offset: int, size: int, dec: int):
        self.name = name
        self.type = type_code
        self.offset = offset
        self.size = size
        self.dec = dec

    def as_dict(self) -> Dict:
        return {"name": self.name, "type": self.type,
                "offset": self.offset, "size": self.size, "dec": self.dec}


class TableSchema:
    __slots__ = ("table_name", "dat_path", "logical_rec_len", "fields")

    def __init__(self, table_name: str, dat_path: str, logical_rec_len: int, fields: List[FieldDef]):
        self.table_name = table_name
        self.dat_path = dat_path
        self.logical_rec_len = logical_rec_len
        self.fields = fields

    @property
    def physical_slot_len(self) -> int:
        return self.logical_rec_len + 1  # +1 for deletion byte in .DAT files


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse(sage_root: str, company_subfolder: Optional[str] = None) -> Dict[str, TableSchema]:
    """Parse FILE.DDF + FIELD.DDF.

    Prefers the company's own DDF files (inside sage_root/company_subfolder/)
    over the root-level DDF files, since company-level DDF files contain the
    full transactional schema (60x more data).

    Returns {TABLE_NAME_UPPER: TableSchema}.
    """
    # Prefer company-level DDF files — they are much more complete
    ddf_root = sage_root
    if company_subfolder:
        company_path = os.path.join(sage_root, company_subfolder)
        if os.path.isdir(company_path) and _find_ddf(company_path, "FILE.DDF"):
            ddf_root = company_path
            log.info(f"Using company-level DDF files from: {ddf_root}")

    file_ddf_path  = _find_ddf(ddf_root, "FILE.DDF")
    field_ddf_path = _find_ddf(ddf_root, "FIELD.DDF")

    if not file_ddf_path:
        raise FileNotFoundError(f"FILE.DDF not found in {ddf_root}")
    if not field_ddf_path:
        raise FileNotFoundError(f"FIELD.DDF not found in {ddf_root}")

    log.info(f"Parsing FILE.DDF  : {file_ddf_path}")
    file_records = _scan_file_ddf(file_ddf_path)

    log.info(f"Parsing FIELD.DDF : {field_ddf_path}")
    field_records = _scan_field_ddf(field_ddf_path)

    log.info(f"  FILE.DDF: {len(file_records)} tables  FIELD.DDF: {len(field_records)} fields")

    # Build field index: file_id → list of FieldDef (sorted by offset)
    fields_by_file_id: Dict[int, List[FieldDef]] = {}
    for fr in field_records:
        fid = fr["Field_File"]
        if fid <= _META_TABLE_MAX_ID:
            continue  # skip X$File, X$Field meta tables
        fdef = FieldDef(
            name=fr["Field_Name"],
            type_code=fr["Field_DataType"],
            offset=fr["Field_Offset"],
            size=fr["Field_Size"],
            dec=fr["Field_Dec"],
        )
        fields_by_file_id.setdefault(fid, []).append(fdef)

    # Sort each table's fields by byte offset
    for fid in fields_by_file_id:
        fields_by_file_id[fid].sort(key=lambda f: f.offset)

    # Build schema: table name → TableSchema
    schema: Dict[str, TableSchema] = {}
    for rec in file_records:
        file_id    = rec["File_Id"]
        table_name = rec["File_Name"].strip().upper()
        file_loc   = rec["File_Loc"].strip().replace("\\", os.sep).replace("/", os.sep)

        if not table_name or file_id <= _META_TABLE_MAX_ID:
            continue

        # Resolve absolute .DAT path
        # Base is ddf_root (may be the company subfolder)
        if os.path.isabs(file_loc):
            dat_path = file_loc
        else:
            # Strip leading ".\" or "./" prefix Pervasive sometimes uses
            rel = file_loc.lstrip(f".{os.sep}").lstrip("./")
            dat_path = os.path.join(ddf_root, rel)
            if not os.path.exists(dat_path):
                dat_path = os.path.join(sage_root, rel)

        fields = fields_by_file_id.get(file_id, [])

        # Compute logical record length from field definitions
        if fields:
            logical_rec_len = max(f.offset + f.size for f in fields)
        else:
            logical_rec_len = 0

        schema[table_name] = TableSchema(
            table_name=table_name,
            dat_path=dat_path,
            logical_rec_len=logical_rec_len,
            fields=fields,
        )

    log.info(f"Schema loaded: {len(schema)} tables")
    return schema


# ---------------------------------------------------------------------------
# FILE.DDF scanner — sliding scan, 107-byte slots
# ---------------------------------------------------------------------------
# Physical slot layout (confirmed by binary inspection):
#   [0]       type byte  (0xFF = deleted record)
#   [1-2]     File_Id    uint16 LE
#   [3-22]    File_Name  20 bytes, zero-padded ASCII
#   [23-104]  File_Loc   82 bytes, zero-padded ASCII (relative path)
#   [105-106] File_Flags uint16 LE

_FILE_SLOT_SIZE = 107
_FILE_NAME_OFFSET = 3      # within physical slot
_FILE_NAME_LEN = 20
_FILE_LOC_OFFSET = 23
_FILE_LOC_LEN = 82


def _scan_file_ddf(path: str) -> List[Dict]:
    """Sliding scan of FILE.DDF to extract all table records."""
    with open(path, "rb") as f:
        data = f.read()

    # Phase 1: find first valid slot anchor
    anchor = _find_file_anchor(data)
    if anchor < 0:
        log.warning(f"FILE.DDF: no valid anchor found — no tables extracted")
        return []

    log.info(f"FILE.DDF: anchor at offset {anchor}")

    # Phase 2: collect all slots from anchor onwards
    records = []
    i = anchor
    while i + _FILE_SLOT_SIZE <= len(data):
        slot = data[i:i + _FILE_SLOT_SIZE]
        if slot[0] != 0xFF:  # not deleted
            fid  = struct.unpack_from("<H", slot, 1)[0]
            name = slot[_FILE_NAME_OFFSET:_FILE_NAME_OFFSET + _FILE_NAME_LEN]
            loc  = slot[_FILE_LOC_OFFSET:_FILE_LOC_OFFSET + _FILE_LOC_LEN]

            name_str = name.rstrip(b"\x00 ").decode("latin-1", errors="replace")
            loc_str  = loc.rstrip(b"\x00 ").decode("latin-1", errors="replace")

            if _is_valid_identifier(name_str) and 1 <= fid <= 100_000:
                records.append({
                    "File_Id":   fid,
                    "File_Name": name_str,
                    "File_Loc":  loc_str,
                })
        i += _FILE_SLOT_SIZE

    log.info(f"FILE.DDF: {len(records)} live table records")
    return records


def _find_file_anchor(data: bytes) -> int:
    """Find FILE.DDF data-section start using the known X$File meta-record.

    Every Pervasive PSQL FILE.DDF starts with a record for the meta-table
    'X$File' which has File_Id=1. We search for the exact byte pattern:
        [0x01 0x00] + b'X$File'
    at slot offsets [1..2] + [3..8] respectively.
    """
    # Slot layout: [type_byte][File_Id uint16 LE][File_Name 20 bytes]...
    # File_Id=1 → bytes \x01\x00; File_Name starts with "X$File"
    pattern = b"\x01\x00X$File"
    idx = data.find(pattern)
    if idx >= 1:
        # idx points to File_Id position; type byte is 1 byte before
        return idx - 1
    # Fallback: search for X$File anywhere (some files may have different ID ordering)
    idx2 = data.find(b"X$File")
    if idx2 >= 3:
        # The name is at offset 3 within the slot
        return idx2 - 3
    return -1


# ---------------------------------------------------------------------------
# FIELD.DDF scanner — sliding scan, 30-byte slots, no deletion byte
# ---------------------------------------------------------------------------
# Physical slot layout (confirmed by binary inspection):
#   [0-1]   Field_File     uint16 LE  (table ID)
#   [2-21]  Field_Name     20 bytes, zero-padded ASCII
#   [22]    Field_DataType uint8
#   [23-24] Field_Offset   uint16 LE
#   [25-26] Field_Size     uint16 LE
#   [27-28] Field_Dec      uint16 LE
#   [29]    padding

_FIELD_SLOT_SIZE = 30
_FIELD_NAME_OFFSET = 2
_FIELD_NAME_LEN = 20


def _scan_field_ddf(path: str) -> List[Dict]:
    """Sliding scan of FIELD.DDF to extract all field definitions."""
    with open(path, "rb") as f:
        data = f.read()

    anchor = _find_field_anchor(data)
    if anchor < 0:
        log.warning(f"FIELD.DDF: no valid anchor found — no fields extracted")
        return []

    log.info(f"FIELD.DDF: anchor at offset {anchor}")

    records = []
    i = anchor
    seq_id = 1
    while i + _FIELD_SLOT_SIZE <= len(data):
        slot = data[i:i + _FIELD_SLOT_SIZE]
        file_id  = struct.unpack_from("<H", slot, 0)[0]
        name_raw = slot[_FIELD_NAME_OFFSET:_FIELD_NAME_OFFSET + _FIELD_NAME_LEN]
        name     = name_raw.rstrip(b"\x00 ").decode("latin-1", errors="replace")
        dtype    = slot[22]
        offset   = struct.unpack_from("<H", slot, 23)[0]
        size     = struct.unpack_from("<H", slot, 25)[0]
        dec      = struct.unpack_from("<H", slot, 27)[0]

        if 1 <= file_id <= 100_000 and _is_valid_identifier(name) and 1 <= size <= 32_768:
            records.append({
                "Field_Id":       seq_id,
                "Field_File":     file_id,
                "Field_Name":     name,
                "Field_DataType": dtype,
                "Field_Offset":   offset,
                "Field_Size":     size,
                "Field_Dec":      dec,
            })
            seq_id += 1

        i += _FIELD_SLOT_SIZE

    log.info(f"FIELD.DDF: {len(records)} live field records")
    return records


def _find_field_anchor(data: bytes) -> int:
    """Scan for first valid FIELD.DDF slot with strict validation.

    Requirements per slot:
      - field_file (bytes 0-1): 1 to 3000 (reasonable table count)
      - field_name (bytes 2-21): valid identifier, 2+ chars, starts with letter
      - field_size (bytes 25-26): 1 to 2048 (reasonable field byte length)
      - field_dec  (bytes 27-28): 0 to 10
      - field_offset (bytes 23-24): 0 to 65535

    Requires 8+ consecutive valid records before committing.
    """
    size = len(data)
    for i in range(size - 10 * _FIELD_SLOT_SIZE):
        valid_count = 0
        j = i
        while j + _FIELD_SLOT_SIZE <= size:
            file_id = struct.unpack_from("<H", data, j)[0]
            if not (1 <= file_id <= 3000):
                break
            name_bytes = data[j + _FIELD_NAME_OFFSET:j + _FIELD_NAME_OFFSET + _FIELD_NAME_LEN]
            name = name_bytes.rstrip(b"\x00 ").decode("latin-1", errors="replace")
            if not (len(name) >= 2 and name[0].isalpha() and _is_valid_identifier(name)):
                break
            sz  = struct.unpack_from("<H", data, j + 25)[0]
            dec = struct.unpack_from("<H", data, j + 27)[0]
            if not (1 <= sz <= 2048 and dec <= 10):
                break
            valid_count += 1
            if valid_count >= 8:
                return i
            j += _FIELD_SLOT_SIZE
        # Quick skip: advance by _FIELD_SLOT_SIZE if current is 0xFF-ish
        if data[i] in (0xFF, 0x00):
            i_step = _FIELD_SLOT_SIZE
        else:
            i_step = 1
        i += i_step - 1  # loop will add 1
    return -1


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _find_ddf(folder: str, filename: str) -> Optional[str]:
    """Find a DDF file case-insensitively in folder."""
    fn_lower = filename.lower()
    for entry in os.listdir(folder):
        if entry.lower() == fn_lower:
            return os.path.join(folder, entry)
    return None


def _is_valid_identifier(name: str) -> bool:
    """Return True if name looks like a valid Sage table or field name."""
    stripped = name.strip()
    if not stripped or len(stripped) > 40:
        return False
    has_letter = any(c.isalpha() for c in stripped)
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                  "0123456789_. $-")
    return has_letter and all(c in allowed for c in stripped)


# ---------------------------------------------------------------------------
# Utility: detect unique company subfolder names from parsed schema
# ---------------------------------------------------------------------------

def detect_companies(schema: Dict[str, "TableSchema"]) -> List[str]:
    """Extract unique company subfolder names from DAT paths in schema."""
    companies = set()
    for ts in schema.values():
        rel = ts.dat_path.replace("\\", "/")
        parts = rel.split("/")
        if len(parts) >= 2:
            companies.add(parts[-2])
    return sorted(companies)
