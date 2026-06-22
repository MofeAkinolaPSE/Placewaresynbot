"""btrieve_reader.py — Pure-Python sequential reader for Pervasive PSQL / Btrieve .DAT files.

No ODBC, no Pervasive installation, no system drivers required.
Works on any OS (Linux inside Docker, Windows 7 with py38, etc.).

Strategy: sequential page scan (not B-tree traversal).
Sufficient for bulk data extraction — reads every live record in file order.

Pervasive PSQL v10 file layout (Sage 50 2013 / Peachtree):
  Page 0     : file header (512 bytes default)
  Pages 1..N : data pages
    Bytes 0-1  : page usage count
    Bytes 2..  : record slots packed end-to-end
      Slot[0]  : deletion byte  (0x00 = active, 0xFF = deleted/free)
      Slot[1..]: logical record data
"""
from __future__ import annotations

import struct
from typing import Dict, Iterator, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Btrieve / Pervasive PSQL type codes (Field_DataType from FIELD.DDF)
# ---------------------------------------------------------------------------
TYPE_CHAR     = 0    # Fixed-length string (latin-1)
TYPE_INT16    = 1    # 2-byte signed integer
TYPE_INT32    = 2    # 4-byte signed integer
TYPE_FLOAT    = 3    # 4-byte IEEE float
TYPE_DATE     = 4    # YYYYMMDD stored as 4-byte BCD or int
TYPE_DATE2    = 5    # Date variant
TYPE_MONEY    = 6    # 8-byte signed int, divide by 10^dec
TYPE_INT8     = 7    # 1-byte signed integer (rare)
TYPE_DECIMAL  = 8    # BCD decimal (sz bytes, dec decimal places)
TYPE_BFLOAT   = 9    # Btrieve float (big-endian 4-byte)
TYPE_TIME     = 10   # HHMMSS as 4-byte int
TYPE_DATE3    = 11   # Numeric decimal (date variant)
TYPE_MONEY2   = 12   # Currency variant
TYPE_LSTRING  = 13   # Length-prefixed string (first byte = len)
TYPE_ZSTRING  = 14   # Null-terminated string (like C string)
TYPE_DATE4    = 15   # 4-byte date int
TYPE_UINT16   = 16   # 2-byte unsigned int (note: some sources use code 15/16)
TYPE_UINT32   = 17   # 4-byte unsigned int
TYPE_AUTOINC  = 18   # Auto-increment (4-byte unsigned)
TYPE_BIT      = 19   # 1-bit (stored in 1 byte)
TYPE_NUMSTR   = 20   # Numeric string (ASCII digits)
TYPE_VARLEN   = 26   # Variable-length string (rare in Peachtree)


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

# Known header offset candidates for page_size and record_length.
# Different Btrieve versions store these in different positions.
_PAGE_SIZE_OFFSETS = (16, 22, 4, 6)
_REC_LEN_OFFSETS   = (10, 4, 8, 12)
_VALID_PAGE_SIZES  = {512, 1024, 2048, 4096, 8192}


def read_header(path: str) -> Tuple[int, int]:
    """Return (page_size, logical_record_length) from a Btrieve file header.

    Falls back to (512, 0) if header is unreadable — caller must supply
    record_length from an external source (e.g. DDF field size sum).
    """
    try:
        with open(path, "rb") as f:
            hdr = f.read(128)
    except OSError:
        return 512, 0

    if len(hdr) < 20:
        return 512, 0

    # Try to detect page size
    page_size = 512
    for off in _PAGE_SIZE_OFFSETS:
        if off + 2 <= len(hdr):
            val = struct.unpack_from("<H", hdr, off)[0]
            if val in _VALID_PAGE_SIZES:
                page_size = val
                break

    # Try to detect logical record length
    rec_len = 0
    for off in _REC_LEN_OFFSETS:
        if off + 2 <= len(hdr):
            val = struct.unpack_from("<H", hdr, off)[0]
            if 1 <= val <= 8192:
                rec_len = val
                break

    return page_size, rec_len


# ---------------------------------------------------------------------------
# Sequential record scanner
# ---------------------------------------------------------------------------

def iter_records(
    path: str,
    record_length: int,
    page_size: int = 512,
) -> Iterator[bytes]:
    """Yield raw bytes for every live (non-deleted) record in a .DAT file.

    record_length: the PHYSICAL slot size (logical record + 1 deletion byte).
    Caller should pass  logical_record_length + 1.

    Yields the full physical slot bytes (index 0 = deletion byte).
    """
    try:
        f_handle = open(path, "rb")
    except OSError as exc:
        raise FileNotFoundError(f"Cannot open {path}: {exc}") from exc

    with f_handle as f:
        page_num = 1
        while True:
            f.seek(page_num * page_size)
            page = f.read(page_size)
            if len(page) < page_size:
                break  # short read = end of file

            offset = 2  # skip 2-byte page usage count
            while offset + record_length <= page_size:
                slot = page[offset: offset + record_length]
                deletion_byte = slot[0] if slot else 0xFF
                if deletion_byte != 0xFF:  # 0xFF = deleted/free slot
                    yield slot
                offset += record_length
            page_num += 1


