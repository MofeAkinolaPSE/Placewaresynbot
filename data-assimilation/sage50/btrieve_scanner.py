"""
btrieve_scanner.py
------------------
Extracts GL journal row data directly from Sage 50 Pervasive PSQL binary .DAT files.
No ODBC required — reads the raw Btrieve B-tree file format.

Discovered record structure in JrnlRow.DAT data pages:
  [0x00] [description text: 1-161 chars] [173-len] [0x00 0x00 0x10 0x00] [16-byte GUID]
  [binary section: ~57-80 bytes of encoded GL account postings]
  [4-byte date: DD MM YYYY_LE16] [more binary]

Usage:
  from btrieve_scanner import scan_jrnlrow
  rows = scan_jrnlrow(dat_path)
  # rows is a list of dicts: description, posting_date, record_id, raw_binary
"""

import struct
import re
import os
from typing import List, Dict, Optional

# ─── constants ────────────────────────────────────────────────────────────────

# Field size for RowDescription: total storage = 173 bytes
# (2-byte LSTRING header + 161 bytes data + 10 bytes overhead in Btrieve block)
_RDESC_TOTAL = 173
# Pattern after description text: [remaining_byte][0x00][0x00][0x10][0x00][16-byte GUID]
_POST_TEXT_FIXED = 5   # remaining(1) + 00(1) + 00(1) + 10(1) + 00(1)
_GUID_LEN = 16
# Binary section between GUID end and date: variable, ~50-80 bytes
_BIN_SEARCH_WINDOW = 120  # scan this many bytes after GUID for date

# Minimum / maximum description length to consider valid
_MIN_DESC = 4
_MAX_DESC = 161

# Printable ASCII set (allow space-tilde)
_PRINTABLE = set(range(0x20, 0x7F))

# Plausible year range for the company
_YEAR_MIN = 2010
_YEAR_MAX = 2026

# ─── helpers ─────────────────────────────────────────────────────────────────

def _is_printable(b: int) -> bool:
    return b in _PRINTABLE


def _decode_date(buf: bytes) -> Optional[str]:
    """
    Search buf for a 4-byte date encoded as: DD MM YYYY_LE16.
    Returns 'YYYY-MM-DD' string or None if not found.
    """
    for i in range(len(buf) - 3):
        year = struct.unpack_from('<H', buf, i + 2)[0]
        if _YEAR_MIN <= year <= _YEAR_MAX:
            day = buf[i]
            month = buf[i + 1]
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f'{year:04d}-{month:02d}-{day:02d}'
    return None


def _extract_records_from_page(page: bytes) -> List[Dict]:
    """
    Scan one 512-byte page for RowDescription records.

    Pattern: 0x00 [text: N bytes] [173-N] 0x00 0x00 0x10 0x00 [16-byte GUID] [binary]
    """
    results = []
    PS = len(page)
    i = 0
    while i < PS - (_MIN_DESC + _POST_TEXT_FIXED + _GUID_LEN + 4):
        if page[i] != 0x00:
            i += 1
            continue

        # Try to read a printable text run starting at i+1
        j = i + 1
        while j < PS and _is_printable(page[j]):
            j += 1

        text_len = j - (i + 1)
        if text_len < _MIN_DESC or text_len > _MAX_DESC:
            i += 1
            continue

        remaining = _RDESC_TOTAL - text_len
        if remaining < 0:
            i += 1
            continue

        # Check mandatory bytes after text: remaining, 0x00, 0x00, 0x10, 0x00
        end = j + _POST_TEXT_FIXED
        if end > PS:
            i += 1
            continue
        if (page[j] != remaining or
                page[j + 1] != 0x00 or
                page[j + 2] != 0x00 or
                page[j + 3] != 0x10 or
                page[j + 4] != 0x00):
            i += 1
            continue

        # Extract GUID (16 bytes after the fixed suffix)
        guid_start = j + _POST_TEXT_FIXED
        guid_end = guid_start + _GUID_LEN
        if guid_end > PS:
            i += 1
            continue
        guid = page[guid_start:guid_end]

        # All-zero GUID → likely an empty/pre-allocated page, skip
        if not any(guid):
            i += 1
            continue

        # Extract description text
        description = page[i + 1:j].decode('ascii', 'replace').strip()

        # Binary section after GUID — search for date
        bin_section = page[guid_end:min(guid_end + _BIN_SEARCH_WINDOW, PS)]
        posting_date = _decode_date(bin_section)

        # Try to extract record sequence ID: 4-byte LE32 before "0a 00 02 00 00 00"
        record_id = None
        m = re.search(b'\x0a\x00\x02\x00\x00\x00', bin_section)
        if m and m.start() >= 4:
            record_id = struct.unpack_from('<I', bin_section, m.start() - 4)[0]

        results.append({
            'description':  description,
            'posting_date': posting_date,
            'record_id':    record_id,
            'page_offset':  i,
            'guid':         guid.hex(),
        })

        # Advance past this match
        i = guid_end
    return results


# ─── public API ──────────────────────────────────────────────────────────────

def scan_jrnlrow(dat_path: str, max_pages: int = 0) -> List[Dict]:
    """
    Full-file scan of JrnlRow.DAT.

    Reads every 512-byte page and extracts RowDescription records using the
    discovered binary pattern. No ODBC or DDF required.

    Args:
        dat_path:  Path to JrnlRow.DAT
        max_pages: If > 0, stop after this many pages (for testing)

    Returns:
        List of dicts with keys:
          description   – GL row description text (RowDescription field)
          posting_date  – 'YYYY-MM-DD' or None
          record_id     – int sequence number or None
          page_offset   – byte offset within the page where match was found
          guid          – 16-byte GUID hex string (unique per record)
    """
    if not os.path.isfile(dat_path):
        raise FileNotFoundError(dat_path)

    file_size = os.path.getsize(dat_path)
    PS = 512
    total_pages = file_size // PS

    records: List[Dict] = []
    seen_guids: set = set()  # deduplicate across pages (shadow copies)

    print(f'Scanning {os.path.basename(dat_path)}: {file_size:,} bytes, {total_pages:,} pages…')

    with open(dat_path, 'rb') as f:
        for pn in range(total_pages if not max_pages else min(total_pages, max_pages)):
            page = f.read(PS)
            if not any(page):  # all-zero page — skip fast
                continue

            for rec in _extract_records_from_page(page):
                g = rec['guid']
                if g in seen_guids:
                    continue
                seen_guids.add(g)
                rec['source_page'] = pn
                records.append(rec)

    print(f'  -> {len(records):,} unique records extracted')
    return records


def scan_jrnlhdr(dat_path: str, max_pages: int = 0) -> List[Dict]:
    """
    Same pattern scan for JrnlHdr.DAT.
    JrnlHdr stores journal entry headers; RowDescription there is the journal reference.
    """
    return scan_jrnlrow(dat_path, max_pages=max_pages)


# ─── JrnlHdr.DAT invoice-header extraction ─────────────────────────────────
# Discovered record structure (validated against Sage's bundled Bellwether
# Garden Supply sample company — same Pervasive PSQL engine/schema as any
# Sage 50 US Edition / Peachtree install):
#
#   [8 random bytes] [4-byte LE32 sequential record id]
#   [Name: variable-length text, max field width 39 bytes]
#   [1 byte: remaining = 39 - len(Name)]
#   [4-byte fixed marker: 00 00 03 00]
#   [variable bytes] [3-byte fixed marker: 08 00 00]
#   [2-byte LE16 length: len(Reference) + 1] [1-byte tag: 0x0f]
#   [Reference text]
#   ... (within next ~150 bytes) [Date1: day, month, year_LE16]
#   ... (within next ~30 bytes after Date1)  [Date2: day, month, year_LE16]
#
# Name is the customer/payee name on the transaction; Reference is the
# invoice/document number Sage assigned; Date1/Date2 are the transaction
# date and a second date (observed ~3 weeks earlier — likely the invoice's
# linked PO/ship date, not yet confirmed which is which against a live
# Sales Invoice). Dollar amounts are NOT in JrnlHdr — they live on the
# JrnlRow GL distribution lines (see scan_jrnlrow) or LineItem detail rows.

_HDR_YEAR_MIN = 2000
_HDR_YEAR_MAX = 2035
_HDR_NAME_MAXWIDTH = 39