# ---------------------------------------------------------------------------
# Field value parser
# ---------------------------------------------------------------------------

def parse_field(
    record: bytes,       # full physical slot (deletion byte at [0])
    data_offset: int,    # byte offset of field within LOGICAL record (after deletion byte)
    size: int,
    type_code: int,
    dec: int = 0,
) -> object:
    """Parse a single field value from a raw record slot.

    data_offset is the logical offset (not including the deletion byte at [0]).
    We therefore read from record[1 + data_offset].
    """
    start = 1 + data_offset  # +1 to skip deletion byte
    end = start + size
    if end > len(record):
        return None
    raw = record[start:end]

    try:
        if type_code in (TYPE_CHAR, TYPE_ZSTRING, TYPE_LSTRING, TYPE_NUMSTR, TYPE_VARLEN):
            # String types
            text = raw.decode("latin-1", errors="replace")
            if type_code == TYPE_LSTRING and raw:
                # First byte is length
                length = raw[0]
                text = raw[1: 1 + min(length, size - 1)].decode("latin-1", errors="replace")
            return text.rstrip("\x00 \xff")

        if type_code == TYPE_INT8:
            return struct.unpack_from("<b", raw)[0]

        if type_code in (TYPE_INT16, TYPE_UINT16):
            fmt = "<H" if type_code == TYPE_UINT16 else "<h"
            return struct.unpack_from(fmt, raw)[0]

        if type_code in (TYPE_INT32, TYPE_UINT32, TYPE_AUTOINC):
            fmt = "<I" if type_code in (TYPE_UINT32, TYPE_AUTOINC) else "<i"
            return struct.unpack_from(fmt, raw)[0]

        if type_code == TYPE_FLOAT:
            return round(struct.unpack_from("<f", raw)[0], 6)

        if type_code == TYPE_BFLOAT:
            # Big-endian float
            return round(struct.unpack_from(">f", raw)[0], 6)

        if type_code in (TYPE_MONEY, TYPE_MONEY2):
            if size == 4:
                raw_int = struct.unpack_from("<i", raw)[0]
            else:
                raw_int = int.from_bytes(raw[:8], byteorder="little", signed=True)
            divisor = 10 ** dec if dec > 0 else 100
            return round(raw_int / divisor, 4)

        if type_code in (TYPE_DATE, TYPE_DATE2, TYPE_DATE3, TYPE_DATE4):
            return _parse_date(raw, type_code)

        if type_code == TYPE_TIME:
            if size == 4:
                t = struct.unpack_from("<I", raw)[0]
                hh = (t // 10000000)
                mm = (t % 10000000) // 100000
                ss = (t % 100000) // 1000
                return f"{hh:02d}:{mm:02d}:{ss:02d}"
            return None

        if type_code == TYPE_BIT:
            return bool(raw[0] & 0x01)

        if type_code == TYPE_DECIMAL:
            # BCD-encoded decimal
            return _parse_bcd(raw, dec)

        # Fallback: return as hex string for unknown types
        return raw.hex()

    except (struct.error, IndexError, ValueError):
        return None


def _parse_date(raw: bytes, type_code: int) -> Optional[str]:
    """Return ISO date string (YYYY-MM-DD) from a Btrieve date field."""
    if len(raw) < 4:
        return None
    try:
        val = struct.unpack_from("<I", raw)[0]
        if val == 0:
            return None
        # Btrieve date: stored as YYYYMMDD integer
        year  = val // 10000
        month = (val % 10000) // 100
        day   = val % 100
        if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
        # Alternative: stored as number of days since some epoch
        # Try the Btrieve epoch (1600-01-01 base or 0000-01-01)
        # If both interpretations fail, return raw hex
        return None
    except (struct.error, OverflowError):
        return None


def _parse_bcd(raw: bytes, dec: int) -> Optional[float]:
    """Parse a BCD-encoded decimal."""
    try:
        digits = ""
        for byte in raw[:-1]:  # last byte is sign
            digits += str((byte >> 4) & 0x0F) + str(byte & 0x0F)
        sign_byte = raw[-1]
        sign = -1 if (sign_byte & 0x0F) in (0x0D, 0x0B) else 1
        value = int(digits) * sign
        return round(value / (10 ** dec), dec) if dec > 0 else float(value)
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Convenience: parse a full record dict from a schema
# ---------------------------------------------------------------------------

def record_to_dict(
    slot: bytes,
    fields: List[Dict],
) -> Dict[str, object]:
    """Parse a raw slot into a dict using a list of field defs.

    Each field def: {"name": str, "type": int, "offset": int, "size": int, "dec": int}
    """
    row: Dict[str, object] = {}
    for fld in fields:
        val = parse_field(
            slot,
            data_offset=fld["offset"],
            size=fld["size"],
            type_code=fld["type"],
            dec=fld.get("dec", 0),
        )
        row[fld["name"]] = val
    return row