def _decode_date_at(data: bytes, start: int, end: int):
    """Search data[start:end] for a [day][month][year_LE16] date. Returns (iso_str, pos) or (None, -1)."""
    limit = min(end, len(data) - 3)
    for i in range(start, limit):
        year = struct.unpack_from('<H', data, i + 2)[0]
        if _HDR_YEAR_MIN <= year <= _HDR_YEAR_MAX:
            day, month = data[i], data[i + 1]
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f'{year:04d}-{month:02d}-{day:02d}', i
    return None, -1


def _try_extract_header(data: bytes, text_start: int) -> Optional[Dict]:
    """Attempt to parse a JrnlHdr record starting at a candidate Name-field offset."""
    j = text_start
    n = len(data)
    while j < n and 32 <= data[j] < 127:
        j += 1
    text_len = j - text_start
    if not (3 <= text_len <= _HDR_NAME_MAXWIDTH):
        return None
    if j >= n or data[j] != _HDR_NAME_MAXWIDTH - text_len:
        return None
    if data[j + 1:j + 5] != b'\x00\x00\x03\x00':
        return None

    name = data[text_start:j].decode('latin-1', 'replace')

    # Reference field: scan a small window after the marker for "08 00 00" + LE16 len + 0x0f tag
    search_from = j + 5
    for k in range(search_from, min(search_from + 30, n - 4)):
        if data[k:k + 3] != b'\x08\x00\x00':
            continue
        length = struct.unpack_from('<H', data, k + 3)[0]
        tag_pos = k + 5
        if not (1 <= length - 1 <= 20) or data[tag_pos:tag_pos + 1] != b'\x0f':
            break
        ref_start = tag_pos + 1
        ref_end = ref_start + length - 1
        if ref_end > n:
            break
        ref = data[ref_start:ref_end].decode('latin-1', 'replace')
        if not ref.isprintable():
            break

        date1, pos1 = _decode_date_at(data, ref_end, ref_end + 150)
        date2 = None
        if pos1 >= 0:
            date2, _ = _decode_date_at(data, pos1 + 4, pos1 + 4 + 30)

        return {
            'name':      name,
            'reference': ref,
            'date':      date1,
            'date2':     date2,
            '_ref_start': ref_start,  # absolute byte offset in data[] for ref text
        }
    return None


def scan_jrnlhdr_invoices(dat_path: str, max_rows: int = 0) -> List[Dict]:
    """
    Extract invoice/transaction header records from JrnlHdr.DAT.

    Returns a list of dicts: {name, reference, date, date2}
    - name:      customer/payee name on the transaction
    - reference: Sage-assigned document/invoice number
    - date:      primary transaction date, 'YYYY-MM-DD'
    - date2:     secondary date found nearby (purpose unconfirmed), or None

    No ODBC or DDF parsing required — pure byte-pattern scan, validated
    against Sage's bundled Bellwether Garden Supply sample data.
    """
    if not os.path.isfile(dat_path):
        raise FileNotFoundError(dat_path)

    with open(dat_path, 'rb') as f:
        data = f.read()

    results: List[Dict] = []
    seen_refs: set = set()
    n = len(data)
    i = 0
    while i < n - 50:
        if data[i] == 0 and data[i + 1] == 0:
            rec = _try_extract_header(data, i + 2)
            if rec and rec['reference'] not in seen_refs:
                seen_refs.add(rec['reference'])
                rec['file_offset'] = i          # position of 0x00 0x00 marker
                rec['ref_offset']  = rec.pop('_ref_start', i)  # position of reference text
                results.append(rec)
                if max_rows and len(results) >= max_rows:
                    break
        i += 1

    return results


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys, json, pathlib

    BASE = pathlib.Path(__file__).parent.parent.parent / 'Installer Files' / 'Sage Data 1' / 'planigli'

    files = {
        'jrnlrow': BASE / 'JRNLROW.DAT',
        'jrnlhdr': BASE / 'JRNLHDR.DAT',
    }

    for name, path in files.items():
        if not path.exists():
            print(f'  SKIP {name}: {path} not found')
            continue
        fn = scan_jrnlrow if name == 'jrnlrow' else scan_jrnlhdr
        rows = fn(str(path))
        out = pathlib.Path(__file__).parent / 'extracted' / f'{name}_binary.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, 'w') as fp:
            json.dump(rows[:500], fp, indent=2, default=str)
        print(f'  Wrote {min(len(rows),500)} of {len(rows)} rows to {out}')

        # Print sample
        for r in rows[:5]:
            print(f"    [{r['posting_date']}] {r['description']}")
